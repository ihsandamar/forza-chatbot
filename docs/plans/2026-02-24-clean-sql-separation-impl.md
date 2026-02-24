# Clean SQL Separation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** LLM sadece field mapping (kolon adları + DateDescriptor) üretir; business rules Python tarafından otomatik uygulanır; SQL syntax hiçbiri LLM'den çıkmaz.

**Architecture:** `business_rules_node` → `state.auto_rules` (resolved rule dicts) yazar. `sql_architect` tool-calling loop olmadan direkt `QuerySchema` üretir (`applied_rule_ids` yok, `business_rules_context` görmez). `sql_generator` `auto_rules`'ı state'ten okur ve `sql_builder`'a direkt geçer.

**Tech Stack:** Python 3.12, Pydantic, LangChain structured output, LangGraph

**Referans dosyalar:**
- `src/graphs/report_agent/subagents/text2sql/prompts.py`
- `src/graphs/report_agent/subagents/text2sql/state.py`
- `src/graphs/report_agent/subagents/text2sql/nodes.py`
- `src/graphs/report_agent/subagents/text2sql/sql_builder.py`
- `src/graphs/report_agent/subagents/text2sql/graph.py`

---

## Task 1: prompts.py — QuerySchema ve SQL_ARCHITECT_PROMPT güncelle

**File:** `src/graphs/report_agent/subagents/text2sql/prompts.py`

**Step 1: `applied_rule_ids` alanını QuerySchema'dan kaldır**

```python
class QuerySchema(BaseModel):
    """
    sql_architect node'unun structured output'u.
    Tüm alanlar gerçek DB kolon adları içerir — Python bu şemadan SQL üretir.
    Business rules Python tarafından otomatik uygulanır (LLM seçmez).
    """
    description:        str
    select_columns:     List[str]
    filters:            List[SchemaFilter]
    aggregations:       List[SchemaAggregation]
    group_by:           List[str]
    order_by_column:    Optional[str] = None
    order_by_direction: Literal["ASC", "DESC"] = "DESC"
    limit:              Optional[int] = None
    # applied_rule_ids KALDIRILDI — Python auto_rules'dan uygular
```

**Step 2: SQL_ARCHITECT_PROMPT'ı yeniden yaz**

`{business_rules_context}` bölümü ve `## UYGULANACAK İŞ KURALLARI` kaldır. KURAL 2 DateDescriptor'a dön. KURAL 6 kaldır. KURAL 7 → KURAL 6 olarak yeniden numarala.

Yeni prompt:

