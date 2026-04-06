# Explicit Chart Type Override — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When user explicitly requests a chart type (e.g. "heatmap grafik ver"), the system MUST use that chart type instead of the rule-based auto-detection.

**Architecture:** Add an explicit chart type extraction layer (`_detect_explicit_chart_type()`) that runs BEFORE the rule-based fast path in `viz_decider_node`. When detected, it forces the chart type while letting the validator handle field mapping. This applies to ALL chart types (heatmap, pie, bar, line, sunburst, treemap, scatter) and works for both NEW_QUERY and REVISUALIZE intents.

**Tech Stack:** Python, LangGraph, Plotly, pytest

---

## Root Cause Analysis

Two bugs were identified from a failed state:

1. **User asked for "heatmap", got `line_chart`**
   - `viz_request` is only set for REVISUALIZE intent (`nodes.py:142`), null for NEW_QUERY
   - `_rule_based_decision()` at `visualization_v2/nodes.py:189-197` returns `line_chart` deterministically for `TIME_SERIES_COMPARISON + comparison_dimension` without checking user's explicit chart type
   - Rule-based path runs BEFORE LLM fallback, so LLM never gets a chance

2. **`active_results` truncated to 10 rows** (by design at `text2sql/nodes.py:1293`)
   - Not a bug — token efficiency for conversation context
   - Full `results` field is used for visualization

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Modify (lines 130-319) | Add `_detect_explicit_chart_type()`, update `viz_decider_node` |
| `src/graphs/report_agent/subagents/visualization_v2/validator.py` | Modify (line 92-95) | Ensure heatmap series_field validation works with explicit override |
| `tests/test_visualization_v2/test_explicit_chart_type.py` | Create | All tests for explicit chart type detection and override |

---

### Task 1: Add `_detect_explicit_chart_type()` Utility Function

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py` (add after line 30)
- Create: `tests/test_visualization_v2/test_explicit_chart_type.py`

- [ ] **Step 1: Write failing tests for chart type detection**

Create `tests/test_visualization_v2/test_explicit_chart_type.py`:

```python
"""Tests for explicit chart type detection from user query."""
import pytest


class TestDetectExplicitChartType:
    """_detect_explicit_chart_type should extract chart type from Turkish/English queries."""

    def _detect(self, query: str):
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _detect_explicit_chart_type
        return _detect_explicit_chart_type(query)

    # --- Heatmap ---
    def test_heatmap_turkish(self):
        assert self._detect("satislari heatmap grafik olarak goster") == "heatmap"

    def test_isi_haritasi(self):
        assert self._detect("kategorilerin isi haritasi") == "heatmap"

    def test_isı_haritası_with_special_chars(self):
        assert self._detect("ısı haritası olarak göster") == "heatmap"

    # --- Pie ---
    def test_pasta_grafik(self):
        assert self._detect("pasta grafik ver") == "pie_chart"

    def test_pie_chart_english(self):
        assert self._detect("show as pie chart") == "pie_chart"

    # --- Bar ---
    def test_bar_grafik(self):
        assert self._detect("bar grafik olarak goster") == "bar_chart"

    def test_cubuk_grafik(self):
        assert self._detect("cubuk grafik ver") == "bar_chart"

    def test_çubuk_grafik(self):
        assert self._detect("çubuk grafik göster") == "bar_chart"

    # --- Line ---
    def test_cizgi_grafik(self):
        assert self._detect("cizgi grafik ile goster") == "line_chart"

    def test_çizgi_grafik(self):
        assert self._detect("çizgi grafik olarak göster") == "line_chart"

    def test_line_chart_english(self):
        assert self._detect("show as line chart") == "line_chart"

    def test_trend_grafik(self):
        assert self._detect("trend grafigi goster") == "line_chart"

    # --- Scatter ---
    def test_scatter_english(self):
        assert self._detect("scatter plot goster") == "scatter_chart"

    def test_dagilim_grafigi(self):
        assert self._detect("dagilim grafigi ver") == "scatter_chart"

    # --- Sunburst ---
    def test_sunburst(self):
        assert self._detect("sunburst grafik ver") == "sunburst"

    # --- Treemap ---
    def test_treemap(self):
        assert self._detect("treemap olarak goster") == "treemap"

    # --- No match ---
    def test_no_explicit_type(self):
        assert self._detect("son 3 aydaki satislari goster") is None

    def test_empty_query(self):
        assert self._detect("") is None

    def test_generic_grafik_no_type(self):
        """'grafik ver' alone should NOT match any specific type."""
        assert self._detect("grafik ver") is None

    def test_case_insensitive(self):
        assert self._detect("HEATMAP grafik ver") == "heatmap"

    def test_partial_word_no_match(self):
        """'barcin' should not match 'bar'."""
        assert self._detect("barcin satis raporu") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_visualization_v2/test_explicit_chart_type.py -v`
Expected: FAIL with ImportError (`_detect_explicit_chart_type` not found)

- [ ] **Step 3: Implement `_detect_explicit_chart_type()`**

Add to `src/graphs/report_agent/subagents/visualization_v2/nodes.py` after line 30 (`NO_GRAPH_TYPES = ...`):

```python
import re

