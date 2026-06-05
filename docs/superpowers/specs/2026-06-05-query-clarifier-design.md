# Query Clarifier Subgraph — Design Spec

**Date:** 2026-06-05  
**Feature:** Sorgu Öncesi Doğrulama / Query Clarification (Report Agent)  
**Status:** Approved

---

## 1. Özet

Kullanıcı bir rapor sorgusu yazdığında, sistem bu sorguyu SQL üretimine göndermeden önce bir "clarity" (netlik) analizi yapar. Eksiklik veya belirsizlik tespit edilirse optimize edilmiş bir versiyon önerir: *"Şunu mu sormak istediniz?"* Kullanıcı onaylarsa optimize sorgu kullanılır; reddederse orijinal sorgu akışa devam eder. Özellik bir feature toggle ile açılıp kapatılabilir.

---

## 2. Graf Akışı

### Güncellenmiş Ana Graf

```
START → classify_intent → [intent_router]
  ├── NEW_QUERY    → query_clarifier → [clarifier_router]
  │                     ├── CLARIFIED → text2sql → hitl_check → viz/build_response → END
  │                     └── PASS      → text2sql → hitl_check → viz/build_response → END
  ├── MODIFY_QUERY → query_clarifier → [clarifier_router]
  │                     ├── CLARIFIED → modify_sql → text2sql → ...
  │                     └── PASS      → modify_sql → text2sql → ...
  ├── VAGUE_QUERY  → query_clarifier → [clarifier_router]
  │                     ├── CLARIFIED → text2sql → ...
  │                     └── PASS      → report_chat → classify_intent (mevcut loop)
  └── USE_RESULT   → (değişmez)
```

**Kural:** `query_clarifier` subgraph `NEW_QUERY`, `MODIFY_QUERY` ve `VAGUE_QUERY` niyetleri için devreye girer. `USE_RESULT` değişmez.

### Davranış Farkları Intent'e Göre

| Intent | Clarity Analizi | PASS davranışı |
|---|---|---|
| NEW_QUERY | Score hesapla, eşik altındaysa öneri üret | Orijinal sorgu → text2sql |
| MODIFY_QUERY | Score hesapla + aktif SQL bağlamıyla değerlendir | Orijinal sorgu → modify_sql |
| VAGUE_QUERY | Her zaman en makul yorumu öner (score hesaplamaz) | → report_chat (fallback) |

---

## 3. Yeni Subgraph: `query_clarifier`

### Dosya Yapısı

```
src/graphs/report_agent/subagents/query_clarifier/
  ├── __init__.py
  ├── graph.py      ← subgraph tanımı + node bağlantıları
  ├── nodes.py      ← clarity_analyzer_node implementasyonu
  ├── state.py      ← QueryClarifierState TypedDict
  └── prompts.py    ← LLM prompt + ClarityAnalysisResult Pydantic modelleri
```

### Subgraph İç Akışı

```
START → clarity_analyzer → [clarity_router]
  ├── needs_clarification → interrupt() → kullanıcı yanıtı → END
  └── pass_through        → END
```

---

## 4. State Değişiklikleri

### `QueryClarifierState` (yeni)

```python
class QueryClarifierState(TypedDict):
    user_query: str
    intent_type: Optional[str]               # NEW_QUERY | MODIFY_QUERY | VAGUE_QUERY
    active_sql: Optional[str]                # MODIFY_QUERY bağlamı için
    # clarity_threshold state'e konmaz — node, RunnableConfig üzerinden
    # ReportAgentConfiguration.query_clarity_threshold'u okur

    # Clarifier çıktıları
    clarity_score: Optional[float]           # 0.0–1.0 (VAGUE için kullanılmaz)
    clarity_issues: Optional[List[str]]      # tespit edilen eksiklikler
    suggested_query: Optional[str]           # optimize edilmiş versiyon
    suggestion_message: Optional[str]        # kullanıcıya gösterilecek Türkçe metin
    clarifier_decision: Optional[str]        # PASS | NEEDS_CLARIFICATION | CLARIFIED
    clarification_accepted: Optional[bool]   # kullanıcı evet=True / hayır=False
```

### `ReportState`'e Eklenenler

```python
clarifier_decision: Optional[str]   # _clarifier_router için
suggested_query: Optional[str]      # kabul edilirse user_query'yi replace eder
```

### `classify_intent_node` Temizleme

Her tur başında sıfırlanacak alanlar (mevcut `pre_built_sql: None` ile birlikte):

```python
"clarifier_decision": None,
"suggested_query": None,
```

---

## 5. Pydantic Modelleri

```python
class ClarityIssueType(str, Enum):
    MISSING_DATE_FILTER    = "missing_date_filter"
    AMBIGUOUS_METRIC       = "ambiguous_metric"
    MISSING_GROUPING       = "missing_grouping"
    AMBIGUOUS_FILTER_VALUE = "ambiguous_filter_value"
    LARGE_RESULT_WARNING   = "large_result_warning"

class ClarityIssue(BaseModel):
    type: ClarityIssueType
    description: str
    severity: Literal["low", "medium", "high"]

class ClarityAnalysisResult(BaseModel):
    clarity_score: float                    # 0.0–1.0; VAGUE için 0.0 sabit döner
    issues: List[ClarityIssue]
    suggested_query: Optional[str]          # optimize edilmiş sorgu metni
    suggestion_message: Optional[str]       # Türkçe öneri mesajı (kullanıcıya gösterilir)
    can_suggest: bool                       # True ise interrupt açılır
```

