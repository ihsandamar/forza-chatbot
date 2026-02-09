# Query Type Detection - Implementation Plan v2 (RELIABILITY FIX)

## 🎯 Amaç

Kullanıcının ne tür bir analiz yaptığını tespit etmek ve buna göre optimal chart seçimi yapmak.

**Mevcut yapı BOZULMAYACAK - Sadece EK özellik olarak eklenecek.**

**Prensip: KISS + RELIABLE - Basit ama doğru çalışan sistem**

---

## ⚠️ v1'den v2'ye Geçiş Nedeni

**v1 Sorunları:**
1. ❌ Factory pattern eksik → LLM injection yapılamıyor
2. ❌ State propagation belirsiz → query_type report_interpreter'a geçmiyor
3. ❌ Error handling zayıf → Bare except kullanılmış
4. ❌ JSON parsing kırılgan → ```json``` wrapper handle edilmiyor

**v2 Çözümleri:**
1. ✅ Mevcut factory pattern kullanılıyor
2. ✅ State propagation açık ve net
3. ✅ Proper error handling + logging
4. ✅ Robust JSON extraction

---

## 📊 Query Types (Sabit 8 Tane)

1. **single_value** - Tek değer → No chart
2. **ranking** - Top-N → Bar chart
3. **comparison** - Karşılaştırma → Bar chart
4. **time_series** - Zaman serisi → Line chart
5. **time_series_comparison** - Çoklu zaman serisi → Multi-line chart
6. **aggregation** - Gruplama → Bar chart
7. **distribution** - Dağılım → Pie chart
8. **trend** - Trend analizi → Line chart

---

## 🏗️ Architecture

```
classify_intent_node (FACTORY ile oluşturulur)
    ↓ (içinde: intent + query_type detection)
    ↓ (state'e query_type kaydedilir)
    ↓
decide_visualization_node (FACTORY'den query_type okur)
    ↓
report_interpreter.interpret_results(query_type=...)
    ↓
Visualization
```

---

## 📁 Dosya Değişiklikleri (CORRECTED)

### 1. **GÜNCELLE:** `src/graphs/report/state.py`

```python
class ReportState(TypedDict):
    # ... mevcut alanlar ...

    # Query Type Detection (NEW) - Minimal
    query_type: Optional[str]                   # "ranking", "comparison", etc.
    query_type_confidence: Optional[float]      # 0.0-1.0
```

**Değişiklik:** +2 satır

---

### 2. **GÜNCELLE:** `src/graphs/report/nodes.py`

#### 2.1. Helper Function (Module Level)

```python
async def _detect_query_type_simple(
    user_message: str,
    active_context: Optional[ActiveQueryContext],
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    Basit query type detection - Tek LLM call.

    Args:
        user_message: Kullanıcı sorusu
        active_context: Aktif context (opsiyonel)
        llm: Language model

    Returns:
        {"query_type": str, "confidence": float}
    """
    # Context formatla (basit)
    context_info = "Yok"
    if active_context:
        filters = active_context.get('applied_filters', [])
        if filters:
            context_info = f"Aktif filtreler var: {len(filters)} filtre"

    # Basit prompt (hardcoded)
    prompt = f"""Kullanıcının ne tür analiz yaptığını tespit et.

Kullanıcı sorusu: {user_message}
Context: {context_info}

Query Types:
- single_value: Tek bir metrik ("Toplam satış?")
- ranking: Top-N sıralama ("En çok satan 10 ürün")
- comparison: İki/daha fazla öğe karşılaştırması ("İstanbul vs Ankara")
- time_series: Zaman içinde değişim ("Son 6 aydaki satışlar")
- time_series_comparison: Çoklu zaman serisi ("X ve Y'nin son yıldaki satışı")
- aggregation: Gruplama ("Kategorilere göre toplam")
- distribution: Dağılım ("Satışların dağılımı")
- trend: Trend analizi ("Satışlar artıyor mu?")

JSON döndür (sadece JSON):
{{
    "query_type": "ranking",
    "confidence": 0.9
}}"""

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # Robust JSON extraction (handle ```json``` wrapper)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        import json
        data = json.loads(content)

        query_type = data.get("query_type", "aggregation")
        confidence = float(data.get("confidence", 0.5))

        # Validate query_type
        valid_types = ["single_value", "ranking", "comparison", "time_series",
                       "time_series_comparison", "aggregation", "distribution", "trend"]
        if query_type not in valid_types:
            logger.warning(f"[QUERY_TYPE] Invalid type '{query_type}', fallback to aggregation")
            query_type = "aggregation"
            confidence = 0.3

        logger.info(f"[QUERY_TYPE] Detected: {query_type} (confidence: {confidence:.2f})")

        return {
            "query_type": query_type,
            "confidence": confidence
        }

    except json.JSONDecodeError as e:
        logger.error(f"[QUERY_TYPE] JSON parse error: {e}. Content: {content[:100]}")
        return {"query_type": "aggregation", "confidence": 0.3}
    except Exception as e:
        logger.error(f"[QUERY_TYPE] Detection error: {e}")
        return {"query_type": "aggregation", "confidence": 0.3}
```

