# NLU Pipeline Redesign — SemanticIntent Architecture

**Tarih:** 2026-04-21
**Kapsam:** Report Agent — Tam pipeline refactor (LLM/Python katman ayrımı)
**Durum:** Tasarım onaylandı, implementasyon planı bekleniyor

---

## 1. Motivasyon

Mevcut sistemde iki temel ihlal var:

1. **Yanlış katmanda kod:** `sql_architect` LLM'i hem semantik anlama hem SQL yapısal üretim yapıyor (407 satır prompt). Turkish suffix regex Python'da — LLM'in dil işi Python'a verilmiş.
2. **Yapısal güvenilmezlik:** SQL yapısal kuralları (GROUP BY, AND/OR, time granularity) LLM'e bırakılmış — deterministik olması gerekirken probabilistik.

**Temel prensip:**
```
LLM   = Semantic   → "Ne dendi?"  (dil anlama, niyet, entity çıkarımı)
Python = Operational → "Nasıl yapılır?" (SQL, kural, doğrulama, grounding)
ChromaDB = Schema mapping → "Bu terim hangi kolona karşılık geliyor?" (local, LLM'e veri gitmez)
```

---

## 2. Katman Sınırları

```
┌─────────────────────────────────────────────────────┐
│  LLM LAYER (Semantic)                               │
│  SQL bilgisi YOK · DB verisi YOK                    │
│  intent_resolver · semantic_extractor               │
│  term_validator · modify_sql · viz_decider          │
├─────────────────────────────────────────────────────┤
│  ChromaDB LAYER (Schema Mapping)  — LOCAL           │
│  term → DB kolon adı eşleştirmesi                   │
│  term_resolver                                      │
├─────────────────────────────────────────────────────┤
│  PYTHON LAYER (Operational)                         │
│  schema_builder · value_grounder · rule_engine      │
│  sql_generator · sql_executor · build_response      │
└─────────────────────────────────────────────────────┘
```

---

## 3. Bileşen Haritası (Eski → Yeni)

| Mevcut | Yeni | Değişim |
|--------|------|---------|
| `classify_intent` [LLM] | `intent_resolver` [LLM] | chart_type çağrısı kaldırıldı; `time_breakdown` field eklendi |
| `sql_architect` [LLM, 407 satır] | `semantic_extractor` [LLM, ~70 satır] | SQL yapısal bilgisi YOK; `SemanticIntent` üretir |
| `schema_validator` [LLM] | ❌ elimine | `schema_builder` Python ile replace |
| `merge_schemas` [Python] | ❌ elimine | gerekmiyor |
| — | `schema_builder` [Python] ← **YENİ** | `SemanticIntent` → `QuerySchema` deterministik dönüşüm |
| `term_store` [ChromaDB + regex] | `term_resolver` [ChromaDB] | Turkish suffix regex kaldırıldı |
| `term_validator` [LLM] | `term_validator` [LLM] | değişmez |
| `value_resolver_service` [Python] | `value_grounder` [Python] | `value_hint` artık zorunlu |
| `business_rules_node` [Python+LLM] | `rule_engine` [Python+LLM] | aggregation-specific uygulama |
| `sql_generator` [Python] | `sql_generator` [Python] | değişmez |
| `modify_sql` [LLM] | `modify_sql` [LLM] | değişmez |
| `viz_decider` [LLM] | `viz_decider` [LLM] | chart_type detection buraya taşındı |

**LLM çağrı sayısı:** max 6 → max 4-5  
**Input token:** ~8.000 → ~1.000 (sql_architect eşdeğeri, ~%85 azalma)

---

## 4. Merkezi Veri Modelleri

### 4.1 `SemanticIntent` — LLM/Python Kontratı

`SemanticIntent` LLM'in SQL bilgisi olmadan ürettiği saf semantik çıkarımdır.

