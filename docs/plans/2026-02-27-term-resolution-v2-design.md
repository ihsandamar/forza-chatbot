# Term Resolution v2 + Prompt/Context Engineering — Design

**Date:** 2026-02-27
**Status:** Approved

---

## Problem

`TermVectorStore` threshold=0.60 çok toleranslı → false positive filter terms WHERE'e giriyordu:
- `filter_return` (DocumentTypeIsReturn=1) — "ödemesi alınan" semantik yanlış eşleşme
- `filter_dine_in` (DocumentKindName='Masa') — "masalarda" yanlış channel filter
- `filter_main_product` (MenuId IS NULL) — "hangi ürün" yanlış eşleşme

Ayrıca `TermVectorStore` ile `BusinessRulesVectorStore` sorumluluk çakışması vardı.
`business_rules_path` hardcode'du, `ReportAgentConfiguration`'da görünmüyordu.

**Failing query:** "Son 1 senede ödemesi alınan masalarda en çok hangi ürün ne kadar ciro yaptı"
**Yanlış SQL:** `AND [DocumentTypeIsReturn] = 1 AND [DocumentKindName] = 'Masa' AND [MenuId] IS NULL`
**Doğru SQL:** sadece `AND [IsTableActive] = 0` (business rule: kapali_masa_filtre)

---

## Tasarım: 3 Katmanlı Koruma

### Katman 1 — Threshold Yükseltme
`_DEFAULT_SIMILARITY_THRESHOLD = 0.60 → 0.75`
Tek satır, savunma-derinliği.

### Katman 2 — Parallel LLM Validation Gate (term_validator_node)
BusinessRulesValidationResult pattern'i ile aynı mimari.
term_resolver → [sql_architect ∥ schema_validator ∥ **term_validator**] → schema_merge
Zero latency: schema_merge zaten 3'ü bekler (fan-in).

**TermValidationResult:**
```python
class TermValidationResult(BaseModel):
    approved_filter_ids: List[str]
    reasoning: str
```

Prompt mantığı: "filter_return için 'iade' açıkça geçiyor mu? Geçmiyorsa REDDET."

### Katman 3 — term_hints Yeniden Yapısı
```
## PYTHON-YÖNETİMLİ FİLTRELER (sen filters'a EKLEME — Python garantili uygular)
- IsTableActive = 0   (ödemesi alınan masa)

## KOLON İPUÇLARI (LLM için rehber)
- "ciro" [RowAmount] → SUM([RowAmount]) kullan
```

---

## Sorumluluk Ayrımı (Düzeltme)

| Sorumluluk | TermVectorStore | BusinessRulesVectorStore |
|---|---|---|
| Metrik/boyut ipuçları | ✅ | — |
| Ambiguity detection | ✅ | — |
| filter_return (iade) | ✅ | — |
| filter_treat (ikram) | ✅ | — |
| IsTableActive filter | ❌ KALKTI | ✅ kapali/acik_masa_filtre |
| MenuId filter | ❌ KALKTI | ✅ sadece_ana_urun |
| IsTreatWasteCancel | ❌ KALKTI | ✅ sadece_normal_satis |
| DocumentKindName | ❌ KALKTI | LLM + value_resolver |

**term_dictionary.json'dan kalkacaklar:**
filter_closed_table, filter_open_table, filter_main_product, filter_normal_sale, filter_dine_in, filter_delivery

---

## Business Rules Runtime Config

`ReportAgentConfiguration`'a eklenir:
```python
business_rules_path: str = Field(
    default="./src/graphs/generic_text2sql/business_rules.json",
    description="Business rules JSON dosya yolu",
)
```
`_get_configurable(config, "business_rules_path", default)` ile okunur.

---

## State Değişikliği

`Text2SQLState`'e tek yeni field:
```python
validated_term_filters: Optional[List[Dict[str, Any]]]
# term_validator onayladığı filter_structured listesi
# sql_generator bunu okur (term_filters yerine)
```

---

## Doğru Beklenen SQL (Failing Query Sonrası)

```sql
SELECT TOP 1 [ProductName],
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [DocumentDate] >= DATEADD(YEAR, -1, '2026-02-27')
    AND [IsTableActive] = 0
GROUP BY [ProductName]
ORDER BY [ToplamCiro] DESC
```

---

## Etkilenen Dosyalar

1. `term_vector_store.py` — threshold 0.75
2. `term_dictionary.json` — 6 filter term kaldırılır
3. `prompts.py` — TermValidationResult + TERM_VALIDATOR_PROMPT + SQL_ARCHITECT_PROMPT + SCHEMA_VALIDATOR_PROMPT
4. `text2sql/nodes.py` — create_term_validator_node + term_hints format + sql_generator validated_term_filters
5. `text2sql/state.py` — validated_term_filters field
6. `state.py` — validated_term_filters field (parent)
7. `text2sql/graph.py` — yeni node + edge + business_rules_path configurable
8. `configuration.py` — business_rules_path field
