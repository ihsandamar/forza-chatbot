# Insight Engine — Design Spec

**Date:** 2026-06-08  
**Status:** Approved  
**Scope:** On-demand insight generation (INSIGHT_REQUEST only)

---

## 1. Problem

Kullanıcı rapor chatbot'una sorgu sorduğunda sistem yalnızca istenen veriyi döner. Ancak verinin içinde gizli olan trend, anomali, segment sapması gibi anlamlı bulgular kullanıcıya sunulmaz. Kullanıcının "Bu veriden ne çıkarabilirim?" sorusuna yanıt verecek bir mekanizma yoktur.

---

## 2. Kapsam

| Mod | Durum |
|-----|-------|
| On-demand (INSIGHT_REQUEST) | ✅ Bu spec kapsamında |
| Reaktif (her sorguda otomatik) | ❌ Kapsam dışı |
| Proaktif (scheduler) | ❌ Kapsam dışı |

---

## 3. Kullanıcı Deneyimi

Kullanıcı aşağıdaki gibi bir şey yazar:

> "Bu veriden ne çıkarabilirim?"  
> "Nelere dikkat etmeliyim?"  
> "Hangi ürün/şube sorunlu?"  
> "Insight ver"

`classify_intent` bu ifadeleri `INSIGHT_REQUEST` olarak sınıflandırır ve `insight_engine` node'una yönlendirir. Sonuç, chatbot yanıtının altında formatlı bir insight bloğu olarak gösterilir.

---

## 4. Mimari

```
classify_intent
  └── INSIGHT_REQUEST
        ↓
  insight_engine  (yeni node, report_agent graph'ına eklenir)
        ├── [1] Comparison Data Fetcher
        ├── [2] Math Engine
        ├── [3] Findings Ranker
        └── [4] LLM Interpreter
                └── insight bloğu → build_response → yanıt altına eklenir
```

`text2sql` atlanır. Mevcut `active_sql` ve `active_results` state'ten alınır.

---

## 5. Bileşenler

### 5.1 Comparison Data Fetcher

Mevcut sorgunun verisini karşılaştırma periyoduyla kıyaslamak için ikinci bir dataset çeker.

**Mode A — Auto SQL Shift (default)**

`active_sql` içindeki tarih filtrelerini parse edip eşdeğer önceki döneme kaydırır.

```
active_sql:  WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-31'
             ↓  (granularity: monthly → bir önceki ay)
comparison:  WHERE DocumentDate BETWEEN '2023-12-01' AND '2023-12-31'
```

Granularity kaynağı: `state.semantic_intent.time.granularity`  
Desteklenen kaydırmalar: daily → -1 gün, weekly → -7 gün, monthly → -1 ay, yearly → -1 yıl.  
LLM çağrısı yoktur. Sonuç: ~200ms ek DB sorgusu.

**Mode B — User-Provided SQL**

Kullanıcı karşılaştırma SQL'ini açıkça belirttiğinde devreye girer.  
State field: `comparison_sql: Optional[str]`  
Fetcher bu SQL'i doğrulayıp çalıştırır, sonucu `comparison_df` olarak döner.

Her iki modun çıktısı aynıdır: `current_df` + `comparison_df` → Math Engine.

---

### 5.2 Math Engine — Plugin Mimarisi (Open/Closed)

Engine kapalıdır; yeni analyzer eklemek için çekirdeğe dokunulmaz.

```
MathEngine
  ├── run(current_df, comparison_df, context) → List[Finding]
  └── analyzers: List[BaseAnalyzer]

BaseAnalyzer (abstract)
  ├── analyze(current_df, comparison_df, context) → List[Finding]
  └── name: str
```

**Dahil Analyzer'lar:**

| Analyzer | Yöntem | Ürettiği Finding Türleri |
|----------|--------|--------------------------|
| `TrendAnalyzer` | Dönemsel % değişim, linear regression slope, moving avg | `trend_increase`, `trend_decline`, `trend_flat` |
| `AnomalyDetector` | Z-score, IQR tabanlı outlier, spike/drop tespiti | `anomaly_high`, `anomaly_low`, `spike`, `drop` |
| `SegmentComparator` | Segment vs ortalama farkı, peer ranking, pareto | `outlier_high`, `outlier_low`, `top_performer`, `bottom_performer`, `pareto_dominant` |
| `MultiDimAnalyzer` | Zaman × segment cross analiz, DayOfWeek/Hour pattern | `pattern_time_segment`, `peak_period`, `weak_period` |
| `SeasonalityAnalyzer` | Haftalık/aylık tekrar pattern, autocorrelation | `seasonal_peak`, `seasonal_trough` |

Yeni bir analyzer eklemek: `BaseAnalyzer` implement et, `MathEngine` constructor'ına geç. Mevcut kod değişmez.

---

### 5.3 Finding Modeli

Her analyzer standart `Finding` nesnesi üretir. LLM'e ham veri yerine bu nesneler gönderilir.