# Explicit chart type keywords — order matters (longer patterns first to avoid partial matches)
_CHART_TYPE_PATTERNS: list[tuple[str, str]] = [
    # Heatmap
    (r"\bheatmap\b", "heatmap"),
    (r"\b[ıi]s[ıi]\s*haritas[ıi]\b", "heatmap"),
    # Pie
    (r"\bpasta\s*grafi[gğ]?[ıi]?\b", "pie_chart"),
    (r"\bpie\s*chart\b", "pie_chart"),
    (r"\bpasta\b", "pie_chart"),
    # Bar
    (r"\b[cç]ubuk\s*grafi[gğ]?[ıi]?\b", "bar_chart"),
    (r"\bbar\s*(?:grafi[gğ]?[ıi]?|chart)\b", "bar_chart"),
    # Line
    (r"\b[cç]izgi\s*grafi[gğ]?[ıi]?\b", "line_chart"),
    (r"\bline\s*chart\b", "line_chart"),
    (r"\btrend\s*grafi[gğ]?[ıi]?\b", "line_chart"),
    # Scatter
    (r"\bscatter\b", "scatter_chart"),
    (r"\bda[gğ][ıi]l[ıi]m\s*grafi[gğ]?[ıi]?\b", "scatter_chart"),
    # Sunburst
    (r"\bsunburst\b", "sunburst"),
    # Treemap
    (r"\btreemap\b", "treemap"),
]


def _detect_explicit_chart_type(user_query: str) -> Optional[str]:
    """
    Detect explicit chart type request from user query.

    Scans for Turkish/English chart type keywords.
    Returns chart_type string or None if no explicit type found.
    """
    if not user_query:
        return None
    q = user_query.lower()
    for pattern, chart_type in _CHART_TYPE_PATTERNS:
        if re.search(pattern, q):
            return chart_type
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_visualization_v2/test_explicit_chart_type.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_visualization_v2/test_explicit_chart_type.py src/graphs/report_agent/subagents/visualization_v2/nodes.py
git commit -m "feat: add _detect_explicit_chart_type() for Turkish/English chart keywords"
```

---

### Task 2: Wire Explicit Chart Type Into `viz_decider_node`

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py` (lines 281-319)
- Modify: `tests/test_visualization_v2/test_explicit_chart_type.py` (add integration tests)

- [ ] **Step 1: Write failing integration tests**

Append to `tests/test_visualization_v2/test_explicit_chart_type.py`:

