# Query Type Detection - Implementation Plan (FINAL)

## 🎯 Amaç

Ardışık sorguları destekleyen, context-aware bir sorgu analiz sistemi.

**Core Problem:** Kullanıcı "En çok ciro yapan 3 şubeyi göster" sorusundan sonra "bu şubelerin satışları" dediğinde, sistem önceki 3 şubeyi hatırlamalı ve sadece onlar için sorgu çalıştırmalı.

**Prensip:** CONTEXT-AWARE + USER INTENT

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    USER QUERY                                │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  CLASSIFY INTENT (with Context)                             │
│  ├─ Intent Detection: visualization vs data vs comparison   │
│  ├─ Query Type Detection: ranking, comparison, time_series  │
│  ├─ Reference Detection: "bu şubeler", "onlar"              │
│  └─ Context Loading: conversation_history, last_results     │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
              ┌───────┴────────┐
              │  Confidence?   │
              └───────┬────────┘
                      │
        ┌─────────────┼─────────────┐
        │ < 0.6       │ >= 0.6      │
        ▼             ▼             │
   ┌─────────┐   ┌─────────────────┘
   │ASK USER │   │
   └────┬────┘   │
        │        │
        └────────┼────────────┐
                 ▼            │
        ┌────────────────────────────────────────┐
        │  EXTRACT QUERY + CONTEXT INJECTION     │
        │  └─ If follow-up: inject previous      │
        │     entities to SQL prompt             │
        └────────────┬───────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────────────────┐
        │  SQL EXECUTION                         │
        │  └─ SQL runs with context filters      │
        └────────────┬───────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────────────────┐
        │  UPDATE CONVERSATION HISTORY           │
        │  ├─ Save query + results + entities    │
        │  └─ Update last_query_results          │
        └────────────┬───────────────────────────┘
                     │
                     ▼
              ┌──────┴────────┐
              │ Intent Type?  │
              └──────┬────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
 ┌──────────┐ ┌──────────┐ ┌──────────┐
 │VISUALIZE │ │DATA ONLY │ │COMPARISON│
 │(chart)   │ │(table)   │ │(chart)   │
 └──────────┘ └──────────┘ └──────────┘
```

---

## 📊 Query Types (8 Types)

Query type sadece **analiz türünü** belirtir, chart'ı belirlemez!

1. **single_value** - Tek değer ("Toplam ciro nedir?")
2. **ranking** - Top-N sıralama ("En çok satan 10 ürün")
3. **comparison** - Karşılaştırma ("İstanbul vs Ankara")
4. **time_series** - Zaman serisi ("Son 6 aydaki satışlar")
5. **time_series_comparison** - Çoklu zaman serisi ("X ve Y'nin son yıldaki satışı")
6. **aggregation** - Gruplama ("Kategorilere göre toplam")
7. **distribution** - Dağılım ("Satışların dağılımı")
8. **trend** - Trend analizi ("Satışlar artıyor mu?")

---

## 🎨 Visualization Logic (CORRECTED)

**Query Type ≠ Chart Type**

**Decision Tree:**
```
1. Intent Detection:
   - user wants visualization? → Continue to chart selection
   - user wants data only? → Return table/data
   - ambiguous? → Ask user

2. IF visualization intent:
   - Query type helps suggest chart
   - But final decision based on:
     * Data structure (columns, rows)
     * User preference
     * Context

3. Chart Selection (if visualization intent):
   - ranking → bar_chart (if count > 3)
   - comparison → bar_chart
   - time_series → line_chart
   - distribution → pie_chart
   - trend → line_chart
   - aggregation → bar_chart or table (depends on data)
```

**Example:**
```
User: "En çok satan 10 ürünü göster"
→ Intent: data_query (no explicit visualization request)
→ Query Type: ranking
→ Output: Table (10 rows) ✅

User: "En çok satan 10 ürünü grafikte göster"
→ Intent: visualization
→ Query Type: ranking
→ Output: Bar chart ✅

User: "Bu şubelerin satışları nasıl?"
→ Intent: ambiguous → Ask user: "Grafik mi, tablo mu?"
```

---

## 📁 State Schema

### src/graphs/report/state.py

```python
from typing import TypedDict, Optional, List, Dict, Any

