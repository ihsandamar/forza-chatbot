# Report Agent Speed Optimization Design

**Goal:** Reduce report agent end-to-end latency from ~25s to <10s without breaking graph architecture.

**Approach:** Eliminate unnecessary LLM calls and add caching — keep graph topology and node responsibilities unchanged.

---

## Current Critical Path (25s)

```
classify_intent(1.5s) → business_rules(3.6s) → term_resolver(0.03s)
→ max(sql_architect(4.0s), schema_validator(3.8s)) → sql_executor(4.5s)
→ viz_decider(3.1s) → chart_generator(6.7s)
```

6 sequential LLM calls + 1 DB call. 3 parallel nodes already exist (sql_architect ∥ schema_validator ∥ term_validator).

## Optimizations

### 1. Business Rules Cache (3.6s → 0.01s warm)

3-layer caching strategy for ChromaDB vector search + LLM validation:

- **Layer 1: Embedding cache** — LRU cache for query → embedding vector. Avoids recomputing sentence-transformer embeddings.
- **Layer 2: Search result cache** — TTL-based cache keyed by query_hash → {rules, merged_sql}. Invalidated when business_rules.json file hash changes.
- **Layer 3: LLM validation preserved** — On cache miss, full semantic search + LLM validation runs (accuracy preserved). On cache hit, validated results returned directly.

Cold: 3.6s (unchanged). Warm: ~0.01s.

### 2. Rule-Based viz_decider (3.1s → 0.01s)

Extend existing fast-path logic with deterministic chart selection based on query_type + data_profile:

| query_type | Default chart | Logic |
|---|---|---|
| RANKING | bar_chart | First string col → x, first numeric → y, sort desc |
| TIME_SERIES / TIME_SERIES_COMPARISON | line_chart | Date col → x, first numeric → y, sort asc |
| COMPARISON | grouped bar | First string → x, first numeric → y, series_field from 2nd string |
| LISTING (>10 rows) | table | No graph |
| SINGLE | single_value | No graph |

LLM fallback: multiple numeric columns, ambiguous mapping, or explicit user viz request.

### 3. Dynamic Chart Template Engine (6.7s → 0.05s)

Replace LLM code generation with parameterized Plotly builders:

**Builder registry:**
```
bar_chart, line_chart, pie_chart, scatter, treemap, sunburst, comparison → BUILDERS dict
```

**Dynamic adaptation layers:**
- **Data type formatting:** column dtype → axis format (currency, percentage, integer)
- **Column metadata labels:** column_metadata descriptions as axis labels
- **Auto-sorting:** RANKING→y desc, TIME_SERIES→x asc
- **Multi-series:** series_field present → grouped/stacked bars
- **Color palette:** ≤5 categories → qualitative, >5 → sequential
- **Responsive layout:** >15 bars → horizontal orientation

**LLM fallback conditions:**
- chart_type not in BUILDERS
- User requests custom formatting ("kırmızı renkle", "logaritmik scale")
- viz_decision fields incomplete (x_field/y_field None)

### 4. Connection Pooling (4.5s → 3-3.5s)

Singleton connection pool for pyodbc — eliminate per-request connection overhead (~0.5-1s).

---

## Target Critical Path

**Warm cache:**
```
classify_intent(1.5s) → business_rules(0.01s) → parallel_llm(4.0s)
→ sql_executor(3.0s) → viz_decider(0.01s) → chart_template(0.05s)
= ~8.6s
```

**Cold cache (first unique query):**
```
classify_intent(1.5s) → business_rules(3.6s) → parallel_llm(4.0s)
→ sql_executor(3.0s) → viz_decider(0.01s) → chart_template(0.05s)
= ~12.2s
```

## Constraints

- Graph topology unchanged (edges, node names, subgraph boundaries)
- Node responsibilities unchanged (each node's inputs/outputs same)
- Accuracy preserved (LLM fallback for edge cases)
- Interrupt/resume (HITL) unaffected
- All optimizations are internal to node implementations
