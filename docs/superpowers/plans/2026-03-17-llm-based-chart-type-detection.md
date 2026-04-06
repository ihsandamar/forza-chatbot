# LLM-Based Chart Type Detection — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace regex-based chart type detection with LLM-based detection so the system can understand typos ("sunbrust"), creative Turkish ("güneş patlaması grafiği"), and any natural language chart type request.

**Architecture:** Remove `_detect_explicit_chart_type()` regex and `explicit_chart_type` parameter. Instead, detect when the user has a chart type preference (via `viz_request` or visualization keywords in query) and route to LLM instead of rule-based path. The existing VIZ_DECIDER_PROMPT already has chart type selection rules — the LLM just needs to be reached.

**Tech Stack:** Python, LangGraph, LangChain structured output, pytest

---

## Root Cause

The rule-based path (`_rule_based_decision`) returns a deterministic chart type for every `query_type` (e.g. TIME_SERIES_COMPARISON → line_chart). It NEVER returns `None` for these cases, so the LLM fallback is never reached. The regex override we added catches exact keywords but fails on:
- Typos: "sunbrust" instead of "sunburst"
- Creative Turkish: "güneş patlaması", "ağaç haritası"
- Any expression not in the pattern list

## Design Decision

**Why LLM instead of regex?**
- LLM understands typos, synonyms, creative expressions
- VIZ_DECIDER_PROMPT already has chart type mapping rules (lines 54-72)
- LLM also handles field mapping (x_field, y_field, series_field) correctly for the chosen chart type
- No maintenance burden of adding new patterns

**When to skip rule-based and go to LLM?**
1. `viz_request` is set → REVISUALIZE intent, user explicitly wants different visualization
2. `user_query` contains a visualization-hint keyword → user mentioned a chart type

The "visualization-hint keyword" check is intentionally broad — just detecting words like "grafik", "chart", "plot", "harita", "diagram" etc. This is NOT chart type detection (LLM does that). It's just a signal that the user has a visualization preference worth consulting the LLM about.

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Modify | Remove regex detection, add `_has_viz_preference()`, update `viz_decider_node` routing |
| `tests/test_visualization_v2/test_explicit_chart_type.py` | Modify | Replace regex tests with LLM routing tests |

---

### Task 1: Replace regex detection with LLM routing (single atomic change)

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py`
- Rewrite: `tests/test_visualization_v2/test_explicit_chart_type.py` (COMPLETE file replacement)

**CRITICAL:** Both source and test files must be changed atomically in one commit. The old test file imports `_detect_explicit_chart_type` and `explicit_chart_type` which are being removed — leaving any old test class will break the suite.

- [ ] **Step 1: Rewrite the ENTIRE test file**

Replace the ENTIRE contents of `tests/test_visualization_v2/test_explicit_chart_type.py` with this complete file:

```python
"""Tests for LLM-based chart type detection routing.

Replaces the old regex-based TestDetectExplicitChartType and TestExplicitChartTypeOverride.
The LLM now handles chart type understanding — these tests verify the routing logic.
"""
import pytest


class TestHasVizPreference:
    """_has_viz_preference detects when user mentions a chart type, triggering LLM path."""

    def _check(self, query):
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _has_viz_preference
        return _has_viz_preference(query)

    # --- Should detect preference (broad keyword match) ---
    def test_heatmap(self):
        assert self._check("heatmap grafik ver") is True

    def test_sunburst_typo(self):
        """'sunbrust' contains 'sunbur' (6-char fragment in _VIZ_HINT_KEYWORDS) — typo tolerance."""
        assert self._check("sunbrust olarak goster") is True

    def test_turkish_grafik(self):
        """'grafik' is a generic viz keyword — triggers LLM regardless of chart type."""
        assert self._check("bunu grafik ver") is True

    def test_chart_english(self):
        assert self._check("show as pie chart") is True

    def test_turkish_harita(self):
        assert self._check("ısı haritası olarak göster") is True

    def test_diagram(self):
        assert self._check("diagram olarak goster") is True

    def test_cubuk(self):
        assert self._check("çubuk grafik göster") is True

    def test_treemap(self):
        assert self._check("treemap ver") is True

    def test_plot(self):
        assert self._check("scatter plot goster") is True

    # --- Should NOT detect preference (no chart type signal) ---
    def test_plain_data_query(self):
        assert self._check("son 3 aydaki satislari goster") is False

    def test_empty(self):
        assert self._check("") is False

    def test_none(self):
        assert self._check(None) is False

    def test_filter_query(self):
        assert self._check("sadece espresso kategorisini filtrele") is False


