# Report Agent LLM-Driven Architecture - Usage Guide

## 📚 Table of Contents

- [Overview](#overview)
- [Feature Flags](#feature-flags)
- [Configuration Examples](#configuration-examples)
- [Components](#components)
- [Gradual Rollout Strategy](#gradual-rollout-strategy)
- [Performance Tuning](#performance-tuning)
- [Troubleshooting](#troubleshooting)

---

## Overview

The Report Agent now supports an **LLM-driven architecture** with business-aware conversation management, intelligent insights extraction, and natural language generation.

**Key Benefits:**
- 🧠 **Business Context Awareness**: Understands user goals and extracts insights
- 💬 **Natural Conversations**: LLM-powered intent understanding and clarifications
- 📊 **Smart Visualization**: Intelligent chart type selection with reasoning
- 🎯 **Focused Responses**: Natural language responses highlighting key insights
- ⚡ **Token Optimization**: Semantic caching and smart context windowing

**Backward Compatible:** All features are opt-in via feature flags. Default behavior unchanged.

---

## Feature Flags

Control LLM-driven features with these flags:

```python
from src.graphs.report import build_report_graph

graph = build_report_graph(
    text2sql_graph=text2sql_graph,
    visualization_graph=viz_graph,
    llm=llm,

    # Feature flags (all default to True/False)
    enable_hitl=True,                      # Human-in-the-loop (existing)
    enable_llm_conversation=True,          # LLM-powered conversation management
    enable_business_insights=True,         # Business insights extraction
    enable_llm_interpretation=True,        # LLM visualization interpretation
    enable_natural_response=True,          # Natural language response generation
    enable_semantic_cache=False,           # Semantic caching (opt-in, adds cost)

    checkpointer=checkpointer
)
```

### Flag Details

| Flag | Purpose | Cost Impact | Default |
|------|---------|-------------|---------|
| `enable_llm_conversation` | Uses ConversationManager for intent understanding | +~250 tokens/req | `True` |
| `enable_business_insights` | Extracts business context and insights from data | +~300 tokens/req | `True` |
| `enable_llm_interpretation` | LLM decides visualization format with reasoning | +~320 tokens/req | `True` |
| `enable_natural_response` | Generates natural language responses | +~350 tokens/req | `True` |
| `enable_semantic_cache` | Caches LLM calls by semantic similarity | Reduces 30-50% tokens | `False` (opt-in) |

**Total Token Usage (all enabled, no cache):** ~2000-2500 tokens/request
**With Semantic Cache (30-50% hit rate):** ~1200-1500 tokens/request

---

## Configuration Examples

### 1. **Full LLM-Driven Mode** (Recommended)

```python
graph = build_report_graph(
    text2sql_graph=text2sql_graph,
    visualization_graph=viz_graph,
    llm=llm,
    enable_llm_conversation=True,
    enable_business_insights=True,
    enable_llm_interpretation=True,
    enable_natural_response=True,
    enable_semantic_cache=True,  # Requires embeddings model
    enable_hitl=True
)
```

**Use Case:** Production with optimal user experience and token optimization.

---

### 2. **Business Insights Only**

```python
graph = build_report_graph(
    text2sql_graph=text2sql_graph,
    visualization_graph=viz_graph,
    llm=llm,
    enable_llm_conversation=False,        # Rule-based intent
    enable_business_insights=True,         # Extract insights
    enable_llm_interpretation=False,       # Rule-based viz
    enable_natural_response=True,          # Natural responses with insights
    enable_semantic_cache=False
)
```

**Use Case:** Add insights to existing flow without changing intent logic.

---

### 3. **Backward Compatible (All LLM Features Disabled)**

```python
graph = build_report_graph(
    text2sql_graph=text2sql_graph,
    visualization_graph=viz_graph,
    llm=llm,
    enable_llm_conversation=False,
    enable_business_insights=False,
    enable_llm_interpretation=False,
    enable_natural_response=False,
    enable_semantic_cache=False,
    enable_hitl=True
)
```

**Use Case:** Legacy behavior, no LLM enhancements.

---

### 4. **Cost-Optimized Mode**

```python
graph = build_report_graph(
    text2sql_graph=text2sql_graph,
    visualization_graph=viz_graph,
    llm=llm,
    enable_llm_conversation=True,         # Smart intent (important)
    enable_business_insights=False,        # Skip insights (save tokens)
    enable_llm_interpretation=False,       # Rule-based viz
    enable_natural_response=False,         # Template responses
    enable_semantic_cache=True             # Cache for repeated queries
)
```

**Use Case:** Minimize token usage while keeping core conversation intelligence.

---

## Components

### 1. **ConversationManager**

**Purpose:** LLM-powered intent understanding with business context reasoning.

**Features:**
- Understands context-referencing queries ("bu ürünlerin", "burdaki")
- Business-aware clarifications
- Smart conversation flow management
- Semantic caching support

**When Enabled:**
- Replaces `IntentClassifier` with `ConversationManager`
- Adds `_intent_reasoning` to state (for debugging)
- Better handling of modification intents

**Example State Output:**
```python
{
    "_intent_type": "modify_filter",
    "_confidence": 0.92,
    "_extracted_entities": {
        "filter_action": "expand",
        "uses_context_reference": True
    },
    "_intent_reasoning": "User is referencing previous results with 'burdaki'..."
}
```

---

### 2. **BusinessContextTracker**

**Purpose:** Tracks business goals and extracts insights from data.

**Features:**
- Identifies user's business question
- Extracts key insights from results
- Generates natural language data summaries
- Suggests smart follow-up questions
- Maintains goal continuity across conversation

**When Enabled:**
- Adds `extract_business_insights` node to graph
- Populates `business_context` in state
- Insights available for response generation

**Example State Output:**
```python
{
    "business_context": {
        "business_question": "Satışları şehir bazında analiz etmek",
        "key_insights": [
            "İstanbul en yüksek satış hacmine sahip (45%)",
            "Ankara'da son aylarda %15 artış var",
            "İzmir satışları stabil seyrediyor"
        ],
        "data_summary": "3 şehir için 150 satış kaydı",
        "suggested_follow_ups": [
            "Hangi ürün kategorileri İstanbul'da daha popüler?",
            "Ankara'daki artışın nedenleri neler?"
        ],
        "user_goal": "Şehirler arası satış performansını karşılaştırmak"
    }
}
```

---

### 3. **ReportInterpreter**

**Purpose:** LLM-assisted visualization decision with reasoning.

**Features:**
- Analyzes data + user intent
- Decides best presentation format
- Suggests alternatives
- Generates key insights
- Rule-based fallback for quick decisions

**When Enabled:**
- Replaces `decide_visualization_node` logic
- Adds `_viz_reasoning` to state
- More intelligent chart type selection

**Example State Output:**
```python
{
    "_viz_decision": {
        "needs_graph": True,
        "output_type": "bar_chart",
        "chart_type": "bar_chart",
        "reason": "Şehirler arası karşılaştırma için bar chart ideal",
        "alternatives": ["table", "pie_chart"],
        "key_insight": "İstanbul açık ara lider"
    },
    "_viz_reasoning": "LLM analyzed 150 rows with 3 cities..."
}
```

---

### 4. **ResponseGenerator**

**Purpose:** Natural language response generation with insights.

**Features:**
- Conversational, helpful tone
- Highlights business insights
- Suggests follow-up actions
- Template fallback for errors/simple cases
- Markdown formatting

**When Enabled:**
- Replaces `build_response_node` with `build_natural_response_node`
- Adds `_response_reasoning` to state
- Professional, insight-rich responses

**Example Output:**
```markdown
📊 **Satış Analizi - Şehir Bazlı**

Sorgunuz için **150 satış kaydı** bulundu.

**Önemli Bulgular:**
• **İstanbul** toplam satışların **%45'ini** oluşturuyor (67K TL)
• **Ankara'da** son 3 ayda **%15 artış** gözlemlendi
• İzmir satışları stabil seyrediyor (~20K TL)

**İlgili Sorular:**
• Hangi ürün kategorileri İstanbul'da daha popüler?
• Ankara'daki artışın nedenleri neler olabilir?

📈 **Grafik:** [Bar Chart]
```

---

### 5. **SemanticCache**

**Purpose:** Embedding-based caching for LLM calls.

**Features:**
- Semantic similarity matching (cosine similarity)
- Configurable threshold (default: 0.95)
- TTL support (default: 1 hour)
- LRU eviction
- Cache statistics

**When Enabled:**
- Requires embeddings model (`llm.get_embeddings()`)
- Reduces redundant LLM calls by 30-50%
- Shared across all LLM components

**Example Usage:**
```python
# Cache hit example
Query 1: "Istanbul satış raporu"
Query 2: "İstanbul satış raporunu göster"
→ Similarity: 0.97 → Cache HIT (no LLM call)

# Cache stats
cache.get_stats()
→ {
    "hits": 15,
    "misses": 35,
    "total_requests": 50,
    "hit_rate": 0.30,
    "cache_size": 42
}
```

---

### 6. **ContextWindow**

**Purpose:** Smart context truncation with relevance scoring.

**Features:**
- Keyword overlap detection
- Recency weighting
- Entity-based relevance
- Token budget management
- Preserves conversation coherence

**When Enabled:**
- Used by `ConversationManager` automatically
- Replaces blind "last N messages" truncation
- Selects most relevant context within token budget

**Example:**
```python
# Full history: 20 messages
# Current query: "İstanbul satışları"

# ContextWindow selects:
# - Message 2: "Satış raporu göster" (keyword: satış)
# - Message 5: "İstanbul için filtrele" (entity: istanbul, keyword: satış)
# - Message 18-20: Last 3 messages (recency)
# → Total: 5 messages (~500 tokens)
```

---

## Gradual Rollout Strategy

### Week 1: Baseline (All OFF)

```python
enable_llm_conversation=False
enable_business_insights=False
enable_llm_interpretation=False
enable_natural_response=False
```

**Metrics:** Establish baseline latency, token usage, quality scores.

---

### Week 2: ConversationManager Only

```python
enable_llm_conversation=True
enable_business_insights=False
enable_llm_interpretation=False
enable_natural_response=False
```

**Monitor:** Intent classification accuracy, clarification quality.

---

### Week 3: Add BusinessContextTracker

```python
enable_llm_conversation=True
enable_business_insights=True
enable_llm_interpretation=False
enable_natural_response=False
```

**Monitor:** Insight relevance, follow-up quality.

---

### Week 4: Full LLM Mode

```python
enable_llm_conversation=True
enable_business_insights=True
enable_llm_interpretation=True
enable_natural_response=True
enable_semantic_cache=True
```

**Monitor:** End-to-end quality, latency, token usage, cache hit rate.

---

## Performance Tuning

### Token Optimization

**1. Enable Semantic Cache** (30-50% reduction)
```python
enable_semantic_cache=True
```

**2. Use Haiku for Simple Tasks**
```python
# In graph builder, consider using haiku for simple components
# (Not implemented yet, but can be added)
```

**3. Tune Context Window**
```python
# In ConversationManager
context_window = ContextWindow(
    max_tokens=1500,  # Reduce from 2000
    min_messages=2     # Reduce from 3
)
```

**4. Optimize Prompts**
- All prompts in `prompts.py` are already optimized
- Modify if you need even shorter prompts

---

### Latency Optimization

**1. Parallel LLM Calls** (Not implemented yet)
- Consider calling multiple LLM components in parallel
- Requires async refactoring

**2. Quick Rules First**
- `ReportInterpreter` already uses quick rules for fast path
- Add more quick rules for common patterns

**3. Cache Aggressively**
- Lower similarity threshold: `threshold=0.93` (from 0.95)
- Increase TTL: `ttl=7200` (2 hours)

---

### Cost Optimization

**Priority Levels:**

**Level 1: Essential** (~500 tokens/req)
```python
enable_llm_conversation=True      # Intent understanding
enable_business_insights=False
enable_llm_interpretation=False
enable_natural_response=False
enable_semantic_cache=True         # Cache to reduce further
```

**Level 2: Moderate** (~1000 tokens/req)
```python
enable_llm_conversation=True
enable_business_insights=True      # Add insights
enable_llm_interpretation=False
enable_natural_response=False
enable_semantic_cache=True
```

**Level 3: Full** (~2000 tokens/req, ~1200 with cache)
```python
# All features enabled
```

---

## Troubleshooting

### Issue: High Token Usage

**Solution:**
1. Enable semantic cache: `enable_semantic_cache=True`
2. Disable non-critical features:
   - `enable_business_insights=False` saves ~300 tokens
   - `enable_llm_interpretation=False` saves ~320 tokens
3. Check cache hit rate: `semantic_cache.get_stats()`
4. Reduce context window size

---

### Issue: Slow Response Times

**Solution:**
1. Enable semantic cache for repeated queries
2. Use quick rules in `ReportInterpreter`
3. Check LLM model latency (consider switching to Haiku)
4. Profile with logs: `logger.setLevel(logging.DEBUG)`

---

### Issue: Poor Quality Insights

**Solution:**
1. Check if data sample is representative:
   - `BusinessContextTracker` uses first 10 rows
   - Ensure data is sorted meaningfully
2. Improve prompts in `prompts.py`:
   - Add more specific instructions
   - Provide examples
3. Increase LLM temperature for more creative insights (not exposed yet)

---

### Issue: Cache Not Working

**Solution:**
1. Verify embeddings model available:
   ```python
   assert hasattr(llm, 'get_embeddings'), "Embeddings required"
   ```
2. Check cache threshold (may be too high):
   ```python
   semantic_cache = SemanticCache(embeddings, threshold=0.90)  # Lower
   ```
3. Monitor cache stats:
   ```python
   logger.info(semantic_cache.get_stats())
   ```

---

### Issue: LLM Reasoning Errors

**Solution:**
1. Check `_intent_reasoning`, `_viz_reasoning`, `_response_reasoning` fields in state
2. Enable debug logging:
   ```python
   logging.getLogger("src.graphs.report").setLevel(logging.DEBUG)
   ```
3. Verify LLM response parsing:
   - JSON format issues
   - Markdown code block extraction
4. Add fallback error handling (already implemented in most components)

---

## Monitoring Metrics

### Key Metrics to Track

**Quality Metrics:**
- Intent classification accuracy (target: 90%+)
- Natural response quality score (user rating 4+/5)
- Business insights relevance (user rating 4+/5)
- Clarification helpfulness (user rating 4+/5)

**Performance Metrics:**
- End-to-end latency (target: 2-3s, with cache: 1-1.5s)
- Token usage per request (target: 2500-4000, with cache: 1200-1500)
- Cache hit rate (target: 30-50%)
- Error rate (target: <5%)

**Cost Metrics:**
- LLM API costs per request
- Embeddings API costs (if cache enabled)
- Cost per user session
- Cost savings from cache

---

## Example: Full Integration

```python
from src.models.llm import LLM
from src.graphs.report import build_report_graph
from langgraph.checkpoint.memory import MemorySaver

# Initialize LLM with embeddings support
llm = LLM(
    model_name="gpt-4",
    temperature=0.7,
    enable_embeddings=True  # For semantic cache
)

# Build graph with LLM-driven features
graph = build_report_graph(
    text2sql_graph=text2sql_compiled,
    visualization_graph=viz_compiled,
    llm=llm,

    # Enable all LLM features
    enable_llm_conversation=True,
    enable_business_insights=True,
    enable_llm_interpretation=True,
    enable_natural_response=True,
    enable_semantic_cache=True,

    # Enable HITL
    enable_hitl=True,

    # Checkpointer for state persistence
    checkpointer=MemorySaver()
)

# Use graph
result = await graph.ainvoke(
    {
        "messages": [HumanMessage(content="İstanbul satış raporu")],
        "active_query_context": None,
        "query_history": [],
        "pending_question": None,
        "waiting_for_user_input": False,
        "user_clarification": None,
        "text2sql_output": None,
        "visualization_output": None,
        "error": None,
        "no_records_message": None,
        "business_context": None  # Will be populated
    },
    config={"configurable": {"thread_id": "user-123"}}
)

# Check business context
business_context = result.get("business_context")
if business_context:
    print("Business Question:", business_context["business_question"])
    print("Key Insights:", business_context["key_insights"])
    print("Suggested Follow-ups:", business_context["suggested_follow_ups"])

# Check LLM reasoning (debugging)
print("Intent Reasoning:", result.get("_intent_reasoning"))
print("Viz Reasoning:", result.get("_viz_reasoning"))
```

---

## Best Practices

1. **Start with baseline** (all features off) to establish metrics
2. **Enable features gradually** to monitor impact
3. **Always enable semantic cache** in production (if embeddings available)
4. **Monitor token usage** and adjust feature flags accordingly
5. **Use debug logging** during development to inspect LLM reasoning
6. **Profile performance** with different feature combinations
7. **Collect user feedback** on response quality and insights
8. **Keep prompts optimized** - avoid unnecessary verbosity
9. **Test fallback behavior** - ensure graceful degradation on LLM errors
10. **Document feature flag decisions** for your use case

---

## Support

For issues, questions, or feature requests:
- Check logs with `logging.DEBUG` level
- Review `_intent_reasoning`, `_viz_reasoning`, `_response_reasoning` fields
- Monitor semantic cache stats
- Profile token usage and latency

**Happy building! 🚀**
