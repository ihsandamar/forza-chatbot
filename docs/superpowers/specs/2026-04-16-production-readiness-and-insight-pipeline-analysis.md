# Production Readiness & Insight Pipeline — Stratejik Analiz

**Tarih:** 2026-04-16  
**Kapsam:** Report Agent — Accuracy (Phase 1) & Insight/Analytics Hazırlığı (Phase 2)  
**Durum:** Analiz — Kod değişikliği içermez

---

## 1. Özet

Bu döküman iki stratejik önceliği ele alır:

1. **Accuracy** — Production'a taşımadan önce intent, SQL ve business rule katmanlarında doğruluk garantisi
2. **Insight Pipeline** — Ham veri → istatistiksel analiz → insan dili içgörü zincirine hazırlık

Ek olarak **mimari karar noktası** analiz edilir: mevcut sistemi mi refactor edelim yoksa yeni bir proje mi başlatalım?

---

## 2. Mevcut Mimari — Hızlı Harita

```
[Kullanıcı Mesajı]
      │
classify_intent (LLM, yapılandırılmış çıktı)
      │
      ├─── NEW_QUERY   → text2sql subgraph (11 node, paralel)
      ├─── MODIFY_QUERY → modify_sql → pre_built_sql bypass
      ├─── USE_RESULT  → extract_entity → compute_results
      └─── VAGUE_QUERY → report_chat (max 2 tur)
                               │
                    [SQL çalıştırıldı, sonuç var]
                               │
                    visualization subgraph (5 node, opsiyonel)
                               │
                    build_response (saf Python)
```

**Text2SQL Subgraph — Paralel Fan-out:**
```
create_table → business_rules → term_resolver
    → [sql_architect ║ schema_validator ║ term_validator]  ← paralel
    → schema_merge → value_resolver → sql_generator → sql_executor
    → [retry loop, max 2] → cleanup_table
```

**LLM Çağrı Sayısı (per query):**
- Maksimum 6: `classify_intent`, `sql_architect`, `schema_validator`, `term_validator`, `viz_decider`, `modify_sql`
- SQL üretimi saf Python (LLM yok) — bu tasarım kararı doğru

---

## 3. PHASE 1 — ACCURACY

### 3.1 Intent Classification

**Mevcut durum:**  
- 4 intent tipi: NEW_QUERY | MODIFY_QUERY | USE_RESULT | VAGUE_QUERY  
- Confidence threshold: 0.70 (genel), 0.85 (MODIFY_QUERY)  
- Confidence < 0.70 → `interrupt()` ile kullanıcıya soru

**Bilinen riskler ve dikkat edilmesi gerekenler:**

| Risk | Neden | Öneri |
|------|-------|-------|
| MODIFY vs NEW_QUERY karışıklığı | Türkçe'de kısa sorgular bağlam yükler ("sadece Ankara'yı göster") | MODIFY için 0.85 threshold doğru; ancak conversation_history window'u gözden geçir |
| USE_RESULT yanlış tetiklenmesi | "Bu ürünlerin ortalaması kaç?" cümlesi hem USE_RESULT hem NEW_QUERY gibi görünür | query_type=SINGLE kısıtı eklenebilir |
| VAGUE döngüsü max 2 tur | Kullanıcı 3. turda hâlâ belirsiz cevap verirse sisteme nasıl düşer? | Fallback intent belirlenmeli (varsayılan: NEW_QUERY) |
| Multi-turn context | `classify_intent` sadece son HumanMessage'ı mı okuyor? | Tüm konuşma geçmişi özetlenerek context window'a alınmalı |

**Test edilmesi gereken kritik senaryolar:**
```
1. "Bir önceki sorgu ile karşılaştır"          → MODIFY vs NEW_QUERY
2. "Toplam ne kadar?"                           → USE_RESULT vs NEW_QUERY  
3. "Istanbul"  (tek kelime)                     → VAGUE_QUERY
4. "Daha önce sorduğum ürünlerin listesi"       → USE_RESULT
5. "Geçen haftanın verilerini göster"           → NEW_QUERY (temporal)
```

---

### 3.2 SQL Generation Accuracy

**Mevcut durum:**  
- `sql_architect` LLM → `QuerySchema` (sütun eşlemeleri)
- `sql_generator` saf Python → T-SQL üretimi
- Retry loop: max 2 deneme

**Kritik nokta — Zayıflık haritası:**

