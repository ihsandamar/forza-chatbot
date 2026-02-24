# Clean SQL Separation Design

**Date:** 2026-02-24
**Goal:** LLM sadece field mapping yapar, Python tüm SQL syntax'ını yazar.

## Problem

Mevcut sistemde LLM bazen SQL syntax üretiyor:
- `value` alanına `DATEADD(...)` yazıyor → sql_builder string'e quote ediyor
- `applied_rule_ids` seçiyor ama yanlış seçebiliyor
- `resolve_date` tool'u karmaşıklık katıyor

## Çözüm: Clean Separation

```
user_query
    ↓
business_rules_node (ChromaDB)
    → state.auto_rules [resolved rule dicts]   ← LLM görmez
    ↓
sql_architect_node (LLM)
    input:  user_query + column_metadata + term_hints
    output: QuerySchema (kolon adları + DateDescriptor)
            SADECE FIELD MAPPING — SQL syntax yok
    ↓
sql_generator_node (Python)
    input:  QuerySchema + state.auto_rules
    output: T-SQL (tüm syntax Python)
```

## LLM Sorumluluğu (sadece bunlar)

- Hangi kolon aggregate edilecek? (`RowAmount`)
- Hangi fonksiyon? (`SUM`)
- Hangi kolon group by? (`CategoryName`)
- Hangi filtreler? (`IsTableActive = 0`, tarih için `DateDescriptor`)
- Limit/order?

## Python Sorumluluğu (tüm SQL syntax)

- `DateDescriptor` → `DATEADD(YEAR, -1, '2026-02-24')`
- `auto_rules.aggregation` → `SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END)`
- `auto_rules.filter` → `WHERE [IsTableActive] = 0`
- Tüm SQL birleştirme

## Değişen Dosyalar

### 1. `prompts.py`
- `{business_rules_context}` bölümü kaldır — LLM kuralları görmez
- KURAL 6 (applied_rule_ids seçimi) kaldır
- KURAL 2 → DateDescriptor'a geri dön (resolve_date tool talimatı kaldır)
- `{term_hints}` kalır

### 2. `nodes.py` — `create_sql_architect_node`
- Tool-calling loop kaldır (`llm.bind_tools`, `HumanMessage`, `ToolMessage`, `resolve_date` import)
- Direkt `llm.with_structured_output(QuerySchema)` kullan
- `business_rules_context` prompt'a geçilmez

### 3. `nodes.py` — `create_business_rules_node`
- `individual_rules` → `state["auto_rules"]` olarak yaz
- `business_rules_context` text'i kaldır (LLM görmeyecek)

### 4. `state.py` — `Text2SQLState`
- `auto_rules: List[Dict]` field ekle
- `business_rules_context: str` kaldır (artık kullanılmıyor)

### 5. `sql_builder.py` — `generate_sql`
- `full_rules_data: List[Dict]` parametresi → `auto_rules: List[Dict]` olarak değiştir
- `applied_rule_ids` lookup kaldır — `auto_rules` direkt `applied_rules` olur

### 6. `graph.py`
- `full_rules_data` yükleme bloğu kaldır
- `create_sql_generator_node(table_name, full_rules_data)` → `create_sql_generator_node(table_name)`
- `sql_generator_node` `auto_rules`'ı `state`'ten okur

### 7. `prompts.py` — `QuerySchema`
- `applied_rule_ids: List[str]` kaldır

## Kaldırılan Dosya/Import'lar
- `date_tool.py` kullanımı kaldır (import, tool binding)
- `HumanMessage`, `ToolMessage` import'ları kaldır

## Beklenen Sonuç

```sql
-- "Son 1 senede ödemesi alınan masaların kategorilere göre en çok ciro yapan kategori"

SELECT TOP 1 [CategoryName],
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [IsTableActive] = 0
  AND [DocumentDate] >= DATEADD(YEAR, -1, '2026-02-24')
GROUP BY [CategoryName]
ORDER BY [ToplamCiro] DESC
```

LLM üretir: `{aggregation: SUM+RowAmount, group_by: CategoryName, filters: [IsTableActive=0, DocumentDate relative year -1], limit: 1}`
Python yazar: tüm SQL syntax