---

## 6. LLM Prompt Tasarımı

### NEW_QUERY / MODIFY_QUERY için

```
Sen bir Türkçe ERP rapor sorgu analizcisisin.

Görevin:
1. Kullanıcının sorgusunu analiz et
2. Bir clarity_score (0.0–1.0) hesapla
3. Eksiklik/belirsizlik varsa tespit et
4. Eğer öneri üretebiliyorsan: optimize edilmiş sorgu + Türkçe öneri mesajı yaz

Mevcut bağlam:
- Intent tipi: {intent_type}
- Aktif SQL var mı: {has_active_sql}
- Aktif SQL özeti: {active_sql_summary}

Clarity Score Rehberi:
- 0.85–1.0 → Net sorgu (tarih + metrik + gruplama hepsi belli)
- 0.65–0.84 → Küçük eksiklik
- 0.40–0.64 → Birden fazla eksiklik, öneri üret
- <0.40    → Çok belirsiz (bu range VAGUE_QUERY yakalar, beklenmez)

Kontrol Listesi:
□ Tarih/dönem filtresi var mı?
□ Metrik net mi? (RowAmount, Quantity, vb.)
□ Gruplama/boyut net mi? (BranchName, CategoryName, ProductName, vb.)
□ Filtre değerleri spesifik mi?
□ Sıralama veya limit gerekiyorsa belirtilmiş mi?

Veritabanı Kolonları: RowAmount, Quantity, DocumentDate, BranchName,
ProductName, CategoryName, BranchCityName, CustomerName

Kullanıcı sorgusu: {user_query}
```

### VAGUE_QUERY için

```
Kullanıcının sorgusu net bir SQL sorgusuna dönüştürmek için çok genel.
Göreve: Bu sorguyu en makul ERP raporu yorumuyla somutlaştır.

Örnek:
- "satışları göster" → "Bu ayki toplam RowAmount, CategoryName bazında gruplandırılmış"
- "ne sattık" → "Son 30 günde en çok satan ilk 10 ProductName (Quantity bazında)"

clarity_score: 0.0 (her zaman)
can_suggest: True (her zaman — VAGUE için öneri zorunlu)

Kullanıcı sorgusu: {user_query}
```

### Kullanıcıya Gösterilen Mesaj Formatı

```
Şunu mu sormak istediniz?

📊 {suggested_query}

Evet ise onaylayın, değilse "hayır" yazın.
```

---

## 7. Konfigürasyon Değişiklikleri

`ReportAgentConfiguration`'a iki yeni alan:

```python
enable_query_clarifier: bool = True
query_clarity_threshold: float = 0.65      # Bu eşiğin altında öneri tetiklenir
```

---

## 8. `classify_intent` Prompt Değişikliği

Mevcut prompt'ta VAGUE_QUERY konusundaki savunmacı kurallar kaldırılır:

**Kaldırılacak satırlar (örnek):**
- "Eğer VAGUE yerine düşük confidence ile NEW_QUERY dönebilirsen tercih et"
- "VAGUE_QUERY yalnızca gerçekten hiçbir şey anlaşılamıyorsa kullan"

**Yerine:**
- "VAGUE_QUERY: Sorgudan spesifik bir SQL üretilemiyorsa kullan. Query clarifier bu durumu ele alacak."

---

## 9. Hata Yönetimi

| Senaryo | Davranış |
|---|---|
| LLM çağrısı başarısız | `clarifier_decision = "PASS"`, loglama, akış devam eder |
| `clarity_score` parse edilemez | `PASS` — sessiz fallback |
| `enable_query_clarifier = False` | Node çağrılmaz, `_intent_router` eski davranışa döner |
| HITL timeout / boş yanıt | `PASS` — orijinal sorgu devam eder |
| `suggested_query` üretilemedi, score düşük | `PASS` — öneri yoksa interrupt açılmaz |
| VAGUE_QUERY + PASS | `report_chat` fallback (mevcut loop) |

**Temel prensip:** Clarifier her zaman fail-safe. Herhangi bir sorun → `PASS`, kullanıcı bloklanmaz.

---

## 10. Etkilenen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `subagents/query_clarifier/` | **YENİ** — tüm subgraph |
| `graph.py` | `query_clarifier` node'u ekle, `_intent_router` ve `_clarifier_router` güncelle |
| `state.py` | `clarifier_decision`, `suggested_query` alanları ekle |
| `nodes.py` | `classify_intent_node` — yeni alanları sıfırla |
| `prompts.py` | `classify_intent` prompt'unu güncelle (VAGUE savunmasını kaldır) |
| `configuration.py` | `enable_query_clarifier`, `query_clarity_threshold` ekle |

---

## 11. Test Senaryoları

| Sorgu | Beklenen Davranış |
|---|---|
| "Ocak 2025 Ankara şubesinin toplam satışı" | PASS — clarity yüksek |
| "Satışları göster" | VAGUE → Clarifier öneri üretir |
| "Kategori bazında toplamı ver" | Score ~0.60 → "CategoryName bazında RowAmount toplamı, tüm zamanlar mı?" önerisi |
| "Geçen ay elektroniği kim sattı" | Score ~0.70 → tarih netti, metrik belirsiz → öneri |
| "Öncekini güncelle, sadece İstanbul" | MODIFY_QUERY → clarifier aktif SQL'i bağlam olarak kullanır |
