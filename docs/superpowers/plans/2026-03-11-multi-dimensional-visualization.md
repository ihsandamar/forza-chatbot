# Multi-Dimensional Visualization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable heatmap and improved multi-dimensional chart routing (multi-line, sunburst/treemap) by propagating `comparison_dimension` from text2sql to the visualization layer and adding heatmap rendering support.

**Architecture:** Three-layer approach: (1) State propagation — carry `comparison_dimension` through ReportState → VisualizationState so the viz layer knows what the SQL entity dimension is, (2) Heatmap renderer — add `"heatmap"` to ChartSpec enum + Plotly `go.Heatmap` builder with pivot reshaping, (3) Semantic routing — upgrade viz_decider's rule-based path and LLM prompt so it picks the right chart type based on dimension count, time granularity, and user intent.

**Tech Stack:** Python 3.11, LangGraph, Pydantic, Plotly, pandas, pytest

---

## Semantic Intent → Chart Type Matrix

This is the core decision logic this plan implements:

| User intent pattern | query_type | comparison_dimension | time_granularity | Chart |
|---|---|---|---|---|
| "kategorilerdeki ciroyu karşılaştır" | COMPARISON | CategoryName | None | bar_chart (grouped) |
| "kategorilere göre haftalık ciro" | TIME_SERIES_COMPARISON | CategoryName | weekly | line_chart (multi-series) |
| "kategorilerin haftanın günlerine göre cirosu" | TIME_SERIES_COMPARISON | CategoryName | day_of_week | **heatmap** |
| "ürünlerin saate göre satışları heatmap" | TIME_SERIES_COMPARISON | ProductName | hour_of_day | **heatmap** |
| "kategoriler ve ürünlerin ciro dağılımı" | COMPARISON / RANKING | None (2 dim in group_by) | None | **sunburst** |
| "şube > kategori > ürün hiyerarşisi" | RANKING | None (3 dim in group_by) | None | **sunburst/treemap** |

**Key semantic rules:**
- entity + zaman trendi (haftalık/aylık/günlük) → multi-line chart (each entity = 1 line)
- entity + aggregate period (hour_of_day/day_of_week/day_of_month) → **heatmap** (x=period, y=entity, color=metric)
- 2+ non-time dimensions without time granularity → **sunburst/treemap** (hierarchical)
- explicit "heatmap" keyword from user → heatmap (override)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/graphs/report_agent/state.py` | Add `comparison_dimension` to ReportState |
| Modify | `src/graphs/report_agent/subagents/visualization_v2/state.py` | Add `comparison_dimension` to VisualizationState |
| Modify | `src/graphs/report_agent/subagents/text2sql/nodes.py:1186` | Return `comparison_dimension` from sql_generator_node |
| Modify | `src/graphs/report_agent/subagents/visualization_v2/models.py` | Add `"heatmap"` to ChartSpec.chart_type Literal |
| Modify | `src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py` | Add `_build_heatmap` + register in `_BUILDERS` |
| Modify | `src/graphs/report_agent/subagents/visualization_v2/validator.py` | Add Rule 3 heatmap validation (needs x+y+value) |
| Modify | `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Upgrade `_rule_based_decision` + aggregate period block |
| Modify | `src/graphs/report_agent/subagents/visualization_v2/prompts.py` | Add heatmap guidance to VIZ_DECIDER_PROMPT |
| Create | `tests/test_visualization_v2/test_heatmap_renderer.py` | Heatmap rendering unit tests |
| Create | `tests/test_visualization_v2/test_multidim_routing.py` | Multi-dimensional routing decision tests |
| Modify | `tests/test_visualization_v2/test_models.py` | Add heatmap ChartSpec validation test |

---

## Chunk 1: State Propagation — comparison_dimension

### Task 1: Add comparison_dimension to ReportState

**Files:**
- Modify: `src/graphs/report_agent/state.py:29` (after time_granularity)
- Test: existing `tests/graphs/report/test_graph_routing.py` — verify no breakage

- [ ] **Step 1: Write the failing test**

```python
# tests/test_visualization_v2/test_multidim_routing.py
"""Multi-dimensional visualization routing tests."""
import pytest


class TestComparisonDimensionPropagation:
    """comparison_dimension flows from text2sql → ReportState → VisualizationState."""

    def test_report_state_has_comparison_dimension_field(self):
        from src.graphs.report_agent.state import ReportState, create_initial_state
        state = create_initial_state()
        assert "comparison_dimension" in state
        assert state["comparison_dimension"] is None

    def test_visualization_state_accepts_comparison_dimension(self):
        from src.graphs.report_agent.subagents.visualization_v2.state import VisualizationState
        state: VisualizationState = {
            "results": [],
            "user_query": "test",
            "comparison_dimension": "CategoryName",
        }
        assert state["comparison_dimension"] == "CategoryName"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_visualization_v2/test_multidim_routing.py::TestComparisonDimensionPropagation -v`