#### 2.2. Factory Function Update

```python
def create_intent_classifier_node(llm: BaseChatModel, enable_fast_path: bool = True):
    """
    Intent classifier node factory.

    UPDATED: Query type detection eklendi.

    Args:
        llm: Language model for classification
        enable_fast_path: Enable fast-path pattern matching

    Returns:
        Node function with query type detection
    """
    # LLM classifier
    llm_classifier = IntentClassifier(llm)
    simple_classifier = SimpleIntentClassifier()

    async def classify_intent_node(state: ReportState) -> Dict[str, Any]:
        """
        Intent classification + query type detection.
        """
        user_message = get_last_user_message(state)
        if not user_message:
            return {"error": "No user message found"}

        logger.info(f"[REPORT] Classifying intent: {user_message[:50]}...")

        active_context = state.get("active_query_context")
        has_context = active_context is not None
        messages = state.get("messages", [])

        # 1. MEVCUT: Intent classification (değişmedi)
        # ... mevcut intent classification logic ...
        # (Fast-path, simple classifier, LLM classifier logic)

        # Örnek basitleştirilmiş (gerçekte mevcut kod korunur):
        intent_result = await llm_classifier.classify(
            user_message=user_message,
            messages=messages,
            active_context=active_context
        )

        # 2. YENİ: Query type detection
        query_type = None
        query_type_confidence = 0.0

        try:
            query_type_result = await _detect_query_type_simple(
                user_message=user_message,
                active_context=active_context,
                llm=llm
            )
            query_type = query_type_result["query_type"]
            query_type_confidence = query_type_result["confidence"]
        except Exception as e:
            logger.error(f"[QUERY_TYPE] Detection failed: {e}")
            # Continue without query_type (backward compatible)

        return {
            "_intent_type": intent_result.intent_type,
            "_confidence": intent_result.confidence,
            "_extracted_entities": intent_result.extracted_entities,
            # YENİ alanlar
            "query_type": query_type,
            "query_type_confidence": query_type_confidence
        }

    return classify_intent_node
```

**Değişiklik:** +80 satır (helper function + factory update)

---

### 3. **GÜNCELLE:** `src/graphs/report/nodes.py` (Visualization Decision Factory)

```python
def create_llm_viz_decision_node(report_interpreter):
    """
    Factory for LLM-assisted visualization decision node.

    UPDATED: Query type support eklendi.

    Args:
        report_interpreter: ReportInterpreter instance

    Returns:
        LLM-powered visualization decision node with query type support
    """
    async def decide_visualization_llm_node(state: ReportState) -> Dict[str, Any]:
        """
        LLM-powered visualization decision with query type awareness.
        """
        text2sql_output = state.get("text2sql_output")
        if not text2sql_output or text2sql_output.get("error"):
            logger.info("[REPORT] [LLM] No valid results for visualization decision")
            return {}

        user_query = get_last_user_message(state) or ""
        results = text2sql_output.get("results", [])
        active_context = state.get("active_query_context")

        # YENİ: State'den query_type al
        query_type = state.get("query_type")

        logger.info(f"[REPORT] [LLM] Deciding visualization for {len(results)} results (query_type={query_type})...")

        try:
            # YENİ: query_type parametresi eklendi
            interpretation = await report_interpreter.interpret_results(
                user_query=user_query,
                data_results=results,
                active_context=active_context,
                query_type=query_type  # ← YENİ parametre
            )

            logger.info(f"[REPORT] [LLM] Decision: {interpretation.output_type} (needs_graph={interpretation.needs_graph})")

            return {
                "_viz_decision": interpretation.dict()
            }

        except Exception as e:
            logger.error(f"[REPORT] [LLM] Visualization decision error: {e}")
            # Fallback to rule-based
            return await decide_visualization_node(state)

    return decide_visualization_llm_node
```