```
[sql_architect LLM]
        │
        ├── Güçlü: Sütun seçimi, aggregation tipi
        ├── Zayıf: Kompleks JOIN mantığı (eğer ileriye taşınırsa)
        └── Zayıf: Çok-boyutlu filtreleme kombinasyonları

[sql_generator Python]
        │
        ├── Güçlü: Deterministik, test edilebilir, hızlı
        ├── Zayıf: Edge case'ler schema değişimlerinde kırılgan
        └── Zayıf: Birden fazla aggregation kolonu için özel mantık
```

**Dikkat edilmesi gereken noktalar:**

1. **Column name resolution:** `value_resolver_service.py`'daki semantik eşleme sürekli büyüyor. Eşleme tablosunun merkezi bir konfigürasyon dosyasına taşınması gerekiyor (kod içi dict yerine YAML/JSON). Bu, test ve bakımı kolaylaştırır.

2. **Pre-built SQL bypass:** `modify_sql` → `pre_built_sql` mekanizması doğru çalışıyor ancak `classify_intent` her turda `pre_built_sql: None` reset'lemelidir — bu zaten var, korunmalı.

3. **Retry kalitesi:** `sql_executor` hata aldığında `sql_architect`'a ne hata mesajı dönüyor? Hata mesajının tam ve anlamlı olması retry başarı oranını doğrudan etkiler.

4. **Business Rules ile SQL çelişmesi:** ChromaDB'den gelen bir kural, `sql_generator`'ın ürettiği SQL'i override ediyorsa bu override'ın log'lanması gerekiyor. Sessiz override debug'u zorlaştırır.

---

### 3.3 Business Rules

**Mevcut durum:**  
- ChromaDB vector store (semantic search)
- Kurallar saf Python ile SQL'e uygulanıyor
- LLM'e kural gösterilmiyor (v2.2'de kaldırıldı — doğru karar)

**Dikkat edilmesi gerekenler:**

| Alan | Risk | Öneri |
|------|------|-------|
| Kural çakışması | İki kural aynı sütunu farklı biçimde manipüle ederse hangisi kazanır? | Kural öncelik sırası tanımlanmalı |
| Semantic search hassasiyeti | ChromaDB cosine similarity threshold'u nedir? Çok düşükse alakasız kurallar çeker | Threshold log'lanmalı ve test edilmeli |
| Kural kapsamı | Hangi sorgu tipleri (SINGLE/RANKING/COMPARISON/TIME_SERIES) için hangi kurallar geçerli? | query_type bazlı kural filtreleme eklenebilir |
| Tarih güvenlik ağı | CAST logic kuralı her zaman tetikleniyor mu? | Spesifik test case'i yazılmalı |

---

### 3.4 Term & Value Resolution

**Value Resolver:**  
- Fuzzy matching + semantik eşleme + interrupt()
- Düşük confidence → kullanıcıya onay sorma
- Cache mekanizması mevcut

**Term Resolver:**  
- Sözlük bazlı fuzzy match
- `term_hints` → LLM'e rehber sağlıyor

**Kritik dikkat noktası — Ambiguous list ordering (dokümante edilmiş):**
Bağımsız eşleşmelerde `term_resolver`'ın sıralama varsayımı production'da risk yaratabilir. Bu varsayımın test coverage'ı olduğundan emin olun.

---

### 3.5 Accuracy için Test Stratejisi

Production'a geçmeden önce aşağıdaki test matrisinin oluşturulması kritik:

```
┌─────────────────────────┬──────────────────┬────────────────────────────┐
│ Test Kategorisi         │ Test Sayısı      │ Başarı Kriteri             │
├─────────────────────────┼──────────────────┼────────────────────────────┤
│ Intent Classification   │ 30+ sorgu        │ %90 doğru sınıflandırma    │
│ SQL Correctness         │ 20+ sorgu tipi   │ %95 çalışan SQL            │
│ Column Resolution       │ 15+ alias        │ %100 doğru eşleme          │
│ Business Rules          │ 10+ senaryo      │ %100 doğru uygulama        │
│ Value Resolution HITL   │ 8+ düşük-conf.   │ Doğru interrupt tetikleme  │
│ Multi-turn Context      │ 5+ konuşma akışı │ Context kaybı yok          │
└─────────────────────────┴──────────────────┴────────────────────────────┘
```

**Öneri:** Bir "golden set" oluşturun — gerçek kullanıcı sorguları + beklenen SQL + beklenen sonuç. Bu set her değişiklik sonrası regresyon testi olarak çalıştırılmalı.

---

## 4. PHASE 2 — INSIGHT PIPELINE

### 4.1 Mevcut Sistem Ne Yapıyor?