Expected: FAIL — `comparison_dimension` not in state

- [ ] **Step 3: Add comparison_dimension to ReportState**

In `src/graphs/report_agent/state.py`, after line 29 (`time_granularity`):

```python
    comparison_dimension: Optional[str]   # text2sql → viz subgraph (DB column: "CategoryName", "ProductName" etc.)
```

In `create_initial_state()`, add:
```python
        comparison_dimension=None,
```

- [ ] **Step 4: Add comparison_dimension to VisualizationState**

In `src/graphs/report_agent/subagents/visualization_v2/state.py`, after line 20 (`time_granularity`):

```python
    comparison_dimension: Optional[str]  # from text2sql, entity column for multi-dim charts
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_visualization_v2/test_multidim_routing.py::TestComparisonDimensionPropagation -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/state.py src/graphs/report_agent/subagents/visualization_v2/state.py tests/test_visualization_v2/test_multidim_routing.py
git commit -m "feat: add comparison_dimension to ReportState and VisualizationState"
```

---

### Task 2: Propagate comparison_dimension from sql_generator_node

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1186`
- Test: `tests/test_visualization_v2/test_multidim_routing.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_visualization_v2/test_multidim_routing.py`:

```python
class TestSqlGeneratorPropagation:
    """sql_generator_node returns comparison_dimension in state output."""

    def test_return_dict_includes_comparison_dimension_key(self):
        """Verify the return dict structure includes comparison_dimension.

        We can't easily unit-test the full node (needs LLM + DB), so we test
        that the state key exists in text2sql state definition.
        """
        from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
        # Text2SQLState must have comparison_dimension for the output to propagate
        import typing
        hints = typing.get_type_hints(Text2SQLState)
        assert "comparison_dimension" in hints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_visualization_v2/test_multidim_routing.py::TestSqlGeneratorPropagation -v`
Expected: FAIL — `comparison_dimension` not in Text2SQLState

- [ ] **Step 3: Add comparison_dimension to Text2SQLState**

Read `src/graphs/report_agent/subagents/text2sql/state.py` and add after `time_granularity`:

```python
    comparison_dimension: Optional[str]   # sql_generator → parent ReportState → viz
```

- [ ] **Step 4: Modify sql_generator_node return to include comparison_dimension**

In `src/graphs/report_agent/subagents/text2sql/nodes.py:1186`, change:

```python
# BEFORE (line 1186):
            return {"sql_queries": [sql], "time_granularity": _time_gran}

# AFTER:
            return {
                "sql_queries": [sql],
                "time_granularity": _time_gran,
                "comparison_dimension": _comp_dim if state.get("query_type") == "TIME_SERIES_COMPARISON" else raw_schema.get("comparison_dimension"),
            }
```

Note: `_comp_dim` is already computed at line 1112 for TIME_SERIES_COMPARISON queries. For other query types, fall back to the raw schema value.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_visualization_v2/test_multidim_routing.py -v && pytest tests/unit/test_aggregate_period_granularity.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/state.py src/graphs/report_agent/subagents/text2sql/nodes.py tests/test_visualization_v2/test_multidim_routing.py
git commit -m "feat: propagate comparison_dimension from sql_generator to viz layer"
```

---

## Chunk 2: Heatmap Renderer

### Task 3: Add heatmap to ChartSpec enum

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/models.py:16-20`
- Test: `tests/test_visualization_v2/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_visualization_v2/test_models.py`:

```python
def test_chartspec_valid_heatmap():
    spec = ChartSpec(
        needs_graph=True,
        chart_type="heatmap",
        x_field="HaftaGunu",
        y_field="ToplamCiro",
        series_field="CategoryName",
        reason="2D distribution",
    )
    assert spec.chart_type == "heatmap"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_visualization_v2/test_models.py::test_chartspec_valid_heatmap -v`
Expected: FAIL — Pydantic validation error ("heatmap" not in Literal)

- [ ] **Step 3: Add "heatmap" to ChartSpec.chart_type**

In `src/graphs/report_agent/subagents/visualization_v2/models.py:16-20`, change:

```python
    chart_type: Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "single_value", "simple_list", "table",
        "comparison", "sunburst", "treemap",
        "heatmap",
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_visualization_v2/test_models.py -v`
Expected: ALL PASS (including new test)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/models.py tests/test_visualization_v2/test_models.py
git commit -m "feat: add heatmap to ChartSpec chart_type enum"
```