**Değişiklik:** +5 satır (query_type parametresi eklendi)

---

### 4. **GÜNCELLE:** `src/graphs/report/report_interpreter.py`

```python
class ReportInterpreter:
    async def interpret_results(
        self,
        user_query: str,
        data_results: List[Dict[str, Any]],
        active_context: Optional[Dict[str, Any]] = None,
        query_type: Optional[str] = None  # YENİ parametre
    ) -> InterpretationResult:
        """
        Query type'a göre chart seçimi.

        Args:
            user_query: Kullanıcı sorusu
            data_results: SQL sonuçları
            active_context: Aktif context
            query_type: Query type (opsiyonel)

        Returns:
            InterpretationResult with visualization decision
        """

        # YENİ: Query type-based quick rules (öncelikli)
        if query_type:
            # Single value
            if query_type == "single_value":
                return InterpretationResult(
                    needs_graph=False,
                    output_type="single_value",
                    chart_type=None,
                    reason="Tek değer - chart gerekmez",
                    alternatives=["table"],
                    key_insight=None,
                    reasoning=f"Query type: {query_type}"
                )

            # Comparison
            elif query_type == "comparison":
                return InterpretationResult(
                    needs_graph=True,
                    output_type="bar_chart",
                    chart_type="bar_chart",
                    reason="Karşılaştırma - bar chart optimal",
                    alternatives=["table"],
                    key_insight=None,
                    reasoning=f"Query type: {query_type}"
                )

            # Time series
            elif query_type == "time_series":
                return InterpretationResult(
                    needs_graph=True,
                    output_type="line_chart",
                    chart_type="line_chart",
                    reason="Zaman serisi - line chart optimal",
                    alternatives=["bar_chart", "table"],
                    key_insight=None,
                    reasoning=f"Query type: {query_type}"
                )

            # Time series comparison
            elif query_type == "time_series_comparison":
                return InterpretationResult(
                    needs_graph=True,
                    output_type="line_chart",
                    chart_type="line_chart",
                    reason="Çoklu zaman serisi - multi-line chart",
                    alternatives=["bar_chart", "table"],
                    key_insight=None,
                    reasoning=f"Query type: {query_type}"
                )

            # Distribution
            elif query_type == "distribution":
                return InterpretationResult(
                    needs_graph=True,
                    output_type="pie_chart",
                    chart_type="pie_chart",
                    reason="Dağılım - pie chart optimal",
                    alternatives=["bar_chart", "table"],
                    key_insight=None,
                    reasoning=f"Query type: {query_type}"
                )

            # Ranking
            elif query_type == "ranking":
                if len(data_results) > 5:
                    return InterpretationResult(
                        needs_graph=True,
                        output_type="bar_chart",
                        chart_type="bar_chart",
                        reason="Top-N ranking - bar chart optimal",
                        alternatives=["table"],
                        key_insight=None,
                        reasoning=f"Query type: {query_type}"
                    )

            # Trend
            elif query_type == "trend":
                return InterpretationResult(
                    needs_graph=True,
                    output_type="line_chart",
                    chart_type="line_chart",
                    reason="Trend analizi - line chart optimal",
                    alternatives=["bar_chart", "table"],
                    key_insight=None,
                    reasoning=f"Query type: {query_type}"
                )

            # Aggregation (default)
            # If query_type is "aggregation" or any other, fall through to existing logic

        # MEVCUT: Quick rules (data-based)
        quick_result = self._quick_rules(user_query, data_results)
        if quick_result:
            logger.info(f"[INTERPRETER] Quick rule applied: {quick_result.output_type}")
            return quick_result

        # MEVCUT: LLM interpretation (fallback)
        if self.use_llm:
            return await self._llm_interpret(user_query, data_results, active_context)

        # MEVCUT: Rule-based fallback
        return self._rule_based_fallback(user_query, data_results)
```

**Değişiklik:** +60 satır (query_type handling)

---

## 🔄 Flow (Açık State Propagation)

```
1. User Query
   ↓
2. classify_intent_node (factory'den oluşturulur, llm inject edilir)
   ↓ (intent + query_type detection)
   ↓ (state'e yazılır: query_type, query_type_confidence)
   ↓
3. extract_query / text2sql
   ↓
4. decide_visualization_llm_node (factory'den oluşturulur)
   ↓ (state'den okur: query_type)
   ↓ (report_interpreter.interpret_results(query_type=...))
   ↓
5. Visualization render
   ↓
6. build_response
```