```python
class SemanticEntity(BaseModel):
    raw_text: str
    entity_type: Literal["filter_value", "dimension", "comparison_value"]
    column_hint: Optional[str] = None      # LLM güçlü ipucu varsa

class SemanticMetric(BaseModel):
    raw_text: str
    aggregation_hint: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]

class SemanticTime(BaseModel):
    raw_text: str                          # "son 3 ay", "aylık", "bu yıl", "ocak 2024"
    breakdown: bool                        # True = GROUP BY kırılımı, False = WHERE filtresi

class SemanticIntent(BaseModel):
    entities:        List[SemanticEntity]
    metrics:         List[SemanticMetric]
    time:            Optional[SemanticTime]
    limit:           Optional[int]
    order_direction: Literal["ASC", "DESC"] = "DESC"
    raw_query:       str                   # orijinal sorgu (retry/debug için)
```

### 4.2 `TermMatch` — ChromaDB/Python Kontratı

`term_resolver` çıktısı; `schema_builder`'ın tükettiği tip.

```python
@dataclass
class TermMatch:
    column_name: str                       # "CategoryName", "RowAmount"
    filter_structured: Optional[Dict]      # filter term ise WHERE koşulu
    specificity: float                     # conflict resolution ağırlığı
    similarity: float                      # ChromaDB cosine similarity skoru
```

### 4.3 `SemanticTime` → `DateDescriptor` Dönüşümü (Python)

`SemanticTime.raw_text` `schema_builder` içinde deterministik Python fonksiyonu ile `DateDescriptor`'a çevrilir — LLM yapmaz.

```
Parser kural tablosu:
"son N ay/gün/yıl/hafta"  → relative, unit=month/day/year/week, amount=-N
"bu yıl/ay/gün/çeyrek"   → current_period, period=year/month/day/quarter
"geçen yıl/ay"            → relative, unit=year/month, amount=-1
"YYYY"                    → exact, value=YYYY-01-01 (yıl filtresi → iki SchemaFilter)
"[ay adı] YYYY"           → exact, value=YYYY-MM-01 (ay filtresi)
"DD [ay adı]"             → exact, value={current_year}-MM-DD
breakdown=True            → group_by ifadesi eklenir (time_granularity)
breakdown=False           → sadece WHERE filtresi
```

Bilinmeyen format → `SemanticExtractionError` → semantic_extractor retry (hata mesajıyla).

### Dönüşüm Tablosu (Örnek)

| LLM çıkarır | Python dönüştürür |
|---|---|
| `Entity("dürümler", filter_value)` | `CategoryName = 'Dürümler'` (term_resolver + value_grounder) |
| `Entity("ürünler", dimension)` | `GROUP BY ProductName` (term_resolver) |
| `Metric("ciro", SUM)` | `SUM(RowAmount) AS ToplamCiro` (term_resolver) |
| `Time("son 1 ay", breakdown=False)` | `DATEADD(MONTH,-1,today) >=` WHERE filter |
| `Time("aylık", breakdown=True)` | `GROUP BY YEAR(DocumentDate), MONTH(DocumentDate)` |
| `Entity("dürümler", comparison_value)` + `Entity("içecek", comparison_value)` | `CategoryName IN ('Dürümler','İçecek')` |

---

## 5. Bileşen Arayüzleri

### 5.1 `intent_resolver` [LLM]

```
Input:  user_query, conversation_history (son 6 msg)
Output: IntentResult
        - intent_type: NEW_QUERY | MODIFY_QUERY | USE_RESULT | VAGUE_QUERY
        - query_type: SINGLE | LISTING | RANKING | COMPARISON | TIME_SERIES_COMPARISON
        - wants_viz: bool
        - time_breakdown: bool   ← YENİ (TIME_SERIES sinyali)
        - use_result_type, compute_operation
HITL:   confidence < 0.70 → choice interrupt
Prompt: ~80 satır (mevcut INTENT_CLASSIFIER_PROMPT sadeleştirilir)
```

### 5.2 `semantic_extractor` [LLM] ← YENİ

```
Input:  user_query
        query_type (intent_resolver'dan)
        column_metadata (kolon ADI + TİP açıklaması — değer içermez)
        conversation_context (son 3 HumanMessage içeriği + active_sql[:500] varsa)
Output: SemanticIntent
HITL:   yok — hata schema_builder/value_grounder'da yakalanır
Prompt: ~70 satır, SQL bilgisi YOK
        Tek soru: "Bu sorguda hangi entity'ler, metrikler, zaman ifadeleri var?"
```