---

### Task 4: Implement _build_heatmap renderer

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py`
- Create: `tests/test_visualization_v2/test_heatmap_renderer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_visualization_v2/test_heatmap_renderer.py
"""Heatmap chart renderer tests."""
import pytest
from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart


@pytest.fixture
def heatmap_results():
    """Category × DayOfWeek cross-tabulation data (flat rows)."""
    return [
        {"CategoryName": "Dürümler", "HaftaGunu": 1, "ToplamCiro": 5000},
        {"CategoryName": "Dürümler", "HaftaGunu": 2, "ToplamCiro": 6000},
        {"CategoryName": "Dürümler", "HaftaGunu": 3, "ToplamCiro": 5500},
        {"CategoryName": "İçecekler", "HaftaGunu": 1, "ToplamCiro": 2000},
        {"CategoryName": "İçecekler", "HaftaGunu": 2, "ToplamCiro": 2500},
        {"CategoryName": "İçecekler", "HaftaGunu": 3, "ToplamCiro": 3000},
        {"CategoryName": "Tatlılar", "HaftaGunu": 1, "ToplamCiro": 1000},
        {"CategoryName": "Tatlılar", "HaftaGunu": 2, "ToplamCiro": 1200},
        {"CategoryName": "Tatlılar", "HaftaGunu": 3, "ToplamCiro": 1100},
    ]


@pytest.fixture
def hour_product_results():
    """Product × HourOfDay data."""
    return [
        {"ProductName": "Latte", "Saat": h, "ToplamCiro": 100 + h * 10}
        for h in range(8, 12)
    ] + [
        {"ProductName": "Espresso", "Saat": h, "ToplamCiro": 80 + h * 5}
        for h in range(8, 12)
    ]


class TestHeatmapRenderer:

    def test_heatmap_basic_renders_html(self, heatmap_results):
        """Heatmap with series_field (y-axis entity) + x_field (period) + y_field (metric)."""
        spec = {
            "chart_type": "heatmap",
            "needs_graph": True,
            "x_field": "HaftaGunu",
            "y_field": "ToplamCiro",
            "series_field": "CategoryName",
            "title": "Kategori × Hafta Günü Ciro",
        }
        html = render_chart(spec, heatmap_results, {})
        assert html is not None
        assert "plotly" in html.lower()

    def test_heatmap_with_hour_product(self, hour_product_results):
        """Heatmap: product × hour."""
        spec = {
            "chart_type": "heatmap",
            "needs_graph": True,
            "x_field": "Saat",
            "y_field": "ToplamCiro",
            "series_field": "ProductName",
            "title": "Ürün × Saat Ciro",
        }
        html = render_chart(spec, hour_product_results, {})
        assert html is not None

    def test_heatmap_empty_results_returns_none(self):
        spec = {
            "chart_type": "heatmap",
            "needs_graph": True,
            "x_field": "HaftaGunu",
            "y_field": "ToplamCiro",
            "series_field": "CategoryName",
        }
        result = render_chart(spec, [], {})
        assert result is None

    def test_heatmap_missing_series_falls_back(self, heatmap_results):
        """Without series_field, heatmap can't pivot — should return None (validator catches this)."""
        spec = {
            "chart_type": "heatmap",
            "needs_graph": True,
            "x_field": "HaftaGunu",
            "y_field": "ToplamCiro",
            "series_field": None,
        }
        result = render_chart(spec, heatmap_results, {})
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_visualization_v2/test_heatmap_renderer.py -v`
Expected: FAIL — `"heatmap"` not in `_BUILDERS`

- [ ] **Step 3: Implement _build_heatmap**

In `src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py`, add the builder function before the `_BUILDERS` dict:

```python
def _build_heatmap(df: pd.DataFrame, spec: dict) -> go.Figure:
    """
    Build a heatmap from flat rows by pivoting.

    Expects:
        x_field: period/category column (becomes x-axis)
        series_field: entity column (becomes y-axis rows)
        y_field: metric column (becomes cell color values)

    Flat data like:
        CategoryName | HaftaGunu | ToplamCiro
        Dürümler     | 1         | 5000
        İçecekler    | 1         | 2000
    Gets pivoted to:
                  HaftaGunu=1  HaftaGunu=2  ...
        Dürümler    5000         6000
        İçecekler   2000         2500
    """
    x = spec.get("x_field")
    y_metric = spec.get("y_field")
    entity = spec.get("series_field")
    title = spec.get("title") or ""

    if not entity or not x or not y_metric:
        return None

    try:
        pivot = df.pivot_table(
            index=entity,
            columns=x,
            values=y_metric,
            aggfunc="sum",
        ).fillna(0)
    except (KeyError, ValueError):
        return None

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=[str(c) for c in pivot.columns],
        y=[str(r) for r in pivot.index],
        colorscale="YlOrRd",
        hoverongaps=False,
        hovertemplate="%{y}<br>%{x}<br>Değer: %{z:,.0f}<extra></extra>",
    ))
    fig.update_layout(title=title)
    return fig