**State Flow:**
```
classify_intent_node:
    output: {"query_type": "ranking", "query_type_confidence": 0.9}
    → state["query_type"] = "ranking"

decide_visualization_llm_node:
    input: state["query_type"]  # "ranking"
    → report_interpreter.interpret_results(query_type="ranking")
    → returns InterpretationResult(chart_type="bar_chart")
```

---

## ✅ Reliability Checklist

### Integration Points
- ✅ **Factory pattern:** Mevcut pattern kullanılıyor
- ✅ **LLM injection:** Factory closure ile inject ediliyor
- ✅ **State propagation:** Açık ve net (classify → state → decide)
- ✅ **Parameter passing:** query_type explicit geçiliyor

### Error Handling
- ✅ **JSON parse error:** try-except + fallback
- ✅ **LLM call error:** try-except + fallback
- ✅ **Invalid query_type:** Validation + fallback
- ✅ **Missing query_type:** None → mevcut logic çalışır

### Backward Compatibility
- ✅ **query_type None:** Mevcut report_interpreter logic çalışır
- ✅ **LLM yok:** Detection atlanır, query_type=None
- ✅ **Eski nodes:** Değişmeden çalışır
- ✅ **State fields:** Optional → eski state'ler bozulmaz

### Edge Cases
- ✅ **Context yok:** context_info = "Yok"
- ✅ **Results boş:** Fallback to mevcut logic
- ✅ **Confidence düşük:** Yine de chart seçimi yapılır
- ✅ **```json``` wrapper:** Robust JSON extraction

---

## 🧪 Test Scenarios

### Test 1: Normal Flow
```python
# Input
user_query = "En çok satan 10 ürün"

# Expected
classify_intent_node → query_type = "ranking"
decide_visualization_node → chart_type = "bar_chart"
```

### Test 2: Query Type Detection Fail
```python
# LLM response: "Error" (invalid JSON)

# Expected
_detect_query_type_simple → {"query_type": "aggregation", "confidence": 0.3}
report_interpreter → fallback to mevcut logic
```

### Test 3: Backward Compatible (query_type None)
```python
# Old system - no query_type field

# Expected
classify_intent_node → query_type = None
report_interpreter → skip query_type logic, use mevcut logic
```

### Test 4: Context-Aware Time Series Comparison
```python
# User: "En yüksek ürün?"
# AI: "X dürüm"
# User: "Y ile karşılaştır"

# Expected
_detect_query_type_simple(context=X) → "time_series_comparison"
report_interpreter → chart_type = "line_chart" (multi-line)
```

---

## 📊 Karmaşıklık Analizi

### Kod Değişikliği
```
state.py:                   +2 satır
nodes.py (helper):          +80 satır
nodes.py (factory update):  +10 satır
nodes.py (viz factory):     +5 satır
report_interpreter.py:      +60 satır

TOPLAM: ~157 satır, 3 dosya
```

### Maintainability
- ✅ Factory pattern (mevcut yapıya uyumlu)
- ✅ Proper error handling
- ✅ Robust JSON parsing
- ✅ Clear state propagation
- ✅ Backward compatible

---

## 📝 Implementation Steps (Doğru Sıra)

### Step 1: State
1. `state.py` → query_type fields ekle

### Step 2: Detection
2. `nodes.py` → _detect_query_type_simple helper ekle
3. `nodes.py` → create_intent_classifier_node factory güncelle
4. Test: query_type detection çalışıyor mu?

### Step 3: Integration
5. `nodes.py` → create_llm_viz_decision_node factory güncelle
6. `report_interpreter.py` → query_type parametresi ekle + if-elif logic
7. Test: query_type → chart mapping çalışıyor mu?

### Step 4: E2E Test
8. Full flow test: User query → chart selection
9. Backward compat test: query_type=None durumu
10. Error case test: LLM fail, JSON parse fail

---

## 🔗 Related Files

**GÜNCELLENEN:**
- `src/graphs/report/state.py` (+2 satır)
- `src/graphs/report/nodes.py` (+95 satır)
- `src/graphs/report/report_interpreter.py` (+60 satır)

**DEĞİŞMEYEN:**
- `src/graphs/report/graph.py` (factory zaten doğru çağrılıyor)
- Tüm diğer dosyalar

---

**Son Güncelleme:** 2026-02-06
**Durum:** RELIABILITY CHECKED ✅
**Versiyon:** 2.0 (Corrected Integration)
**Karmaşıklık:** Minimal (~157 satır)
**Reliability:** HIGH ⭐⭐⭐