class TestShouldUseLLM:
    """_should_use_llm decides when to skip rule-based and route to LLM."""

    def _check(self, viz_request, user_query):
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _should_use_llm
        return _should_use_llm(viz_request, user_query)

    def test_viz_request_set_always_triggers_llm(self):
        """REVISUALIZE (viz_request set) always goes to LLM."""
        assert self._check("sunburst olarak ver", "sunburst olarak ver") is True

    def test_viz_request_with_any_text(self):
        """Any non-empty viz_request triggers LLM."""
        assert self._check("baska turlu goster", "baska turlu goster") is True

    def test_user_query_with_chart_keyword(self):
        """user_query with chart keyword → LLM."""
        assert self._check(None, "kategorileri heatmap grafik olarak goster") is True

    def test_plain_query_uses_rule_based(self):
        """No chart preference → rule-based path."""
        assert self._check(None, "son 3 aydaki satislari goster") is False

    def test_typo_sunbrust_triggers_llm(self):
        """'sunbrust' contains 'sunbur' fragment → LLM."""
        assert self._check(None, "sunbrust grafik ver") is True

    def test_none_query_uses_rule_based(self):
        assert self._check(None, "") is False


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


class TestEndToEndLLMRouting:
    """Verify routing + rule-based still works for non-preference queries."""

    def test_plain_query_still_gets_rule_based_line_chart(self):
        """No chart keyword → rule-based → line_chart for TIME_SERIES_COMPARISON."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import (
            _should_use_llm,
            _rule_based_decision,
        )
        assert _should_use_llm(None, "son 3 aydaki satislari goster") is False

        profile = {
            "dimension_columns": ["CategoryName", "Ay"],
            "metric_columns": ["ToplamCiro"],
            "time_column": "Ay",
            "row_count": 49,
        }
        result = _rule_based_decision(
            "TIME_SERIES_COMPARISON", True, profile,
            time_granularity="monthly", comparison_dimension="CategoryName",
        )
        assert result["chart_type"] == "line_chart"

    @pytest.mark.asyncio
    async def test_validator_still_fills_fields_for_sunburst(self):
        """Validator field completion works regardless of routing path."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import spec_validator_node

        state = {
            "results": [
                {"CategoryName": "ESPRESSO", "Ay": "2026-01", "ToplamCiro": 50000},
                {"CategoryName": "CAYLAR", "Ay": "2026-01", "ToplamCiro": 30000},
            ],
            "viz_decision": {
                "needs_graph": True,
                "chart_type": "sunburst",
                "x_field": "Ay",
                "y_field": "ToplamCiro",
                "series_field": "CategoryName",
                "hierarchy_fields": ["CategoryName", "Ay"],
            },
            "data_profile": {
                "dimension_columns": ["CategoryName", "Ay"],
                "metric_columns": ["ToplamCiro"],
                "time_column": "Ay",
                "columns": [
                    {"name": "CategoryName", "role": "dimension", "type": "text"},
                    {"name": "Ay", "role": "time", "type": "text"},
                    {"name": "ToplamCiro", "role": "metric", "type": "numeric"},
                ],
            },
        }
        result = await spec_validator_node(state)
        validated = result["viz_decision"]
        assert validated["chart_type"] == "sunburst"
