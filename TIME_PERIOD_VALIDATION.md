# Time Period Validation - Zaman Aralığı Kontrolü

## Problem
Time series sorguları için zaman aralığı zorunlu olmasına rağmen, kullanıcı belirtmediğinde sistem hata veriyor veya yanlış sonuç üretiyor.

**Örnek Sorun:**
```
Kullanıcı: "Satışların zaman içindeki değişimini göster"
→ Query type: time_series ✅
→ Period: YOK ❌
→ SQL: Hatalı veya eksik
```

## Çözüm

### 1. Period Validation Eklendi
**Dosya:** `src/graphs/report/nodes.py` - `validate_entities_node`

Artık `time_series` ve `time_series_comparison` sorguları için period kontrolü yapılıyor.

#### Kontrol Edilen Yerler:
1. **parsed_intent** içindeki filters
2. **active_query_context** içindeki applied_filters
3. **User query** içinde zaman göstergeleri ("son", "geçen", "bu yıl", vs.)

```python
# Period Validation Logic
if query_type in ["time_series", "time_series_comparison"]:
    # Check parsed_intent steps for DocumentDate filters with DATEADD
    # Check active_query_context for period
    # Check user query for time indicators

    if not period:
        needs_clarification = True
        clarification_type = "period"
```

### 2. Period Clarification Eklendi
**Dosya:** `src/graphs/report/nodes.py` - `ask_user_for_clarification_node`

Period eksikse kullanıcıya soruluyor:

```
🤔 Sorgunuz: "Satışların zaman içindeki değişimini göster"

⏰ Hangi zaman aralığını analiz etmek istiyorsunuz?

Öneriler:
- Son 7 gün
- Son 1 ay
- Son 3 ay
- Son 6 ay
- Son 1 yıl
- Bu ay
- Bu yıl

Lütfen zaman aralığını girin (örn: "son 6 ay", "bu yıl"):
```

#### Period Mapping:
```python
period_mapping = {
    "son 7 gün": "7 DAY",
    "son 1 ay": "1 MONTH",
    "son 3 ay": "3 MONTH",
    "son 6 ay": "6 MONTH",
    "son 1 yıl": "1 YEAR",
    "bu ay": "CURRENT_MONTH",
    "bu yıl": "CURRENT_YEAR",
}
```

### 3. Clarification Type Tracking
State'e yeni field eklendi:
- `_clarification_type`: "entity" veya "period"
- `extracted_period`: Period bilgisi ve kaynağı

```python
{
    "extracted_period": {
        "period": "6 MONTH",
        "period_source": "user_clarification",  # or "parsed_intent", "active_context", "user_query"
        "has_period": True
    },
    "_clarification_type": "period"
}
```

## Kullanım Senaryoları

### Senaryo 1: Period Belirtilmiş ✅
```
Input: "Son 6 aydaki satışların zaman içindeki değişimi"

Validation:
  query_type: time_series
  period: "6 MONTH" (from user_query) ✅
  needs_clarification: False

→ SQL execute edilir
```

### Senaryo 2: Period Belirtilmemiş ❌ → Kullanıcıya Sor
```
Input: "Satışların zaman içindeki değişimini göster"

Validation:
  query_type: time_series
  period: None ❌
  needs_clarification: True
  clarification_type: "period"

Ask User:
  🤔 Hangi zaman aralığını analiz etmek istiyorsunuz?
  User: "son 3 ay"

Result:
  extracted_period: { period: "3 MONTH", source: "user_clarification" }
  → SQL execute edilir ✅
```

### Senaryo 3: Entity + Period İkisi de Eksik
```
Input: "Bunların satışlarını zaman içinde göster"

Validation:
  query_type: time_series_comparison
  entities: [] ❌
  period: None ❌
  clarification_type: "entity"  (önce entity sor)

Step 1 - Ask Entity:
  🤔 Hangi ProductName'leri karşılaştırmak istiyorsunuz?
  User: "Klasik Dürüm, Cajun Dürüm"

Step 2 - Ask Period:
  🤔 Hangi zaman aralığını analiz etmek istiyorsunuz?
  User: "son 1 yıl"

Result:
  entities: ["Klasik Dürüm", "Cajun Dürüm"] ✅
  period: "1 YEAR" ✅
  → SQL execute edilir ✅
```