```

Register in `_BUILDERS`:
```python
_BUILDERS = {
    "bar_chart": _build_bar,
    "line_chart": _build_line,
    "pie_chart": _build_pie,
    "scatter_chart": _build_scatter,
    "scatter": _build_scatter,
    "sunburst": _build_sunburst,
    "treemap": _build_treemap,
    "comparison": _build_comparison,
    "heatmap": _build_heatmap,
}
```

- [ ] **Step 4: Handle None return from _build_heatmap in render_chart**

The existing `render_chart` function at line 49 calls `_BUILDERS[chart_type](df, spec)` and expects a `go.Figure`. If `_build_heatmap` returns `None` (missing fields), the subsequent `_apply_labels(fig, ...)` call will crash. Add a None guard **immediately after** `fig = _BUILDERS[chart_type](df, spec)` and **before** any `_apply_*` calls:

```python
        fig = _BUILDERS[chart_type](df, spec)
        if fig is None:
            return None
        fig = _apply_labels(fig, spec, column_metadata)
        # ... rest unchanged
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_visualization_v2/test_heatmap_renderer.py -v && pytest tests/test_visualization_v2/test_chart_renderer.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py tests/test_visualization_v2/test_heatmap_renderer.py
git commit -m "feat: implement heatmap chart renderer with pivot reshaping"
```

---

### Task 5: Add heatmap validation rule

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/validator.py:66-90` (Rule 3 block)
- Test: `tests/test_visualization_v2/test_validator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_visualization_v2/test_validator.py`:

```python
def test_rule3_heatmap_without_series_falls_to_bar():
    """Heatmap requires series_field for pivot; without it, fall back to bar_chart."""
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    spec = {
        "needs_graph": True,
        "chart_type": "heatmap",
        "x_field": "HaftaGunu",
        "y_field": "ToplamCiro",
        "series_field": None,
    }
    results = [
        {"HaftaGunu": 1, "ToplamCiro": 5000},
        {"HaftaGunu": 2, "ToplamCiro": 6000},
    ]
    profile = {
        "dimension_columns": ["HaftaGunu"],
        "metric_columns": ["ToplamCiro"],
        "time_column": None,
        "columns": [
            {"name": "HaftaGunu", "role": "time", "type": "int"},
            {"name": "ToplamCiro", "role": "metric", "type": "float"},
        ],
    }
    validated = validate_spec(spec, results, profile)
    assert validated["chart_type"] == "bar_chart"


def test_rule3_heatmap_with_series_stays_heatmap():
    """Heatmap with all required fields passes validation."""
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    spec = {
        "needs_graph": True,
        "chart_type": "heatmap",
        "x_field": "HaftaGunu",
        "y_field": "ToplamCiro",
        "series_field": "CategoryName",
    }
    results = [
        {"CategoryName": "Dürümler", "HaftaGunu": 1, "ToplamCiro": 5000},
        {"CategoryName": "İçecekler", "HaftaGunu": 1, "ToplamCiro": 2000},
    ]
    profile = {
        "dimension_columns": ["CategoryName", "HaftaGunu"],
        "metric_columns": ["ToplamCiro"],
        "time_column": None,
        "columns": [
            {"name": "CategoryName", "role": "dimension", "type": "str"},
            {"name": "HaftaGunu", "role": "time", "type": "int"},
            {"name": "ToplamCiro", "role": "metric", "type": "float"},
        ],
    }
    validated = validate_spec(spec, results, profile)
    assert validated["chart_type"] == "heatmap"
    assert validated["series_field"] == "CategoryName"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_visualization_v2/test_validator.py::test_rule3_heatmap_without_series_falls_to_bar -v`
Expected: FAIL — no heatmap validation rule, stays "heatmap"

- [ ] **Step 3: Add heatmap validation to Rule 3 block**

In `src/graphs/report_agent/subagents/visualization_v2/validator.py`, after the scatter_chart Rule 3 block (after line 90), add:

```python
    if chart_type == "heatmap":
        if not spec.get("series_field"):
            spec["chart_type"] = "bar_chart"
            logger.info("[VALIDATOR] Rule 3: heatmap without series_field -> bar_chart")
```