```python
SQL_ARCHITECT_PROMPT = """Sen bir T-SQL sorgu mimarısın. Kullanıcı sorusunu analiz et ve yapılandırılmış bir sorgu şeması (QuerySchema) üret.

## SORGUDA TESPİT EDİLEN İŞ TERİMLERİ (Doğrudan Uygula)
{term_hints}

## BUGÜNÜN TARİHİ
- Tarih: {today_date}
- Yıl: {current_year}
- Ay: {current_month}
- Çeyrek: {current_quarter}

## KULLANICI SORUSU
{user_query}

## SORGU TİPİ
{query_type}

## VERİTABANI KOLON BİLGİLERİ
{column_metadata}

## KONUŞMA BAĞLAMI
{conversation_context}

## ÖNCEKİ SQL HATASI (varsa — şemayı buna göre düzelt)
{sql_error}

---

## KURALLAR

### KURAL 0 — Terim Eşleştirmeleri (EN YÜKSEK ÖNCELİK)
"SORGUDA TESPİT EDİLEN İŞ TERİMLERİ" bölümündeki eşleştirmeleri MUTLAKA uygula.
Bu bölümdeki filtreler ve kolon seçimleri kesindir — column_metadata'dan bağımsız olarak geçerlidir.

### KURAL 1 — Kolon Adları
SADECE yukarıdaki KOLON BİLGİLERİ'ndeki gerçek DB adlarını kullan.
Kullanıcı "şube" derse → kolon açıklamalarına bak, doğru DB kolon adını yaz.
Hiçbir zaman "tarih", "şube", "tutar" gibi Türkçe field_hint yazma — gerçek DB adını yaz.

### KURAL 2 — Tarih Filtreleri (DateDescriptor ZORUNLU)
Sorguda tarih ifadesi varsa ("son 3 ay", "bu yıl", "ocak 2024" gibi):
  date_descriptor alanını doldur — value alanını KULLANMA.

Örnekler:
  "son 3 ay"      → {{"type":"relative","unit":"month","amount":-3}},   operator: ">="
  "son 7 gün"     → {{"type":"relative","unit":"day","amount":-7}},     operator: ">="
  "son 1 yıl"     → {{"type":"relative","unit":"year","amount":-1}},    operator: ">="
  "bu yıl"        → {{"type":"current_period","period":"year"}},        operator: ">="
  "bu ay"         → {{"type":"current_period","period":"month"}},       operator: ">="
  "bugün"         → {{"type":"current_period","period":"day"}},         operator: ">="
  "bu çeyrek"     → {{"type":"current_period","period":"quarter"}},     operator: ">="
  "15 ocak"       → {{"type":"exact","value":"{current_year}-01-15"}},  operator: "="
  "ocak 2024"     → iki filter: >= {{"type":"exact","value":"2024-01-01"}}
                              ve <= {{"type":"exact","value":"2024-01-31"}}

Tarih filtresi için value alanını KULLANMA — date_descriptor kullan.

### KURAL 3 — GROUP BY Zorunluluğu (KRİTİK)
Aggregation varsa:
  - select_columns: BOŞ bırak []
  - group_by: tüm non-aggregate kolonları ekle
  - aggregations: SUM/COUNT/AVG/MAX/MIN ile doldur

YANLIŞ ❌:
  select_columns=["ProductName"], aggregations=[SUM(Quantity)], group_by=[]

DOĞRU ✅:
  select_columns=[], aggregations=[SUM(Quantity) AS TotalQty], group_by=["ProductName"]

### KURAL 4 — RANKING Sorguları
"Top 10 / en çok / en az / sıralama" → limit + order_by_column + en az 1 aggregation ZORUNLU.
Örnek: "en çok satan 10 ürün" → aggregations=[SUM(Quantity)], group_by=["ProductName"],
       order_by_column="TotalQty", order_by_direction="DESC", limit=10

### KURAL 5 — Periyodik Gruplama
"günlük satışlar"  → group_by: ["CAST(TarihKolonu AS DATE)"]
"aylık satışlar"   → group_by: ["YEAR(TarihKolonu)", "MONTH(TarihKolonu)"]
"yıllık satışlar"  → group_by: ["YEAR(TarihKolonu)"]
"saatlik dağılım"  → group_by: ["CAST(TarihKolonu AS DATE)", "HourKolonu"]
Tarih kolonu adını column_metadata'dan al.

### KURAL 6 — Hata Düzeltme
ÖNCEKİ SQL HATASI varsa:
  - Hata mesajını analiz et
  - Yanlış kolon adı → column_metadata'dan doğrusunu bul
  - GROUP BY hatası → Kural 3'ü uygula
  - Syntax hatası → ilgili field'ı düzelt
"""
```

**Step 3: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.prompts import QuerySchema, SQL_ARCHITECT_PROMPT; print('OK')"
```

Beklenen: `OK`

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "refactor(text2sql): remove applied_rule_ids from QuerySchema, revert KURAL 2 to DateDescriptor, remove KURAL 6"
```

---

## Task 2: state.py — `auto_rules` ekle, `business_rules_context` kaldır

**File:** `src/graphs/report_agent/subagents/text2sql/state.py`

**Step 1: State'i güncelle**

```python
from typing import Any, Dict, List, Optional, TypedDict


class Text2SQLState(TypedDict, total=False):
    """
    Text2SQL subagent state.

    Overlapping keys (LangGraph otomatik parent ReportState ile sync eder):
        user_query, query_type, active_sql, active_filters,
        sql_queries, results, error, active_results

    Internal keys (sadece bu subgraph içinde kullanılır):
        query_schema, auto_rules, retry_count, sql_error
    """

    # --- ReportState overlapping ---
    user_query: str
    query_type: Optional[str]
    active_sql: Optional[str]
    active_filters: Optional[List[Dict[str, Any]]]
    sql_queries: Optional[List[str]]
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]

    # --- Internal ---
    query_schema: Optional[Dict[str, Any]]       # QuerySchema.model_dump()
    auto_rules:   Optional[List[Dict[str, Any]]] # ChromaDB'den bulunan rules — sql_generator uygular
    retry_count:  int                            # 0 | 1 | 2
    sql_error:    Optional[str]                  # Son SQL hata mesajı (retry için)
    # business_rules_context KALDIRILDI — LLM artık kuralları görmüyor
```