```python
@dataclass
class Finding:
    # Kimlik
    type: str               # "trend_decline", "anomaly_high", vb.
    analyzer: str           # kaynağı

    # Boyut
    dimension: str          # "ProductName", "BranchName", vb.
    value: str              # "Burger", "Ankara", vb.
    metric: str             # "RowAmount", "Quantity", vb.

    # Kanıt (deterministik, Python hesaplar)
    current_value: float
    comparison_value: float
    change_pct: float

    # Sıralama
    significance: float     # 0.0–1.0

    # Bağlam
    period_label: str       # "son 7 gün vs önceki 7 gün"

    # Analyzer'a özgü ilave kanıt
    extra: dict             # {"slope": -18.3, "r_squared": 0.87, "z_score": -2.8, ...}
```

LLM bu `Finding` nesnelerini okur; sayı üretmez, sadece yorumlar.

---

### 5.4 Findings Ranker

`significance` score'a göre azalan sırada sıralar.  
Eşik: `significance < 0.40` olan bulgular elenir.  
LLM'e gönderilen maksimum bulgu sayısı: `TOP_N = 8` (config ile ayarlanabilir).

Significance hesabı analyzer'a özgüdür:
- TrendAnalyzer: `|change_pct| / 100` (normalize) × `r_squared`
- AnomalyDetector: `min(|z_score| / 4, 1.0)`
- SegmentComparator: `|vs_avg_pct| / 100` (normalize)

---

### 5.5 LLM Interpreter

LLM'e gönderilen prompt 4 bileşenden oluşur:

```
[1] KULLANICI BAĞLAMI
    Kullanıcı sorusu: {user_query}
    Aktif filtreler: {active_filters}
    Dönem: {period_label}

[2] BULGULAR (significance sıralı, max TOP_N)
    1. {type} | {dimension}={value} | {metric} | change={change_pct}% | sig={significance}
       Kanıt: {extra}
    ...

[3] KURALLAR
    - Sadece verilen bulgulardan çıkarım yap
    - Kendi hesaplama yapma
    - Her kritik bulgu için somut aksiyon öner
    - Türkçe yaz

[4] FORMAT
    → Kısa özet (1-2 cümle)
    → Kritik bulgular (madde madde, sayılarla destekli)
    → Aksiyon önerileri
```

Model: mevcut supervisor config'deki model (gpt-4.1-mini veya eşdeğeri).

---

## 6. State Değişiklikleri

`ReportState`'e eklenmesi gereken field'lar (insight_engine text2sql'i atladığı için `Text2SqlState` değişmez):

| Field | Tip | Açıklama |
|-------|-----|----------|
| `comparison_sql` | `Optional[str]` | Kullanıcı tarafından sağlanan karşılaştırma SQL'i |
| `insight_findings` | `Optional[List[dict]]` | Ranker çıktısı (debug/log için) |
| `insight_output` | `Optional[str]` | LLM Interpreter'ın ürettiği insight metni |

---

## 7. Graph Değişiklikleri

**report_agent graph'ına eklenenler:**

1. `insight_engine_node` — yeni node
2. `classify_intent` router: `INSIGHT_REQUEST` → `insight_engine_node` dalı
3. `insight_engine_node` → `build_response_node` bağlantısı

**Değiştirilmeyenler:** text2sql, visualization, modify_sql, tüm mevcut node'lar.

---

## 8. Yeni Dosya Yapısı

```
src/graphs/report_agent/
  ├── nodes.py                          (insight_engine_node eklenir)
  ├── state.py                          (3 yeni field)
  └── insight_engine/                   (yeni modül)
        ├── __init__.py
        ├── engine.py                   (MathEngine orchestrator)
        ├── models.py                   (Finding dataclass)
        ├── ranker.py                   (FindingsRanker)
        ├── fetcher.py                  (ComparisonDataFetcher, Mode A + B)
        ├── llm_interpreter.py          (LLM prompt + çağrısı)
        └── analyzers/
              ├── __init__.py
              ├── base.py               (BaseAnalyzer ABC)
              ├── trend.py              (TrendAnalyzer)
              ├── anomaly.py            (AnomalyDetector)
              ├── segment.py            (SegmentComparator)
              ├── multidim.py           (MultiDimAnalyzer)
              └── seasonality.py        (SeasonalityAnalyzer)
```

---

## 9. Kapsam Dışı (Bu Spec)

- Reaktif mod (her sorguda otomatik insight)
- Proaktif mod (scheduler tabanlı)
- Insight geçmişi / cache
- Kullanıcı bazlı insight tercihleri
- Insight feedback mekanizması (thumbs up/down)

---

## 10. Başarı Kriterleri

- `INSIGHT_REQUEST` intent'i doğru sınıflandırılıyor
- Math Engine en az 3 analyzer çalıştırıyor ve `Finding` listesi üretiyor
- LLM Interpreter kendi sayı üretmiyor, sadece Finding'lerdeki sayıları kullanıyor
- Yeni analyzer eklemek mevcut dosyalara dokunmayı gerektirmiyor
- Yanıt süresi: karşılaştırma DB sorgusu + LLM çağrısı dahil ≤ 5 saniye
