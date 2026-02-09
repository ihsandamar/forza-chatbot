# Conversational Report Agent - Optimization Plan

## 🎯 Hedefler

1. **Token Verimliliği**: Conversational/session içinde gereksiz token harcaması minimize et
2. **Hız**: Cevap sürelerini azalt (Graph boundary overhead'i elimine et)
3. **Doğruluk**: Context-aware reasoning ile cevap kalitesini artır

## 📊 Mevcut Durum Analizi

### ✅ Tamamlanan Optimizasyonlar (Merged Mode)

```
BEFORE (Separate Graphs):
Report Agent → [Text2SQL Graph] → Report Agent
              ↓
      Graph boundary overhead (~300-400ms)
      State serialization/deserialization
      Context loss between graphs

AFTER (Merged Mode):
Report Agent + Text2SQL Nodes (Embedded)
      ↓
✅ No graph boundary overhead
✅ Direct state sharing
✅ Single execution context
```

**Performans Kazanımları:**
- Graph invocation overhead: ~300-400ms eliminated
- State copying overhead: Eliminated
- Total latency reduction: ~20-30%

### 🔄 Conversational Flow (Şu Anki)

```
START
  ↓
immediate_ack (instant feedback)
  ↓
classify_intent (intent + confidence)
  ↓ (conditional)
├── [ask_user] ← HITL interrupt
│      ↓
│   process_clarification
│      ↓
├── [rollback] → build_response
│
└── extract_query
      ↓
    create_table (MERGED)
      ↓
    sql_architect (MERGED)
      ↓
    retrieve_business_rules (MERGED)
      ↓
    metadata_enrichment (MERGED)
      ↓
    value_resolver (MERGED)
      ↓
    sql_query_builder (MERGED)
      ↓
    sql_executor (MERGED)
      ↓
    cleanup_table (MERGED)
      ↓
    check_results
      ↓
    decide_visualization
      ↓
    [visualization] (if needed)
      ↓
    build_response
      ↓
    END
```

## 🚀 Conversational Optimization Opportunities

### 1. **Intent Classification Enhancement** (CRITICAL)

**Problem:**
- `classify_intent` şu anda her mesajı bağımsız değerlendiriyor
- Conversation history kullanılmıyor
- Context loss → Yanlış intent → Gereksiz full query execution

**Solution:**
```python
# CURRENT: Simple intent classification
classify_intent → new_query (always full execution)

# OPTIMIZED: Context-aware intent classification
classify_intent + conversation_context → {
    "new_query",           # Full execution
    "refine_query",        # Delta update (modify filters)
    "expand_query",        # Incremental (add columns/aggregations)
    "clarification",       # No execution, ask question
    "rollback",           # Revert to checkpoint
    "visualize_existing"  # Skip Text2SQL, reuse data
}
```

**Implementation:**
```python
# src/graphs/report/nodes.py - classify_intent enhancement

async def classify_intent_node(state: ReportState):
    # Get conversation context
    query_history = state.get("query_history", [])
    active_context = state.get("active_query_context")

    # Conversation-aware prompt
    context_summary = _build_context_summary(query_history, active_context)

    intent = llm.invoke({
        "user_message": current_message,
        "conversation_context": context_summary,  # NEW: Context injection
        "previous_queries": [q.user_message for q in query_history[-3:]],
        "current_filters": active_context.applied_filters if active_context else []
    })

    # Determine execution path
    if intent == "refine_query":
        return {
            "_intent_type": "refine_query",
            "_execution_mode": "delta",  # NEW: Delta execution mode
            "_reuse_table": True,        # NEW: Reuse master table
            "_delta_changes": intent.delta_changes
        }
```

**Token Savings:**
- ❌ BEFORE: Full context window (entire schema + business rules) = ~2000 tokens
- ✅ AFTER: Delta context (only changes) = ~200 tokens
- **Savings: ~90% token reduction for refinements**

---

### 2. **Delta SQL Execution** (HIGH PRIORITY)

**Problem:**
- Her mesajda full SQL query rebuild
- Master table her seferinde yeniden oluşturuluyor
- Gereksiz DB roundtrips

**Solution: Smart Routing with Delta Execution**

```python
# New conditional edge after classify_intent

def route_after_intent_smart(state: ReportState) -> str:
    intent = state.get("_intent_type")
    execution_mode = state.get("_execution_mode")

    if intent == "new_query":
        return "extract_query"  # Full flow

    elif intent == "refine_query" and execution_mode == "delta":
        return "delta_sql_modifier"  # NEW NODE: Skip to SQL modification

    elif intent == "visualize_existing":
        return "decide_visualization"  # Skip Text2SQL entirely

    elif intent == "rollback":
        return "rollback"

    else:
        return "extract_query"  # Fallback to full flow
```

**New Node: `delta_sql_modifier`**

```python
async def delta_sql_modifier_node(state: ReportState) -> Dict[str, Any]:
    """
    Modify existing SQL instead of rebuilding from scratch.

    Handles:
    - Filter additions/removals
    - Column additions
    - Aggregation changes
    - Ordering changes
    """
    active_context = state.get("active_query_context")
    delta_changes = state.get("_delta_changes")

    # Get base SQL from active context
    base_sql = active_context.get("current_sql")

    # Apply delta modifications
    modified_sql = apply_delta_changes(base_sql, delta_changes)

    # Skip create_table, sql_architect, etc.
    return {
        "sql_queries": [modified_sql],
        "_skip_table_creation": True  # Reuse existing master table
    }
```

**Graph Changes:**

```python
# src/graphs/report/graph.py

# Add delta_sql_modifier node
graph.add_node("delta_sql_modifier", delta_sql_modifier_node)

# Add smart routing edge
graph.add_conditional_edges(
    "classify_intent",
    route_after_intent_smart,
    {
        "extract_query": "extract_query",           # Full flow
        "delta_sql_modifier": "delta_sql_modifier", # Delta flow (NEW)
        "decide_visualization": "decide_visualization", # Skip Text2SQL
        "rollback": "rollback",
        "ask_user": "ask_user"
    }
)

# Delta flow bypass
graph.add_edge("delta_sql_modifier", "sql_executor")  # Skip 8 nodes!
```

**Performance Impact:**

| Execution Type | Nodes Executed | Latency | Token Usage |
|----------------|----------------|---------|-------------|
| **Full Query** | 15 nodes | ~8-12s | ~3000 tokens |
| **Delta Update** | 7 nodes | ~3-5s | ~500 tokens |
| **Visualize Existing** | 3 nodes | ~1-2s | ~100 tokens |

**Savings: ~60-80% latency + ~80-90% tokens for refinements**

---

### 3. **Semantic Cache for Conversations** (MEDIUM PRIORITY)

**Problem:**
- Cache hits düşük (each query unique)
- Conversation içinde benzer sorular tekrar ediliyor
- Semantic similarity threshold çok yüksek (0.95)

**Solution: Conversation-Aware Caching**

```python
# src/graphs/report/semantic_cache.py

class ConversationalSemanticCache:
    def __init__(self, embeddings, threshold=0.85):  # Lower threshold
        self.threshold = threshold
        self.session_cache = {}  # NEW: Per-session cache

    async def get(self, query: str, session_id: str, context: dict):
        """
        Multi-level cache lookup:
        1. Exact match in session cache (fastest)
        2. Semantic similarity in session cache
        3. Global semantic similarity
        """

        # Level 1: Session exact match
        session_key = f"{session_id}:{hash(query)}"
        if session_key in self.session_cache:
            return self.session_cache[session_key]

        # Level 2: Session semantic match
        session_entries = self._get_session_entries(session_id)
        match = self._find_semantic_match(query, session_entries, threshold=0.85)
        if match:
            return match

        # Level 3: Global semantic match (stricter)
        match = self._find_semantic_match(query, self.global_cache, threshold=0.92)
        return match

    def set(self, query: str, session_id: str, result: Any, ttl: int = 3600):
        """Store in both session and global cache."""
        session_key = f"{session_id}:{hash(query)}"
        self.session_cache[session_key] = {
            "result": result,
            "timestamp": time.time(),
            "ttl": ttl
        }
        self.global_cache[query] = result
```

**Cache Strategy for Conversations:**

```python
# When to cache:
1. Successful SQL execution → Cache (query → results)
2. Intent classification → Cache (message + context → intent)
3. Business insights → Cache (data → insights)
4. Visualization decision → Cache (data profile → viz type)

# When to invalidate:
1. Delta update → Invalidate dependent caches
2. Session timeout → Clear session cache
3. Schema change → Clear all caches
```

**Token Savings:**
- Intent classification cache hit: ~500 tokens saved
- SQL execution cache hit: ~1000 tokens + DB roundtrip saved
- **Estimated cache hit rate in conversations: 30-40%**

---

### 4. **Context Injection into Text2SQL Nodes** (CRITICAL)

**Problem:**
- Text2SQL nodes conversation context'i görmüyor
- `sql_architect` her seferinde sıfırdan başlıyor
- Önceki query bilgisi kullanılmıyor

**Solution: Conversation Context Propagation**

```python
# src/graphs/report/nodes.py - extract_query enhancement

async def extract_query_node(state: ReportState) -> Dict[str, Any]:
    user_query = get_last_user_message(state)
    active_context = state.get("active_query_context")

    # NEW: Inject conversation context for Text2SQL nodes
    conversation_context = None
    if active_context:
        conversation_context = {
            "previous_table": active_context.get("current_table"),
            "previous_filters": active_context.get("applied_filters", []),
            "previous_columns": active_context.get("grouping_columns", []),
            "result_row_count": active_context.get("result_row_count", 0),
            "last_execution_time": active_context.get("last_execution_time")
        }

    return {
        "user_query": user_query,
        "conversation_context": conversation_context  # NEW: Pass to Text2SQL
    }
```

**Text2SQL Node Enhancement:**

```python
# src/graphs/generic_text2sql/nodekit.py - sql_architect enhancement

async def sql_architect_node(self, state: GenericText2SQLState, *, config: RunnableConfig):
    user_query = state["user_query"]
    conversation_context = state.get("conversation_context")  # NEW

    # Build context-aware prompt
    if conversation_context:
        prompt_context = f"""
Previous Query Context:
- Table: {conversation_context['previous_table']}
- Filters: {conversation_context['previous_filters']}
- Columns: {conversation_context['previous_columns']}
- Result Count: {conversation_context['result_row_count']}

User is likely:
- Refining previous query
- Asking follow-up question
- Requesting different view of same data

Consider reusing table and modifying filters/columns instead of starting fresh.
"""
    else:
        prompt_context = "This is a new query with no previous context."

    response = await llm.ainvoke({
        "user_query": user_query,
        "conversation_context": prompt_context,  # NEW
        "schema_metadata": schema_text,
        "business_rules": business_rules_text
    })

    # Parse intent - now context-aware
    intent = parse_intent(response)

    # NEW: Flag for delta execution
    if conversation_context and intent.get("is_refinement"):
        return {
            "parsed_intent": intent,
            "_delta_execution": True,
            "_base_query": conversation_context["previous_table"]
        }
```

**Token Savings:**
- Context-aware prompts reduce redundant schema descriptions
- Smart reuse of previous query components
- **Estimated: ~30% token reduction in conversational queries**

---

### 5. **Master Table Persistence** (HIGH PRIORITY)

**Problem:**
- `create_table` ve `cleanup_table` her sorguda çalışıyor
- Conversation içinde aynı tablo tekrar tekrar oluşturuluyor
- DB overhead + latency

**Solution: Session-Based Table Management**

```python
# src/graphs/generic_text2sql/nodekit.py - create_table enhancement

async def create_master_table_node(self, state: GenericText2SQLState, *, config: RunnableConfig):
    table_name = _extract_config_value(config, state, "table_name", self.config, "MasterReportDocumentTable")

    # NEW: Check if table already exists for this session
    session_id = config.get("configurable", {}).get("thread_id")
    reuse_table = state.get("_reuse_table", False)

    if reuse_table and session_id:
        table_key = f"{session_id}_{table_name}"

        # Check if table exists
        if await self._table_exists(table_key):
            logger.info(f"[CREATE_TABLE] ✓ Reusing existing table: {table_key}")
            return {
                "master_table_name": table_key,
                "_table_reused": True
            }

    # Create new table (existing logic)
    # ...
```

**Cleanup Strategy:**

```python
# Option 1: Lazy cleanup (on session end)
# - Keep tables for entire session
# - Cleanup on session timeout or explicit end

# Option 2: Reference counting
# - Track table usage count
# - Cleanup only when no more queries referencing it

# Option 3: Time-based (RECOMMENDED)
# - Keep tables for 15 minutes
# - Refresh TTL on each query
# - Background cleanup task
```

**Performance Impact:**
- Table creation: ~500ms → 0ms (reuse)
- Table cleanup: ~200ms → 0ms (lazy)
- **Total: ~700ms saved per refinement query**

---

### 6. **Smart Edge Decision Points** (CRITICAL)

**New Conditional Edges to Add:**

```python
# 1. POST-INTENT CLASSIFICATION
graph.add_conditional_edges(
    "classify_intent",
    route_after_intent_smart,
    {
        "extract_query": "extract_query",           # Full flow (new query)
        "delta_sql_modifier": "delta_sql_modifier", # Delta flow (refinement)
        "decide_visualization": "decide_visualization", # Reuse data (viz change)
        "rollback": "rollback",                     # Undo
        "ask_user": "ask_user"                      # HITL
    }
)

# 2. POST-EXTRACT-QUERY (Skip table creation if reusing)
graph.add_conditional_edges(
    "extract_query",
    lambda s: "sql_architect" if s.get("_reuse_table") else "create_table",
    {
        "create_table": "create_table",  # New table
        "sql_architect": "sql_architect" # Reuse existing table
    }
)

# 3. POST-SQL-ARCHITECT (Skip value resolution if no fuzzy values)
graph.add_conditional_edges(
    "metadata_enrichment",
    lambda s: "sql_query_builder" if _no_fuzzy_values(s) else "value_resolver",
    {
        "value_resolver": "value_resolver",      # Need resolution
        "sql_query_builder": "sql_query_builder" # Skip resolution
    }
)

# 4. POST-CHECK-RESULTS (Cache decision: recompute or reuse)
graph.add_conditional_edges(
    "check_results",
    lambda s: "build_response" if _can_skip_viz(s) else route_after_results(s),
    {
        "extract_business_insights": "extract_business_insights",
        "decide_visualization": "decide_visualization",
        "build_response": "build_response",  # Skip viz entirely
        "ask_user": "ask_user"
    }
)
```

**Decision Logic Examples:**

```python
def _no_fuzzy_values(state: ReportState) -> bool:
    """Skip value_resolver if all values are exact matches."""
    parsed_intent = state.get("parsed_intent")
    if not parsed_intent:
        return False

    for step in parsed_intent.get("steps", []):
        for filter_def in step.get("filters", []):
            if filter_def.get("value_hint", "").endswith("?"):
                return False  # Fuzzy value detected

    return True  # All exact, skip value_resolver

def _can_skip_viz(state: ReportState) -> bool:
    """Skip visualization if user just wants data."""
    intent = state.get("_intent_type")
    user_query = state.get("user_query", "").lower()

    # Keywords indicating no viz needed
    no_viz_keywords = ["liste", "göster", "say", "topla", "count", "sum"]

    return any(keyword in user_query for keyword in no_viz_keywords)
```

---

### 7. **Conversation State Schema Enhancement**

**Add New Fields to ReportState:**

```python
# src/graphs/report/state.py

class ReportState(TypedDict):
    # ... existing fields ...

    # NEW: Conversation tracking
    session_id: Optional[str]                       # Thread/session ID
    conversation_turn: Optional[int]                # Turn counter
    last_intent: Optional[str]                      # Previous intent

    # NEW: Execution optimization
    _execution_mode: Optional[str]                  # "full" | "delta" | "reuse"
    _reuse_table: Optional[bool]                    # Reuse master table flag
    _skip_table_creation: Optional[bool]            # Skip create_table node
    _delta_changes: Optional[Dict[str, Any]]        # Delta modifications

    # NEW: Cache tracking
    _cache_hits: Optional[List[str]]                # Which caches hit
    _token_usage: Optional[Dict[str, int]]          # Token tracking per node

    # NEW: Performance metrics
    _node_timings: Optional[Dict[str, float]]       # Latency per node
    _total_latency: Optional[float]                 # End-to-end latency
```

---

## 📋 Implementation Checklist

### Phase 1: Foundation (Week 1)
- [ ] Add conversation context fields to ReportState
- [ ] Enhance `classify_intent` with conversation awareness
- [ ] Implement smart routing after intent classification
- [ ] Add session_id tracking via thread_id

### Phase 2: Delta Execution (Week 2)
- [ ] Create `delta_sql_modifier` node
- [ ] Add conditional edge for delta flow
- [ ] Implement SQL delta logic (filter/column modifications)
- [ ] Add table reuse logic in `create_table` node
- [ ] Skip cleanup for reused tables

### Phase 3: Context Injection (Week 3)
- [ ] Pass conversation context from Report to Text2SQL nodes
- [ ] Enhance `sql_architect` prompt with context
- [ ] Add context-aware intent detection in Text2SQL
- [ ] Implement smart node skipping based on context

### Phase 4: Cache Optimization (Week 4)
- [ ] Implement ConversationalSemanticCache
- [ ] Add session-based cache layer
- [ ] Lower similarity threshold for conversations (0.85)
- [ ] Add cache invalidation logic for delta updates

### Phase 5: Performance & Monitoring (Week 5)
- [ ] Add latency tracking per node
- [ ] Add token usage tracking
- [ ] Implement performance metrics logging
- [ ] Create dashboard for optimization metrics

---

## 🎯 Expected Performance Improvements

### Conversational Query Performance

| Metric | Current | Target | Improvement |
|--------|---------|--------|-------------|
| **First Query Latency** | 8-12s | 6-8s | ~25% |
| **Follow-up Query Latency** | 8-12s | 2-4s | ~70% |
| **Tokens per First Query** | ~3000 | ~2500 | ~15% |
| **Tokens per Follow-up** | ~3000 | ~500 | ~85% |
| **Cache Hit Rate** | 10-15% | 35-45% | ~3x |
| **DB Roundtrips per Refinement** | 3-4 | 1 | ~70% |

### Cost Savings (per 1000 queries in conversation)

**Assumptions:**
- 40% of queries are follow-ups/refinements
- GPT-4o-mini: $0.15/1M input tokens, $0.60/1M output tokens
- Average conversation: 5 turns

**Current Cost:**
- Input: 5 queries × 3000 tokens × $0.15/1M = $0.00225
- Output: 5 queries × 500 tokens × $0.60/1M = $0.0015
- **Total per conversation: $0.00375**
- **1000 conversations: $3.75**

**Optimized Cost:**
- First query: 2500 tokens input + 500 output = $0.00068
- 4 follow-ups: 4 × 500 tokens input + 500 output = $0.00150
- **Total per conversation: $0.00218**
- **1000 conversations: $2.18**

**Savings: ~40% ($1.57 per 1000 conversations)**

---

## 🔍 Testing Strategy

### Unit Tests
```python
# tests/test_conversational_flow.py

async def test_delta_execution_flow():
    """Test delta execution skips unnecessary nodes."""
    state = {
        "messages": [...],
        "_intent_type": "refine_query",
        "_execution_mode": "delta",
        "active_query_context": {...}
    }

    result = await graph.ainvoke(state)

    # Assert delta flow
    assert result["_skip_table_creation"] == True
    assert result["_node_timings"]["create_table"] == 0  # Skipped
    assert result["_total_latency"] < 5000  # < 5s

async def test_context_injection():
    """Test conversation context passed to Text2SQL."""
    state = {
        "messages": [...],
        "active_query_context": {...}
    }

    result = await graph.ainvoke(state)

    assert result["conversation_context"] is not None
    assert "previous_table" in result["conversation_context"]
```

### Integration Tests
```python
async def test_full_conversation():
    """Test multi-turn conversation optimization."""

    # Turn 1: Initial query
    state1 = await graph.ainvoke({
        "messages": [HumanMessage("2024 satışlarını göster")]
    }, config={"configurable": {"thread_id": "test-session-1"}})

    assert state1["_execution_mode"] == "full"
    latency1 = state1["_total_latency"]

    # Turn 2: Refinement
    state2 = await graph.ainvoke({
        "messages": [HumanMessage("Sadece Istanbul için")]
    }, config={"configurable": {"thread_id": "test-session-1"}})

    assert state2["_execution_mode"] == "delta"
    assert state2["_reuse_table"] == True
    latency2 = state2["_total_latency"]

    # Assert optimization
    assert latency2 < latency1 * 0.5  # At least 50% faster
```

---

## 📚 Documentation Updates

### User Guide
- [ ] Document conversation best practices
- [ ] Add examples of delta queries
- [ ] Explain session management
- [ ] Performance tips for conversations

### Developer Guide
- [ ] Architecture diagrams with new flows
- [ ] Delta execution implementation details
- [ ] Cache configuration guide
- [ ] Performance profiling guide

---

## 🚧 Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **False delta detection** | Wrong execution path → incorrect results | Strict intent classification + confidence thresholds |
| **Stale cached data** | Outdated results | Smart cache invalidation + TTL management |
| **Table conflicts** | Session isolation issues | Use thread_id in table names |
| **Context overflow** | Large conversation history → high tokens | Sliding window (last 5 turns) + summarization |
| **Increased complexity** | Harder to debug | Comprehensive logging + visualization tools |

---

## 📊 Success Metrics

### Key Performance Indicators (KPIs)

1. **Latency Metrics**
   - P50/P90/P99 latency for first vs. follow-up queries
   - Target: Follow-up queries < 4s (P90)

2. **Cost Metrics**
   - Token usage per conversation
   - Cache hit rate
   - Target: 40% cost reduction in conversations

3. **Accuracy Metrics**
   - Delta execution correctness
   - Context-aware intent classification accuracy
   - Target: 95%+ correctness

4. **User Experience**
   - Conversation completion rate
   - User satisfaction (feedback)
   - Target: 20% improvement in UX scores

---

## 🎓 Best Practices for Conversational Queries

### For Users

**✅ DO:**
- "2024 satışlarını göster" → "Sadece Istanbul için"
- "En çok satış yapan ürünler" → "Top 10'a indir"
- "Aylık bazda göster" → "Grafik olarak göster"

**❌ DON'T:**
- Unrelated queries in same session (breaks context)
- Extremely long gaps between messages (cache expires)
- Mixing multiple topics (confuses intent)

### For Developers

**Delta Execution Triggers:**
- Filter refinements
- Column additions/removals
- Aggregation changes
- Ordering changes

**Full Execution Triggers:**
- New table/dataset
- Complex analytical changes
- Business rule changes
- Time range expansions (> 2x)

---

## 🔗 Related Files & Components

### Key Files to Modify
```
src/graphs/report/
  ├── graph.py                    # Add delta flow edges
  ├── nodes.py                    # Enhance classify_intent, add delta_sql_modifier
  ├── state.py                    # Add conversation fields
  └── semantic_cache.py           # Add conversational cache

src/graphs/generic_text2sql/
  ├── nodekit.py                  # Context injection
  └── state.py                    # Add conversation_context field

tests/
  ├── test_conversational_flow.py # New tests
  └── test_delta_execution.py     # New tests
```

### Dependencies
```yaml
# No new dependencies required
# All optimizations use existing infrastructure:
# - LangGraph (conditional edges, state management)
# - Semantic cache (already implemented)
# - Thread-based persistence (already available)
```

---

## 🎉 Summary

This optimization plan focuses on three key areas:

1. **Smart Routing**: Intent-based execution paths (full vs. delta vs. reuse)
2. **Context Propagation**: Pass conversation context through all nodes
3. **Resource Reuse**: Cache hits, table persistence, delta SQL

**Expected Impact:**
- ⚡ **70% faster** follow-up queries
- 💰 **40% cost reduction** in conversations
- 🎯 **Better accuracy** through context awareness
- 🚀 **Improved UX** with faster responses

**Implementation Priority:**
1. Smart routing + delta execution (highest impact)
2. Context injection (accuracy + cost)
3. Cache optimization (cost + speed)
4. Performance monitoring (observability)

---

**Next Steps:**
1. Review this plan with the team
2. Prioritize phases based on business needs
3. Create detailed technical design docs for Phase 1
4. Start implementation with unit tests
5. Monitor metrics and iterate