**Step 2: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState; print('OK')"
```

Beklenen: `OK`

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/state.py
git commit -m "refactor(text2sql): replace business_rules_context with auto_rules in Text2SQLState"
```

---

## Task 3: nodes.py — `business_rules_node` güncelle

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: `create_business_rules_node`'u güncelle**

`business_rules_context` text üretimini kaldır. `auto_rules` listesini state'e yaz.

```python
def create_business_rules_node(vector_store: BusinessRulesVectorStore) -> Callable:
    """
    Pure Python: user_query → state.auto_rules (resolved rule dicts).
    ChromaDB semantic search. sql_generator bu listeyi direkt uygular.
    LLM business rules görmez.
    """

    async def business_rules_node(state: dict) -> dict:
        user_query = state.get("user_query", "")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _db_executor,
            lambda: vector_store.get_relevant_rules_for_query(
                user_query=user_query,
                n_results=5,
                use_hybrid=True,
            ),
        )

        individual_rules = result.get("individual_rules", [])
        logger.info(
            f"[BUSINESS_RULES] {result['total_count']} rules "
            f"({result['default_count']} default, {result['semantic_count']} semantic)"
        )
        return {"auto_rules": individual_rules}

    return business_rules_node
```

> **Not:** `_format_rule_sql_hint` helper artık kullanılmıyor — silinebilir.

**Step 2: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.nodes import create_business_rules_node; print('OK')"
```

Beklenen: `OK`

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "refactor(text2sql): business_rules_node writes auto_rules to state instead of business_rules_context"
```

---

## Task 4: nodes.py — `sql_architect_node` sadeleştir

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: Import bölümünden tool-calling import'larını kaldır**

Şu satırları kaldır:
```python
from langchain_core.messages import HumanMessage, ToolMessage
from src.graphs.report_agent.subagents.text2sql.date_tool import resolve_date
```

**Step 2: `create_sql_architect_node`'u yeniden yaz**

```python
def create_sql_architect_node(llm, column_metadata: Dict[str, Any]) -> Callable:
    """
    LLM (STRUCTURED OUTPUT): user_query → QuerySchema.

    LLM sadece field mapping yapar:
      - Hangi kolon aggregate edilecek
      - Hangi kolon group by
      - Hangi filtreler (DateDescriptor ile tarihler)
    Business rules Python (sql_generator) tarafından auto_rules'dan uygulanır.
    """
    structured_llm = llm.with_structured_output(QuerySchema)

    async def sql_architect_node(state: dict, *, config: RunnableConfig = None) -> dict:
        user_query             = state.get("user_query", "")
        query_type             = state.get("query_type", "SINGLE")
        active_sql             = state.get("active_sql")
        active_filters         = state.get("active_filters") or []
        sql_error              = state.get("sql_error") or "Yok"
        effective_metadata     = _get_configurable(config, "column_metadata", column_metadata)
        today                  = date.today()

        # Konuşma bağlamı
        conversation_context = "Yeni sorgu, önceki bağlam yok."
        if active_sql:
            conversation_context = f"Önceki SQL: {active_sql[:300]}"
            if active_filters:
                conversation_context += f"\nAktif filtreler: {json.dumps(active_filters[:3], ensure_ascii=False)}"

        # Terim eşleştirme
        term_hints = resolve_terms(user_query)

        prompt = SQL_ARCHITECT_PROMPT.format(
            term_hints=term_hints,
            user_query=user_query,
            query_type=query_type,
            today_date=today.isoformat(),
            current_year=today.year,
            current_month=today.month,
            current_quarter=(today.month - 1) // 3 + 1,
            column_metadata=json.dumps(effective_metadata, ensure_ascii=False, indent=2),
            conversation_context=conversation_context,
            sql_error=sql_error,
        )

        logger.info(f"[SQL_ARCHITECT] Planning: {user_query[:80]} (type={query_type})")
        schema: QuerySchema = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[SQL_ARCHITECT] Schema: filters={len(schema.filters)}, "
            f"aggs={len(schema.aggregations)}, group_by={schema.group_by}, "
            f"limit={schema.limit}"
        )
        return {
            "query_schema": schema.model_dump(),
            "sql_error": None,
        }

    return sql_architect_node
```

