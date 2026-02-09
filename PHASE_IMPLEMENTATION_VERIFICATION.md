# Phase Implementation Verification Guide

## ✅ Yapılan Düzeltmeler

### Sorun
Yeni implementation çalışmıyordu çünkü:
- `create_conversation_aware_intent_node` güncellenmmemişti (sadece `create_intent_classifier_node` güncellenmişti)
- Logging eksikti, hangi phase'lerin çalıştığı belli değildi

### Düzeltme
1. ✅ `create_conversation_aware_intent_node` güncellendi (Phase 2 logic eklendi)
2. ✅ Tüm critical noktalara logging eklendi
3. ✅ Router'da detaylı log mesajları

---

## 🔍 Test Nasıl Yapılır

### 1. Log Kontrol Noktaları

Implementation'ın çalışıp çalışmadığını kontrol etmek için şu log mesajlarını arayın:

#### Phase 1: Reference Detection
```
[REFERENCE_LLM] Message: '...', has_reference=True/False, type=..., conf=...
```

#### Phase 2: Query Analysis
```
[QUERY_ANALYSIS] Result: type=ranking, conf=0.95, followup=False
```

#### Phase 3: Router Check
```
[ROUTER] [PHASE3-6] Composite router check: query_type=ranking, conf=0.95, followup=False, needs_clarification=False
```

#### Phase 4: Context Injection
```
[PHASE4] Context injection check: is_followup=True, has_last_results=True
[REPORT] [PHASE4] Context injection: 3 branch entities
```

#### Phase 5: History Update
```
[PHASE5] [HISTORY] Updated: 1 entries, last_results=present
[PHASE5] [HISTORY] Last query results: 3 branch entities (preview: ['Şube A', 'Şube B', 'Şube C'])
```

---

## 🧪 Test Senaryoları

### Test 1: Normal Query (No Follow-up)

**User Query:**
```
"En çok ciro yapan 3 şubeyi göster"
```

**Expected Logs:**
```
[REFERENCE_LLM] Message: '...', has_reference=False, type=none
[QUERY_ANALYSIS] Result: type=ranking, conf=0.90, followup=False
[ROUTER] [PHASE3-6] Composite router check: query_type=ranking, conf=0.90, followup=False, needs_clarification=False
[PHASE4] Context injection check: is_followup=False, has_last_results=False
[PHASE5] [HISTORY] Updated: 1 entries, last_results=present
[PHASE5] [HISTORY] Last query results: 3 branch entities (preview: ['Şube A', 'Şube B', 'Şube C'])
```

**Expected Result:**
- ✅ Query type detected: ranking
- ✅ No context injection
- ✅ History updated with 3 branches

---

### Test 2: Follow-up Query

**Setup:** First run Test 1 to populate history

**User Query:**
```
"Bu şubelerin satışları"
```

**Expected Logs:**
```
[REFERENCE_LLM] Message: 'Bu şubelerin satışları', has_reference=True, type=previous_results, conf=0.90
[QUERY_ANALYSIS] Result: type=aggregation, conf=0.85, followup=True
[ROUTER] [PHASE3-6] Composite router check: query_type=aggregation, conf=0.85, followup=True, needs_clarification=False
[PHASE4] Context injection check: is_followup=True, has_last_results=True
[REPORT] [PHASE4] Context injection: 3 branch entities
[REPORT] [PHASE4] SQL context hint: ...WHERE branch IN ('Şube A', 'Şube B', 'Şube C')...
```

**Expected Result:**
- ✅ Reference detected: "bu şubelerin"
- ✅ Follow-up query: True
- ✅ Context injected to SQL
- ✅ SQL WHERE clause includes only 3 branches

---

### Test 3: Ambiguous Query → Ask User

**User Query:**
```
"bunları analiz et"
```

**Expected Logs:**
```
[QUERY_ANALYSIS] Result: type=aggregation, conf=0.40, followup=False
[QUERY_ANALYSIS] Low confidence (0.40), needs clarification
[ROUTER] [PHASE3-6] Composite router check: query_type=aggregation, conf=0.40, followup=False, needs_clarification=True
[ROUTER] [PHASE3] Query type unclear, routing to ask_user_clarification
```

**Expected Result:**
- ✅ Low confidence detected
- ✅ Router sends to ask_user_clarification
- ✅ User sees options: ranking, comparison, time_series, etc.

---

## 🐛 Debugging

### Phase'ler Görünmüyorsa

1. **LLM Kontrolü:**
   ```python
   # Graph builder'da hangi intent classifier kullanılıyor?
   # Log'da şunu arayın:
   "[REPORT] Using ConversationManager for intent understanding"
   # veya
   "[REPORT] Using IntentClassifier (standard)"
   ```

2. **State Kontrolü:**
   ```python
   # classify_intent_node'dan sonra state'te şu field'ler olmalı:
   - query_type
   - query_type_confidence
   - reference_context
   - _needs_clarification
   ```

3. **Router Kontrolü:**
   ```python
   # composite_router kullanılıyor mu?
   # Log'da şunu arayın:
   "[ROUTER] [PHASE3-6] Composite router check"
   ```

### SQL Context Injection Çalışmıyorsa

1. **extract_query_node log kontrolü:**
   ```
   [PHASE4] Context injection check: is_followup=True, has_last_results=True
   ```

2. **last_query_results kontrolü:**
   - Önceki sorguda Phase 5 çalışmış mı?
   - `[PHASE5] [HISTORY] Last query results` log'u var mı?

3. **SQL query'ye bak:**
   - WHERE clause var mı?
   - Entity'ler doğru escape edilmiş mi?

---

## 📊 Implementation Status

| Component | Status | Log Prefix |
|-----------|--------|------------|
| Reference Detection | ✅ | `[REFERENCE_LLM]` |
| Query Analysis | ✅ | `[QUERY_ANALYSIS]` |
| Router | ✅ | `[ROUTER] [PHASE3-6]` |
| Context Injection | ✅ | `[PHASE4]` |
| History Update | ✅ | `[PHASE5] [HISTORY]` |

---

## 🚀 Next Steps

1. Run a test query
2. Check logs for phase markers
3. Verify each phase is executing
4. Test follow-up query flow
5. Monitor conversation history memory

---

**Last Updated:** 2026-02-09
**Status:** ✅ FIXED - Ready for Testing