class ReportState(TypedDict):
    # ... existing fields ...

    # Query Analysis (NEW)
    query_type: Optional[str]                          # "ranking", "comparison", etc.
    query_type_confidence: Optional[float]             # 0.0-1.0

    # Follow-up Support (NEW)
    conversation_history: Optional[List[Dict[str, Any]]]
    # Format: [
    #   {
    #     "query": "En çok ciro yapan 3 şubeyi göster",
    #     "query_type": "ranking",
    #     "results": [{"branch": "Şube A", "revenue": 100000}, ...],
    #     "timestamp": "2026-02-09T10:30:00"
    #   }
    # ]

    last_query_results: Optional[Dict[str, Any]]
    # Format: {
    #   "entities": ["Şube A", "Şube B", "Şube C"],
    #   "entity_type": "branch",  # branch, product, category
    #   "filters": {"branch__in": ["Şube A", "Şube B", "Şube C"]}
    # }

    reference_context: Optional[Dict[str, Any]]
    # Format: {
    #   "is_followup": bool,
    #   "has_reference": bool,
    #   "reference_patterns": ["bu", "onlar"],
    #   "previous_entities": ["Şube A", "Şube B", "Şube C"],
    #   "entity_type": "branch"
    # }

    # Router Flags (NEW)
    _needs_clarification: Optional[bool]  # True → route to ask_user
```

---

## 🔧 Implementation

### 1. Reference Detection Helper

```python
# src/graphs/report/nodes.py

def _detect_references(user_message: str) -> Dict[str, Any]:
    """
    Detect if user is referencing previous results.

    Examples:
        "bu şubeler" → has_reference=True
        "onların satışı" → has_reference=True
        "İstanbul'un cirosu" → has_reference=False (specific entity)
    """
    user_lower = user_message.lower()

    # Turkish reference patterns
    reference_patterns = {
        "demonstrative": ["bu ", "şu ", "o ", "bunlar", "şunlar", "onlar"],
        "possessive": ["bunun", "şunun", "onun", "bunların", "onların"],
        "indirect": ["yukarıdaki", "önceki", "aynı"],
    }

    found_patterns = []
    for pattern_type, patterns in reference_patterns.items():
        for pattern in patterns:
            if pattern in user_lower:
                found_patterns.append(pattern)

    has_reference = len(found_patterns) > 0

    # Filter out time references ("bu ay", "bu yıl")
    time_patterns = ["bu ay", "bu yıl", "bu hafta", "bu gün"]
    if any(tp in user_lower for tp in time_patterns):
        has_reference = False

    return {
        "has_reference": has_reference,
        "reference_patterns": found_patterns,
        "needs_context": has_reference
    }
```

### 2. Context-Aware Query Analysis

```python
# src/graphs/report/nodes.py

