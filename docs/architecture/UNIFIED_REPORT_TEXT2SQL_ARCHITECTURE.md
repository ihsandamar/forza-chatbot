# Unified Report + Text2SQL Architecture - Performance Optimization Plan

## 🎯 Problem: Response Time Çok Uzun

### Mevcut Durum Analizi

#### Current Flow (Sequential, ~5-8 saniye)

```
┌─────────────────────────────────────────────────────────────────┐
│                    REPORT AGENT                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. immediate_ack                        (instant)              │
│  2. classify_intent                      (LLM #1 - 500ms)       │
│     └─> ConversationManager                                     │
│  3. extract_query                        (no LLM)               │
│  4. text2sql (calls entire text2sql graph below)                │
│     │                                                            │
│     ├─> GENERIC TEXT2SQL GRAPH                                  │
│     │   ┌──────────────────────────────────────────┐           │
│     │   │ 1. create_table           (DB - 100ms)   │           │
│     │   │ 2. sql_architect          (LLM #2 - 1s)  │           │
│     │   │ 3. retrieve_business_rules (vector - 50ms)│          │
│     │   │ 4. metadata_enrichment    (DB - 100ms)   │           │
│     │   │ 5. value_resolver         (LLM #3 - 500ms)│          │
│     │   │ 6. sql_query_builder      (no LLM)       │           │
│     │   │ 7. sql_executor           (DB - 200ms)   │           │
│     │   │ 8. cleanup_table          (DB - 50ms)    │           │
│     │   └──────────────────────────────────────────┘           │
│     │                                                            │
│  5. check_results                        (no LLM)               │
│  6. extract_business_insights            (LLM #4 - 800ms)       │
│     └─> BusinessContextTracker                                  │
│  7. decide_visualization                 (LLM #5 - 700ms)       │
│     └─> ReportInterpreter                                       │
│  8. visualization                        (render - 100ms)       │
│  9. build_response                       (LLM #6 - 600ms)       │
│     └─> ResponseGenerator                                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

TOTAL: ~5-8 saniye (6 LLM çağrısı, hepsi sequential)
```

### Problem Noktaları

1. **Sequential LLM Calls:** 6 LLM çağrısı sırayla (classify_intent, sql_architect, value_resolver, business_insights, viz_decision, response_gen)
2. **Context Duplication:** Her agent ayrı ayrı context işliyor
3. **Redundant Processing:** Text2SQL ve Report Agent benzer bilgileri işliyor
4. **No Parallelization:** Paralelleştirilebilecek işlemler sequential
5. **No Smart Caching:** Semantic cache kullanılsa bile yeterli değil

---

## 🚀 Optimized Architecture - Unified Graph

### Hedef: ~2-3 saniye (50-60% iyileşme)

### Strategy

1. **Parallel LLM Calls:** İlgisiz LLM çağrılarını paralel yap
2. **Shared Context:** Tek bir context, her iki agent kullanır
3. **Smart Fast-Paths:** Basit sorgular için LLM bypass
4. **Unified State:** Tek state, tüm bilgiyi tutar
5. **Aggressive Caching:** Her seviyede cache

---

## 🏗️ New Unified Architecture

### Option 1: Parallel Execution (Recommended)