**Step 3: `_format_rule_sql_hint` helper'ı kaldır** (artık kullanılmıyor)

**Step 4: Docstring güncelle (nodes.py başı)**

```python
    sql_architect        - LLM (STRUCTURED OUTPUT): user_query → QuerySchema (field mapping only)
```

**Step 5: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.nodes import create_sql_architect_node; print('OK')"
```

Beklenen: `OK`

**Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "refactor(text2sql): sql_architect_node - remove tool-calling loop, direct structured output, no business_rules_context"
```

---

## Task 5: sql_builder.py — `generate_sql` imzasını güncelle

**File:** `src/graphs/report_agent/subagents/text2sql/sql_builder.py`

**Step 1: `generate_sql` fonksiyonunu güncelle**

`full_rules_data` parametresini `auto_rules` olarak değiştir, `applied_rule_ids` lookup'ı kaldır.

```python
def generate_sql(
    schema_dict: Dict[str, Any],
    table_name: str,
    auto_rules: List[Dict[str, Any]],
    today: date,
) -> str:
    """
    QuerySchema dict + auto_rules + bugünün tarihi → T-SQL string.

    Args:
        schema_dict: QuerySchema.model_dump() çıktısı
        table_name:  Hedef tablo adı (runtime config'ten gelir)
        auto_rules:  business_rules_node'dan gelen resolved rule listesi (direkt uygulanır)
        today:       Bugünün tarihi (tarih çözme için)

    Returns:
        Executable T-SQL string
    """
    # auto_rules direkt applied_rules olarak kullan (ID lookup yok)
    applied_rules = auto_rules

    if applied_rules:
        logger.info(f"[SQL_GENERATOR] Applying {len(applied_rules)} auto rules: {[r.get('id') for r in applied_rules]}")

    # ... (geri kalan kod aynı)
```

Kaldırılacak satırlar:
```python
# ESKİ — kaldır:
applied_ids: List[str] = schema_dict.get("applied_rule_ids", [])
applied_rules = [r for r in full_rules_data if r.get("id") in applied_ids]
```

**Step 2: Smoke test**

```bash
python -c "
from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
from datetime import date
schema = {
    'select_columns': [],
    'filters': [{'column': 'DocumentDate', 'operator': '>=', 'date_descriptor': {'type': 'relative', 'unit': 'year', 'amount': -1}, 'logical_operator': 'AND'}],
    'aggregations': [{'function': 'SUM', 'column': 'RowAmount', 'alias': 'ToplamCiro'}],
    'group_by': ['CategoryName'],
    'order_by_column': 'ToplamCiro',
    'order_by_direction': 'DESC',
    'limit': 1,
    'description': 'test',
}
auto_rules = [{'id': 'iade_dusulmus', 'sql': {'aggregation': 'SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END)', 'filter': None, 'group_by': None}, 'is_default': True}]
sql = generate_sql(schema, 'MasterReportDocumentTable', auto_rules, date(2026, 2, 24))
print(sql)
assert 'CASE WHEN' in sql, 'Business rule uygulanmadi'
assert 'DATEADD(YEAR' in sql, 'Tarih filtresi yok'
assert \"'DATEADD\" not in sql, 'DATEADD string literal olarak wrap edildi'
print('PASS')
"
```

Beklenen çıktı:
```sql
SELECT TOP 1 [CategoryName],
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [DocumentDate] >= DATEADD(YEAR, -1, '2026-02-24')
GROUP BY [CategoryName]
ORDER BY [ToplamCiro] DESC
PASS
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/sql_builder.py
git commit -m "refactor(sql-builder): replace full_rules_data+applied_rule_ids with direct auto_rules parameter"
```

---

## Task 6: nodes.py — `sql_generator_node` state'ten `auto_rules` okusun

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: `create_sql_generator_node`'u güncelle**

`full_rules_data` parametresini kaldır. `auto_rules`'ı state'ten oku.