Also add `"heatmap"` to the `_SERIES_COMPATIBLE` set in Rule 6 (line 124) so series_field auto-fill works for heatmap too:

```python
    _SERIES_COMPATIBLE = {"line_chart", "bar_chart", "comparison", "scatter_chart", "heatmap"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_visualization_v2/test_validator.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/validator.py tests/test_visualization_v2/test_validator.py
git commit -m "feat: add heatmap validation rule (requires series_field for pivot)"
```

---

## Chunk 3: Semantic Chart Routing

### Task 6: Upgrade viz_decider rule-based decision

This is the core routing logic. The current `_rule_based_decision` and aggregate period block need to use `comparison_dimension` for smarter decisions.

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py:130-195` (rule-based) and `261-272` (aggregate period)
- Test: `tests/test_visualization_v2/test_multidim_routing.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_visualization_v2/test_multidim_routing.py`:

```python
class TestAggregateWithEntity:
    """Aggregate period + comparison_dimension → heatmap instead of bar_chart."""

    def test_aggregate_period_with_entity_returns_heatmap(self):
        """day_of_week + CategoryName → heatmap (entity × period matrix)."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

        profile = {
            "row_count": 21,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": ["CategoryName"],
            "time_column": "HaftaGunu",
            "has_multiple_dimensions": True,
        }
        # We need to test the viz_decider_node directly since aggregate period
        # is handled before _rule_based_decision. But the logic will move into
        # _rule_based_decision. So test _rule_based_decision with new params.
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="day_of_week",
            comparison_dimension="CategoryName",
        )
        assert result is not None
        assert result["chart_type"] == "heatmap"
        assert result["x_field"] == "HaftaGunu"
        assert result["series_field"] == "CategoryName"

    def test_aggregate_period_without_entity_stays_bar(self):
        """day_of_week without entity → bar_chart (simple distribution)."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

        profile = {
            "row_count": 7,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": [],
            "time_column": "HaftaGunu",
            "has_multiple_dimensions": False,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="day_of_week",
            comparison_dimension=None,
        )
        assert result is not None
        assert result["chart_type"] == "bar_chart"
        assert result["x_field"] == "HaftaGunu"


class TestTimeSeriesWithEntity:
    """TIME_SERIES_COMPARISON + entity → multi-line chart."""

    def test_weekly_with_entity_returns_line_with_series(self):
        """weekly + CategoryName → line_chart with series_field."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

        profile = {
            "row_count": 40,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": ["CategoryName"],
            "time_column": "Hafta",
            "has_multiple_dimensions": True,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="weekly",
            comparison_dimension="CategoryName",
        )
        assert result is not None
        assert result["chart_type"] == "line_chart"
        assert result["series_field"] == "CategoryName"

    def test_monthly_without_entity_returns_simple_line(self):
        """monthly without entity → line_chart, no series_field."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

        profile = {
            "row_count": 12,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": [],
            "time_column": "Ay",
            "has_multiple_dimensions": False,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="monthly",
            comparison_dimension=None,
        )
        assert result is not None
        assert result["chart_type"] == "line_chart"
        assert result["series_field"] is None


