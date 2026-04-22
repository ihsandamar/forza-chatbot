# Report Agent — NLU & Business Logic Pipeline

> Kullanıcının girdiği doğal dil sorgusunun iş mantığına (SQL + visualization) dönüştürüldüğü katmanların tam referansı.

---

## İçindekiler

1. [Genel Mimari Akışı](#1-genel-mimari-akışı)
2. [Supervisor Routing](#2-supervisor-routing)
3. [Intent Classification](#3-intent-classification)
4. [Term Resolver](#4-term-resolver)
5. [Value Resolver Service](#5-value-resolver-service)
6. [SQL Architect (Text2SQL NLU)](#6-sql-architect-text2sql-nlu)
7. [Business Rules](#7-business-rules)
8. [Column Metadata](#8-column-metadata)
9. [SQL Generator (Pure Python)](#9-sql-generator-pure-python)
10. [Modify Query Yolu](#10-modify-query-yolu)
11. [Vague Query & Clarification Loop](#11-vague-query--clarification-loop)
12. [Visualization Decision](#12-visualization-decision)
13. [HITL & Interrupt Noktaları](#13-hitl--interrupt-noktaları)
14. [State Yönetimi](#14-state-yönetimi)
15. [Graph Akışı (Routing)](#15-graph-akışı-routing)
16. [Uçtan Uca Örnek](#16-uçtan-uca-örnek)

---

## 1. Genel Mimari Akışı

```
USER INPUT
    ↓
[Supervisor Agent]         → REPORT_AGENT / ROUTING_AGENT / CHAT_AGENT kararı
    ↓
[classify_intent]          → NEW_QUERY / MODIFY_QUERY / USE_RESULT / VAGUE_QUERY
    ↓
[term_resolver]            → term_filters (Python garantili) + term_hints (LLM tavsiyesi)
    ↓
[sql_architect]  (LLM)    → QuerySchema (filtreler, aggregation, group by, time granularity...)
[schema_validator](LLM)   → paralel doğrulama
    ↓
[business_rules]           → auto_rules (default + semantic search + LLM validation)
    ↓
[value_resolver]           → filter değerlerini DB'deki gerçek değerlere eşle
    ↓
[sql_generator]  (Python) → T-SQL
    ↓
[sql_executor]             → Sonuçlar
    ↓
[viz_decider]    (LLM)    → chart_type + alan haritalaması
    ↓
[build_response]           → Tablo / Grafik / Hata
```

---

## 2. Supervisor Routing

**Dosya:** `src/graphs/supervisor/prompts.py:8-54`

Kullanıcı mesajı hangi agent'a gideceğine burada karar verilir:

| Agent | Tetikleyiciler |
|---|---|
| **REPORT_AGENT** | "rapor", "analiz", "göster", "listele", "grafik", "chart", SQL/veri sorguları |
| **ROUTING_AGENT** | "nerede", "hangi sayfada", navigasyon/dokümantasyon |
| **CHAT_AGENT** | Genel sohbet, açıklamalar |

---

## 3. Intent Classification

**Dosya:** `src/graphs/report_agent/nodes.py:89-253`
**Prompt:** `src/graphs/report_agent/prompts.py:98-180` — `INTENT_CLASSIFIER_PROMPT`

### Intent Tipleri

| Intent | Açıklama |
|---|---|
| `NEW_QUERY` | Yeni bir veri sorgusu |
| `MODIFY_QUERY` | Önceki sorguyu değiştir |
| `USE_RESULT` | Önceki sonuçları kullan (revisualize / compute / new_query / modify_context) |
| `VAGUE_QUERY` | Çok genel / belirsiz — clarification gerekli |

### Query Tipleri

| Query Type | Açıklama | Örnek |
|---|---|---|
| `SINGLE` | Tek metrik veya toplam | "Toplam ciro nedir?" |
| `LISTING` | Boyuta göre listeleme | "İstanbul şubelerinin satışları" |
| `RANKING` | Sıralama / Top-N | "En çok satan 10 ürün" |
| `COMPARISON` | İki+ grup karşılaştırması (zaman granülaritesi YOK) | "Dürüm vs Pizza karşılaştırması" |
| `TIME_SERIES_COMPARISON` | Dönemsel kırılım (zaman granülaritesi VAR) | "Son 1 ayın aylık trendi" |

### Structured Output: `IntentClassificationResult`
**Dosya:** `src/graphs/report_agent/prompts.py:10-28`

```python
class IntentClassificationResult:
    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY"]
    query_type: Literal["SINGLE", "LISTING", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float                    # 0.0–1.0
    wants_visualization: bool
    use_result_type: Optional[Literal["new_query", "revisualize", "compute", "modify_context"]]
    compute_operation: Optional[Literal["sum", "avg", "count", "min", "max"]]
    modification_action: Optional[str]
    modification_target: Optional[str]
    modification_value: Optional[str]
```

### Confidence Eşikleri

```
CONFIDENCE_THRESHOLD        = 0.70   # Genel intent — altında interrupt()
MODIFY_AMBIGUITY_THRESHOLD  = 0.85   # MODIFY_QUERY — daha yüksek güven gerekli
```

**Girdi:** son 4 mesaj (conversation_history), user_query, has_active_sql, result_count
**Chart type:** Paralel LLM çağrısı → `ChartTypeResult`; başarısız olursa `_detect_chart_type_from_query()` (keyword fallback, satır 70-86)

---

## 4. Term Resolver

**Dosya:** `src/graphs/report_agent/subagents/text2sql/stores/term_store.py`
**Veri:** `src/graphs/report_agent/data/vector/term_dictionary.json`

### Amaç

Kullanıcının doğal dil ifadelerini (ör: "dürümler", "İstanbul", "ciro") DB kolonlarına ve filtre değerlerine bağlar. Sonuçlar SQL Architect LLM'e geçmeden önce Python katmanında garanti altına alınır.

### TermStore Metotları

| Metot | Satır | Açıklama |
|---|---|---|
| `__init__()` | 113 | ChromaDB + dict_path + similarity_threshold (default 0.75) |
| `initialize()` | 133 | Graph startup'ta bir kez — ChromaDB collection oluştur, JSON yükle |
| `_build_index()` | 174 | JSON → embedding → ChromaDB |
| `resolve()` | 207 | **Ana metot** — keyword_pre_resolve → semantic_search → conflict_resolution |
| `_keyword_pre_resolve()` | 225 | Threshold bağımsız exact alias match, longest-match-first |
| `_semantic_search()` | 300 | ChromaDB cosine similarity; threshold < 0.75 olanlar elenir |
| `_apply_conflict_resolution()` | 344 | Unambiguous → resolved, Ambiguous → suppress veya interrupt |

### Term Dictionary Yapısı (JSON)

```json
{
  "id": "metric_revenue",
  "category": "metric",
  "term": "ciro",
  "aliases": ["satış tutarı", "tutar"],
  "column": "RowAmount",
  "specificity": 1.0,
  "hint": "...",
  "filter_structured": null,
  "ambiguous_columns": []
}
```

### Üç Aşamalı Resolve Pipeline

**Aşama 1 — Keyword Pre-Resolve** (satır 225-294)
- Sorgu metninde exact alias match
- Longest-match-first: "satış tutarı" > "tutar"
- filter_structured ve ambiguous_columns olanlar bu aşamada işlenmez
- Threshold bağımsız (güvenilir)

**Aşama 2 — Semantic Search** (satır 300-338)
- ChromaDB cosine similarity, Top-K=15
- Distance → Similarity: `similarity = 1 - distance`
- threshold=0.75 altındakiler elenir

**Aşama 3 — Conflict Resolution** (satır 344-483)
- Sıralama: `similarity × specificity` (azalan)
- **Unambiguous term** (column var, ambiguous_columns boş):
  - `filter_structured` → `term_filters` (Python garantili WHERE filter)
  - Yoksa → `column_hint_lines` (LLM'e tavsiye)
- **Ambiguous term** (ambiguous_columns var):
  - Tüm/kısmen resolved → SUPPRESS (conflict çözülmüş)
  - Hiçbiri → INTERRUPT (kullanıcıya sor)

### TermResolverOutput

```python
@dataclass
class TermResolverOutput:
    term_filters: List[Dict]          # Python garantili WHERE filtreler
    candidate_filter_terms: List[Dict]# term_validator LLM gate için bekleyen
    hints_text: str                   # PYTHON-YÖNETİMLİ + KOLON İPUÇLARI bölümleri
    ambiguous: List[AmbiguousMatch]  # interrupt() için belirsiz terimler
```

### Term Durum Tablosu

| Durum | Tanım | Sonuç |
|---|---|---|
| **Resolved** | conflict_resolution'dan geçti | term_filters veya hints_text'e eklenir |
| **Ambiguous** | ambiguous_columns var, çakışma var | interrupt() → kullanıcı seçer |
| **Suppressed** | Ambiguous ama başka kolon zaten resolved | Hint olarak eklenir, interrupt çıkmaz |

---

## 5. Value Resolver Service

**Dosya:** `src/graphs/report_agent/subagents/text2sql/value_resolver_service.py`

### Amaç

SQL Architect'in ürettiği filter değerlerini (`value_hint`) DB'deki gerçek değerlere eşler. Örn: kullanıcı "dürümler" yazdıysa DB'de "Dürümler" veya "DÜRÜMLER" olabilir.

### Public Metotlar

| Metot | Satır | İmza |
|---|---|---|
| `initialize()` | 168 | Tablo şemasını keşfet, cache stratejisi belirle, semantic mapping init |
| `resolve()` | 254 | `(user_input, column, threshold=75)` → `{original, resolved, confidence, column}` veya None |
| `resolve_column_name()` | 579 | Semantic/natural language kolon adını DB kolona çevir |
| `get_column_aliases()` | 636 | DB kolon için tüm semantic alias'larını döndür |

### Column Semantic Mapping (satır 482-577)

`resolve_column_name()` içinde kullanılır. Normalize (lowercase, Türkçe karakter → ASCII, boşluk/underscore kaldır) sonrası:

| Alias (normalize) | DB Kolonu |
|---|---|
| `tutar`, `satistutar`, `toplam` | `RowAmount` |
| `miktar`, `adet` | `Quantity` |
| `tarih`, `tarihsaat` | `DocumentDate` |
| `sube`, `subeadi` | `BranchName` |
| `urun`, `urunadi` | `ProductName` |
| `kategori`, `kategoriadi` | `CategoryName` |
| `sehir`, `sehiradi` | `BranchCityName` |
| `musteri`, `musteriadi` | `CustomerName` |
| `kasiyer` | `CashierName` |
| `indirim`, `indirimimtutar` | `DiscountAmountTotal` |

### Fuzzy Matching

**Kütüphane:** `rapidfuzz`

**Scorer Hiyerarşisi:**

| Scorer | Ağırlık | Açıklama |
|---|---|---|
| `fuzz.ratio` | 1.00 | Tam eşleşme |
| `fuzz.token_sort_ratio` | 0.95 | Kelime sırası önemsiz |
| `fuzz.token_set_ratio` | 0.90 | Kısmi eşleşme |
| `fuzz.partial_ratio` | 0.80 | Substring |

**Kelime sayısı penaltisi:** `diff > 2 → ×0.85`, `diff > 1 → ×0.92`, `diff > 0 → ×0.97`

### Cache Stratejisi

| Distinct Count | Strateji | Max Kayıt | TTL |
|---|---|---|---|
| ≤20 | `full_cache` | +10 | 1440 dk (24h) |
| ≤100 | `full_cache` | +20 | 240 dk (4h) |
| ≤500 | `full_cache` | 500 | 60 dk |
| ≤1000 | `full_cache` | 1000 | 30 dk |
| >1000 | `db_search` | 20 | 15 dk |

`full_cache`: INFORMATION_SCHEMA → tüm distinct değerler belleğe alınır
`db_search`: Her sorguda LIKE ile DB aranır

### interrupt() Tetikleme Senaryoları

| Senaryo | Source Key | Kullanıcıya |
|---|---|---|
| Değer DB'de yok | `vr_*_not_found__<hint>` | "Doğru değeri girin" |
| Düşük confidence (50–75) | `vr_*_choice__<hint>` | Seçenekler dropdown |
| Manuel giriş seçildi | `vr_*_manual__<hint>` | Metin input |

---

## 6. SQL Architect (Text2SQL NLU)

**Dosya:** `src/graphs/report_agent/subagents/text2sql/nodes.py`
**Prompt:** `src/graphs/report_agent/subagents/text2sql/prompts.py:145-552` — `SQL_ARCHITECT_PROMPT`

### Girdi

```
user_query          — Kullanıcı sorusu
query_type          — intent sınıflandırmasından gelen (SINGLE / RANKING / ...)
term_hints          — TermResolver'dan: PYTHON-YÖNETİMLİ + KOLON İPUÇLARI
column_metadata     — DB kolon açıklamaları (JSON string)
conversation_context— Son mesajlar (zamir çözümü)
today_date/current_year/current_month/current_quarter — Tarih bağlamı
sql_error           — Varsa önceki SQL hatası (retry path)
```

### Structured Output: `QuerySchema`
**Dosya:** `src/graphs/report_agent/subagents/text2sql/prompts.py:86-106`

```python
class QuerySchema:
    description: str
    select_columns: List[str]
    filters: List[SchemaFilter]
    aggregations: List[SchemaAggregation]
    group_by: List[str]
    time_granularity: Optional[Literal["hourly","daily","weekly","monthly","yearly",
                                       "hour_of_day","day_of_week","day_of_month"]]
    comparison_dimension: Optional[str]
    order_by_column: Optional[str]
    order_by_direction: Literal["ASC", "DESC"]
    limit: Optional[int]
```

### SchemaFilter (satır 61-77)

```python
class SchemaFilter:
    column: str
    operator: Literal["=",">","<",">=","<=","!=","LIKE","IS NULL","IS NOT NULL",
                      "BETWEEN","IN","NOT IN"]
    value: Optional[str]
    values: Optional[List[str]]
    date_descriptor: Optional[DateDescriptor]
    value_hint: Optional[str]          # Fuzzy match için orijinal kullanıcı değeri
    logical_operator: Literal["AND","OR"]
    resolved_value: Optional[str]      # value_resolver tarafından doldurulur
    resolution_confidence: Optional[float]
```

### DateDescriptor (satır 45-59)

```python
class DateDescriptor:
    type: Literal["exact", "relative", "current_period"]
    unit: Optional[Literal["day","month","year","quarter"]]
    amount: Optional[int]    # Negatif = geçmiş
    period: Optional[Literal["day","month","year","quarter"]]
    value: Optional[str]     # "YYYY-MM-DD" (exact için)
```

### Schema Validator (Second Opinion)

**Prompt:** `src/graphs/report_agent/subagents/text2sql/prompts.py:559-598`

SQL Architect ile **paralel** çalışır. GROUP BY, filters, limit üzerinde bağımsız LLM doğrulaması. Output: `SchemaValidationResult`

### Term Validator (LLM Gate)

**Prompt:** `src/graphs/report_agent/subagents/text2sql/prompts.py:112-138`

TermResolver'ın `candidate_filter_terms`'ini doğrular. Kullanıcı terimi **açıkça** belirtmemişse reddeder.

```python
class TermValidationResult:
    approved_filter_ids: List[str]  # Onaylanan term ID'leri
    reasoning: str
```

---

## 7. Business Rules

**Store Dosyası:** `src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py`
**Veri:** `src/graphs/report_agent/data/vector/business_rules.json`
**Validator Prompt:** `src/graphs/report_agent/subagents/text2sql/prompts.py:717+` — `BUSINESS_RULES_VALIDATOR_PROMPT`

### BusinessRulesStore Metotları

| Metot | Satır | Açıklama |
|---|---|---|
| `initialize()` | 60 | ChromaDB collection oluştur, JSON yükle |
| `search_rules()` | 161 | `(query, n_results=5, include_defaults=True)` → semantic search |
| `get_relevant_rules_for_query()` | 268 | Hybrid: semantic + keyword search |
| `keyword_search()` | 212 | Keyword bazlı search |
| `merge_sql_components()` | 231 | Kuralları SQL bileşenlerine birleştir |

### Kural Yapısı (JSON)

```json
{
  "id": "iade_dusulmus",
  "description": "İade tutarlarını negatif al",
  "is_default": true,
  "sql": {
    "aggregation": "CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[{column}] ELSE [{column}] END",
    "filter": null,
    "group_by": null,
    "select": null,
    "join": null,
    "having": null
  }
}
```

### Mevcut Kurallar

| Kural ID | Default | SQL Etkisi | Tetikleyici |
|---|---|---|---|
| `iade_dusulmus` | ✅ Evet | Aggregation: `CASE WHEN DocumentTypeIsReturn=1 THEN -column` | Her sorgu |
| `kapali_masa_filtre` | ❌ | WHERE: `[IsTableActive] = 0` | "kapalı masalar" kelimeleri |
| `acik_masa_filtre` | ❌ | WHERE: `[IsTableActive] = 1` | "açık masalar" kelimeleri |
| `sadece_normal_satis` | ❌ | WHERE: `DocumentDetailIsTreatWasteCancel IS NULL` | Açıkça belirtilince |
| `sadece_ana_urun` | ❌ | WHERE: `MenuId IS NULL OR MenuId = '00000...'` | Açıkça belirtilince |

### SQL'e Uygulanma (`sql_builder.py`)

- `aggregation`: `_build_select_parts()` (satır 155-205) — agg_rule varsa SUM ifadesi replace edilir
- `filter`: `_build_where()` (satır 208-237) — AND ile WHERE'e eklenir
- `group_by`: `_build_group_by()` (satır 240-254) — ek GROUP BY eklemeleri

**COMPARISON query'lerde çakışan rule filter'lar:** `_merge_conflicting_rule_filters_for_comparison()` (nodes.py satır 1009-1065) — IN operatörüne çevirir

### Business Rules Node (nodes.py:943)

```
vector_search(user_query) → kural adayları
    ↓
[opsiyonel] LLM validator (business_rules_validator)
    ↓
auto_rules → state'e yazılır → sql_generator'a geçer
```

---

## 8. Column Metadata

**Dosya:** `src/graphs/report_agent/configuration.py:305-348`

### Yapı

`Dict[str, str]` — basit dict. Her giriş: `"KolonAdı": "Açıklama (tip ipucu)"`

### Mevcut Kolonlar

| Kolon | Açıklama |
|---|---|
| `DocumentDate` | Satış tarihi (datetime) |
| `DocumentId` | Adisyon ID (guid). Adisyon toplam hesaplarken GROUP BY DocumentId gerekli |
| `DayOfWeek` | Gün (1=Pazartesi…7=Pazar) |
| `Hour` | Saat (0-23) |
| `IsTableActive` | Masa durumu. 1: Açık, 0: Kapalı |
| `ProductName` | Ürün adı |
| `CategoryName` | Kategori adı |
| `MenuId` | NULL/Empty Guid = ana ürün; değer var = menü içi seçenek |
| `Quantity` | Satış miktarı (adet) |
| `RowAmount` | Satış tutarı (TL) |
| `DiscountAmountTotal` | İndirim tutarı (TL) |
| `DocumentDetailIsTreatWasteCancel` | Null: Normal, 1: İkram, 2: Zayi, 3: İptal |
| `BranchName` | Şube adı |
| `BranchCityName` | Şehir |
| `BranchTownName` | İlçe |
| `DocumentTypeName` | İşlem tipi |
| `DocumentKindName` | Satış kanalı |
| `DocumentTypeIsReturn` | İade mi? (0: Normal, 1: İade) |
| `CashierName` | Kasiyer adı |
| `DeliveryUserName` | Kurye adı |
| `CustomerName` | Müşteri adı |
| `TableNo` | Masa numarası |

### SQL Architect'e Aktarım

```python
# nodes.py satır ~600
column_metadata = json.dumps(effective_metadata, ensure_ascii=False, indent=2)

SQL_ARCHITECT_PROMPT.format(
    column_metadata=column_metadata,
    ...
)
```

Prompt içinde `## VERİTABANI KOLON BİLGİLERİ` başlığı altında JSON string olarak geçer.

### Tip İpuçları (Description String)

LLM bu açıklamaları okuyarak tip çıkarımı yapar:
- `"(datetime)"` → DateDescriptor, CAST(DocumentDate AS DATE)
- `"(adet)"` → Sayısal, `>`, `<`, `BETWEEN`
- `"(TL)"` → Decimal, aggregation uygulanabilir
- `"1: Açık, 0: Kapalı"` → Boolean (0/1), `=` operatörü

### Yeni Kolon Ekleme

1. `configuration.py:305-348` — metadata dict'e ekle
2. Opsiyonel: `term_dictionary.json` — term/alias ekle
3. Opsiyonel: `value_resolver_service.py:_init_column_semantic_mapping()` — semantic alias ekle
4. Opsiyonel: `business_rules.json` — kural ekle

---

## 9. SQL Generator (Pure Python)

**Dosya:** `src/graphs/report_agent/subagents/text2sql/sql_builder.py`
**Ana fonksiyon:** `generate_sql(schema_dict, table_name, auto_rules, today)`

### Girdiler

- `QuerySchema` (dict olarak) — architect'ten
- `term_filters` — TermResolver'dan Python garantili filtreler
- `auto_rules` — BusinessRules'tan
- `today` — Tarih referansı

### Çıktı

Geçerli T-SQL string.

### SQL Üretim Adımları

```
1. _build_select_parts()    → SELECT kolon listesi + aggregation + auto_rule agg modifier
2. _build_where()           → WHERE: term_filters + schema filters + auto_rule filters
3. _build_group_by()        → GROUP BY + auto_rule group_by eklemeleri
4. _build_order_by()        → ORDER BY
5. LIMIT                    → TOP N (SQL Server syntax)
6. DateDescriptor → SQL     → relative dates Python'da hesaplanır (DATEADD vs.)
```

---

## 10. Modify Query Yolu

**Node:** `src/graphs/report_agent/nodes.py:270-358` — `create_modify_sql_node()`
**Prompt:** `src/graphs/report_agent/prompts.py:182-249` — `SQL_MODIFIER_PROMPT`

### Girdi

- `active_sql` — Mevcut sorgu
- `user_query` — Değişiklik isteği
- `active_results` — Önceki sonuçların ilk 5 satırı
- `conversation_context` — Son 6 mesaj (zamir çözümü için)

### Structured Output: `SqlModificationResult`

```python
class SqlModificationResult:
    modified_sql: str
    explanation: str
    confidence: float
    modification_hints: List[ModificationHint]   # DB kolon + embedded_value
```

### Kurallar

- Mevcut SQL yapısını koru (WHERE → AND ile ekle)
- SELECT/GROUP BY/ORDER BY sadece talep varsa değişir
- `CAST([DocumentDate] AS DATE)` zorunlu
- LIKE ile `%wildcard%` kullanımı
- Zamir referansları son 6 mesajdan çözülür

**Confidence < 0.5 → interrupt()** — kullanıcıya açıklama istenir

### pre_built_sql Bypass

Modify SQL başarılı olunca `pre_built_sql` state'e yazılır. `sql_generator_node` bunu görünce LLM çağrısını atlar, direkt SQL kullanır.

**Dosyalar:** `state.py`, `text2sql/state.py`, `nodes.py: modify_sql_node` ve `sql_generator_node`

---

## 11. Vague Query & Clarification Loop

**Node:** `src/graphs/report_agent/nodes.py:364-410` — `create_report_chat_node()`
**Prompt:** `src/graphs/report_agent/prompts.py:269-286` — `QUERY_CLARIFICATION_PROMPT`

### Output: `QueryClarificationResult`

```python
class QueryClarificationResult:
    message: str           # Kullanıcıya açıklama
    suggestions: List[str] # 3-4 spesifik sorgu önerisi
```

### Loop Koruması

```python
MAX_CLARIFICATION_TURNS = 2      # satır 361
```

- 2 tur aşılırsa `_skip_vague_check = True` → VAGUE → NEW_QUERY olarak işlenir

---

## 12. Visualization Decision

**Dosya:** `src/graphs/report_agent/subagents/visualization_v2/prompts.py:8+` — `VIZ_DECIDER_PROMPT`

### Girdi

- `conversation_context`, `user_query`
- `query_type`, `time_granularity`
- `wants_visualization` (intent classifier'dan)
- `column_info` — kolon bilgileri
- `sample_rows` — ilk 3 satır

### Çıktı

- `needs_graph: bool`
- `chart_type` — bar_chart, line_chart, pie_chart, scatter_chart, heatmap, sunburst, treemap
- `x_field`, `y_field`, `series_field` — alan haritalaması

---

## 13. HITL & Interrupt Noktaları

| Node | Dosya:Satır | Koşul | Kullanıcıya |
|---|---|---|---|
| `classify_intent` | nodes.py:193-197 | confidence < 0.70 | Intent seçimi |
| `modify_sql` | nodes.py:325-338 | confidence < 0.50 | Açıklama iste |
| `report_chat` | nodes.py:394-398 | VAGUE_QUERY | Sorgu önerileri |
| `term_resolver` | term_store.py | Ambiguous term | Değer seçimi |
| `value_resolver` | value_resolver_service.py | Not found / low confidence | Değer giriş/seçim |
| `hitl_check_node` | nodes.py:723-743 | text2sql subgraph clarification sinyali | Upstream interrupt |

---

## 14. State Yönetimi

**Dosya:** `src/graphs/report_agent/state.py`

### ReportState (Seçilmiş Alanlar)

```python
class ReportState(TypedDict):
    # Core
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    session_id: Optional[str]

    # Intent
    intent_type: Optional[str]             # NEW_QUERY | MODIFY_QUERY | USE_RESULT | VAGUE_QUERY
    query_type: Optional[str]              # SINGLE | LISTING | RANKING | COMPARISON | TIME_SERIES_COMPARISON
    intent_confidence: Optional[float]
    wants_visualization: Optional[bool]
    requested_chart_type: Optional[str]
    use_result_type: Optional[str]         # revisualize | compute | new_query | modify_context
    compute_operation: Optional[str]       # sum | avg | count | min | max

    # Conversation Cache
    active_sql: Optional[str]
    active_results: Optional[List[Dict]]
    active_filters: Optional[List[Dict]]

    # Text2SQL Pipeline
    sql_queries: Optional[List[str]]
    pre_built_sql: Optional[str]           # Bypass: modify_sql → sql_generator
    time_granularity: Optional[str]
    comparison_dimension: Optional[str]
    modification_hints: Optional[List[Dict]]
    results: Optional[List[Dict]]
    error: Optional[str]
    candidate_filter_terms: Optional[List[Dict]]
    validated_term_filters: Optional[List[Dict]]

    # Visualization
    viz_request: Optional[str]
    visualization_output: Optional[Dict]

    # Loop Protection
    _clarification_count: Optional[int]
    _skip_vague_check: Optional[bool]

    # HITL
    text2sql_clarification: Optional[dict]
    text2sql_answers: Optional[list]
    _hitl_answered: bool

    # Response
    final_response: Optional[str]
```

---

## 15. Graph Akışı (Routing)

**Dosya:** `src/graphs/report_agent/graph.py`

```
START
  ↓
classify_intent
  ├─ NEW_QUERY         → text2sql → hitl_check → visualization → build_response → END
  ├─ MODIFY_QUERY      → modify_sql → text2sql → hitl_check → visualization → build_response → END
  ├─ USE_RESULT
  │   ├─ revisualize   → visualization → build_response → END
  │   ├─ compute       → compute_results → build_response → END
  │   ├─ new_query     → extract_entity → text2sql → ... → END
  │   └─ modify_context→ extract_entity → modify_sql → text2sql → ... → END
  ├─ VAGUE_QUERY       → report_chat → classify_intent  [max 2 tur]
  └─ (fallback)        → text2sql → ...
```

### Text2SQL Subgraph İç Akışı

```
term_resolver
  ↓
sql_architect  ─── (paralel) ─── schema_validator
  ↓
term_validator
  ↓
business_rules
  ↓
value_resolver
  ↓
sql_generator
  ↓
sql_executor
```

---

## 16. Uçtan Uca Örnek

**Sorgu:** *"Dürümler kategorisinin son 1 aydaki aylık satış trendi"*

```
[SUPERVISOR]
  → REPORT_AGENT

[classify_intent]
  → intent: NEW_QUERY
  → query_type: TIME_SERIES_COMPARISON
  → wants_visualization: true
  → confidence: 0.95 → interrupt yok

[term_resolver]
  "dürümler" → semantic search → CategoryName filter (term_filter: Python garantili)

[sql_architect]  LLM
  Girdi:
    query_type: TIME_SERIES_COMPARISON
    term_hints: "CategoryName = 'dürümler'" (Python-garantili, EKLE deme)
    column_metadata: { DocumentDate, CategoryName, RowAmount, ... }
  
  QuerySchema:
    filters:       [CategoryName = "dürümler"]
    aggregations:  [SUM(RowAmount) AS ToplamCiro]
    group_by:      ["YEAR(DocumentDate)", "MONTH(DocumentDate)"]
    time_granularity: "monthly"
    order_by:      YEAR(DocumentDate) ASC

[business_rules]
  auto_rules: [iade_dusulmus] (is_default=true)
  aggregation modifier: SUM → CASE WHEN DocumentTypeIsReturn=1 THEN -RowAmount ELSE RowAmount END

[value_resolver]
  "dürümler" → DB'de "Dürümler" → confidence: 0.97 → otomatik resolve

[sql_generator]  Pure Python
  SELECT
    YEAR([DocumentDate]) AS Yil,
    MONTH([DocumentDate]) AS Ay,
    SUM(CASE WHEN [DocumentTypeIsReturn]=1 THEN -[RowAmount] ELSE [RowAmount] END) AS ToplamCiro
  FROM [MasterReportDocumentTable]
  WHERE [CategoryName] = 'Dürümler'
    AND CAST([DocumentDate] AS DATE) >= DATEADD(MONTH,-1,CAST(GETDATE() AS DATE))
  GROUP BY YEAR([DocumentDate]), MONTH([DocumentDate])
  ORDER BY YEAR([DocumentDate]) ASC, MONTH([DocumentDate]) ASC

[sql_executor]
  → [{"Yil":2026,"Ay":3,"ToplamCiro":15000.50}, ...]

[viz_decider]
  → needs_graph: true
  → chart_type: line_chart
  → x_field: Yil+Ay, y_field: ToplamCiro

[build_response]
  → Plotly line chart iframe + özet metin
```

---

## Hızlı Referans — Dosya Tablosu

| Dosya | Satır | Konu |
|---|---|---|
| `report_agent/nodes.py` | 89-253 | classify_intent_node |
| `report_agent/nodes.py` | 270-358 | modify_sql_node |
| `report_agent/nodes.py` | 364-410 | report_chat_node (VAGUE) |
| `report_agent/nodes.py` | 413-440 | extract_entity_node |
| `report_agent/nodes.py` | 571-628 | compute_results_node |
| `report_agent/nodes.py` | 655-720 | build_response_node |
| `report_agent/nodes.py` | 723-743 | hitl_check_node |
| `report_agent/prompts.py` | 98-180 | INTENT_CLASSIFIER_PROMPT |
| `report_agent/prompts.py` | 182-249 | SQL_MODIFIER_PROMPT |
| `report_agent/prompts.py` | 269-286 | QUERY_CLARIFICATION_PROMPT |
| `report_agent/graph.py` | 37-69 | _intent_router() |
| `report_agent/state.py` | 7-96 | ReportState |
| `report_agent/configuration.py` | 305-348 | column_metadata |
| `text2sql/nodes.py` | 560-617 | sql_architect_node |
| `text2sql/nodes.py` | 943-1002 | business_rules_node |
| `text2sql/nodes.py` | 1114-1350 | sql_generator_node |
| `text2sql/prompts.py` | 145-552 | SQL_ARCHITECT_PROMPT |
| `text2sql/prompts.py` | 112-138 | TERM_VALIDATOR_PROMPT |
| `text2sql/prompts.py` | 559-598 | SCHEMA_VALIDATOR_PROMPT |
| `text2sql/prompts.py` | 717+ | BUSINESS_RULES_VALIDATOR_PROMPT |
| `text2sql/stores/term_store.py` | 113+ | TermStore |
| `text2sql/stores/business_rules_store.py` | 28+ | BusinessRulesStore |
| `text2sql/value_resolver_service.py` | 18+ | ValueResolverService |
| `text2sql/sql_builder.py` | 1+ | generate_sql() |
| `supervisor/prompts.py` | 8-54 | SUPERVISOR_SYSTEM_PROMPT |
| `visualization_v2/prompts.py` | 8+ | VIZ_DECIDER_PROMPT |
