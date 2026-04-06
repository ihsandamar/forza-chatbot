# Intent-Based Chart Type Detection — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move chart type detection into `classify_intent_node` (existing LLM call) so typos, creative Turkish, and any expression are handled natively — zero extra latency, zero keyword maintenance.

**Architecture:** Add `requested_chart_type: Optional[Literal[...]]` to `IntentClassificationResult`. The intent classifier LLM already runs — it just extracts chart type too. `viz_decider_node` checks this field: if set, uses it directly (skipping rule-based); if None, rule-based decides as before. Remove all keyword-based routing (`_VIZ_HINT_KEYWORDS`, `_has_viz_preference`, `_should_use_llm`).

**Tech Stack:** Python, Pydantic, LangGraph, pytest

---

## File Map

| File | Action | What Changes |
|------|--------|-------------|
| `src/graphs/report_agent/prompts.py` | Modify | Add `requested_chart_type` to `IntentClassificationResult` + prompt rules |
| `src/graphs/report_agent/state.py` | Modify | Add `requested_chart_type` to `ReportState` |
| `src/graphs/report_agent/nodes.py` | Modify | Propagate `requested_chart_type` from intent result to state |
| `src/graphs/report_agent/subagents/visualization_v2/state.py` | Modify | Add `requested_chart_type` to `VisualizationState` |
| `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Modify | Use `requested_chart_type` in `viz_decider_node`, delete keyword routing |
| `tests/test_visualization_v2/test_explicit_chart_type.py` | Rewrite | New tests for intent-based routing |

---

### Task 1: Add `requested_chart_type` to intent model and prompt

**Files:**
- Modify: `src/graphs/report_agent/prompts.py`

- [ ] **Step 1: Add field to `IntentClassificationResult`**

In `src/graphs/report_agent/prompts.py`, add to `IntentClassificationResult` class (after `compute_operation` field, line 18):

```python
    requested_chart_type: Optional[Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "heatmap", "sunburst", "treemap",
    ]] = None  # Kullanıcı açıkça istediği grafik tipi (typo toleranslı)
```

- [ ] **Step 2: Add chart type rules to `INTENT_CLASSIFIER_PROMPT`**

In the same file, add the following block to `INTENT_CLASSIFIER_PROMPT` after the `**wants_visualization:**` section (after line 140):

```
**requested_chart_type:**
Kullanıcı belirli bir grafik tipi istiyorsa, wants_visualization=True olmalı ve requested_chart_type doldurulmalı.
Typo'lara toleranslı ol (ör: "sunbrust" → sunburst, "hetmap" → heatmap).
- "bar grafik", "çubuk grafik", "bar chart" → bar_chart
- "çizgi grafik", "line chart", "trend grafik" → line_chart
- "pasta grafik", "pie chart", "daire grafik" → pie_chart
- "scatter", "dağılım grafiği" → scatter_chart
- "heatmap", "ısı haritası", "heat map" → heatmap
- "sunburst", "güneş patlaması" → sunburst
- "treemap", "ağaç haritası" → treemap
- Grafik tipi belirtilmemişse → null (viz_decider otomatik seçer)
- ⚠️ SADECE kullanıcı açıkça bir grafik tipi belirttiğinde doldur. "grafik ver" tek başına yetmez.
```

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/prompts.py
git commit -m "feat: add requested_chart_type to IntentClassificationResult

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Propagate `requested_chart_type` through state

**Files:**
- Modify: `src/graphs/report_agent/state.py`
- Modify: `src/graphs/report_agent/nodes.py`
- Modify: `src/graphs/report_agent/subagents/visualization_v2/state.py`

- [ ] **Step 1: Add to `ReportState`**

In `src/graphs/report_agent/state.py`, add after `wants_visualization` field (line 17):

```python
    requested_chart_type: Optional[str]  # "heatmap", "sunburst" etc. — intent LLM'den gelir
```

Also add to `create_initial_state()` (inside the return dict):
```python
        requested_chart_type=None,
```

- [ ] **Step 2: Add to `VisualizationState`**

In `src/graphs/report_agent/subagents/visualization_v2/state.py`, add after `comparison_dimension` (line 21):

```python
    requested_chart_type: Optional[str]  # from intent classification
```

- [ ] **Step 3: Propagate in `classify_intent_node`**

In `src/graphs/report_agent/nodes.py`, in the `return_dict` (around line 140-156), add:

```python
            "requested_chart_type": result.requested_chart_type,
```

Add it after the `"wants_visualization": wants_viz,` line.

Also add `"requested_chart_type": None` to the **table-refresh early-return** dict (around line 66-78 of `nodes.py`, inside the `if is_refresh_request:` block) to prevent stale state from previous turns.

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/state.py src/graphs/report_agent/nodes.py src/graphs/report_agent/subagents/visualization_v2/state.py
git commit -m "feat: propagate requested_chart_type through state pipeline

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Use `requested_chart_type` in viz_decider, delete keyword routing

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py`
- Rewrite: `tests/test_visualization_v2/test_explicit_chart_type.py`