### 5.3 `term_resolver` [ChromaDB LOCAL]

```
Input:  SemanticIntent.entities + SemanticIntent.metrics (raw_text listesi)
Output: {raw_text → TermMatch} map  +  candidate_filter_terms (term_validator için)
HITL:   ambiguous term → choice interrupt (korunur)
Sıralama: term_resolver ÖNCE tamamlanır → term_validator SONRA (paralel DEĞİL)
          term_validator, term_resolver'ın candidate_filter_terms çıktısına bağımlı
Değişen: Turkish suffix regex KALDIRILDI
         Conflict resolution: similarity × specificity sort, ilk winner
         Threshold: per-category — term_dictionary.json entry'lerine opsiyonel
           `"similarity_threshold": float` field eklenir; yoksa category-based
           default: filter_structured içerenler = 0.85, diğerleri = 0.75
```

### 5.4 `term_validator` [LLM]

```
Input:  user_query + candidate_filter_terms (term_resolver çıktısı)
Output: approved_filter_ids
Sıralama: term_resolver tamamlandıktan SONRA başlar
Değişen: yok — SRP zaten doğruydu
```

### 5.5 `schema_builder` [Python] ← YENİ

```
Input:  SemanticIntent
        term_resolution map
        query_type + time_breakdown (intent_resolver'dan)
Output: QuerySchema (mevcut tip — sql_generator değişmez)
HITL:   yok — deterministik, hata → retry
Sorumluluk:
  Entity(filter_value) + TermMatch → SchemaFilter
    - value_hint: HER ZAMAN set edilir — SchemaFilter tipi Optional kalır (breaking
      change değil) ama schema_builder runtime'da None bırakmaz; test ile
      garanti altına alınır (test_value_hint_always_set)
    - operator: entity_type + column_hint'ten Python kuralıyla türetilir
  Entity(dimension) + TermMatch → group_by entry
  Entity(comparison_value) → SchemaFilter operator=IN, values=[...] (AND/OR hatası imkânsız)
  SemanticTime(breakdown=True) + query_type → time_granularity + group_by ifadeleri
    - "aylık" → YEAR(DocumentDate) + MONTH(DocumentDate)
    - "günlük" → CAST(DocumentDate AS DATE)
    - "haftalık" → YEAR(DocumentDate) + DATEPART(WEEK, DocumentDate)
    - Redundant zaman kolonu kontrolü: deterministik
  SemanticMetric + TermMatch → SchemaAggregation
  limit + order_direction → QuerySchema.limit + order_by_direction
  time_breakdown tutarlılık: intent_resolver time_breakdown=True ise
    SemanticIntent.time.breakdown False olsa bile schema_builder override eder
    (intent routing kararı semantic extractor çıktısından üstündür)
```

### 5.6 `value_grounder` [Python + DB]

```
Input:  QuerySchema.filters (value_hint ZORUNLU — schema_builder garantiliyor)
Output: resolved_value + confidence per filter
HITL:   not_found → text input interrupt
        50 ≤ conf < 75 → choice interrupt
        conf ≥ 75 → otomatik resolve
Değişen: value_hint None check kaldırıldı (artık mümkün değil)
```

### 5.7 `rule_engine` [Python + ChromaDB + opsiyonel LLM]

```
Input:  QuerySchema + user_query + query_type
Output: augmented QuerySchema
Değişen:
  is_default=true kurallar → HER ZAMAN Python uygular, LLM gate yok
  aggregation-specific: SUM/AVG için apply, COUNT için skip
  non-default kurallar → ChromaDB search + LLM gate (korunur)
  COMPARISON çakışma → _merge_conflicting_rule_filters (korunur)
```

### 5.8 `sql_generator` [Python]

```
Değişmez. Input/output aynı.
```

### 5.9 `viz_decider` [LLM]

```
Değişen: chart_type keyword detection buraya taşındı (intent_resolver'dan)
         _detect_chart_type_from_query() → viz_decider fallback olarak korunur
         SRP: "grafik kararı" tek yerde
```

---

## 6. Pipeline Akışı

### NEW_QUERY