```python
def create_sql_generator_node(
    default_table_name: str,
) -> Callable:
    """
    Pure Python: QuerySchema + state.auto_rules → T-SQL. LLM kullanmaz.
    """

    async def sql_generator_node(state: dict, *, config: RunnableConfig = None) -> dict:
        raw_schema = state.get("query_schema")
        if not raw_schema:
            return {"error": "QuerySchema bulunamadı", "results": []}

        table_name = _get_configurable(config, "table_name", default_table_name)
        auto_rules = state.get("auto_rules") or []
        today = date.today()

        try:
            sql = generate_sql(raw_schema, table_name, auto_rules, today)
            logger.info(f"[SQL_GENERATOR] SQL ready: {sql[:200]}")
            return {"sql_queries": [sql]}
        except Exception as e:
            logger.error(f"[SQL_GENERATOR] Build error: {e}")
            return {"error": f"SQL oluşturulamadı: {e}", "results": []}

    return sql_generator_node
```

**Step 2: Import doğrula**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.nodes import create_sql_generator_node; print('OK')"
```

Beklenen: `OK`

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "refactor(text2sql): sql_generator_node reads auto_rules from state, removes full_rules_data param"
```

---

## Task 7: graph.py — `full_rules_data` yüklemeyi kaldır

**File:** `src/graphs/report_agent/subagents/text2sql/graph.py`

**Step 1: `full_rules_data` yükleme bloğunu kaldır**

Şu bloğu tamamen sil:
```python
# --- Full rules data (sql_generator için) ---
try:
    with open(business_rules_path, "r", encoding="utf-8") as f:
        rules_json = json.load(f)
    full_rules_data = (
        rules_json if isinstance(rules_json, list)
        else rules_json.get("business_logic_rules", rules_json.get("rules", []))
    )
    logger.info(f"[TEXT2SQL] Loaded {len(full_rules_data)} business rules for sql_generator")
except Exception as e:
    logger.warning(f"[TEXT2SQL] Could not load business rules JSON: {e}")
    full_rules_data = []
```

**Step 2: `create_sql_generator_node` çağrısını güncelle**

```python
# ESKİ:
sql_generator = create_sql_generator_node(table_name, full_rules_data)

# YENİ:
sql_generator = create_sql_generator_node(table_name)
```

**Step 3: `json` import'una bak** — eğer başka yerde kullanılmıyorsa kaldır. Şu an `json` import'u `column_metadata` JSON dump için kullanılıyor — kalabilir.

**Step 4: Import doğrula**

```bash
python -c "
from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph
print('OK')
"
```

Beklenen: `OK`

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py
git commit -m "refactor(text2sql): remove full_rules_data loading from graph - auto_rules comes from state"
```

---

## Task 8: Uçtan uca doğrulama

**Step 1: Tüm modülleri import et**

```bash
python -c "
from src.graphs.report_agent.subagents.text2sql.prompts import QuerySchema, SQL_ARCHITECT_PROMPT
from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
from src.graphs.report_agent.subagents.text2sql.nodes import (
    create_business_rules_node,
    create_sql_architect_node,
    create_sql_generator_node,
)
from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph
print('All imports OK')
assert 'applied_rule_ids' not in QuerySchema.model_fields, 'applied_rule_ids hala QuerySchema icinde!'
assert 'auto_rules' in Text2SQLState.__annotations__, 'auto_rules state icinde yok!'
print('Schema checks OK')
"
```

**Step 2: `SQL_ARCHITECT_PROMPT` format test**

```bash
python -c "
from src.graphs.report_agent.subagents.text2sql.prompts import SQL_ARCHITECT_PROMPT
result = SQL_ARCHITECT_PROMPT.format(
    term_hints='test',
    user_query='test',
    query_type='SINGLE',
    today_date='2026-02-24',
    current_year=2026,
    current_month=2,
    current_quarter=1,
    column_metadata='{}',
    conversation_context='yok',
    sql_error='Yok',
)
assert '{business_rules_context}' not in result
assert 'KURAL 6' not in result
assert 'applied_rule_ids' not in result
assert 'DateDescriptor' in result or 'date_descriptor' in result
print('Prompt format OK')
"
```

**Step 3: langgraph dev yeniden başlat ve LangGraph Studio'da test**

Test sorgusu:
```
Son 1 senede ödemesi alınan masaların kategorilere göre en çok ciro yapan kategori nedir?
```

Beklenen SQL:
```sql
SELECT TOP 1 [CategoryName],
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [IsTableActive] = 0
  AND [DocumentDate] >= DATEADD(YEAR, -1, '2026-02-24')
GROUP BY [CategoryName]
ORDER BY [ToplamCiro] DESC
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(text2sql): clean SQL separation complete - LLM field mapping only, Python all SQL syntax"
```