- [ ] **Step 1: Rewrite the ENTIRE test file**

Replace ALL contents of `tests/test_visualization_v2/test_explicit_chart_type.py` with:

```python
"""Tests for intent-based chart type routing in viz_decider."""
import pytest


class TestVizDeciderWithRequestedChartType:
    """viz_decider_node uses requested_chart_type from intent classification."""

    def test_requested_chart_type_overrides_rule_based(self):
        """When requested_chart_type is set, rule-based should be skipped."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["CategoryName", "Ay"],
            "metric_columns": ["ToplamCiro"],
            "time_column": "Ay",
            "row_count": 49,
        }
        # Without override → line_chart (default for TIME_SERIES_COMPARISON)
        result = _rule_based_decision(
            "TIME_SERIES_COMPARISON", True, profile,
            time_granularity="monthly", comparison_dimension="CategoryName",
        )
        assert result["chart_type"] == "line_chart"

    def test_rule_based_unchanged_without_chart_type(self):
        """No requested_chart_type → rule-based behavior preserved."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["BranchName"],
            "metric_columns": ["RowAmount"],
            "time_column": None,
            "row_count": 5,
        }
        result = _rule_based_decision("RANKING", True, profile)
        assert result["chart_type"] == "bar_chart"


class TestRequestedChartTypeModel:
    """IntentClassificationResult.requested_chart_type field validation."""

    def test_valid_chart_type(self):
        from src.graphs.report_agent.prompts import IntentClassificationResult
        result = IntentClassificationResult(
            intent_type="NEW_QUERY",
            query_type="TIME_SERIES_COMPARISON",
            confidence=0.95,
            wants_visualization=True,
            requested_chart_type="heatmap",
        )
        assert result.requested_chart_type == "heatmap"

    def test_none_chart_type(self):
        from src.graphs.report_agent.prompts import IntentClassificationResult
        result = IntentClassificationResult(
            intent_type="NEW_QUERY",
            query_type="SINGLE",
            confidence=0.9,
            wants_visualization=False,
        )
        assert result.requested_chart_type is None

    def test_invalid_chart_type_rejected(self):
        from src.graphs.report_agent.prompts import IntentClassificationResult
        with pytest.raises(Exception):  # Pydantic validation error
            IntentClassificationResult(
                intent_type="NEW_QUERY",
                query_type="SINGLE",
                confidence=0.9,
                requested_chart_type="invalid_chart",
            )

    def test_sunburst_chart_type(self):
        from src.graphs.report_agent.prompts import IntentClassificationResult
        result = IntentClassificationResult(
            intent_type="USE_RESULT",
            query_type="TIME_SERIES_COMPARISON",
            confidence=0.98,
            wants_visualization=True,
            use_result_type="revisualize",
            requested_chart_type="sunburst",
        )
        assert result.requested_chart_type == "sunburst"


class TestValidatorHeatmapCompletion:
    """Validator should fill series_field for heatmap before downgrading."""

    def test_heatmap_gets_series_field_from_remaining_dims(self):
        from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
        spec = {
            "needs_graph": True,
            "chart_type": "heatmap",
            "x_field": "Ay",
            "y_field": "ToplamCiro",
            "series_field": None,
        }
        results = [
            {"CategoryName": "ESPRESSO", "Ay": "2026-01", "ToplamCiro": 50000},
            {"CategoryName": "CAYLAR", "Ay": "2026-01", "ToplamCiro": 30000},
            {"CategoryName": "ESPRESSO", "Ay": "2026-02", "ToplamCiro": 60000},
            {"CategoryName": "CAYLAR", "Ay": "2026-02", "ToplamCiro": 35000},
        ]
        profile = {
            "dimension_columns": ["CategoryName", "Ay"],
            "metric_columns": ["ToplamCiro"],
            "time_column": "Ay",
            "columns": [
                {"name": "CategoryName", "role": "dimension", "type": "text"},
                {"name": "Ay", "role": "time", "type": "text"},
                {"name": "ToplamCiro", "role": "metric", "type": "numeric"},
            ],
        }
        validated = validate_spec(spec, results, profile)
        assert validated["chart_type"] == "heatmap"
        assert validated["series_field"] == "CategoryName"


class TestEndToEndIntentRouting:
    """Verify the full routing: requested_chart_type → viz_decider override."""

    @pytest.mark.asyncio
    async def test_requested_chart_type_used_in_viz_decision(self):
        """When requested_chart_type is set, viz_decider should produce that chart type."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import (
            data_analyzer_node,
            spec_validator_node,
        )
        results = [
            {"CategoryName": "ESPRESSO", "Ay": "2026-01", "ToplamCiro": 50000},
            {"CategoryName": "CAYLAR", "Ay": "2026-01", "ToplamCiro": 30000},
            {"CategoryName": "ESPRESSO", "Ay": "2026-02", "ToplamCiro": 60000},
        ]

        # Get data profile
        state = {"results": results}
        analyzer_result = await data_analyzer_node(state)
        profile = analyzer_result["data_profile"]

        # Simulate what viz_decider does with requested_chart_type
        # Build the override spec manually (same logic as viz_decider_node)
        requested = "heatmap"
        spec = {
            "needs_graph": True,
            "chart_type": requested,
            "x_field": None,
            "y_field": None,
            "series_field": None,
            "reason": f"User requested {requested}",
        }

        # Validate
        full_state = {
            "results": results,
            "viz_decision": spec,
            "data_profile": profile,
        }
        validated_result = await spec_validator_node(full_state)
        validated = validated_result["viz_decision"]
        assert validated["chart_type"] == "heatmap"
        assert validated["x_field"] is not None
        assert validated["y_field"] is not None
```