class TestMultiDimensionHierarchy:
    """2+ non-time dimensions without time → sunburst."""

    def test_two_dimensions_no_time_returns_sunburst(self):
        """CategoryName + ProductName → sunburst (hierarchy)."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

        profile = {
            "row_count": 50,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": ["CategoryName", "ProductName"],
            "time_column": None,
            "has_multiple_dimensions": True,
        }
        result = _rule_based_decision(
            query_type="COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity=None,
            comparison_dimension=None,
        )
        assert result is not None
        assert result["chart_type"] == "sunburst"
        assert result["hierarchy_fields"] == ["CategoryName", "ProductName"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_visualization_v2/test_multidim_routing.py::TestAggregateWithEntity -v`
Expected: FAIL — `_rule_based_decision()` doesn't accept `time_granularity`/`comparison_dimension`

- [ ] **Step 3: Refactor _rule_based_decision signature**

In `src/graphs/report_agent/subagents/visualization_v2/nodes.py`, modify `_rule_based_decision` (line 130) to accept new parameters:

```python
def _rule_based_decision(
    query_type: str,
    wants_viz: bool,
    profile: dict,
    time_granularity: Optional[str] = None,
    comparison_dimension: Optional[str] = None,
) -> Optional[dict]:
    """
    Deterministic chart type selection.
    Uses time_granularity + comparison_dimension for smarter multi-dim routing.
    Returns None → LLM fallback.
    """
    if not wants_viz:
        return None

    metric_cols = profile.get("metric_columns", [])
    time_col = profile.get("time_column")
    dim_cols = profile.get("dimension_columns", [])
    row_count = profile.get("row_count", 0)

    if not metric_cols:
        return None

    if query_type == "LISTING":
        return {
            "needs_graph": False, "chart_type": "table",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "LISTING -> table",
        }

    if query_type == "SINGLE" and row_count == 1 and len(metric_cols) == 1:
        return {
            "needs_graph": False, "chart_type": "single_value",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Single value result",
        }

    # --- AGGREGATE PERIOD routing (hour_of_day, day_of_week, day_of_month) ---
    _AGG_X_FIELD_MAP = {"hour_of_day": "Saat", "day_of_week": "HaftaGunu", "day_of_month": "AyinGunu"}
    if time_granularity and time_granularity in AGGREGATE_PERIOD_GRANULARITIES:
        x_field = _AGG_X_FIELD_MAP.get(time_granularity)
        if comparison_dimension:
            # entity × period → heatmap
            return {
                "needs_graph": True, "chart_type": "heatmap",
                "x_field": x_field, "y_field": None,
                "series_field": comparison_dimension,
                "reason": f"Aggregate period ({time_granularity}) + entity ({comparison_dimension}) -> heatmap",
            }
        else:
            # simple period distribution → bar_chart
            return {
                "needs_graph": True, "chart_type": "bar_chart",
                "x_field": x_field, "y_field": None,
                "series_field": None,
                "reason": f"Aggregate period distribution ({time_granularity})",
            }

    # --- TIME_SERIES_COMPARISON routing ---
    if query_type == "TIME_SERIES_COMPARISON":
        if comparison_dimension:
            # entity + time trend → multi-line (each entity = 1 line)
            return {
                "needs_graph": True, "chart_type": "line_chart",
                "x_field": None, "y_field": None,
                "series_field": comparison_dimension,
                "reason": f"Time series + entity ({comparison_dimension}) -> multi-line",
            }
        has_dims = len(dim_cols) >= 1
        if has_dims:
            # Dimension columns exist but comparison_dimension wasn't set by text2sql.
            # Fall back to LLM for correct field mapping.
            return None
        # simple time series (no entity)
        return {
            "needs_graph": True, "chart_type": "line_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Simple time series -> line chart",
        }

    if query_type == "TIME_SERIES":
        return {
            "needs_graph": True, "chart_type": "line_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Time series -> line chart",
        }

    # --- COMPARISON / RANKING with multiple dimensions → sunburst ---
    if query_type in ("COMPARISON", "RANKING") and len(dim_cols) >= 2 and not time_col:
        return {
            "needs_graph": True, "chart_type": "sunburst",
            "x_field": None, "y_field": None, "series_field": None,
            "hierarchy_fields": dim_cols[:3],  # max 3 levels
            "reason": f"Multi-dimension hierarchy ({dim_cols[:3]}) -> sunburst",
        }

    if query_type == "RANKING":
        return {
            "needs_graph": True, "chart_type": "bar_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Ranking -> bar chart",
        }

    if query_type == "COMPARISON":
        return {
            "needs_graph": True, "chart_type": "bar_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Comparison -> bar chart",
        }

    return None
```

- [ ] **Step 4: Update viz_decider_node to pass new params**

In `viz_decider_node` (line 239-328), update the call site. Remove the standalone aggregate period block (lines 261-272) since it's now inside `_rule_based_decision`, and pass the new params:

```python
        # Replace lines 261-282 with:
        _time_gran = state.get("time_granularity")
        _comp_dim = state.get("comparison_dimension")

        # Rule-based fast path (includes aggregate period routing)
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

- [ ] **Step 5: Fix existing tests that call _rule_based_decision**

The existing tests in `tests/test_visualization_v2/test_nodes.py` call `_rule_based_decision` with the old signature (3 positional args). The new params have defaults, so positional calls still work. However, verify that the **behavioral change** doesn't break existing expectations:

**IMPORTANT**: The refactored function removes the LLM fallback for `TIME_SERIES_COMPARISON` when `comparison_dimension=None`. Previously, `has_multi_dim or dim_count >= 1` returned `None` (LLM fallback). Now it returns a simple `line_chart`. This is acceptable because the validator (Rule 4 + Rule 6) fills in missing fields. But if `comparison_dimension` is not set by text2sql, multi-entity queries get a simple line chart instead of a multi-series one. This is the correct fallback — the LLM path remains available for truly ambiguous cases via `return None` at the function end.

Note: `tests/test_viz_decider_fast_path.py` imports from the v1 `visualization` module (`_rule_based_viz_decision`), NOT from v2 `_rule_based_decision`. It is unaffected by this change.

Run: `pytest tests/test_visualization_v2/test_nodes.py -v`

If any fail, verify the expected behavior matches the new routing logic.

- [ ] **Step 6: Run all routing tests**

Run: `pytest tests/test_visualization_v2/test_multidim_routing.py -v && pytest tests/test_visualization_v2/test_nodes.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py tests/test_visualization_v2/test_multidim_routing.py
git commit -m "feat: semantic chart routing with comparison_dimension (heatmap, multi-line, sunburst)"
```

---

### Task 7: Update VIZ_DECIDER_PROMPT with heatmap guidance

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/prompts.py`

- [ ] **Step 1: Update the prompt**

In `src/graphs/report_agent/subagents/visualization_v2/prompts.py`, add heatmap to chart_type selection (after line 61 "treemap/agac harita" → treemap):

```python
- "heatmap/ısı haritası" → heatmap
```

Update the "Belirtmemisse veri profiline gore" section (after line 70 "2+ dimension hiyerarsi"):

```python
- Entity + toplu dağılım (hour_of_day/day_of_week/day_of_month) → heatmap
```

Add a new section after the Aggregate Period rules (after line 81):

```python
### 🗺️ HEATMAP KURALLARI
- Heatmap = İKİ boyutlu matris görselleştirmesi (satır × sütun → renk yoğunluğu)
- ZORUNLU ALANLAR: x_field (periyod/kategori), series_field (entity), y_field (metrik)
- Tipik kullanım: entity × zaman periyodu matrisi
  → "kategorilerin haftanın günlerine göre cirosu" → x_field="HaftaGunu", series_field="CategoryName"
  → "ürünlerin saatlere göre satışları" → x_field="Saat", series_field="ProductName"
- Kullanıcı "heatmap" veya "ısı haritası" derse → chart_type="heatmap"
- 2 boyut + 1 metrik + toplu dağılım periyodu varsa heatmap öner
```

- [ ] **Step 2: Run LLM-dependent tests (if any)**

Run: `pytest tests/test_visualization_v2/ -v`
Expected: ALL PASS (prompt changes don't break unit tests)

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/prompts.py
git commit -m "feat: add heatmap guidance to VIZ_DECIDER_PROMPT"
```

---

### Task 8: Update intent classifier prompt for heatmap keyword

**Files:**
- Modify: `src/graphs/report_agent/prompts.py:134-140` (wants_visualization section)

- [ ] **Step 1: Add "heatmap" and "ısı haritası" to wants_visualization triggers**

In `src/graphs/report_agent/prompts.py`, line 136, update the trigger words:

```python
  → "grafik", "chart", "çizgi grafik", "bar", "pasta", "görselleştir", "diyagram", "şekil olarak göster", "heatmap", "ısı haritası", "sunburst", "treemap" gibi ifadeler içeriyorsa
```

- [ ] **Step 2: Run existing intent tests**

Run: `pytest tests/graphs/report/test_graph_routing.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/prompts.py
git commit -m "feat: add heatmap/sunburst/treemap keywords to wants_visualization triggers"
```

---

## Chunk 4: Integration Verification

### Task 9: End-to-end integration test

**Files:**
- Create: `tests/integration/test_multidim_viz_e2e.py`

- [ ] **Step 1: Write integration test**

```python
# tests/integration/test_multidim_viz_e2e.py
"""
End-to-end integration tests for multi-dimensional visualization routing.
Tests the full pipeline: state → data_analyzer → viz_decider → validator → renderer.
No LLM calls — uses rule-based path only.
"""
import pytest
from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
from src.graphs.report_agent.subagents.text2sql.nodes import AGGREGATE_PERIOD_GRANULARITIES


class TestHeatmapEndToEnd:
    """Category × DayOfWeek → heatmap pipeline."""

    @pytest.fixture
    def category_dayofweek_data(self):
        """Simulates SQL output: CategoryName × HaftaGunu × ToplamCiro."""
        rows = []
        categories = ["Dürümler", "İçecekler", "Tatlılar"]
        for cat in categories:
            for day in range(1, 8):
                rows.append({
                    "CategoryName": cat,
                    "HaftaGunu": day,
                    "ToplamCiro": 1000 + day * 100 + hash(cat) % 500,
                })
        return rows

    def test_full_pipeline_produces_heatmap_html(self, category_dayofweek_data):
        # Step 1: Analyze data
        analyzer = DataAnalyzer()
        profile_state = analyzer.analyze({"raw_data": category_dayofweek_data})
        profile = profile_state["data_profile"]

        # Step 2: Rule-based decision
        decision = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="day_of_week",
            comparison_dimension="CategoryName",
        )
        assert decision is not None
        assert decision["chart_type"] == "heatmap"

        # Step 3: Validate spec
        validated = validate_spec(decision, category_dayofweek_data, profile)
        assert validated["chart_type"] == "heatmap"
        assert validated["series_field"] == "CategoryName"

        # Step 4: Render
        html = render_chart(validated, category_dayofweek_data, {})
        assert html is not None
        assert "plotly" in html.lower()
        assert len(html) > 100


class TestMultiLineEndToEnd:
    """Category × weekly → multi-line chart pipeline."""

    @pytest.fixture
    def category_weekly_data(self):
        rows = []
        for cat in ["Dürümler", "İçecekler"]:
            for week in range(1, 5):
                rows.append({
                    "CategoryName": cat,
                    "Yil": 2026,
                    "Hafta": week,
                    "ToplamCiro": 5000 + week * 200,
                })
        return rows

    def test_full_pipeline_produces_multiline(self, category_weekly_data):
        analyzer = DataAnalyzer()
        profile_state = analyzer.analyze({"raw_data": category_weekly_data})
        profile = profile_state["data_profile"]

        decision = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="weekly",
            comparison_dimension="CategoryName",
        )
        assert decision is not None
        assert decision["chart_type"] == "line_chart"
        assert decision["series_field"] == "CategoryName"

        validated = validate_spec(decision, category_weekly_data, profile)
        assert validated["chart_type"] == "line_chart"

        html = render_chart(validated, category_weekly_data, {})
        assert html is not None


class TestSunburstEndToEnd:
    """Category + Product hierarchy → sunburst pipeline."""

    @pytest.fixture
    def hierarchy_data(self):
        return [
            {"CategoryName": "Dürümler", "ProductName": "Tavuk Dürüm", "ToplamCiro": 15000},
            {"CategoryName": "Dürümler", "ProductName": "Et Dürüm", "ToplamCiro": 12000},
            {"CategoryName": "İçecekler", "ProductName": "Kola", "ToplamCiro": 8000},
            {"CategoryName": "İçecekler", "ProductName": "Ayran", "ToplamCiro": 5000},
            {"CategoryName": "Tatlılar", "ProductName": "Künefe", "ToplamCiro": 6000},
        ]

    def test_full_pipeline_produces_sunburst(self, hierarchy_data):
        analyzer = DataAnalyzer()
        profile_state = analyzer.analyze({"raw_data": hierarchy_data})
        profile = profile_state["data_profile"]

        decision = _rule_based_decision(
            query_type="COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity=None,
            comparison_dimension=None,
        )
        assert decision is not None
        assert decision["chart_type"] == "sunburst"
        assert "CategoryName" in decision["hierarchy_fields"]
        assert "ProductName" in decision["hierarchy_fields"]

        validated = validate_spec(decision, hierarchy_data, profile)
        html = render_chart(validated, hierarchy_data, {})
        assert html is not None
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/integration/test_multidim_viz_e2e.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run full test suite to verify no regressions**

Run: `pytest tests/ -v --timeout=60`
Expected: ALL PASS (or only pre-existing failures)

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_multidim_viz_e2e.py
git commit -m "test: add end-to-end integration tests for heatmap, multi-line, sunburst"
```

---

## Summary of Changes

| File | Change | Lines affected |
|------|--------|---------------|
| `state.py` (report_agent) | Add `comparison_dimension` field | +2 lines |
| `state.py` (visualization_v2) | Add `comparison_dimension` field | +1 line |
| `state.py` (text2sql) | Add `comparison_dimension` field | +1 line |
| `nodes.py` (text2sql) | Return `comparison_dimension` in output | ~3 lines changed |
| `models.py` (visualization_v2) | Add `"heatmap"` to Literal | +1 line |
| `chart_renderer.py` | Add `_build_heatmap` + register + None guard | ~35 lines added |
| `validator.py` | Heatmap Rule 3 + add to _SERIES_COMPATIBLE | ~4 lines added |
| `nodes.py` (visualization_v2) | Refactor `_rule_based_decision` + consolidate aggregate routing | ~60 lines changed |
| `prompts.py` (visualization_v2) | Heatmap guidance section | ~10 lines added |
| `prompts.py` (report_agent) | Heatmap/sunburst keywords in wants_visualization | ~1 line changed |

**Total: ~120 lines of production code changed/added across 10 files**

No existing functionality is removed. All changes are additive or refinements of existing routing logic. The `_rule_based_decision` refactor consolidates the aggregate period handling (previously in `viz_decider_node` body) into the function, making it testable.
