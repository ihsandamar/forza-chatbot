# Text2SQL Subagent Redesign

**Tarih:** 2026-02-23
**Branch:** fix/report-agent-sql
**Hedef:** Deterministik, hızlı, doğru T-SQL üretimi

---

## Problem

Mevcut `report_agent/text2sql` subagent'ı:
- 2 LLM çağrısı (planner + builder) — gereksiz
- `sql_builder` LLM tabanlı — deterministik değil, hata yapıyor
- Tarih çözme eksik — "son 3 ay" gibi ifadeler güvenilmez
- GROUP BY / SELECT alignment rehberi yetersiz
- Prompt kalitesi generic_text2sql'in çok gerisinde

---

## Seçilen Yaklaşım: Collapsed Architect + Python SQL Builder

### Graph Akışı

```
START
  ↓
create_table      ← Pure Python (no-op if no query config)
  ↓
business_rules    ← Pure Python: ChromaDB semantic search → applied_rules state'e yaz
  ↓
sql_architect     ← LLM (TEK ÇAĞRI): NL → QuerySchema
  ↓
value_resolver    ← Pure Python: fuzzy match → interrupt() if low confidence
  ↓
sql_generator     ← Pure Python: QuerySchema → T-SQL (NO LLM)
  ↓
sql_executor      ← Pure Python: execute, hata → sql_architect'e dön (max 2 retry)
  ↓
cleanup_table     ← Pure Python (no-op if no query config)
  ↓
END
```

**LLM çağrısı:** Normal akışta **1**, retry'da **max +2**

---

## Pydantic Modeller (prompts.py)

### DateDescriptor

LLM tarih niyetini yapısal olarak üretir, Python DATEADD'e çevirir.

```python
class DateDescriptor(BaseModel):
    type: Literal["exact", "relative", "current_period"]
    # exact        → value: "2024-01-15"
    # relative     → unit + amount: -3 ay geçmiş
    # current_period → period: bu ay / bu yıl / bugün
    unit:   Optional[Literal["day", "month", "year", "quarter"]] = None
    amount: Optional[int] = None   # Geçmiş: negatif, gelecek: pozitif
    period: Optional[Literal["day", "month", "year", "quarter"]] = None
    value:  Optional[str] = None   # "YYYY-MM-DD" formatı
```

### SchemaFilter

```python
class SchemaFilter(BaseModel):
    column:           str        # Gerçek DB kolon adı
    operator:         Literal["=", ">", "<", ">=", "<=", "!=", "LIKE",
                               "IS NULL", "IS NOT NULL", "BETWEEN"]
    value:            Optional[str] = None
    date_descriptor:  Optional[DateDescriptor] = None  # Tarih filtresi ise
    value_hint:       Optional[str] = None   # Orijinal kullanıcı değeri (fuzzy için)
    logical_operator: Literal["AND", "OR"] = "AND"
    # value_resolver tarafından doldurulur:
    resolved_value:   Optional[str] = None
    resolution_confidence: Optional[float] = None
```

### SchemaAggregation

```python
class SchemaAggregation(BaseModel):
    function: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]
    column:   str    # Gerçek DB kolon adı
    alias:    str    # Sonuç kolon alias'ı
```

### QuerySchema (LLM Çıktısı)

```python
class QuerySchema(BaseModel):
    description:        str
    select_columns:     List[str]   # Boş ise aggregation sonuçları kullanılır
    filters:            List[SchemaFilter]
    aggregations:       List[SchemaAggregation]
    group_by:           List[str]   # Gerçek kolon adları veya SQL expression
    order_by_column:    Optional[str] = None
    order_by_direction: Literal["ASC", "DESC"] = "DESC"
    limit:              Optional[int] = None
    applied_rule_ids:   List[str] = []  # Business rule ID'leri (Python uygular)
```

**Kural:** Aggregation varsa `select_columns` boş, `group_by` dolu olmalı.

---

## SQL Architect Prompt Tasarımı

### Inject Edilen Bağlam