```
┌─────────────────────────────────────────────────────────────────┐
│              UNIFIED REPORT + TEXT2SQL AGENT                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  START                                                           │
│    │                                                             │
│    ├─> immediate_ack                     (instant)              │
│    │                                                             │
│    └─> classify_intent_fast              (Fast Path)            │
│        ├─ Simple rules                   (0ms)                  │
│        └─ If complex → LLM               (LLM #1 - 500ms)       │
│                                                                  │
│        [PARALLEL EXECUTION BLOCK - ~2s total]                   │
│        ┌────────────────────────────────────────────┐          │
│        │ Thread 1: SQL Generation                   │          │
│        │  ├─> create_table        (DB - 100ms)      │          │
│        │  ├─> sql_architect       (LLM #2 - 1s)    │          │
│        │  ├─> retrieve_rules      (vector - 50ms)  │          │
│        │  ├─> metadata_enrich     (DB - 100ms)     │          │
│        │  ├─> value_resolve       (cached/fast)    │          │
│        │  ├─> sql_build           (no LLM)         │          │
│        │  ├─> sql_execute         (DB - 200ms)     │          │
│        │  └─> cleanup_table       (DB - 50ms)      │          │
│        │                                            │          │
│        │ Thread 2: Context Preparation (Parallel)  │          │
│        │  └─> prepare_viz_context (fast)           │          │
│        └────────────────────────────────────────────┘          │
│                                                                  │
│        [WAIT FOR BOTH THREADS]                                  │
│                                                                  │
│        check_results                      (no LLM)              │
│                                                                  │
│        [PARALLEL EXECUTION BLOCK - ~800ms total]                │
│        ┌────────────────────────────────────────────┐          │
│        │ Thread A: Business Insights                │          │
│        │  └─> extract_insights   (LLM #3 - 800ms) │          │
│        │                                            │          │
│        │ Thread B: Viz Decision                     │          │
│        │  └─> decide_viz         (LLM #4 - 700ms) │          │
│        └────────────────────────────────────────────┘          │
│                                                                  │
│        [WAIT FOR BOTH]                                          │
│                                                                  │
│        visualization                      (render - 100ms)      │
│        build_response                     (LLM #5 - 600ms)      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

TOTAL: ~2.5-3s (5 LLM calls, 2 parallel blocks)
50% FASTER! ⚡
```

---

### Option 2: Unified Single-Pass Architecture (Aggressive)

```
┌─────────────────────────────────────────────────────────────────┐
│         UNIFIED SINGLE-PASS ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  START                                                           │
│    │                                                             │
│    └─> unified_intent_and_sql_generation                        │
│        │                                                         │
│        │  Single LLM Call (LLM #1 - 1.5s)                      │
│        │  Outputs:                                              │
│        │    - Intent classification                             │
│        │    - SQL query (structured)                            │
│        │    - Detected entities                                 │
│        │    - Suggested viz type                                │
│        │                                                         │
│        └─> parallel_execution_block                             │
│            ┌────────────────────────────────────────┐          │
│            │ Thread 1: SQL Execution                │          │
│            │  ├─> metadata_enrich    (DB - 100ms)   │          │
│            │  ├─> value_resolve      (fast)         │          │
│            │  ├─> sql_execute        (DB - 200ms)   │          │
│            │                                        │          │
│            │ Thread 2: Business Context Prep        │          │
│            │  └─> prepare_context    (fast)         │          │
│            └────────────────────────────────────────┘          │
│                                                                  │
│        [WAIT FOR BOTH]                                          │
│                                                                  │
│        unified_response_generation       (LLM #2 - 1s)          │
│        │  Inputs:                                               │
│        │    - Query results                                     │
│        │    - Intent info                                       │
│        │    - Viz suggestion                                    │
│        │  Outputs:                                              │
│        │    - Business insights                                 │
│        │    - Final viz decision                                │
│        │    - Natural language response                         │
│        │    - Follow-up suggestions                             │
│                                                                  │
│        visualization                      (render - 100ms)      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

TOTAL: ~2s (2 LLM calls, 1 parallel block)
60-70% FASTER! ⚡⚡
```

---

## 📊 Detailed Comparison

| Architecture | LLM Calls | Sequential | Parallel | Total Time | Improvement |
|--------------|-----------|------------|----------|------------|-------------|
| **Current** | 6 | 6 | 0 | ~5-8s | baseline |
| **Parallel (Option 1)** | 5 | 3 | 2 blocks | ~2.5-3s | **50%** |
| **Unified (Option 2)** | 2 | 1 | 1 block | ~2s | **60-70%** |

---

## 🛠️ Implementation Strategy

### Phase 1: Quick Wins (1 week) - Option 1

#### 1.1 Enable Semantic Cache Everywhere

**Target:** 30-50% token reduction