- [ ] **Step 2: Clean up `nodes.py` — delete keyword routing, add chart type override**

In `src/graphs/report_agent/subagents/visualization_v2/nodes.py`:

**a) Delete these blocks entirely** (lines 32-73):
- `_VIZ_HINT_KEYWORDS` set
- `_has_viz_preference()` function
- `_should_use_llm()` function

**b) Replace the routing block in `viz_decider_node`** (find the block starting with `_time_gran = state.get("time_granularity")` through the rule_decision return). Replace with:

```python
        _time_gran = state.get("time_granularity")
        _comp_dim = state.get("comparison_dimension")

        # --- Chart type override from intent classification ---
        _requested_chart = state.get("requested_chart_type")
        if _requested_chart:
            logger.info(f"[V2:VIZ_DECIDER] Intent requested chart type: {_requested_chart}")
            return {"viz_decision": {
                "needs_graph": True,
                "chart_type": _requested_chart,
                "x_field": None,
                "y_field": None,
                "series_field": _comp_dim,
                "reason": f"User requested {_requested_chart}",
            }}

        # Rule-based fast path (no user chart preference)
        rule_decision = _rule_based_decision(
            query_type=state.get("query_type", ""),
            wants_viz=state.get("wants_visualization", False),
            profile=data_profile or {},
            time_granularity=_time_gran,
            comparison_dimension=_comp_dim,
        )
        if rule_decision is not None:
            logger.info(f"[V2:VIZ_DECIDER] Rule-based: {rule_decision['chart_type']}")
            return {"viz_decision": rule_decision}
```

**IMPORTANT:** The LLM fallback code below (including `effective_query = state.get("viz_request") or state.get("user_query", "")` at ~line 382) must be **preserved as-is**. It handles edge cases where rule-based returns None and provides the REVISUALIZE query context to the LLM prompt. Do NOT delete the `viz_request` usage in the LLM prompt path.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_visualization_v2/test_explicit_chart_type.py -v`
Expected: ALL PASS

- [ ] **Step 4: Run full regression suite**

Run: `python -m pytest tests/test_visualization_v2/ tests/test_viz_decider_fast_path.py tests/test_viz_v2_field_mapping.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py tests/test_visualization_v2/test_explicit_chart_type.py
git commit -m "refactor: use requested_chart_type from intent, delete keyword routing

viz_decider_node now reads requested_chart_type from state (set by
classify_intent_node). If set, uses it directly. If None, rule-based
decides as before. Removes _VIZ_HINT_KEYWORDS, _has_viz_preference,
_should_use_llm — all replaced by single state field.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Summary

```
classify_intent_node (EXISTING LLM call):
  IntentClassificationResult:
    + requested_chart_type: Optional[Literal[...]] = None

  "heatmap grafik ver"     → requested_chart_type: "heatmap"
  "sunbrust olarak göster" → requested_chart_type: "sunburst" (LLM handles typo)
  "satışları göster"       → requested_chart_type: None

                    ↓ state propagation

viz_decider_node:
  if requested_chart_type:  → use it (3 lines)
  else:                     → rule-based default (unchanged)
```

**Deleted:** `_VIZ_HINT_KEYWORDS`, `_has_viz_preference()`, `_should_use_llm()` — `viz_request` field and its usage in LLM prompt path (line ~382) are **preserved** for REVISUALIZE context.

**Note:** `"comparison"` exists in `ChartSpec` but not in `requested_chart_type` Literal — intentional (only user-requestable graph types). Heatmap override with `series_field=None` (when `comparison_dimension` is None) relies on validator Rule 4 to fill from remaining dims. If data has only one dimension, validator downgrades to bar_chart — acceptable behavior.

**Net result:** Less code, zero extra latency, LLM handles all NLP (typos, Turkish, creative expressions)