```
intent_resolver
    │
    ▼
semantic_extractor
    │
    ▼
[ChromaDB] term_resolver          ← önce tamamlanır
    │  candidate_filter_terms üretir
    ▼
[LLM] term_validator              ← term_resolver çıktısına bağımlı, sıralı
    │
    ▼
                         [Python] schema_builder
                                   │
                                   ▼
                         [Python] value_grounder
                         (HITL olabilir)
                                   │
                                   ▼
                          [Python] rule_engine
                                   │
                                   ▼
                         [Python] sql_generator
                                   │
                                   ▼
                         [Python] sql_executor
                         (hata → semantic_extractor retry, max 2)
                                   │
                              wants_viz?
                                   │
                          [LLM] viz_decider (opsiyonel)
                                   │
                         [Python] build_response
```

### MODIFY_QUERY

```
intent_resolver → modify_sql [LLM]
    │  modification_hints üretir (string filtre değerleri)
    │  pre_built_sql state'e yazılır
    ▼
value_grounder (modification_hints için — HITL olabilir)
    │
    ▼
sql_executor → viz_decider → build_response
```

Not: `pre_built_sql` bypass `sql_generator`'ı atlar ama `value_grounder`
modification_hints'i çözümlemeye devam eder.

### USE_RESULT

```
intent_resolver (use_result_type belirlenir)
    │
    ├── revisualize  → viz_decider → build_response
    ├── compute      → compute_results [Python] → build_response
    └── new_query / modify_context
             │
             ▼
       extract_entity [LLM]  (mevcut sonuçtan entity çıkarır)
             │  new_query_seed (doğal dil)
             ▼
       semantic_extractor  (new_query_seed ile)
             │
             ▼  (NEW_QUERY akışının geri kalanı)
           ...  → sql_executor → build_response
```

### VAGUE_QUERY

```
intent_resolver (VAGUE_QUERY)
    │
    ▼
vague_handler [LLM]  → QueryClarificationResult (suggestions)
    │  interrupt (kullanıcıya öneriler)
    ▼
intent_resolver (tekrar — max 2 tur)
    │
    _clarification_count ≥ 2 → _skip_vague_check=True → NEW_QUERY zorla
```

### Retry

```
sql_executor HATA
    │
    retry_count < 2
    │
    ▼
sql_error state'e yaz → semantic_extractor'a dön
(sql_architect'e değil — hata genellikle anlama kaynaklı)
```

---

## 7. State Değişiklikleri

### Eklenen

```python
semantic_intent: Optional[Dict]   # SemanticIntent.model_dump() — semantic_extractor çıktısı
term_resolution: Optional[Dict]   # {raw_text → TermMatch dict} — term_resolver çıktısı
```

### Kaldırılan

```python
schema_validation   # schema_validator yok artık
term_hints          # semantic_extractor artık term_hints almıyor; ChromaDB çıktısı
                    # doğrudan schema_builder'a gidiyor
```

### Değişmeyen (geriye dönük uyumluluk)

```python
# Ana pipeline
query_schema, active_sql, active_results, active_filters
pre_built_sql, sql_error, auto_rules
time_granularity, comparison_dimension, modification_hints
validated_term_filters, candidate_filter_terms

# HITL
text2sql_clarification, text2sql_answers, _hitl_answered

# Conversation
messages, user_query, session_id, intent_type, query_type
intent_confidence, wants_visualization, requested_chart_type
use_result_type, compute_operation

# Loop koruma
_clarification_count, _skip_vague_check

# Response
results, error, final_response, visualization_output, viz_request
```

### Reset (her tur — `intent_resolver` sıfırlar)

```python
semantic_intent: None
term_resolution: None
pre_built_sql: None          # mevcut — korunur
time_granularity: None       # mevcut — korunur
modification_hints: None     # mevcut — korunur
text2sql_clarification: None
text2sql_answers: None
_hitl_answered: False
visualization_output: None
```

---

## 8. Hata Hiyerarşisi

```python
class NLUError(AppBaseException): pass
class SemanticExtractionError(NLUError): pass   # LLM parse failure
class TermResolutionError(NLUError): pass        # ChromaDB bulamadı
class SchemaBuilderError(NLUError): pass         # Python kural ihlali → retry
class ValueGroundingError(NLUError): pass        # DB'de değer yok → HITL
class SQLGenerationError(NLUError): pass         # SQL üretim hatası → retry
```