```python
# In build_report_graph
semantic_cache = SemanticCache(
    embeddings=llm.get_embeddings(),
    threshold=0.95,
    ttl=3600,
    max_size=2000  # Increase cache size
)

# Share cache between all components
conversation_manager = ConversationManager(llm, semantic_cache=semantic_cache)
business_tracker = BusinessContextTracker(llm, semantic_cache=semantic_cache)
report_interpreter = ReportInterpreter(llm, semantic_cache=semantic_cache)
response_generator = ResponseGenerator(llm, semantic_cache=semantic_cache)

# Also pass to text2sql graph
text2sql_graph = build_text2sql_graph(llm, semantic_cache=semantic_cache)
```

#### 1.2 Fast-Path for Simple Intents

**Target:** Skip LLM for 40% of queries

```python
def classify_intent_with_fast_path(state: ReportState):
    """Fast path for obvious intents."""
    user_message = get_last_user_message(state).lower()

    # Fast path: Explicit patterns (no LLM)
    if any(kw in user_message for kw in ["geri al", "iptal", "undo"]):
        return {"_intent_type": "rollback", "_confidence": 1.0}

    if any(kw in user_message for kw in ["grafik yap", "chart", "bar chart"]):
        return {"_intent_type": "visualize", "_confidence": 0.95}

    # Fast path: Simple queries (no context, no ambiguity)
    if not state.get("active_query_context") and is_simple_query(user_message):
        return {"_intent_type": "new_query", "_confidence": 0.9}

    # Complex: Use LLM
    return await conversation_manager.understand_intent(...)
```

#### 1.3 Parallel Business Insights + Viz Decision

**Target:** Save ~500ms

```python
async def parallel_insights_and_viz(state: ReportState):
    """Run insights extraction and viz decision in parallel."""
    import asyncio

    # Prepare both tasks
    insights_task = business_tracker.extract_insights(...)
    viz_task = report_interpreter.interpret_results(...)

    # Run in parallel
    insights, viz_decision = await asyncio.gather(
        insights_task,
        viz_task
    )

    return {
        "business_context": insights,
        "_viz_decision": viz_decision.dict()
    }
```

**Expected Result:** ~3-3.5s (from 5-8s) - **40% faster**

---

### Phase 2: Parallel SQL + Context (2 weeks) - Still Option 1

#### 2.1 Parallel SQL Generation + Context Prep

```python
async def parallel_sql_and_context_prep(state: ReportState):
    """Run SQL generation and context preparation in parallel."""
    import asyncio

    # Task 1: SQL generation (expensive)
    async def generate_sql():
        return await text2sql_graph.ainvoke(...)

    # Task 2: Prepare viz context (cheap, but can start early)
    async def prepare_context():
        # Pre-compute things we'll need for viz
        return {
            "user_preferences": extract_preferences(state),
            "recent_patterns": analyze_recent_queries(state)
        }

    # Run in parallel
    sql_output, context_prep = await asyncio.gather(
        generate_sql(),
        prepare_context()
    )

    return {
        "text2sql_output": sql_output,
        "_context_prep": context_prep
    }
```

**Expected Result:** ~2.5-3s - **50% faster**

---

### Phase 3: Unified Architecture (4 weeks) - Option 2

#### 3.1 Unified Intent + SQL Generation (Single LLM Call)

**File:** `src/graphs/unified/unified_intent_sql_node.py`

```python
UNIFIED_INTENT_SQL_PROMPT = """Sen bir akıllı SQL asistanısın.

Kullanıcı mesajı: {user_message}

Context: {context_info}

Schema: {schema_info}

Tek bir JSON response'da şunları ver:
{{
    "intent": {{
        "type": "new_query|modify_filter|rollback|visualize",
        "confidence": 0.95,
        "entities": {{"table": "...", "filters": [...]}}
    }},
    "sql": {{
        "steps": [
            {{"action": "filter", "field": "City", "value": "Istanbul"}},
            {{"action": "aggregate", "function": "COUNT", "field": "Sales"}},
            {{"action": "group_by", "fields": ["City"]}}
        ],
        "suggested_viz": "bar_chart"
    }}
}}"""

async def unified_intent_and_sql_node(state: UnifiedState):
    """Single LLM call for both intent + SQL."""
    result = await llm.ainvoke(UNIFIED_INTENT_SQL_PROMPT)
    parsed = json.loads(result.content)

    return {
        "_intent": parsed["intent"],
        "sql_steps": parsed["sql"]["steps"],
        "_suggested_viz": parsed["sql"]["suggested_viz"]
    }
```