async def _analyze_query_with_context(
    user_message: str,
    active_context: Optional[Dict],
    conversation_history: Optional[List[Dict]],
    last_query_results: Optional[Dict],
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    Analyze user query with conversation context.

    Returns:
        {
            "query_type": str,
            "confidence": float,
            "is_followup": bool,
            "needs_clarification": bool,
            "reference_context": Dict
        }
    """
    # 1. Detect references
    ref_detection = _detect_references(user_message)
    is_followup = ref_detection["has_reference"]

    # 2. Build context for LLM
    context_parts = []
    previous_context = ""

    if is_followup and conversation_history:
        last_conv = conversation_history[-1]
        prev_query = last_conv.get("query", "")
        prev_type = last_conv.get("query_type", "")
        prev_results = last_conv.get("results", [])

        # Extract entities from previous results
        prev_entities = []
        if prev_results and len(prev_results) > 0:
            first_key = list(prev_results[0].keys())[0]
            prev_entities = [r.get(first_key) for r in prev_results[:5]]

        previous_context = f"""
Önceki Sorgu: "{prev_query}"
Query Type: {prev_type}
Sonuçlar: {prev_entities}
Kullanıcı bu sonuçlara referans veriyor.
"""
        context_parts.append(f"Önceki sorgu: {prev_type}")

    # 3. LLM prompt
    prompt = f"""Kullanıcının sorgu türünü tespit et.

Soru: {user_message}
Context: {' | '.join(context_parts) if context_parts else 'Yok'}
Referans: {'EVET - önceki sonuçları kullanmalı' if is_followup else 'YOK'}

{previous_context if is_followup else ''}

Query Types:
- single_value: Tek metrik
- ranking: Top-N sıralama
- comparison: Karşılaştırma
- time_series: Zaman serisi
- time_series_comparison: Çoklu zaman serisi
- aggregation: Gruplama
- distribution: Dağılım
- trend: Trend

JSON döndür:
{{
    "query_type": "ranking",
    "confidence": 0.9,
    "needs_clarification": false,
    "reasoning": "..."
}}"""

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # Extract JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        import json
        data = json.loads(content)

        query_type = data.get("query_type", "aggregation")
        confidence = float(data.get("confidence", 0.5))
        needs_clarification = data.get("needs_clarification", False)

        # Validate query_type
        valid_types = ["single_value", "ranking", "comparison", "time_series",
                       "time_series_comparison", "aggregation", "distribution", "trend"]
        if query_type not in valid_types:
            logger.warning(f"[QUERY_TYPE] Invalid: {query_type}, fallback to aggregation")
            query_type = "aggregation"
            confidence = 0.3

        # Low confidence → clarification needed
        if confidence < 0.6:
            needs_clarification = True

        # Build reference context
        reference_context = {
            "is_followup": is_followup,
            "has_reference": ref_detection["has_reference"],
            "reference_patterns": ref_detection["reference_patterns"],
            "previous_entities": [],
            "entity_type": None
        }

        if is_followup and last_query_results:
            reference_context["previous_entities"] = last_query_results.get("entities", [])
            reference_context["entity_type"] = last_query_results.get("entity_type")

        logger.info(f"[QUERY_ANALYSIS] type={query_type}, conf={confidence:.2f}, "
                   f"followup={is_followup}, clarify={needs_clarification}")

        return {
            "query_type": query_type,
            "confidence": confidence,
            "is_followup": is_followup,
            "needs_clarification": needs_clarification,
            "reference_context": reference_context,
        }

    except json.JSONDecodeError as e:
        logger.error(f"[QUERY_ANALYSIS] JSON parse error: {e}")
        return {
            "query_type": "aggregation",
            "confidence": 0.3,
            "is_followup": is_followup,
            "needs_clarification": True,
            "reference_context": {},
        }
    except Exception as e:
        logger.error(f"[QUERY_ANALYSIS] Error: {e}")
        return {
            "query_type": "aggregation",
            "confidence": 0.3,
            "is_followup": is_followup,
            "needs_clarification": True,
            "reference_context": {},
        }
```

### 3. Update Intent Classifier Factory

```python
# src/graphs/report/nodes.py

def create_intent_classifier_node(llm: BaseChatModel, enable_fast_path: bool = True):
    """Factory for intent classifier with context support."""

    llm_classifier = IntentClassifier(llm)

    async def classify_intent_node(state: ReportState) -> Dict[str, Any]:
        """
        Classify intent + analyze query type with context.
        """
        user_message = get_last_user_message(state)
        if not user_message:
            return {"error": "No user message found"}

        logger.info(f"[REPORT] Classifying: {user_message[:50]}...")

        active_context = state.get("active_query_context")
        conversation_history = state.get("conversation_history", [])
        last_query_results = state.get("last_query_results")
        messages = state.get("messages", [])

        # 1. EXISTING: Intent classification
        intent_result = await llm_classifier.classify(
            user_message=user_message,
            messages=messages,
            active_context=active_context
        )

        # 2. NEW: Context-aware query analysis
        query_analysis = {}
        try:
            query_analysis = await _analyze_query_with_context(
                user_message=user_message,
                active_context=active_context,
                conversation_history=conversation_history,
                last_query_results=last_query_results,
                llm=llm
            )
        except Exception as e:
            logger.error(f"[QUERY_ANALYSIS] Failed: {e}")

        should_ask_user = query_analysis.get("needs_clarification", False)

        return {
            "_intent_type": intent_result.intent_type,
            "_confidence": intent_result.confidence,
            "_extracted_entities": intent_result.extracted_entities,
            # NEW fields
            "query_type": query_analysis.get("query_type"),
            "query_type_confidence": query_analysis.get("confidence", 0.0),
            "reference_context": query_analysis.get("reference_context", {}),
            "_needs_clarification": should_ask_user,
        }

    return classify_intent_node
```

### 4. Ask User Node

```python
# src/graphs/report/nodes.py

async def ask_user_for_clarification_node(state: ReportState) -> Dict[str, Any]:
    """
    Ask user when query type is ambiguous.
    """
    from langgraph.types import interrupt

    user_message = get_last_user_message(state)
    query_type = state.get("query_type", "unknown")
    confidence = state.get("query_type_confidence", 0.0)
    reference_context = state.get("reference_context", {})

    options = {
        "ranking": "Sıralama (Top-N)",
        "comparison": "Karşılaştırma (A vs B)",
        "time_series": "Zaman Serisi",
        "aggregation": "Gruplama/Toplam",
        "distribution": "Dağılım",
    }

    context_info = ""
    if reference_context.get("is_followup"):
        prev_entities = reference_context.get("previous_entities", [])
        if prev_entities:
            context_info = f"\n\n📌 Önceki sonuçlar: {', '.join(prev_entities[:3])}"

    message = f"""🤔 **Sorgunuz:** "{user_message}"

Sorgu türü belirsiz (güven: {confidence:.0%}). Hangi analiz türünü istiyorsunuz?{context_info}

**Seçenekler:**
"""
    for key, label in options.items():
        message += f"\n- **{key}**: {label}"

    user_choice = interrupt({
        "message": message,
        "type": "query_type_clarification",
        "options": list(options.keys()),
    })

    logger.info(f"[ASK_USER] User selected: {user_choice}")

    return {
        "query_type": user_choice,
        "query_type_confidence": 1.0,
        "_needs_clarification": False,
    }
```

### 5. Context Injection to SQL

```python
# src/graphs/report/nodes.py

async def extract_query_info_node(state: ReportState) -> Dict[str, Any]:
    """
    Extract query info + inject context to SQL prompt.

    CRITICAL: If follow-up query, inject previous entities to SQL.
    """
    user_message = get_last_user_message(state)
    reference_context = state.get("reference_context", {})
    last_query_results = state.get("last_query_results")

    # EXISTING: Normal query extraction
    # ... existing logic ...

    # NEW: Context injection for follow-up queries
    sql_context = ""
    if reference_context.get("is_followup") and last_query_results:
        prev_entities = last_query_results.get("entities", [])
        entity_type = last_query_results.get("entity_type", "entity")

        if prev_entities:
            # Escape for SQL safety
            entities_escaped = [str(e).replace("'", "''") for e in prev_entities[:10]]
            entities_str = "', '".join(entities_escaped)

            sql_context = f"""
CONTEXT (PREVIOUS RESULTS):
User is referencing previous query results.
Previous entities ({entity_type}): ['{entities_str}']

IMPORTANT: Add WHERE clause to filter by these entities:
WHERE {entity_type} IN ('{entities_str}')
OR
WHERE {entity_type}_name IN ('{entities_str}')
"""
            logger.info(f"[SQL_CONTEXT] Injected {len(prev_entities)} {entity_type} entities")

    # Inject context to SQL generation prompt
    # ... (modify your SQL prompt builder to include sql_context) ...

    return {
        # ... existing return fields ...
        "_sql_context_injected": bool(sql_context),
    }
```

### 6. Update Conversation History

```python
# src/graphs/report/nodes.py

async def update_conversation_history_node(state: ReportState) -> Dict[str, Any]:
    """
    Update conversation history after SQL execution.

    CRITICAL: Must be called after every successful query!
    """
    from datetime import datetime

    text2sql_output = state.get("text2sql_output")
    if not text2sql_output or text2sql_output.get("error"):
        return {}  # Don't save failed queries

    user_query = get_last_user_message(state)
    query_type = state.get("query_type")
    results = text2sql_output.get("results", [])

    # Get or init history
    conversation_history = state.get("conversation_history") or []

    # Add new entry
    new_entry = {
        "query": user_query,
        "query_type": query_type,
        "results": results[:10],  # Max 10 results to save memory
        "timestamp": datetime.now().isoformat(),
    }
    conversation_history.append(new_entry)

    # Keep only last 5 queries
    if len(conversation_history) > 5:
        conversation_history = conversation_history[-5:]

    # Update last_query_results for next follow-up
    last_query_results = None
    if results and len(results) > 0:
        first_key = list(results[0].keys())[0]
        entities = [r.get(first_key) for r in results]

        # Detect entity type (simple heuristic)
        entity_type = "unknown"
        if "branch" in first_key.lower() or "sube" in first_key.lower():
            entity_type = "branch"
        elif "product" in first_key.lower() or "urun" in first_key.lower():
            entity_type = "product"
        elif "category" in first_key.lower() or "kategori" in first_key.lower():
            entity_type = "category"

        last_query_results = {
            "entities": entities,
            "entity_type": entity_type,
            "filters": {f"{first_key}__in": entities},
        }

    logger.info(f"[HISTORY] Updated: {len(conversation_history)} entries, "
               f"last_results={'present' if last_query_results else 'none'}")

    return {
        "conversation_history": conversation_history,
        "last_query_results": last_query_results,
    }
```

### 7. Router Function

```python
# src/graphs/report/graph.py

def route_after_intent_classification(state: ReportState) -> str:
    """
    Route after intent classification.

    Returns:
        "ask_user" → needs clarification
        "extract_query" → continue normal flow
    """
    needs_clarification = state.get("_needs_clarification", False)

    if needs_clarification:
        logger.info("[ROUTER] Needs clarification, asking user")
        return "ask_user"

    return "extract_query"
```

### 8. Update Graph Builder

```python
# src/graphs/report/graph.py

def build_report_graph(...):
    """
    Build report graph with follow-up support.
    """
    # ... existing nodes ...

    # NEW: Add ask_user node
    graph.add_node("ask_user_clarification", ask_user_for_clarification_node)

    # NEW: Add history update node
    graph.add_node("update_conversation_history", update_conversation_history_node)

    # UPDATE: Conditional routing after intent classification
    graph.add_conditional_edges(
        "classify_intent",
        route_after_intent_classification,
        {
            "ask_user": "ask_user_clarification",
            "extract_query": "extract_query_info",
        }
    )

    # NEW: Ask user → continue to extract
    graph.add_edge("ask_user_clarification", "extract_query_info")

    # NEW: SQL execution → update history → visualization
    graph.add_edge("execute_sql", "update_conversation_history")
    graph.add_edge("update_conversation_history", "decide_visualization")

    # ... rest of existing edges ...
```

---

## 🧪 Test Scenarios

### Scenario 1: Normal Query (No Follow-up)

```python
Input:
  user_query = "En çok ciro yapan 3 şubeyi göster"

Expected Flow:
  1. classify_intent_node:
     - query_type = "ranking"
     - confidence = 0.9
     - is_followup = False
     - _needs_clarification = False

  2. extract_query_info_node:
     - No context injection
     - Normal SQL generation

  3. execute_sql:
     - Returns 3 branches

  4. update_conversation_history_node:
     - conversation_history = [{"query": "...", "results": [{"branch": "Şube A", ...}]}]
     - last_query_results = {"entities": ["Şube A", "Şube B", "Şube C"], "entity_type": "branch"}

  5. decide_visualization:
     - Intent check: user didn't ask for visualization
     - Output: Table/Data ✅
```

### Scenario 2: Follow-up Query

```python
State Before:
  conversation_history = [{
    "query": "En çok ciro yapan 3 şubeyi göster",
    "results": [{"branch": "Şube A"}, {"branch": "Şube B"}, {"branch": "Şube C"}]
  }]
  last_query_results = {"entities": ["Şube A", "Şube B", "Şube C"], "entity_type": "branch"}

Input:
  user_query = "Bu şubelerin en çok satış yapılan günü"

Expected Flow:
  1. classify_intent_node:
     - _detect_references → has_reference=True ("bu şubelerin")
     - query_type = "time_series"
     - is_followup = True
     - reference_context = {
         "is_followup": True,
         "previous_entities": ["Şube A", "Şube B", "Şube C"],
         "entity_type": "branch"
       }

  2. extract_query_info_node:
     - Context injection!
     - SQL prompt includes: WHERE branch IN ('Şube A', 'Şube B', 'Şube C')

  3. execute_sql:
     - SQL: SELECT branch, date, sales FROM ... WHERE branch IN ('Şube A', 'Şube B', 'Şube C')
     - Returns data ONLY for 3 branches ✅

  4. update_conversation_history_node:
     - Appends new query to history

  5. decide_visualization:
     - User didn't ask for chart → Data/Table
```

### Scenario 3: Ambiguous Query → Ask User

```python
Input:
  user_query = "bunları analiz et"

Expected Flow:
  1. classify_intent_node:
     - query_type = "aggregation" (guess)
     - confidence = 0.4 (LOW!)
     - _needs_clarification = True

  2. route_after_intent_classification:
     - Returns "ask_user"

  3. ask_user_for_clarification_node:
     - Shows options to user
     - User selects: "comparison"
     - Updates: query_type="comparison", confidence=1.0

  4. extract_query_info_node:
     - Continues with user-selected query_type
```

### Scenario 4: User Requests Visualization

```python
Input:
  user_query = "En çok satan 10 ürünü grafikte göster"

Expected Flow:
  1. classify_intent_node:
     - intent = "visualization" (user explicitly asked for "grafikte")
     - query_type = "ranking"

  2. decide_visualization:
     - Intent = visualization → Continue to chart
     - Query type = ranking → bar_chart
     - Output: Bar chart ✅
```

---

## ✅ Implementation Checklist

### Phase 1: Foundation
- [ ] Update `state.py` with new fields
- [ ] Add `_detect_references` helper
- [ ] Test reference detection

### Phase 2: Query Analysis
- [ ] Add `_analyze_query_with_context` helper
- [ ] Update `create_intent_classifier_node` factory
- [ ] Test context-aware analysis
- [ ] Test follow-up detection

### Phase 3: User Clarification
- [ ] Add `ask_user_for_clarification_node`
- [ ] Add `route_after_intent_classification` router
- [ ] Update graph with conditional edges
- [ ] Test ask_user flow

### Phase 4: Context Injection (CRITICAL)
- [ ] Update `extract_query_info_node` (SQL context injection)
- [ ] Test SQL WHERE clause generation
- [ ] Test follow-up queries return correct results
- [ ] **SECURITY:** Verify SQL injection prevention (escape strings!)

### Phase 5: History Management
- [ ] Add `update_conversation_history_node`
- [ ] Update graph with history edge
- [ ] Test history updates
- [ ] Test memory management (max 5 entries)

### Phase 6: End-to-End Testing
- [ ] Test: Normal query
- [ ] Test: Follow-up query (2-step)
- [ ] Test: Multi-step follow-up (3+ steps)
- [ ] Test: Ambiguous query → ask_user
- [ ] Test: User requests visualization
- [ ] Test: Backward compatibility

---

## ⚠️ Critical Risks

### Risk 1: SQL Injection
**Problem:** Previous entities injected to SQL prompt

**Mitigation:**
```python
# Escape single quotes
entities_escaped = [str(e).replace("'", "''") for e in entities]
```

### Risk 2: Memory Leak
**Problem:** Conversation history grows unbounded

**Mitigation:**
- Max 5 queries in history
- Max 10 results per query

### Risk 3: Reference Resolution Failure
**Problem:** "bu şubeler" but no previous results

**Mitigation:**
- Check `last_query_results` exists
- Graceful degradation → normal flow

---

## 📊 Summary

**Files Changed:** 4 files
- `state.py`: +5 lines
- `nodes.py`: +400 lines
- `graph.py`: +15 lines
- `report_interpreter.py`: No change (intent-based, not query_type-based)

**Total:** ~420 lines

**Implementation Time:** 5-7 days

**Status:** READY FOR IMPLEMENTATION ✅