| Alan | Kaynak |
|------|--------|
| `today_date` | Python `date.today()` |
| `current_year`, `current_month` | Python |
| `column_metadata` | Runtime config (ReportAgentConfiguration) |
| `business_rules_context` | ChromaDB semantic search çıktısı |
| `query_type` | ReportState (classify_intent node'dan) |
| `conversation_context` | active_sql + active_filters (opsiyonel) |

### Prompt Kuralları

```
KURAL 1 — Kolon adları
  SADECE column_metadata'daki gerçek DB adlarını kullan.
  "tarih" değil → column_metadata'dan doğru adı bul.

KURAL 2 — Tarih (DateDescriptor ile)
  "son 3 ay"  → {type:"relative", unit:"month", amount:-3}
  "bu yıl"    → {type:"current_period", period:"year"}
  "bu ay"     → {type:"current_period", period:"month"}
  "bugün"     → {type:"current_period", period:"day"}
  "15 ocak"   → {type:"exact", value:"{current_year}-01-15"}
  Tarih için value alanını KULLANMA, date_descriptor kullan.

KURAL 3 — GROUP BY zorunluluğu
  Aggregation varsa: SELECT'teki non-aggregate her kolon group_by'da OLMALI.
  YANLIŞ: select=[X], aggregations=[SUM(Y)], group_by=[]
  DOĞRU:  select_columns=[], aggregations=[SUM(Y)], group_by=[X]

KURAL 4 — RANKING sorguları
  limit + order_by + en az 1 aggregation zorunlu.

KURAL 5 — Business rules
  applied_rule_ids'e uygulanacak rule ID'lerini yaz.
  SQL BİLEŞENLERİNİ kendin yazma — Python uygular.

KURAL 6 — Periyodik gruplama
  "günlük" → group_by: ["CAST(col AS DATE)"]
  "aylık"  → group_by: ["YEAR(col)", "MONTH(col)"]
  "yıllık" → group_by: ["YEAR(col)"]
```

---

## Python SQL Generator (sql_builder.py)

```python
def generate_sql(
    schema: QuerySchema,
    table_name: str,
    business_rules: list[dict],
    today: date,
) -> str:
    ...
```

### DateDescriptor → SQL

```
relative(month, -3)    → col >= DATEADD(MONTH, -3, '2025-02-23')
current_period(month)  → YEAR(col) = 2025 AND MONTH(col) = 2
current_period(year)   → YEAR(col) = 2025
current_period(day)    → CAST(col AS DATE) = '2025-02-23'
exact("2024-01-15")    → col = '2024-01-15'
```

### Business Rules SQL Ekleme

```python
for rule_id in schema.applied_rule_ids:
    rule = find_rule(rule_id, business_rules)
    if rule["sql_filter"]:
        where_parts.append(rule["sql_filter"])
    if rule["sql_aggregation"]:
        # SUM(col) → SUM(CASE WHEN ... THEN col ELSE 0 END)
        wrap_aggregation(rule["sql_aggregation"])
```

---

## Value Resolver & interrupt()

```
confidence ≥ 75   → resolved_value doldur, devam
confidence 50–74  → interrupt("'tunalı' için 'TUNALI ŞUBESİ' mi?", options)
confidence < 50   → interrupt("'{value_hint}' için lütfen tam değeri girin")
```

---

## Dosya Yapısı

| Dosya | Değişiklik |
|-------|-----------|
| `prompts.py` | Tüm modeller yeniden yazılır: QuerySchema + DateDescriptor + SchemaFilter + SchemaAggregation + SQL_ARCHITECT_PROMPT |
| `nodes.py` | `sql_planner` → `sql_architect` (config RunnableConfig ile tarih inject), `sql_builder` → `sql_generator` (Python çağrısı) |
| `sql_builder.py` | **YENİ** — Pure Python SQL üretici |
| `graph.py` | business_rules node create_table'dan sonraya, sql_generator eklenir |
| `state.py` | `query_plan` → `query_schema` field adı güncellenir |

### Silinecek

- `SQL_BUILDER_PROMPT`, `GeneratedSQL`, `FixedSQL`
- `QueryPlan`, `QueryFilter`, `QueryAggregation` (yerini `QuerySchema` alır)

---

## Başarı Kriterleri

- [ ] Tek LLM çağrısı ile doğru SQL üretimi
- [ ] Tarih ifadeleri deterministik Python kodu ile çözülüyor
- [ ] GROUP BY / SELECT alignment hatası yok
- [ ] Business rules SQL bileşenleri Python tarafında uygulanıyor
- [ ] Düşük confidence → interrupt() çalışıyor