#### 3.2 Unified Response Generation (Single LLM Call)

```python
UNIFIED_RESPONSE_PROMPT = """Sen bir iş analitiği asistanısın.

Kullanıcı sorusu: {user_query}
Veri sonuçları: {data_results}
Intent bilgisi: {intent_info}
Önerilen görselleştirme: {suggested_viz}

Tek bir JSON response'da şunları ver:
{{
    "insights": [
        "Istanbul en yüksek satış hacmine sahip",
        "Son 3 ayda %15 artış var"
    ],
    "viz_decision": {{
        "type": "bar_chart",
        "reason": "Şehirler arası karşılaştırma için ideal"
    }},
    "response": "📊 Satış Analizi...",
    "follow_ups": [
        "Hangi ürünler en çok satıyor?",
        "Artışın nedenleri neler?"
    ]
}}"""

async def unified_response_node(state: UnifiedState):
    """Single LLM call for insights + viz + response."""
    result = await llm.ainvoke(UNIFIED_RESPONSE_PROMPT)
    parsed = json.loads(result.content)

    return {
        "business_context": {
            "key_insights": parsed["insights"],
            "suggested_follow_ups": parsed["follow_ups"]
        },
        "_viz_decision": parsed["viz_decision"],
        "final_response": parsed["response"]
    }
```

**Expected Result:** ~2s - **60-70% faster**

---

## 🎯 Recommended Implementation Plan

### Week 1-2: Quick Wins (Phase 1)
- ✅ Enable semantic cache everywhere
- ✅ Add fast-path intent classification
- ✅ Parallelize business insights + viz decision
- **Target:** 3-3.5s (~40% improvement)

### Week 3-4: Parallel Optimization (Phase 2)
- ✅ Parallel SQL + context preparation
- ✅ Optimize text2sql graph (cache, fast-paths)
- **Target:** 2.5-3s (~50% improvement)

### Week 5-8: Unified Architecture (Phase 3)
- ✅ Design unified state
- ✅ Implement unified intent+SQL node
- ✅ Implement unified response node
- ✅ Full integration testing
- **Target:** 2s (~60-70% improvement)

---

## 📝 Unified State Design

### UnifiedState (combines Report + Text2SQL)

```python
class UnifiedState(TypedDict):
    """Unified state for combined Report + Text2SQL agent."""

    # -------------------------------------------------------------------------
    # Core (from both agents)
    # -------------------------------------------------------------------------
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    active_context: Optional[ActiveQueryContext]

    # -------------------------------------------------------------------------
    # Intent (unified)
    # -------------------------------------------------------------------------
    intent_type: Optional[str]
    intent_confidence: float
    extracted_entities: Dict[str, Any]
    intent_reasoning: Optional[str]  # LLM reasoning trace

    # -------------------------------------------------------------------------
    # SQL (from text2sql)
    # -------------------------------------------------------------------------
    sql_steps: List[Dict[str, Any]]  # Structured SQL steps
    sql_query: Optional[str]          # Final SQL
    sql_results: Optional[List[Dict]]
    schema_metadata: Optional[Dict]

    # -------------------------------------------------------------------------
    # Business Context (from report)
    # -------------------------------------------------------------------------
    business_context: Optional[BusinessContext]
    suggested_viz: Optional[str]      # From unified intent+SQL

    # -------------------------------------------------------------------------
    # Visualization
    # -------------------------------------------------------------------------
    viz_decision: Optional[Dict[str, Any]]
    viz_output: Optional[Dict[str, Any]]

    # -------------------------------------------------------------------------
    # Response
    # -------------------------------------------------------------------------
    final_response: Optional[str]
    error: Optional[str]
```