| Hata | Aksiyon |
|------|---------|
| `SemanticExtractionError` | retry (max 1) |
| `TermResolutionError` (ambiguous) | HITL interrupt |
| `SchemaBuilderError` | sql_error → semantic_extractor retry |
| `ValueGroundingError` (not found) | HITL interrupt |
| `ValueGroundingError` (low conf) | HITL interrupt (suggestions) |
| `SQLGenerationError` | sql_error → semantic_extractor retry |

---

## 9. Gözlemlenebilirlik — Log Standardı

Her bileşen üç log satırı:

```python
logger.info(f"[COMPONENT] INPUT: {özet}")
logger.info(f"[COMPONENT] DECISION: {karar} reason={gerekçe}")
logger.info(f"[COMPONENT] OUTPUT: {sonuç}")
# HITL varsa:
logger.warning(f"[COMPONENT] HITL: {tip} key={source_key}")
```

---

## 10. Test Stratejisi

### Birim Testleri (LangGraph'tan bağımsız)

```python
# schema_builder — pure Python
test_comparison_query_generates_IN_not_AND()
test_monthly_time_series_group_by()
test_daily_time_series_group_by()
test_value_hint_always_set()
test_redundant_time_column_not_generated()

# sql_generator — mevcut testler korunur
# value_grounder — DB mock ile
test_low_confidence_triggers_hitl()
test_not_found_triggers_hitl()
```

### LLM Evaluation Testleri (release öncesi)

```
intent_resolver:    30 sorgu → %90+ doğru sınıflandırma
semantic_extractor: 20 sorgu → entity/metric/time doğru çıkarım
```

### Golden Set (zorunlu, production öncesi)

```
30+ gerçek sorgu → expected SemanticIntent + expected SQL
CI'da schema_builder + sql_generator çalıştırılır (LLM çağrısı yok)
Her commit'te regresyon testi
```

---

## 11. Implementasyon Sırası (Yüksek Seviye)

```
Aşama 1 — Temel (bağımlılık yok):
  P1.1  SemanticIntent veri modeli yaz
  P1.2  schema_builder Python bileşeni yaz + birim testleri
  P1.3  term_resolver regex'i kaldır, threshold per-category ekle

Aşama 2 — LLM değişiklikleri:
  P2.1  semantic_extractor prompt yaz (~70 satır)
  P2.2  intent_resolver prompt sadeleştir (time_breakdown ekle)
  P2.3  viz_decider'a chart_type detection taşı

Aşama 3 — Entegrasyon:
  P3.1  text2sql subgraph node sırası güncelle
  P3.2  schema_validator + merge_schemas kaldır
  P3.3  State'e semantic_intent ekle, schema_validation kaldır
  P3.4  value_grounder value_hint zorunluluk kontrolü

Aşama 4 — Temizlik:
  P4.1  rule_engine aggregation-specific uygulama
  P4.2  Hata hiyerarşisi
  P4.3  Log standardı tüm bileşenlere
  P4.4  Golden set oluştur
```

---

## 12. `hitl_check_node` Rolü

`hitl_check_node` mevcut sistemde `text2sql` subgraph içindeki HITL sinyallerini `report_agent` üst graph seviyesine taşır. Bu mekanizma **değişmez**.

```
text2sql subgraph (value_grounder / term_resolver HITL)
    │  text2sql_clarification state'e yazar
    ▼
hitl_check_node (report_agent seviyesi)
    │  text2sql_clarification varsa → interrupt() çağırır
    ▼
HITL yanıt gelince → text2sql_answers state'e yazar → subgraph devam eder
```

---

## 13. Kapsam Dışı

- Supervisor routing → değişmez
- HITL mekanizması (dağıtık) → değişmez
- `modify_sql` → değişmez
- `sql_generator` → değişmez
- `build_response` → değişmez
- Visualization subgraph → değişmez (sadece chart_type taşıma)
- Insight pipeline (Phase 2) → ayrı spec

---

*Bu tasarım onaylandıktan sonra `superpowers:writing-plans` ile implementasyon planı oluşturulacak.*