```
Ham veri (SQL sonucu)
      │
      ├── compute_results: SUM/AVG/COUNT/MIN/MAX (saf Python aggregation)
      ├── visualization: Plotly chart (görsel temsil)
      └── build_response: Tablo formatı (markdown + iframe)
```

**Eksik olan:** İstatistiksel analiz, trend tespiti, anomali, tahmin — hiçbiri yok.

### 4.2 Matematiksel Katman → Sistem Bileşeni Eşlemesi

Aşağıdaki harita, sağlanan matematiksel analiz planını mevcut mimari bileşenlerine oturtmaktadır:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     MATEMATİKSEL KATMAN HARİTASI                        │
├────────────────┬──────────────────────────────┬─────────────────────────┤
│ Katman         │ Teknikler                    │ Uygun Mimari Bileşen    │
├────────────────┼──────────────────────────────┼─────────────────────────┤
│ LAYER 1        │ WoW, MoM, CAGR, momentum,   │ Yeni: analytics_engine  │
│ Temel Metrik   │ volatility, acceleration     │ (saf Python servis)     │
├────────────────┼──────────────────────────────┼─────────────────────────┤
│ LAYER 2        │ Linear/Polynomial regression,│ Yeni: analytics_engine  │
│ Trend &        │ LOWESS, Mann-Kendall,        │ veya ayrı subgraph node │
│ Seasonality    │ Sen's Slope, STL, FFT,       │                         │
│                │ day-of-week indexing         │                         │
├────────────────┼──────────────────────────────┼─────────────────────────┤
│ LAYER 3        │ Z-score, IQR, Isolation      │ Yeni: analytics_engine  │
│ Anomali        │ Forest, CUSUM, Changepoint   │ Kritik: zaman serisi    │
│                │ Detection (PELT)             │ varlığı kontrolü        │
├────────────────┼──────────────────────────────┼─────────────────────────┤
│ LAYER 4        │ Pearson/Spearman, Granger    │ Yeni: analytics_engine  │
│ İlişki         │ Causality, PCA, DTW          │ Çok değişkenli veri     │
│                │                              │ gerektirir              │
├────────────────┼──────────────────────────────┼─────────────────────────┤
│ LAYER 5        │ ARIMA, Prophet, SARIMA,      │ Ayrı: forecast_engine   │
│ Tahmin         │ XGBoost, HW Smoothing        │ (opsiyonel, karmaşık)   │
├────────────────┼──────────────────────────────┼─────────────────────────┤
│ SEGMENT        │ BCG Matrix, Pareto, HHI,     │ Yeni: segment_engine    │
│ Analizi        │ Rank Stability               │ (L1 üzerine inşa edilir)│
└────────────────┴──────────────────────────────┴─────────────────────────┘
```

### 4.3 Önerilen Insight Subgraph Mimarisi

```
[SQL Sonucu — DataFrame]
        │
data_profiler (saf Python)
   ├── Veri tipi tespiti (numeric/categorical/temporal)
   ├── Satır sayısı, zaman serisi var mı?
   └── Hangi katmanlar uygulanabilir? → DataProfile
        │
analytics_router (saf Python, kural bazlı)
   ├── time_series=True → trend + seasonal + anomaly
   ├── multi_product=True → correlation + PCA
   ├── single_snapshot=True → sadece temel metrikler
   └── → AnalyticsPlan (hangi analizler çalışacak)
        │
analytics_engine (saf Python — scipy, numpy, statsmodels)
   ├── LAYER 1: temel metrikler (her zaman)
   ├── LAYER 2: trend (zaman serisi varsa)
   ├── LAYER 3: anomali (yeterli veri varsa, n≥14)
   └── → AnalyticsResult (ham bulgular)
        │
insight_filter (saf Python)
   ├── Anlamsız bulguları at (p > 0.05, r² < 0.3)
   ├── Çelişen sinyalleri uzlaştır
   └── → SignificantFindings (önceliklendirilmiş liste)
        │
insight_narrator (LLM — tek çağrı)
   ├── SignificantFindings → Türkçe insan dili
   ├── Prompt: bulgular + iş bağlamı + güven seviyeleri
   └── → NarrativeInsight (kullanıcıya sunulacak metin)
        │
build_response (mevcut — genişletilir)
   ├── Tablo + Chart (mevcut)
   └── + Insight paneli (yeni)