```python
class TestExplicitChartTypeOverride:
    """viz_decider should use explicit chart type when user requests one."""

    def test_rule_based_overridden_by_explicit_heatmap(self):
        """TIME_SERIES_COMPARISON normally → line_chart, but user says heatmap → heatmap."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["CategoryName", "Ay"],
            "metric_columns": ["ToplamCiro"],
            "time_column": "Ay",
            "row_count": 49,
        }
        # Without explicit → line_chart (existing behavior)
        result = _rule_based_decision(
            "TIME_SERIES_COMPARISON", True, profile,
            time_granularity="monthly", comparison_dimension="CategoryName",
        )
        assert result["chart_type"] == "line_chart"

        # With explicit → heatmap
        result = _rule_based_decision(
            "TIME_SERIES_COMPARISON", True, profile,
            time_granularity="monthly", comparison_dimension="CategoryName",
            explicit_chart_type="heatmap",
        )
        assert result["chart_type"] == "heatmap"

    def test_explicit_pie_overrides_bar(self):
        """RANKING normally → bar_chart, but user says pie → pie_chart."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["BranchName"],
            "metric_columns": ["RowAmount"],
            "time_column": None,
            "row_count": 5,
        }
        result = _rule_based_decision(
            "RANKING", True, profile,
            explicit_chart_type="pie_chart",
        )
        assert result["chart_type"] == "pie_chart"

    def test_explicit_none_preserves_default(self):
        """No explicit type → default rule-based behavior unchanged."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["BranchName"],
            "metric_columns": ["RowAmount"],
            "time_column": None,
            "row_count": 5,
        }
        result = _rule_based_decision(
            "RANKING", True, profile,
            explicit_chart_type=None,
        )
        assert result["chart_type"] == "bar_chart"

    def test_explicit_heatmap_sets_series_field(self):
        """Heatmap with comparison_dimension should set series_field."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["CategoryName", "Ay"],
            "metric_columns": ["ToplamCiro"],
            "time_column": "Ay",
            "row_count": 49,
        }
        result = _rule_based_decision(
            "TIME_SERIES_COMPARISON", True, profile,
            time_granularity="monthly", comparison_dimension="CategoryName",
            explicit_chart_type="heatmap",
        )
        assert result["series_field"] == "CategoryName"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_visualization_v2/test_explicit_chart_type.py::TestExplicitChartTypeOverride -v`
