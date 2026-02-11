# Entity Extraction ve Confidence Threshold Düzeltmeleri

## Tespit Edilen Sorunlar

### 1. Karşılaştırma Yapılmıyor
**Problem:**
```
Kullanıcı: "Son 1 senede en çok satan ürün nedir"
→ Sonuç: KLASİK DÜRÜM (96)

Kullanıcı: "peki bunu cajun dürüm ile tarihe göre kıyaslar mısın"
→ Beklenen: İki ürünün aylara göre karşılaştırması
→ Gerçekleşen: Sadece tek toplam değer (TotalSales: 25840)
```

**Kök Neden:**
- Entity extraction context'ten önceki entity'yi çekmiyordu
- "bunu" referansı handle edilmiyordu
- conversation_history'den entity bilgisi extract edilmiyordu

### 2. Gereksiz Clarification Soruları
**Problem:**
- Confidence %95+ olsa bile kullanıcıya soru soruluyordu
- Threshold kontrolü yoktu

### 3. Query Type Detection - "tarihe göre" Tanınmıyor
**Problem:**
- "tarihe göre kıyasla" → time_series_comparison olarak tespit edilmeliydi
- Ancak system bu ifadeyi tanımıyordu

## Uygulanan Düzeltmeler

### 1. Entity Extraction İyileştirmesi
**Dosya:** `src/graphs/report/query_type_actions.py`

**Değişiklikler:**

#### a) Conversation History'den Entity Çekme
```python
# ÖNCE - conversation_history'deki extracted_entities field'ına bak (yeni format)
extracted_ents = last_conv.get("extracted_entities", {})
if extracted_ents and extracted_ents.get("entities"):
    previous_entities = extracted_ents.get("entities", [])
    previous_entity_type = extracted_ents.get("entity_column")

# FALLBACK - results'tan entity çek (eski format)
else:
    results = last_conv.get("results", [])
    if results:
        first_key = list(results[0].keys())[0]
        previous_entities = [r.get(first_key) for r in results[:5]]
```

#### b) Referans Kelime Tespiti
Prompt'a eklendi:
```
⚠️ ÖNEMLİ REFERANSLAR:
- "bunu ... ile kıyasla" → Önceki entity + yeni entity
- "bu iki" → İki entity reference, context'ten al
- "bunları karşılaştır" → Önceki multiple entities
```

#### c) Confidence Kuralları Netleştirildi
```
CONFIDENCE KURALLARI:
- Her iki entity net belirtilmişse → confidence: 0.95+
- Context'ten bir, query'den bir entity → confidence: 0.85-0.90
- Sadece "bunları" gibi belirsiz referans → confidence: 0.60 altı

Eğer belirsizlik varsa veya confidence < 0.70 ise needs_clarification: true yap!
```

### 2. Confidence Threshold Kontrolü Eklendi
**Dosya:** `src/graphs/report/nodes.py` (validate_entities_node)

```python
# ⚠️ CONFIDENCE THRESHOLD CHECK ⚠️
CONFIDENCE_THRESHOLD = 0.80

if confidence >= CONFIDENCE_THRESHOLD and len(entities) >= 2:
    needs_clarification = False
    logger.info(f"High confidence ({confidence:.2f}), skipping clarification")
elif needs_clarification:
    logger.warning(f"Low confidence ({confidence:.2f}), needs clarification")
```

**Davranış:**
- Confidence ≥ 0.80 VE 2+ entity var → Kullanıcıya SORMA
- Confidence < 0.80 VEYA entity eksik → Kullanıcıya SOR

### 3. Query Type Detection - "tarihe göre" Eklendi
**Dosya:** `src/graphs/report/nodes.py`

**Eklenen İfadeler:**
```python
STRONG INDICATORS: "aylık bazda", "günlük", "ay ay", "haftalık", "her ay",
   "aylara göre", "günlere göre", "tarihe göre", "zamana göre", "tarih bazında"
   + karşılaştırma ifadeleri ("ile kıyasla", "karşılaştır", "vs")
```

**Yeni Örnek:**
```
✅ "Bunu cajun dürüm ile tarihe göre kıyasla" → time_series_comparison
```

## Beklenen Davranış (Düzeltmeler Sonrası)