```

**LLM kullanımı:** Sadece `insight_narrator` — tüm matematik saf Python. Bu, maliyet ve hız açısından kritik.

### 4.4 Hangi Kütüphaneler?

```
LAYER 1-3 için (hafif, production'a uygun):
  numpy          → vektörel hesaplama
  scipy          → istatistiksel testler (Mann-Kendall, Z-score)
  statsmodels    → OLS regression, ARIMA (L5 için)
  pymannkendall  → Mann-Kendall trend testi (lightweight)
  ruptures       → Changepoint detection (PELT)

LAYER 4 için (orta ağırlık):
  scikit-learn   → PCA, Isolation Forest
  scipy.stats    → Pearson/Spearman correlation

LAYER 5 için (ağır, opsiyonel):
  prophet        → Mevsimsel tahmin (Meta, production-grade)
  
ZATEN VARSA:
  pandas         → DataFrame işleme (mevcut sistemde kullanılıyor mu? kontrol et)
```

**Dikkat:** Prophet bağımlılık ağırlığı nedeniyle Docker image'ını ciddi büyütür. L5 ayrı bir servis olarak düşünülebilir.

---

## 5. MİMARİ KARAR: Refactor mı, Yeni Proje mi?

### 5.1 Mevcut Sistemin Güçlü Yanları (Korunacak)

- LangGraph StateGraph altyapısı: sağlam, test edilmiş
- Paralel fan-out (sql_architect ║ schema_validator ║ term_validator): doğru tasarım
- HITL interrupt mekanizması: production-grade
- Pre-built SQL bypass: MODIFY_QUERY için doğru çözüm
- ChromaDB business rules indexing: ölçeklenebilir
- Saf Python SQL generator: deterministik, hız avantajı

### 5.2 Mevcut Sistemin Zayıf Noktaları

- Insight üretimi yok (en büyük eksik)
- Column name resolution sözlüğü kod içinde (bakım zorluğu)
- Analytics için state alanı tanımlanmamış (48 alan zaten fazla)
- Test coverage'ı eksik (golden set yok)

### 5.3 Karar Matrisi

| Kriter | Yeni Proje | Refactor |
|--------|-----------|---------|
| Mevcut LangGraph altyapısı | Kaybedilir | Korunur ✓ |
| HITL mekanizması | Yeniden yazılır | Korunur ✓ |
| Business rules + vector store | Yeniden yazılır | Korunur ✓ |
| Insight pipeline ekleme | Temiz slate | Mevcut state'e eklenir (mümkün) ✓ |
| State karmaşıklığı | Sıfırdan tasarlanır | 48 alan yönetimi zorlaşabilir |
| Mimari borç | Taşınmaz | Taşınır |
| Delivery süresi | Uzun | Kısa ✓ |
| Production riski | Yüksek (bilinmeyenler) | Düşük (battle-tested) ✓ |

**Öneri: Refactor — Yeni subgraph ekle, var olanı değiştirme.**

Gerekçe: Mevcut sistemdeki HITL mekanizması, business rules altyapısı ve LangGraph StateGraph yapısı ciddi bir yatırımı temsil eder. Bunları yeniden yazmak en az 6-8 haftalık kayıp anlamına gelir. Insight pipeline, mevcut sisteme yeni bir subgraph olarak eklenebilir. Karmaşık `ReportState`'i ise "insight" alanları için bir sub-state (`AnalyticsState`) ile bölmek yeterli olacaktır.

---

## 6. STATE YÖNETİMİ — Dikkat Noktaları

Mevcut `ReportState` 48 alan içeriyor. Insight pipeline eklenmesiyle bu sayı 60-70'e çıkabilir. Bu, iki riski beraberinde getirir:

1. **Cognitive complexity:** Hangi node hangi alanı okur/yazar belirsizleşir
2. **LangGraph checkpoint boyutu:** Büyük state → checkpointing maliyeti artar

**Öneri — State bölme stratejisi:**
```python
class ReportState(TypedDict):
    # Mevcut alanlar (korunur)
    ...
    
    # Yeni: Analytics sub-state (opsiyonel, None olabilir)
    analytics_result: Optional[AnalyticsResult]
    insight_narrative: Optional[str]
    analytics_plan: Optional[AnalyticsPlan]
```

`AnalyticsResult` ve `AnalyticsPlan` ayrı Pydantic modeller olmalı — TypedDict inline değil. Bu, serialization ve test edilebilirliği kolaylaştırır.

---

## 7. ÖNCELİKLENDİRME VE YOL HARİTASI

### Phase 1 — Accuracy (ÖNCELİK: KRİTİK)

```
P1.1  Golden test seti oluştur (30+ gerçek sorgu)
P1.2  Intent classification regresyon testleri yaz
P1.3  Column resolution sözlüğünü YAML'a taşı
P1.4  Business rules öncelik sırası tanımla
P1.5  Retry loop'unda hata mesajı kalitesini iyileştir
P1.6  Tüm testler geçene kadar production geçişi yok
```

### Phase 2A — Analytics Temeli (Layer 1-3)

```
P2A.1  DataProfiler servisini yaz (pandas + numpy)
P2A.2  TemelMetrik hesaplayıcısı (WoW, MoM, momentum)
P2A.3  TrendAnalyzer (Mann-Kendall + OLS)
P2A.4  AnomalyDetector (Z-score + CUSUM başlangıç)
P2A.5  InsightFilter (istatistiksel anlamlılık kapısı)
P2A.6  InsightNarrator LLM node'u (tek çağrı)
P2A.7  Insight subgraph'ını report_agent'a bağla
```

### Phase 2B — İleri Analitik (Layer 4-5, opsiyonel)

```
P2B.1  CorrelationAnalyzer (Pearson + Spearman)
P2B.2  SegmentationEngine (BCG matrix + Pareto)
P2B.3  Forecaster (Prophet entegrasyonu — ayrı değerlendirme)
```

**ROI sıralaması:** P1 > P2A.1-6 > P2A.7 > P2B.1-2 > P2B.3

---

## 8. PRODUCTION GEÇİŞİ İÇİN KONTROL LİSTESİ

```
[ ] Golden test seti hazır ve tüm testler geçiyor
[ ] Intent classification %90+ doğruluk (test seti üzerinde)
[ ] SQL generation %95+ başarı oranı (test seti üzerinde)
[ ] Column resolution %100 (bilinen alias'lar için)
[ ] Business rules çakışma senaryoları test edildi
[ ] HITL interrupt tüm düşük-confidence senaryolarda çalışıyor
[ ] Multi-turn context kayıpsız aktarılıyor
[ ] Pre-built SQL bypass regresyon testi geçiyor
[ ] Retry loop hata mesajları anlamlı ve test edildi
[ ] Docker container'da tüm testler geçiyor
[ ] Loglama: her karar noktası izlenebilir
[ ] Monitoring: hata oranları ve latency ölçülüyor
```

---

## 9. AKILDA TUTULMASI GEREKEN PRENSİPLER

### Accuracy için:

> **"Doğruluk, hız ve özellikten önce gelir."**  
> Bir intent yanlış sınıflandırıldığında tüm pipeline yanlış çalışır. Bu katmanı kırmadan production'a geçmek, her bug'ı kullanıcı önünde bulmak anlamına gelir.

> **"LLM'e SQL yazdırma, SQL'i Python üret."**  
> Mevcut `sql_generator` saf Python tasarımı korunmalı. LLM'in güçlü olduğu yer: anlama, eşleme, sınıflandırma. SQL üretimi: deterministik Python.

### Insight için:

> **"İstatistiksel anlamlılık kapısı olmadan insight olmaz."**  
> `InsightFilter` katmanı — p > 0.05 olan bulguları kullanıcıya gösterme. Anlamsız korelasyonlar güven kaybına yol açar.

> **"Kullanıcıya sayı değil, cümle ver."**  
> `r² = 0.87, slope = 2.3` yerine: *"Americano satışları son 6 haftada tutarlı biçimde artıyor, trendin güvenilirliği %87."*

> **"Her matematik katmanı bağımsız test edilebilir olmalı."**  
> `analytics_engine`'deki her fonksiyon input DataFrame → output dict formatında olmalı. LangGraph'tan bağımsız test edilebilir.

---

## 10. REFERANS MATERYALLERİ

### Kod konumları:
- Intent classification: `src/graphs/report_agent/nodes.py` — `create_classify_intent_node()`
- SQL generation: `src/graphs/report_agent/subagraphs/text2sql/nodes.py` — `sql_generator_node()`
- Business rules: `src/graphs/report_agent/subagraphs/text2sql/nodes.py` — `business_rules_node()`
- Value resolver: `src/services/value_resolver_service.py`
- State: `src/graphs/report_agent/state.py`
- Visualization: `src/graphs/report_agent/subagraphs/visualization_v2/`

### Kütüphane kaynakları:
- `pymannkendall`: Mann-Kendall trend testi için Python paketi
- `ruptures`: Changepoint detection (PELT algoritması)
- `prophet`: Meta'nın mevsimsel tahmin kütüphanesi
- `statsmodels`: OLS, ARIMA, STL decomposition

---

*Bu doküman bir analiz belgesidir. Implementasyon kararları verilmeden önce accuracy phase'in tamamlanması zorunludur.*