---

## 🔧 Migration Strategy

### Backward Compatibility

**Option:** Feature flag for unified vs legacy mode

```python
def build_unified_report_graph(
    llm: LLM,
    use_unified_architecture: bool = False,  # Feature flag
    enable_semantic_cache: bool = True,
    enable_parallel_execution: bool = True,
    **kwargs
):
    if use_unified_architecture:
        # Phase 3: Unified architecture
        return build_unified_graph(llm, **kwargs)
    elif enable_parallel_execution:
        # Phase 2: Parallel optimization
        return build_parallel_optimized_graph(llm, **kwargs)
    else:
        # Phase 1: Current with quick wins
        return build_report_graph(llm, **kwargs)
```

---

## 📊 Expected Performance Gains

### Latency

| Phase | Architecture | Latency | Improvement |
|-------|-------------|---------|-------------|
| **Baseline** | Current | 5-8s | - |
| **Phase 1** | Quick wins | 3-3.5s | **40%** |
| **Phase 2** | Parallel | 2.5-3s | **50%** |
| **Phase 3** | Unified | 2s | **60-70%** |

### Token Usage

| Phase | Tokens/Request | Improvement |
|-------|----------------|-------------|
| **Baseline** | 2500-4000 | - |
| **Phase 1** | 1500-2500 | **30-40%** (cache) |
| **Phase 2** | 1200-2000 | **40-50%** |
| **Phase 3** | 800-1200 | **60-70%** |

---

## 🎯 Success Metrics

### Performance
- ✅ Latency < 3s (Phase 1-2)
- ✅ Latency < 2s (Phase 3)
- ✅ Token usage < 1500/request (with cache)
- ✅ Cache hit rate > 40%

### Quality
- ✅ Intent accuracy ≥ 90%
- ✅ SQL correctness ≥ 95%
- ✅ Response quality ≥ 4/5
- ✅ No quality degradation from optimization

---

## 🚀 Start Here: Quick Implementation (Phase 1)

### 1. Enable Semantic Cache

```python
# In your main graph builder
from src.graphs.report.semantic_cache import SemanticCache

semantic_cache = SemanticCache(
    embeddings=llm.get_embeddings(),
    threshold=0.95,
    ttl=3600
)

# Pass to all components
graph = build_report_graph(
    text2sql_graph=text2sql_graph,
    visualization_graph=viz_graph,
    llm=llm,
    enable_semantic_cache=True,  # Already supports this!
    semantic_cache_instance=semantic_cache  # Pass shared instance
)
```

### 2. Parallelize Insights + Viz

```python
# In nodes.py, add new node
async def parallel_insights_viz_node(state: ReportState):
    import asyncio

    tasks = []

    # Task 1: Business insights
    if business_tracker:
        tasks.append(business_tracker.extract_insights(...))

    # Task 2: Viz decision
    if report_interpreter:
        tasks.append(report_interpreter.interpret_results(...))

    # Run in parallel
    results = await asyncio.gather(*tasks)

    return {
        "business_context": results[0] if len(results) > 0 else None,
        "_viz_decision": results[1].dict() if len(results) > 1 else None
    }
```

### 3. Wire in graph.py

```python
# Replace sequential execution with parallel
if enable_parallel_execution:
    graph.add_node("parallel_insights_viz", parallel_insights_viz_node)
    graph.add_edge("check_results", "parallel_insights_viz")
    graph.add_edge("parallel_insights_viz", "decide_visualization")
else:
    # Old sequential way
    graph.add_edge("check_results", "extract_business_insights")
    graph.add_edge("extract_business_insights", "decide_visualization")
```

**Deploy and measure!**

---

## 📚 Related Documents

- Current Report Agent: `docs/architecture/STATEFUL_REPORT_AGENT.md`
- LLM-Driven Report: `docs/architecture/REPORT_AGENT_LLM_DRIVEN.md`
- Generic Text2SQL: `src/graphs/generic_text2sql/README.md`

---

**Let's optimize! 🚀**
