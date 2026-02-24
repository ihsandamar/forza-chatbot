# Text2SQL Subagent Plan

**Klasör:** `src/graphs/report_agent/subagents/text2sql/`
**Amaç:** `user_query` + `column_metadata` + `business_rules` → `results`

---

## Tasarım Kararları

### Mevcut sistemden ne alıyoruz
| Bileşen | Karar | Gerekçe |
|---------|-------|---------|
| `ValueResolverService` | **Kopyala** | Türkçe fuzzy matching + cache stratejisi kritik, sıfırdan yazma |
| `BusinessRulesVectorStore` | **Kopyala** | ChromaDB + hybrid search çalışıyor, değiştirme |
| Post-processing regex | **Kaldır** | LLM daha iyi prompt ile doğru üretir; hata → retry |
| `create_master_table` / `cleanup_master_table` | **Kaldır** | Report agent artık temp tablo kullanmıyor |
| `metadata_enrichment` node (ayrı) | **Kaldır** | column_metadata config'den gelir, runtime discovery yok |

### Yeni tasarım prensipleri
- **S:** Her node tek iş — plan, resolve, retrieve, build, execute
- **O:** ValueResolverService ve BusinessRulesVectorStore factory ile inject edilir
- **KISS:** 5 node, sequential, post-processing regex yok
- **YAGNI:** Metadata runtime discovery yok (config'den gelir)

---

## Node Yapısı (5 Node)

```
START
  ↓
sql_planner          ← LLM: user_query → QueryPlan (field_hints + value_hints)
  ↓
value_resolver       ← Pure Python: value_hints → resolved DB değerleri (rapidfuzz + cache)
  ↓
business_rules       ← Pure Python: user_query → merged SQL components (ChromaDB)
  ↓
sql_builder          ← LLM: QueryPlan (resolved) + business_rules + column_metadata → SQL
  ↓
sql_executor         ← Pure Python: SQL çalıştır → hata varsa retry
  ↑___________________|  (retry: sql_error set, sql_builder'a geri dön, max 2)
  ↓
 END
```

---

## Node Detayları

### Node 1: `sql_planner` — LLM
**Tek Sorumluluk:** Kullanıcı niyetini yapısal sorgu planına çevirmek.

Reads (Text2SQLState'den):
- `user_query`
- `query_type` (SINGLE / RANKING / COMPARISON / TIME_SERIES_COMPARISON)
- `active_sql` (varsa — MODIFY_QUERY'den gelen bağlam)
- `active_filters`

Writes:
- `query_plan` (QueryPlan.model_dump())

LLM structured output: `QueryPlan`

---

### Node 2: `value_resolver` — Pure Python
**Tek Sorumluluk:** QueryPlan filtrelerindeki `value_hint`'leri gerçek DB değerlerine çevirmek.

Reads:
- `query_plan` (filters[].field_hint + value_hint)

Writes:
- `query_plan` (filters[].resolved_value eklendi)

`ValueResolverService.resolve(value_hint, resolved_column)` çağrısı per filter.
`column_semantic_map` ile `field_hint → DB kolon adı` eşleştirmesi yapılır.
Confidence < 75 olan değerler `value_hint` olarak bırakılır (LLM SQL'de LIKE kullanır).

---

### Node 3: `business_rules` — Pure Python
**Tek Sorumluluk:** user_query için alakalı business rule SQL bileşenlerini bulmak.

Reads:
- `user_query`

Writes:
- `business_rules_context` (merged SQL components: aggregation, filter, group_by, vb.)

`BusinessRulesVectorStore.get_relevant_rules_for_query()` çağrısı.
Sonuç: `merged_sql` dict → string olarak state'e yazılır.

---

### Node 4: `sql_builder` — LLM
**Tek Sorumluluk:** QueryPlan (resolved) + business rules + column_metadata → geçerli T-SQL.

Reads:
- `query_plan` (resolved_value'lar dahil)
- `business_rules_context`
- `sql_error` (retry durumunda — hatayı bilerek düzeltir)

Writes:
- `sql_queries` (List[str], genelde 1 SQL)

LLM structured output: `GeneratedSQL`

Value matching kuralları (prompt içinde):
- `resolved_value` varsa: `WHERE kolon = 'resolved_value'` (kesin eşleşme)
- `resolved_value` yoksa: `WHERE UPPER(kolon) LIKE UPPER('%value_hint%')` (fuzzy)
- Tarih: `YEAR(kolon) = ...`, `MONTH(kolon) = ...`, `CONVERT(date, ...)`
- Sayısal: doğrudan karşılaştırma

---

### Node 5: `sql_executor` — Pure Python
**Tek Sorumluluk:** SQL'i çalıştırmak ve retry yönetimi.

Reads:
- `sql_queries[0]`
- `retry_count`

Writes (başarıda):
- `results`
- `error = None`
- `active_sql` (conversation context güncelle)
- `active_results` (ilk 10 satır)
- `active_filters` (query_plan'dan çıkartılan filtreler)
- `retry_count = 0`

Writes (hata + retry < 2):
- `sql_error` (hata mesajı)
- `retry_count += 1`
- → `sql_builder`'a geri dön

Writes (hata + retry >= 2):
- `error` (kullanıcıya gösterilecek)
- `results = []`

DB: `pyodbc` + `ThreadPoolExecutor` (async uyumluluğu için).

---

## State Tasarımı

```python
class Text2SQLState(TypedDict, total=False):
    # ReportState overlapping keys (LangGraph otomatik map eder)
    user_query: str
    query_type: Optional[str]
    active_sql: Optional[str]
    active_filters: Optional[List[Dict]]
    sql_queries: Optional[List[str]]
    results: Optional[List[Dict]]
    error: Optional[str]
    active_results: Optional[List[Dict]]

    # Internal — subgraph içinde kalır, parent'a geçmez
    query_plan: Optional[Dict]             # QueryPlan.model_dump()
    business_rules_context: Optional[str]  # Merged SQL components string
    retry_count: int                       # 0-2
    sql_error: Optional[str]              # Son SQL hata mesajı
```

---

## Pydantic Modelleri

```python
class QueryFilter(BaseModel):
    field_hint: str
    operator: Literal["=", ">", "<", ">=", "<=", "!=", "LIKE", "IN",
                      "BETWEEN", "IS NULL", "IS NOT NULL"]
    value_hint: str
    resolved_value: Optional[str] = None   # value_resolver tarafından doldurulur
    logical_operator: Literal["AND", "OR"] = "AND"

class QueryAggregation(BaseModel):
    function: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]
    field_hint: str
    alias: str

class QueryPlan(BaseModel):
    description: str
    select_columns: List[str]             # Agg yoksa gösterilecek kolonlar
    filters: List[QueryFilter]
    aggregations: List[QueryAggregation]
    group_by: List[str]
    order_by_field: Optional[str] = None
    order_by_direction: Literal["ASC", "DESC"] = "DESC"
    limit: Optional[int] = None

class GeneratedSQL(BaseModel):
    sql: str
    explanation: str                       # Kolon eşleştirme kararları (debug)

class FixedSQL(BaseModel):
    sql: str
    fix_explanation: str
```

---

## Routing

```python
def _route_after_executor(state: Text2SQLState) -> str:
    if state.get("sql_error") and state.get("retry_count", 0) < 2:
        return "sql_builder"   # Retry
    return END
```

`sql_planner → value_resolver → business_rules → sql_builder → sql_executor` → conditional.
`sql_executor` → hata varsa → `sql_builder` → `sql_executor` (max 2 döngü).

---

## Kopyalanacak Dosyalar

Bu dosyalar **doğrudan kopyalanır**, import path'leri güncellenir:

```
src/graphs/generic_text2sql/value_resolver_service.py
  → src/graphs/report_agent/subagents/text2sql/value_resolver_service.py

src/graphs/generic_text2sql/business_rules_vector_store.py
  → src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py
```

Import path değişikliği dışında bu dosyalara dokunulmaz.

`business_rules.json` referansı: `sql_builder` node factory'sine path inject edilir.

---

## Dosya Yapısı

```
subagents/text2sql/
├── __init__.py                    # zaten var
├── state.py                       # Text2SQLState
├── prompts.py                     # QueryPlan, GeneratedSQL, FixedSQL + 2 prompt
├── nodes.py                       # 5 node factory fonksiyonu
├── graph.py                       # build_text2sql_graph — 5 node, 1 conditional edge
├── value_resolver_service.py      # kopyalandı (rapidfuzz + pyodbc cache)
└── business_rules_vector_store.py # kopyalandı (ChromaDB + hybrid search)
```

---

## Eski vs Yeni Karşılaştırma

| | Eski | Yeni |
|--|------|------|
| Node sayısı | 8 | 5 |
| Value resolution | Ayrı servis node (sql_architect sonrası ayrı step) | Node olarak pipeline'da |
| Business rules | ChromaDB (kopyalanıyor) | ChromaDB (kopyalanıyor) |
| Post-processing regex | 300+ satır | **Yok** |
| Temp table (create/cleanup) | Var | **Yok** |
| Metadata runtime discovery | Var (INFORMATION_SCHEMA sorgusu) | **Yok** (config'den) |
| LLM çağrısı/tur | 3-4 | 2 (planner + builder) |