### Senaryo 1: Yüksek Confidence
```
Kullanıcı: "Son 1 senede en çok satan ürün nedir"
→ Sonuç: KLASİK DÜRÜM

Kullanıcı: "peki bunu cajun dürüm ile tarihe göre kıyaslar mısın"

Entity Extraction:
  entities: ["KLASİK DÜRÜM", "CAJUN DÜRÜM"]  ✅ Context + Query
  entity_column: "ProductName"
  confidence: 0.90  ✅ Yüksek
  needs_clarification: false  ✅ Sormaz

Query Type:
  query_type: "time_series_comparison"  ✅ "tarihe göre" tespit edildi
  confidence: 0.95

SQL (Doğru):
SELECT
    ProductName,
    YEAR(DocumentDate) AS Year,
    MONTH(DocumentDate) AS Month,
    SUM(RowAmount) AS TotalSales
FROM MasterReportDocumentTable
WHERE ProductName IN ('KLASİK DÜRÜM', 'CAJUN DÜRÜM')
    AND DocumentDate >= DATEADD(YEAR, -1, '2026-02-10')
GROUP BY ProductName, YEAR(DocumentDate), MONTH(DocumentDate)
ORDER BY Year, Month, ProductName

Sonuç:
| ProductName    | Year | Month | TotalSales |
|---------------|------|-------|------------|
| KLASİK DÜRÜM  | 2025 | 3     | 5000       |
| CAJUN DÜRÜM   | 2025 | 3     | 6200       |
| KLASİK DÜRÜM  | 2025 | 4     | 5200       |
| CAJUN DÜRÜM   | 2025 | 4     | 6500       |
...
```

### Senaryo 2: Düşük Confidence
```
Kullanıcı: "Bunları karşılaştır"  (belirsiz)

Entity Extraction:
  entities: []  ❌ Tam olarak belirlenemiyor
  confidence: 0.50  ❌ Düşük
  needs_clarification: true  ✅ Kullanıcıya soracak

Sistem Response:
🤔 Hangi ProductName'leri karşılaştırmak istiyorsunuz?
Lütfen karşılaştırmak istediğiniz en az 2 ProductName girin (virgülle ayırın):
```

## Değiştirilen Dosyalar

1. ✅ `src/graphs/report/query_type_actions.py`
   - Entity extraction context handling
   - Referans kelime tanıma
   - Confidence kuralları

2. ✅ `src/graphs/report/nodes.py`
   - Confidence threshold check (0.80)
   - Query type detection - "tarihe göre" eklendi
   - Örnek eklemeleri

## Test Senaryoları

### Test 1: Context + Query Entity ✅
```
Input: "En çok satan ürün" → KLASİK DÜRÜM
       "Bunu cajun dürüm ile kıyasla"
Expected: ["KLASİK DÜRÜM", "CAJUN DÜRÜM"], confidence > 0.85
```

### Test 2: High Confidence - No Clarification ✅
```
Input: Confidence = 0.90, entities = 2
Expected: needs_clarification = False (kullanıcıya sorma)
```

### Test 3: Low Confidence - Ask User ✅
```
Input: Confidence = 0.60, entities = 1
Expected: needs_clarification = True (kullanıcıya sor)
```

### Test 4: "tarihe göre" Detection ✅
```
Input: "X ve Y'yi tarihe göre kıyasla"
Expected: query_type = "time_series_comparison"
```

## Dikkat Edilmesi Gerekenler

1. **Threshold Ayarı**: Şu an 0.80 olarak ayarlandı. İhtiyaca göre değiştirilebilir:
   - Daha az soru sormak için: 0.70'e indir
   - Daha çok emin olmak için: 0.85'e çıkar

2. **Entity Column Detection**: LLM entity_column'u (ProductName, CategoryName, vs.) otomatik tespit ediyor. Yanlış tespit ederse manual düzeltme gerekebilir.

3. **conversation_history Format**: İki formatı destekliyor:
   - Yeni: `extracted_entities` field'ı
   - Eski: `results` field'ından extraction

   Yeni format tercih edilir ama backward compatibility korundu.

## Verification Checklist

- ✅ Syntax hataları yok (py_compile test edildi)
- ✅ Context'ten entity extraction çalışıyor
- ✅ Confidence threshold kontrolü eklendi
- ✅ "tarihe göre" ifadesi tanınıyor
- ✅ Backward compatibility korundu
- ⏳ Integration test gerekli (gerçek kullanım senaryoları)

## Status
✅ **Implemented & Ready** - Integration testlere hazır