Expected: FAIL (TypeError — `_rule_based_decision` doesn't accept `explicit_chart_type` param)

- [ ] **Step 3: Add `explicit_chart_type` parameter to `_rule_based_decision()`**

Modify `src/graphs/report_agent/subagents/visualization_v2/nodes.py`.

Change the function signature at line 130:

```python
def _rule_based_decision(
    query_type: str,
    wants_viz: bool,
    profile: dict,
    time_granularity: Optional[str] = None,
    comparison_dimension: Optional[str] = None,
    explicit_chart_type: Optional[str] = None,
) -> Optional[dict]:
```

Add explicit chart type override block right after the `if not metric_cols: return None` check (after line 151), BEFORE any rule-based routing:

```python
    # --- Explicit chart type override (user said "heatmap", "pasta grafik", etc.) ---
    if explicit_chart_type:
        logger.info(f"[V2:RULE] Explicit chart type override: {explicit_chart_type}")
        return {
            "needs_graph": True,
            "chart_type": explicit_chart_type,
            "x_field": None,
            "y_field": None,
            "series_field": comparison_dimension,
            "reason": f"User explicitly requested {explicit_chart_type}",
        }
```

- [ ] **Step 4: Update `viz_decider_node` to detect and pass explicit chart type**

Modify `src/graphs/report_agent/subagents/visualization_v2/nodes.py` lines 306-316.

Replace the rule_decision block:

```python
        _time_gran = state.get("time_granularity")
        _comp_dim = state.get("comparison_dimension")

        # Detect explicit chart type from user query
        effective_query = state.get("viz_request") or state.get("user_query", "")
        _explicit = _detect_explicit_chart_type(effective_query)
        if _explicit:
            logger.info(f"[V2:VIZ_DECIDER] Explicit chart type detected: {_explicit} from query")

        # Rule-based fast path (includes aggregate period routing)
        rule_decision = _rule_based_decision(
            query_type=state.get("query_type", ""),
            wants_viz=state.get("wants_visualization", False),
            profile=data_profile or {},
            time_granularity=_time_gran,
            comparison_dimension=_comp_dim,
            explicit_chart_type=_explicit,
        )
        if rule_decision is not None:
            logger.info(f"[V2:VIZ_DECIDER] Rule-based: {rule_decision['chart_type']}")
            return {"viz_decision": rule_decision}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_visualization_v2/test_explicit_chart_type.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run existing tests to verify no regressions**

Run: `python -m pytest tests/test_visualization_v2/ tests/test_viz_decider_fast_path.py -v`
Expected: ALL PASS — existing behavior unchanged when `explicit_chart_type=None`

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py tests/test_visualization_v2/test_explicit_chart_type.py
git commit -m "feat: explicit chart type override in viz_decider rule-based path"
```

---

### Task 3: Fix Validator Heatmap Field Completion

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/validator.py` (lines 92-112)
- Modify: `tests/test_visualization_v2/test_explicit_chart_type.py` (add validator test)

The current validator (line 92-95) downgrades heatmap to bar_chart if `series_field` is missing. But when explicit chart type is used, the rule-based path sets `series_field=comparison_dimension`. However, if `comparison_dimension` was null, `series_field` will be null too.

The validator's Rule 6 (line 128-154) already auto-fills `series_field` from remaining dimensions — but it runs AFTER Rule 3 which downgrades heatmap. We need to reorder so Rule 6 runs before Rule 3's heatmap check.

- [ ] **Step 1: Write failing test**

Append to `tests/test_visualization_v2/test_explicit_chart_type.py`:

```python
class TestValidatorHeatmapCompletion:
    """Validator should fill series_field for heatmap before downgrading."""

    def test_heatmap_gets_series_field_from_remaining_dims(self):
        from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
        spec = {
            "needs_graph": True,
            "chart_type": "heatmap",
            "x_field": "Ay",
            "y_field": "ToplamCiro",
            "series_field": None,  # Missing! Should be filled by validator
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
        assert validated["chart_type"] == "heatmap", "Should stay heatmap after series_field filled"
        assert validated["series_field"] == "CategoryName"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_visualization_v2/test_explicit_chart_type.py::TestValidatorHeatmapCompletion -v`
Expected: FAIL — validator downgrades heatmap to bar_chart before filling series_field

- [ ] **Step 3: Fix validator — move series_field completion before heatmap check**

In `src/graphs/report_agent/subagents/visualization_v2/validator.py`, move Rule 6 (series_field completion, lines 128-154) to run BEFORE Rule 3 (chart-data compatibility, line 66).

The new order should be:
1. Rule 1: Column existence (lines 43-52) — unchanged
2. Rule 2: Role conformity (lines 54-64) — unchanged
3. **Rule 4: Missing field completion (lines 97-112)** — moved up
4. **Rule 6: Series field completion (lines 128-154)** — moved up
5. **Rule 3: Chart-data compatibility (lines 66-95)** — moved down (now has complete fields)
6. Rule 5: Multi-metric validation (lines 114-126) — unchanged

Replace the body of `validate_spec()` (from line 33 to 156) with this reordered version:

```python
    spec = dict(spec)  # copy
    if not results:
        return spec

    actual_columns = list(results[0].keys())
    dimension_cols = profile.get("dimension_columns", [])
    metric_cols = profile.get("metric_columns", [])
    time_col = profile.get("time_column")
    columns_info = {c["name"]: c for c in profile.get("columns", [])}

    # Rule 1: Column existence
    for field_name in ("x_field", "y_field", "series_field"):
        value = spec.get(field_name)
        if value and value not in actual_columns:
            resolved = _fuzzy_resolve(value, actual_columns)
            if resolved:
                logger.info(f"[VALIDATOR] Rule 1: '{value}' -> '{resolved}'")
            else:
                logger.warning(f"[VALIDATOR] Rule 1: '{value}' not found, cleared")
            spec[field_name] = resolved

    # Rule 2: Role conformity (swap if x=metric and y=dimension)
    x = spec.get("x_field")
    y = spec.get("y_field")
    if x and y:
        x_info = columns_info.get(x, {})
        y_info = columns_info.get(y, {})
        x_is_metric = x_info.get("role") == "metric" or x in metric_cols
        y_is_dim = y_info.get("role") == "dimension" or y in dimension_cols
        if x_is_metric and y_is_dim:
            spec["x_field"], spec["y_field"] = y, x
            logger.info(f"[VALIDATOR] Rule 2: Swapped x/y ({x} <-> {y})")

    # Rule 4: Missing field completion (BEFORE chart-data compat so fields are available)
    if spec.get("needs_graph") and not spec.get("x_field"):
        spec["x_field"] = time_col or (dimension_cols[0] if dimension_cols else None)
        if spec["x_field"]:
            logger.info(f"[VALIDATOR] Rule 4: x_field filled -> '{spec['x_field']}'")

    if spec.get("needs_graph") and not spec.get("y_field") and not spec.get("y_fields"):
        spec["y_field"] = metric_cols[0] if metric_cols else None
        if spec["y_field"]:
            logger.info(f"[VALIDATOR] Rule 4: y_field filled -> '{spec['y_field']}'")

    if spec.get("needs_graph") and (not spec.get("x_field") or not spec.get("y_field")):
        if not spec.get("y_fields"):
            spec["needs_graph"] = False
            spec["chart_type"] = "table"
            logger.warning("[VALIDATOR] Rule 4: Cannot determine axes -> table fallback")
            return spec

    # Rule 6: Series field completion (BEFORE chart-data compat so heatmap check has series_field)
    _SERIES_COMPATIBLE = {"line_chart", "bar_chart", "comparison", "scatter_chart", "heatmap"}
    if (
        spec.get("needs_graph")
        and spec.get("chart_type") in _SERIES_COMPATIBLE
        and not spec.get("series_field")
        and spec.get("x_field")
        and spec.get("y_field")
    ):
        x = spec["x_field"]
        y = spec["y_field"]
        remaining_dims = [
            d for d in dimension_cols
            if d != x and d != y
        ]
        if remaining_dims:
            best = None
            best_unique = 999
            for dim in remaining_dims:
                if dim in actual_columns:
                    unique = len(set(row.get(dim) for row in results))
                    if unique > 1 and unique < best_unique:
                        best = dim
                        best_unique = unique
            if best is not None and best_unique <= 50:
                spec["series_field"] = best
                logger.info(f"[VALIDATOR] Rule 6: series_field filled -> '{best}' ({best_unique} unique)")

    # Rule 3: Chart-data compatibility (now with complete fields)
    chart_type = spec.get("chart_type")

    if chart_type == "pie_chart":
        x_val = spec.get("x_field")
        if x_val and x_val in actual_columns:
            unique_count = len(set(row.get(x_val) for row in results))
            if unique_count > 15 and not spec.get("top_n"):
                spec["top_n"] = 10
                logger.info(f"[VALIDATOR] Rule 3: pie_chart {unique_count} categories -> top_n=10")

    if chart_type == "line_chart":
        x_val = spec.get("x_field")
        is_time = (
            time_col is not None
            or (x_val and columns_info.get(x_val, {}).get("role") == "time")
        )
        if not is_time:
            spec["chart_type"] = "bar_chart"
            logger.info("[VALIDATOR] Rule 3: line_chart without time -> bar_chart")

    if chart_type == "scatter_chart":
        if len(metric_cols) < 2 and not spec.get("y_fields"):
            spec["chart_type"] = "bar_chart"
            logger.info("[VALIDATOR] Rule 3: scatter with <2 metrics -> bar_chart")

    if chart_type == "heatmap":
        if not spec.get("series_field"):
            spec["chart_type"] = "bar_chart"
            logger.info("[VALIDATOR] Rule 3: heatmap without series_field -> bar_chart")

    # Rule 5: Multi-metric validation
    y_fields = spec.get("y_fields")
    if y_fields:
        valid = [f for f in y_fields if f in actual_columns]
        if len(valid) == 0:
            spec["y_fields"] = None
            logger.warning("[VALIDATOR] Rule 5: No valid y_fields, cleared")
        elif len(valid) == 1:
            spec["y_field"] = valid[0]
            spec["y_fields"] = None
            logger.info(f"[VALIDATOR] Rule 5: Single y_field '{valid[0]}', moved to y_field")
        else:
            spec["y_fields"] = valid

    return spec
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_visualization_v2/test_explicit_chart_type.py::TestValidatorHeatmapCompletion -v`
Expected: PASS

- [ ] **Step 5: Run ALL validator tests to verify no regressions**

Run: `python -m pytest tests/test_visualization_v2/test_validator.py tests/test_visualization_v2/test_explicit_chart_type.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/validator.py tests/test_visualization_v2/test_explicit_chart_type.py
git commit -m "fix: reorder validator rules so series_field is filled before heatmap check"
```

---

### Task 4: End-to-End Integration Test

**Files:**
- Modify: `tests/test_visualization_v2/test_explicit_chart_type.py` (add E2E test)

- [ ] **Step 1: Write E2E test simulating the exact failing scenario**

Append to `tests/test_visualization_v2/test_explicit_chart_type.py`:

```python
class TestEndToEndExplicitHeatmap:
    """Full pipeline: user asks for heatmap → system produces heatmap."""

    @pytest.mark.asyncio
    async def test_heatmap_request_produces_heatmap_chart(self):
        """Reproduce the exact failing scenario from the bug report."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import (
            data_analyzer_node,
            spec_validator_node,
            _detect_explicit_chart_type,
            _rule_based_decision,
        )

        # This is the exact data shape from the failing state
        results = [
            {"CategoryName": "ESPRESSO", "Ay": "2025-12", "ToplamCiro": 2975597.967},
            {"CategoryName": "ESPRESSO", "Ay": "2026-01", "ToplamCiro": 51522465.1855},
            {"CategoryName": "ESPRESSO", "Ay": "2026-02", "ToplamCiro": 87212170.671},
            {"CategoryName": "CAYLAR", "Ay": "2025-12", "ToplamCiro": 700527.06},
            {"CategoryName": "CAYLAR", "Ay": "2026-01", "ToplamCiro": 10818175.6485},
            {"CategoryName": "CAYLAR", "Ay": "2026-02", "ToplamCiro": 19362311.808},
            {"CategoryName": "PASTALAR", "Ay": "2025-12", "ToplamCiro": 1137962.053},
            {"CategoryName": "PASTALAR", "Ay": "2026-01", "ToplamCiro": 12142220.20563},
            {"CategoryName": "PASTALAR", "Ay": "2026-02", "ToplamCiro": 20071334.934232},
        ]

        user_query = "Son 3 aydaki satislari karsilastir ve bunlar icinde hangi kategoriler ne kadar satmis onu da gosteren heatmap grafik ver"

        # Step 1: Detect explicit chart type
        explicit = _detect_explicit_chart_type(user_query)
        assert explicit == "heatmap"

        # Step 2: Get data profile
        state = {"results": results}
        analyzer_result = await data_analyzer_node(state)
        profile = analyzer_result["data_profile"]

        # Step 3: Rule-based decision with explicit override
        decision = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="monthly",
            comparison_dimension="CategoryName",
            explicit_chart_type=explicit,
        )
        assert decision is not None
        assert decision["chart_type"] == "heatmap"
        assert decision["series_field"] == "CategoryName"

        # Step 4: Validate spec
        full_state = {
            "results": results,
            "viz_decision": decision,
            "data_profile": profile,
        }
        validated_result = await spec_validator_node(full_state)
        validated = validated_result["viz_decision"]
        assert validated["chart_type"] == "heatmap", f"Expected heatmap, got {validated['chart_type']}"
        assert validated["series_field"] == "CategoryName"
        assert validated["x_field"] is not None
        assert validated["y_field"] is not None
```

- [ ] **Step 2: Run E2E test**

Run: `python -m pytest tests/test_visualization_v2/test_explicit_chart_type.py::TestEndToEndExplicitHeatmap -v`
Expected: PASS

- [ ] **Step 3: Run FULL test suite for visualization_v2**

Run: `python -m pytest tests/test_visualization_v2/ tests/test_viz_decider_fast_path.py tests/test_viz_v2_field_mapping.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_visualization_v2/test_explicit_chart_type.py
git commit -m "test: add E2E test for explicit heatmap request scenario"
```

---

## Summary of Changes

| File | Change | Lines Affected |
|------|--------|---------------|
| `visualization_v2/nodes.py` | Add `_detect_explicit_chart_type()` function | +45 lines (after line 30) |
| `visualization_v2/nodes.py` | Add `explicit_chart_type` param to `_rule_based_decision()` | Lines 130-151 modified |
| `visualization_v2/nodes.py` | Extract + pass explicit chart type in `viz_decider_node` | Lines 306-319 modified |
| `visualization_v2/validator.py` | Reorder rules: field completion before heatmap check | Lines 33-156 reordered |
| `tests/.../test_explicit_chart_type.py` | New: 20+ tests covering detection, override, validator, E2E | New file |

**Total: ~3 files modified, ~1 file created, ~100 lines of production code, ~200 lines of tests**