## Validation Flow

```
classify_intent
    ↓
validate_entities_node
    ↓
    ├─ Entity Validation (comparison/ranking)
    │   ├─ Extract entities from context
    │   ├─ Check minimum count
    │   └─ Check confidence threshold
    │
    └─ Period Validation (time_series)
        ├─ Check parsed_intent
        ├─ Check active_context
        ├─ Check user query indicators
        └─ If missing → needs_clarification = True
    ↓
    [needs_clarification?]
    ↓
    ├─ YES → ask_user_for_clarification_node
    │          ├─ clarification_type = "entity" → Ask entities
    │          └─ clarification_type = "period" → Ask period
    │
    └─ NO → extract_query (continue)
```

## Zaman Göstergeleri (Auto-Detection)

Sistemin otomatik tespit ettiği zaman ifadeleri:
- "son"
- "geçen"
- "bu"
- "şu"
- "bu yıl"
- "geçen ay"
- "son 6 ay"
- "son hafta"

Bu ifadeler varsa `period_source = "user_query"` olarak işaretlenir.

## State Updates

### validate_entities_node dönüş değeri:
```python
{
    "extracted_entities": {...},       # Entity validation sonucu
    "extracted_period": {              # YENİ: Period validation sonucu
        "period": "6 MONTH",
        "period_source": "user_query",
        "has_period": True
    },
    "_needs_clarification": True/False,
    "_clarification_type": "entity" / "period" / None,  # YENİ
    "_entity_validation_done": True
}
```

### ask_user_for_clarification_node dönüş değeri (period):
```python
{
    "extracted_period": {
        "period": "3 MONTH",
        "period_source": "user_clarification",
        "has_period": True
    },
    "_needs_clarification": False,
    "_clarification_type": None
}
```

## Dikkat Edilmesi Gerekenler

1. **Period Format**: Kullanıcıdan alınan period, SQL architect tarafından işlenecek formata dönüştürülüyor:
   - "son 6 ay" → "6 MONTH"
   - "bu yıl" → "CURRENT_YEAR"

2. **Fallback**: Eğer period mapping'de yoksa, kullanıcının girdiği text as-is kullanılır (SQL architect parse edecek).

3. **Sequential Clarification**: Entity ve period ikisi de eksikse:
   - Önce entity sorulur
   - Sonra period sorulur
   - İki aşamalı validation

4. **Priority**: Entity clarification, period clarification'dan önceliklidir.

## Test Senaryoları

### Test 1: Period var, entity yok ✅
```
Input: "Son 6 aydaki ürünlerin satışlarını göster"
Expected: period = "6 MONTH" ✅, entities validation gerekli
```

### Test 2: Period yok, entity var ✅
```
Input: "Klasik Dürüm'ün satışlarını göster"
Expected: entities = ["Klasik Dürüm"] ✅, period clarification gerekli
```

### Test 3: İkisi de yok ❌ → İkisini de sor
```
Input: "Satışları göster"
Expected:
  Step 1: entities sor
  Step 2: period sor
```

### Test 4: İkisi de var ✅ → Direkt execute
```
Input: "Klasik Dürüm'ün son 6 aydaki satışlarını göster"
Expected: entities = ["Klasik Dürüm"] ✅, period = "6 MONTH" ✅
```

## Değiştirilen Dosyalar

- ✅ `src/graphs/report/nodes.py`
  - `validate_entities_node`: Period validation eklendi
  - `ask_user_for_clarification_node`: Period clarification eklendi

## Status
✅ **Implemented & Ready** - Test edilmeye hazır

## İyileştirme Fikirleri (Gelecek)

1. **Smart Period Suggestion**: Conversation history'ye göre kullanıcının tipik period tercihini öğren
2. **Period Validation**: SQL architect'ten önce period'un valid olup olmadığını kontrol et
3. **Multi-turn Period**: "Evet ama son 1 yıl için" gibi modifikasyonları handle et
4. **Period Auto-expand**: "Son dönem" → Otomatik olarak uygun period seç (örn: son 3 ay)