```

- [ ] **Step 2: Implement the routing changes in nodes.py**

In `src/graphs/report_agent/subagents/visualization_v2/nodes.py`:

**a) Remove `import re`** (line 17). It is only used by the regex functions being deleted — safe to remove unconditionally.

**b) Remove the old regex code.** Delete these blocks entirely:
- `_GRAFIK = ...` constant (line 36)
- `_CHART_TYPE_PATTERNS` list (lines 37-58)
- `_detect_explicit_chart_type()` function (lines 62-75)

**c) Remove `explicit_chart_type` parameter from `_rule_based_decision()`.** Revert the function signature to:
```python
def _rule_based_decision(
    query_type: str,
    wants_viz: bool,
    profile: dict,
    time_granularity: Optional[str] = None,
    comparison_dimension: Optional[str] = None,
) -> Optional[dict]:
```

**d) Remove the explicit override block** inside `_rule_based_decision()` (the `if explicit_chart_type:` block that returns early).

**e) Add the new functions** where the old regex code was:

```python
# Broad visualization keywords — NOT chart type detection.
# Just a signal that user has a chart preference worth consulting the LLM about.
# The LLM does the actual chart type understanding (handles typos, Turkish, creative expressions).
# Note: "pasta" is excluded to avoid false positives on food category queries —
# "pasta grafik" is caught by "grafik" anyway.
_VIZ_HINT_KEYWORDS = {
    # Chart type names (English + partial fragments for typo tolerance)
    "heatmap", "sunbur", "treemap", "scatter", "pie",
    # Chart type names (Turkish fragments)
    "cubuk", "çubuk", "cizgi", "çizgi",
    # Generic visualization terms (these catch "X grafik ver" for any X)
    "grafik", "grafig", "grafiğ", "chart", "plot", "diagram",
    "harita", "haritas",
}


def _has_viz_preference(user_query: str) -> bool:
    """
    Check if user query contains any visualization-related keyword.

    This is NOT chart type detection — just a broad signal that the user
    mentioned something about chart types. The LLM handles actual understanding.
    Intentionally broad to catch typos like 'sunbrust' (contains 'sunbur').
    """
    if not user_query:
        return False
    q = user_query.lower()
    return any(kw in q for kw in _VIZ_HINT_KEYWORDS)


def _should_use_llm(viz_request: Optional[str], user_query: str) -> bool:
    """
    Decide whether to skip rule-based path and use LLM for chart type decision.

    Returns True when:
    1. viz_request is set (REVISUALIZE — user explicitly wants different visualization)
    2. user_query contains visualization-hint keywords (user mentioned a chart type)
    """
    if viz_request:
        return True
    return _has_viz_preference(user_query)
```

**f) Update `viz_decider_node`** to use the new routing. Replace the block from `_time_gran = ...` through the rule_decision return with:

```python
        _time_gran = state.get("time_granularity")
        _comp_dim = state.get("comparison_dimension")

        # Check if user has a chart type preference → LLM should decide
        _viz_request = state.get("viz_request")
        _user_query = state.get("user_query", "")
        _use_llm = _should_use_llm(_viz_request, _user_query)

        if _use_llm:
            logger.info("[V2:VIZ_DECIDER] User has viz preference → skipping rule-based, using LLM")
        else:
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

        # LLM path (either user preference or rule-based returned None)
```

The rest of the LLM fallback code stays exactly as is — it already uses `effective_query`, `conversation_context`, and the VIZ_DECIDER_PROMPT which handles chart type understanding.

- [ ] **Step 3: Run all tests**

Run: `python -m pytest tests/test_visualization_v2/test_explicit_chart_type.py -v`
Expected: ALL PASS

- [ ] **Step 4: Run full suite for regressions**

Run: `python -m pytest tests/test_visualization_v2/ tests/test_viz_decider_fast_path.py tests/test_viz_v2_field_mapping.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py tests/test_visualization_v2/test_explicit_chart_type.py
git commit -m "refactor: replace regex chart type detection with LLM-based routing

Remove _detect_explicit_chart_type() regex approach. Instead, detect when
user has a chart type preference (_has_viz_preference) and skip rule-based
path to let the LLM handle chart type understanding. LLM can handle typos,
creative Turkish expressions, and any natural language chart request.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

## Summary of Changes

| Before (Regex) | After (LLM) |
|----------------|-------------|
| `_detect_explicit_chart_type()` parses exact keywords | `_has_viz_preference()` checks broad keyword signal |
| Regex miss → rule-based default (line_chart) | Broad keyword match → LLM decides chart type |
| Can't handle typos, creative Turkish | LLM understands "sunbrust", "güneş patlaması", etc. |
| `explicit_chart_type` param in `_rule_based_decision` | Removed — routing happens at `viz_decider_node` level |
| Rule-based ALWAYS runs first | Rule-based SKIPPED when user has viz preference |

**Key insight:** The existing VIZ_DECIDER_PROMPT (prompts.py:54-72) already has all the chart type mapping rules. The LLM was always capable of handling this — it just wasn't being reached because rule-based intercepted first.

**Total: 1 task, 2 files modified, ~50 lines of production code changed, ~120 lines of tests**
