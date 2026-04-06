# Visualization V2 Subagent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Yeni visualization subagent: LLM sadece JSON config uretir, deterministic template engine grafik cizer, exec() tamamen kaldirilir.

**Architecture:** Iki katmanli ayrim — Karar Katmani (LLM + rules + validator) ve Cizim Katmani (template engine, pure Plotly API). Yeni kod `visualization_v2/` dizinine yazilir, eski korunur. Entegrasyon son adimda tek import degisikligi ile yapilir.

**Tech Stack:** Python 3.12, Pydantic v2, Plotly Express/Graph Objects, LangGraph StateGraph, rapidfuzz, pytest

---

### Task 1: ChartSpec Model ve State

**Files:**
- Create: `src/graphs/report_agent/subagents/visualization_v2/__init__.py`
- Create: `src/graphs/report_agent/subagents/visualization_v2/models.py`
- Create: `src/graphs/report_agent/subagents/visualization_v2/state.py`
- Test: `tests/test_visualization_v2/test_models.py`

**Step 1: Create directory and __init__.py**

```bash
mkdir -p src/graphs/report_agent/subagents/visualization_v2
mkdir -p tests/test_visualization_v2
```

Create empty `__init__.py`:
```python
# src/graphs/report_agent/subagents/visualization_v2/__init__.py
```

Create empty `tests/test_visualization_v2/__init__.py`.

**Step 2: Write failing test for ChartSpec**

```python
# tests/test_visualization_v2/test_models.py
"""ChartSpec model validation tests."""
import pytest
from pydantic import ValidationError


def test_chartspec_valid_bar():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=True,
        chart_type="bar_chart",
        x_field="BranchName",
        y_field="RowAmount",
        reason="Bar chart for branch comparison",
    )
    assert spec.chart_type == "bar_chart"
    assert spec.x_field == "BranchName"
    assert spec.orientation is None


def test_chartspec_valid_multi_metric():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=True,
        chart_type="bar_chart",
        x_field="BranchName",
        y_fields=["RowAmount", "Quantity"],
        reason="Multi metric bar",
    )
    assert spec.y_fields == ["RowAmount", "Quantity"]
    assert spec.y_field is None


def test_chartspec_valid_no_graph():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=False,
        chart_type="table",
        reason="Table display",
    )
    assert spec.needs_graph is False
    assert spec.x_field is None


def test_chartspec_invalid_chart_type():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    with pytest.raises(ValidationError):
        ChartSpec(
            needs_graph=True,
            chart_type="invalid_type",
            reason="should fail",
        )


def test_chartspec_hierarchy_fields():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=True,
        chart_type="sunburst",
        hierarchy_fields=["CategoryName", "ProductName"],
        y_field="RowAmount",
        reason="Sunburst hierarchy",
    )
    assert spec.hierarchy_fields == ["CategoryName", "ProductName"]


def test_chartspec_sort_and_topn():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=True,
        chart_type="bar_chart",
        x_field="ProductName",
        y_field="RowAmount",
        sort_by="RowAmount",
        sort_order="desc",
        top_n=10,
        reason="Top 10 products",
    )
    assert spec.sort_order == "desc"
    assert spec.top_n == 10
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/test_visualization_v2/test_models.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 4: Write models.py**

```python
# src/graphs/report_agent/subagents/visualization_v2/models.py
"""
Visualization V2 — Data Models

ChartSpec: LLM veya rule-based path'in urettigi chart specification.
Validator'dan gectikten sonra template engine'e gider.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel


class ChartSpec(BaseModel):
    """Chart specification — LLM/rule-based cikti, validator girdisi."""

    needs_graph: bool
    chart_type: Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "single_value", "simple_list", "table",
        "comparison", "sunburst", "treemap",
    ]

    # Field mapping
    x_field: Optional[str] = None
    y_field: Optional[str] = None
    y_fields: Optional[List[str]] = None
    series_field: Optional[str] = None
    hierarchy_fields: Optional[List[str]] = None

    # Visual control
    title: Optional[str] = None
    orientation: Optional[Literal["v", "h"]] = None
    sort_by: Optional[str] = None
    sort_order: Optional[Literal["asc", "desc"]] = None
    top_n: Optional[int] = None

    reason: str
```

**Step 5: Write state.py**

```python
# src/graphs/report_agent/subagents/visualization_v2/state.py
"""
Visualization V2 — State Definition

VisualizationState: LangGraph shared-state pattern ile parent ReportState'e baglanir.
Mevcut v1 state ile ayni key'ler — parent uyumlu.
"""
from typing import Any, Dict, List, Optional, TypedDict


class VisualizationState(TypedDict, total=False):
    # --- ReportState overlapping (auto-sync) ---
    results: Optional[List[Dict[str, Any]]]
    user_query: str
    viz_request: Optional[str]
    query_type: Optional[str]
    wants_visualization: Optional[bool]
    visualization_output: Optional[Dict[str, Any]]
    error: Optional[str]

    # --- Internal ---
    data_profile: Optional[Dict[str, Any]]
    viz_decision: Optional[Dict[str, Any]]  # ChartSpec.model_dump()
    plotly_html_snippet: Optional[str]
```

**Step 6: Run tests**

Run: `pytest tests/test_visualization_v2/test_models.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/__init__.py \
        src/graphs/report_agent/subagents/visualization_v2/models.py \
        src/graphs/report_agent/subagents/visualization_v2/state.py \
        tests/test_visualization_v2/__init__.py \
        tests/test_visualization_v2/test_models.py
git commit -m "feat(viz-v2): add ChartSpec model and state definition"
```

---

### Task 2: Spec Validator

**Files:**
- Create: `src/graphs/report_agent/subagents/visualization_v2/validator.py`
- Test: `tests/test_visualization_v2/test_validator.py`

**Step 1: Write failing tests**

```python
# tests/test_visualization_v2/test_validator.py
"""ChartSpec validator tests — 5 validation rules."""
import pytest


@pytest.fixture
def sample_profile():
    return {
        "row_count": 5,
        "column_count": 3,
        "columns": [
            {"name": "BranchName", "role": "dimension", "type": "text"},
            {"name": "RowAmount", "role": "metric", "type": "numeric"},
            {"name": "DocumentDate", "role": "time", "type": "date"},
        ],
        "dimension_columns": ["BranchName"],
        "metric_columns": ["RowAmount"],
        "time_column": "DocumentDate",
        "has_time_series": True,
        "has_multiple_dimensions": False,
        "is_aggregated": True,
    }


@pytest.fixture
def sample_results():
    return [
        {"BranchName": "Istanbul", "RowAmount": 50000, "DocumentDate": "2026-01-15"},
        {"BranchName": "Ankara", "RowAmount": 35000, "DocumentDate": "2026-01-15"},
        {"BranchName": "Izmir", "RowAmount": 28000, "DocumentDate": "2026-01-15"},
    ]


# --- Rule 1: Column existence ---

def test_rule1_valid_columns_unchanged(sample_results, sample_profile):
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    spec = {
        "needs_graph": True, "chart_type": "bar_chart",
        "x_field": "BranchName", "y_field": "RowAmount",
        "series_field": None, "reason": "test",
    }
    result = validate_spec(spec, sample_results, sample_profile)
    assert result["x_field"] == "BranchName"
    assert result["y_field"] == "RowAmount"


def test_rule1_fuzzy_resolves_close_name(sample_results, sample_profile):
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    spec = {
        "needs_graph": True, "chart_type": "bar_chart",
        "x_field": "Branch_Name", "y_field": "Row_Amount",
        "series_field": None, "reason": "test",
    }
    result = validate_spec(spec, sample_results, sample_profile)
    assert result["x_field"] == "BranchName"
    assert result["y_field"] == "RowAmount"


def test_rule1_hallucinated_column_cleared(sample_results, sample_profile):
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    spec = {
        "needs_graph": True, "chart_type": "bar_chart",
        "x_field": "TotallyFakeColumn", "y_field": "RowAmount",
        "series_field": None, "reason": "test",
    }
    result = validate_spec(spec, sample_results, sample_profile)
    # Rule 1 clears it, Rule 4 fills from profile
    assert result["x_field"] in ["BranchName", "DocumentDate"]


# --- Rule 2: Role conformity ---

def test_rule2_swaps_reversed_xy(sample_results, sample_profile):
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    spec = {
        "needs_graph": True, "chart_type": "bar_chart",
        "x_field": "RowAmount", "y_field": "BranchName",
        "series_field": None, "reason": "test",
    }
    result = validate_spec(spec, sample_results, sample_profile)
    assert result["x_field"] == "BranchName"
    assert result["y_field"] == "RowAmount"


# --- Rule 3: Chart-data compatibility ---

def test_rule3_pie_too_many_categories_sets_topn():
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    results = [{"Cat": f"Cat{i}", "Val": i * 10} for i in range(30)]
    profile = {
        "dimension_columns": ["Cat"], "metric_columns": ["Val"],
        "time_column": None, "columns": [
            {"name": "Cat", "role": "dimension", "type": "text"},
            {"name": "Val", "role": "metric", "type": "numeric"},
        ],
    }
    spec = {
        "needs_graph": True, "chart_type": "pie_chart",
        "x_field": "Cat", "y_field": "Val",
        "series_field": None, "top_n": None, "reason": "test",
    }
    result = validate_spec(spec, results, profile)
    assert result.get("top_n") is not None
    assert result["top_n"] <= 15


def test_rule3_line_without_time_falls_to_bar(sample_results):
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    profile = {
        "dimension_columns": ["BranchName"], "metric_columns": ["RowAmount"],
        "time_column": None, "columns": [
            {"name": "BranchName", "role": "dimension", "type": "text"},
            {"name": "RowAmount", "role": "metric", "type": "numeric"},
        ],
    }
    spec = {
        "needs_graph": True, "chart_type": "line_chart",
        "x_field": "BranchName", "y_field": "RowAmount",
        "series_field": None, "reason": "test",
    }
    result = validate_spec(spec, results=sample_results, profile=profile)
    assert result["chart_type"] == "bar_chart"


# --- Rule 4: Missing field completion ---

def test_rule4_fills_missing_xy_from_profile(sample_results, sample_profile):
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    spec = {
        "needs_graph": True, "chart_type": "bar_chart",
        "x_field": None, "y_field": None,
        "series_field": None, "reason": "test",
    }
    result = validate_spec(spec, sample_results, sample_profile)
    assert result["x_field"] is not None
    assert result["y_field"] is not None


def test_rule4_no_fields_possible_falls_to_table():
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    results = [{"text": "hello"}]
    profile = {
        "dimension_columns": ["text"], "metric_columns": [],
        "time_column": None, "columns": [
            {"name": "text", "role": "dimension", "type": "text"},
        ],
    }
    spec = {
        "needs_graph": True, "chart_type": "bar_chart",
        "x_field": None, "y_field": None,
        "series_field": None, "reason": "test",
    }
    result = validate_spec(spec, results, profile)
    assert result["needs_graph"] is False
    assert result["chart_type"] == "table"


# --- Rule 5: Multi-metric validation ---

def test_rule5_invalid_yfields_removed(sample_results, sample_profile):
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    spec = {
        "needs_graph": True, "chart_type": "bar_chart",
        "x_field": "BranchName", "y_fields": ["RowAmount", "FakeMetric"],
        "series_field": None, "reason": "test",
    }
    result = validate_spec(spec, sample_results, sample_profile)
    assert result.get("y_fields") is None
    assert result["y_field"] == "RowAmount"


def test_rule5_valid_multi_metric_kept():
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
    results = [{"Branch": "A", "Sales": 100, "Qty": 5}]
    profile = {
        "dimension_columns": ["Branch"], "metric_columns": ["Sales", "Qty"],
        "time_column": None, "columns": [
            {"name": "Branch", "role": "dimension", "type": "text"},
            {"name": "Sales", "role": "metric", "type": "numeric"},
            {"name": "Qty", "role": "metric", "type": "numeric"},
        ],
    }
    spec = {
        "needs_graph": True, "chart_type": "bar_chart",
        "x_field": "Branch", "y_fields": ["Sales", "Qty"],
        "series_field": None, "reason": "test",
    }
    result = validate_spec(spec, results, profile)
    assert result["y_fields"] == ["Sales", "Qty"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_visualization_v2/test_validator.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write validator.py**

```python
# src/graphs/report_agent/subagents/visualization_v2/validator.py
"""
Visualization V2 — ChartSpec Validator

Pure Python, LLM yok. 5 kural sirayla calisir:
1. Kolon varlik kontrolu (fuzzy match results kolonlarina karsi)
2. Rol uyumu (x=dimension, y=metric; ters ise swap)
3. Chart-data uyumu (pie+30 kategori, line+zaman yok, vb.)
4. Eksik field tamamlama (profile'dan doldur)
5. Multi-metric dogrulama (y_fields gecerli mi?)
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def validate_spec(
    spec: dict,
    results: List[Dict[str, Any]],
    profile: dict,
) -> dict:
    """
    Validate and fix ChartSpec dict against actual data.

    Args:
        spec: ChartSpec.model_dump() or rule-based dict
        results: SQL query results (actual column names)
        profile: DataProfile dict

    Returns:
        Validated/fixed spec dict (same structure)
    """
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

    # Rule 3: Chart-data compatibility
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

    # Rule 4: Missing field completion
    if spec.get("needs_graph") and not spec.get("x_field"):
        spec["x_field"] = time_col or (dimension_cols[0] if dimension_cols else None)
        if spec["x_field"]:
            logger.info(f"[VALIDATOR] Rule 4: x_field filled -> '{spec['x_field']}'")

    if spec.get("needs_graph") and not spec.get("y_field") and not spec.get("y_fields"):
        spec["y_field"] = metric_cols[0] if metric_cols else None
        if spec["y_field"]:
            logger.info(f"[VALIDATOR] Rule 4: y_field filled -> '{spec['y_field']}'")

    if spec.get("needs_graph") and not spec.get("x_field") and not spec.get("y_field"):
        spec["needs_graph"] = False
        spec["chart_type"] = "table"
        logger.warning("[VALIDATOR] Rule 4: Cannot determine axes -> table fallback")

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


def _fuzzy_resolve(value: str, actual_columns: List[str]) -> Optional[str]:
    """Fuzzy match a field name against actual result columns."""
    # Exact case-insensitive
    lower_map = {c.lower(): c for c in actual_columns}
    if value.lower() in lower_map:
        return lower_map[value.lower()]

    # Underscore/space normalized
    normalized = value.replace("_", "").replace(" ", "").lower()
    for col in actual_columns:
        if col.replace("_", "").replace(" ", "").lower() == normalized:
            return col

    # Fuzzy match
    try:
        from rapidfuzz import process
        match = process.extractOne(value, actual_columns, score_cutoff=80)
        return match[0] if match else None
    except ImportError:
        return None
```

**Step 4: Run tests**

Run: `pytest tests/test_visualization_v2/test_validator.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/validator.py \
        tests/test_visualization_v2/test_validator.py
git commit -m "feat(viz-v2): add ChartSpec validator with 5 validation rules"
```

---

### Task 3: Chart Renderer (Deterministic Template Engine)

**Files:**
- Create: `src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py`
- Test: `tests/test_visualization_v2/test_chart_renderer.py`

**Step 1: Write failing tests**

```python
# tests/test_visualization_v2/test_chart_renderer.py
"""Deterministic chart renderer tests — no LLM, no exec()."""
import pytest


@pytest.fixture
def bar_results():
    return [
        {"BranchName": "Istanbul", "TotalSales": 50000},
        {"BranchName": "Ankara", "TotalSales": 35000},
        {"BranchName": "Izmir", "TotalSales": 28000},
    ]


@pytest.fixture
def col_meta():
    return {
        "BranchName": "Sube adi",
        "TotalSales": "Toplam satis (TL)",
    }


def test_bar_chart_basic(bar_results, col_meta):
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    spec = {
        "chart_type": "bar_chart", "x_field": "BranchName", "y_field": "TotalSales",
        "title": "Sube Satis",
    }
    html = render_chart(spec, bar_results, col_meta)
    assert html is not None
    assert "plotly" in html.lower()


def test_bar_chart_horizontal():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [{"Name": f"Item{i}", "Val": i * 10} for i in range(20)]
    spec = {
        "chart_type": "bar_chart", "x_field": "Name", "y_field": "Val",
        "orientation": "h", "title": "Horizontal",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_bar_chart_multi_metric():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Branch": "A", "Sales": 100, "Qty": 5},
        {"Branch": "B", "Sales": 200, "Qty": 10},
    ]
    spec = {
        "chart_type": "bar_chart", "x_field": "Branch",
        "y_fields": ["Sales", "Qty"], "title": "Multi",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_line_chart():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Month": "2026-01", "Revenue": 5000},
        {"Month": "2026-02", "Revenue": 6000},
    ]
    spec = {
        "chart_type": "line_chart", "x_field": "Month", "y_field": "Revenue",
        "title": "Trend",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_line_chart_multi_metric():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Month": "2026-01", "Sales": 100, "Qty": 5},
        {"Month": "2026-02", "Sales": 200, "Qty": 10},
    ]
    spec = {
        "chart_type": "line_chart", "x_field": "Month",
        "y_fields": ["Sales", "Qty"], "title": "Multi line",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_pie_chart():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Category": "A", "Count": 30},
        {"Category": "B", "Count": 50},
        {"Category": "C", "Count": 20},
    ]
    spec = {
        "chart_type": "pie_chart", "x_field": "Category", "y_field": "Count",
        "title": "Dagilim",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_pie_chart_topn():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [{"Cat": f"C{i}", "Val": i} for i in range(20)]
    spec = {
        "chart_type": "pie_chart", "x_field": "Cat", "y_field": "Val",
        "top_n": 5, "title": "Top 5",
    }
    html = render_chart(spec, results, {})
    assert html is not None
    # Should contain "Diger" for grouped others
    assert "Diger" in html or "Di" in html


def test_scatter_chart():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [{"X": i, "Y": i ** 2} for i in range(5)]
    spec = {"chart_type": "scatter_chart", "x_field": "X", "y_field": "Y", "title": "Scatter"}
    html = render_chart(spec, results, {})
    assert html is not None


def test_sunburst_with_hierarchy():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Category": "A", "Product": "P1", "Sales": 100},
        {"Category": "A", "Product": "P2", "Sales": 200},
        {"Category": "B", "Product": "P3", "Sales": 300},
    ]
    spec = {
        "chart_type": "sunburst",
        "hierarchy_fields": ["Category", "Product"],
        "y_field": "Sales", "title": "Hierarchy",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_treemap():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Category": "A", "Sales": 100},
        {"Category": "B", "Sales": 200},
    ]
    spec = {
        "chart_type": "treemap", "x_field": "Category", "y_field": "Sales",
        "title": "Treemap",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_comparison():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Branch": "A", "Period": "Q1", "Sales": 100},
        {"Branch": "A", "Period": "Q2", "Sales": 150},
        {"Branch": "B", "Period": "Q1", "Sales": 200},
    ]
    spec = {
        "chart_type": "comparison", "x_field": "Branch", "y_field": "Sales",
        "series_field": "Period", "title": "Compare",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_sort_by_applied():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Name": "C", "Val": 10},
        {"Name": "A", "Val": 30},
        {"Name": "B", "Val": 20},
    ]
    spec = {
        "chart_type": "bar_chart", "x_field": "Name", "y_field": "Val",
        "sort_by": "Val", "sort_order": "desc", "title": "Sorted",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_unsupported_chart_type_returns_none():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    spec = {"chart_type": "unknown_type", "x_field": "A", "y_field": "B", "title": ""}
    html = render_chart(spec, [{"A": 1, "B": 2}], {})
    assert html is None


def test_empty_results_returns_none():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    spec = {"chart_type": "bar_chart", "x_field": "A", "y_field": "B", "title": ""}
    html = render_chart(spec, [], {})
    assert html is None


def test_column_metadata_used_as_labels(bar_results, col_meta):
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    spec = {
        "chart_type": "bar_chart", "x_field": "BranchName", "y_field": "TotalSales",
        "title": "Test",
    }
    html = render_chart(spec, bar_results, col_meta)
    assert "Sube adi" in html or "Sube" in html
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_visualization_v2/test_chart_renderer.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write chart_renderer.py**

```python
# src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py
"""
Visualization V2 — Chart Renderer (Deterministic)

CIZIM KATMANI: Pure Plotly API cagrilari, LLM yok, exec() yok.
Girdi: Validated ChartSpec dict + DataFrame
Cikti: HTML snippet veya None
"""
import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

MAX_TRACES = 50


def render_chart(
    spec: dict,
    results: List[Dict[str, Any]],
    column_metadata: Dict[str, Any],
) -> Optional[str]:
    """
    Render a Plotly chart from validated ChartSpec.

    Args:
        spec: Validated ChartSpec dict
        results: SQL query results
        column_metadata: Column name -> description mapping

    Returns:
        HTML snippet string or None if unsupported/empty
    """
    chart_type = spec.get("chart_type")
    if chart_type not in _BUILDERS:
        logger.warning(f"[RENDERER] Unsupported chart_type '{chart_type}'")
        return None

    if not results:
        return None

    try:
        df = pd.DataFrame(results)
        df = _apply_preprocessing(df, spec)
        fig = _BUILDERS[chart_type](df, spec)
        fig = _apply_labels(fig, spec, column_metadata)
        fig = _apply_number_format(fig, df, spec)
        fig = _apply_layout(fig, spec)

        if len(fig.data) > MAX_TRACES:
            fig.data = fig.data[:MAX_TRACES]

        return fig.to_html(include_plotlyjs="cdn", full_html=False)

    except Exception as e:
        logger.error(f"[RENDERER] Failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def _apply_preprocessing(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """Apply top_n and sort before chart building."""
    y = spec.get("y_field")
    top_n = spec.get("top_n")
    sort_by = spec.get("sort_by")
    sort_order = spec.get("sort_order", "desc")

    if top_n and y and y in df.columns and len(df) > top_n:
        df = df.nlargest(top_n, y)

    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=(sort_order == "asc"))

    return df


# ---------------------------------------------------------------------------
# Chart Builders
# ---------------------------------------------------------------------------

def _build_bar(df: pd.DataFrame, spec: dict) -> go.Figure:
    x = spec.get("x_field")
    y = spec.get("y_field")
    y_fields = spec.get("y_fields")
    series = spec.get("series_field")
    title = spec.get("title") or ""
    orientation = spec.get("orientation")

    # Multi-metric bar
    if y_fields and len(y_fields) > 1:
        fig = go.Figure()
        for metric in y_fields:
            fig.add_trace(go.Bar(x=df[x], y=df[metric], name=metric))
        fig.update_layout(barmode="group", title=title)
        return fig

    # Horizontal bar
    if orientation == "h" or (orientation is None and len(df) > 15):
        if not spec.get("sort_by"):
            df = df.sort_values(y, ascending=True)
        return px.bar(df, x=y, y=x, orientation="h", color=series, title=title)

    # Grouped bar with series
    if series:
        return px.bar(df, x=x, y=y, color=series, barmode="group", title=title)

    # Simple bar
    if not spec.get("sort_by"):
        df = df.sort_values(y, ascending=False)
    return px.bar(df, x=x, y=y, title=title)


def _build_line(df: pd.DataFrame, spec: dict) -> go.Figure:
    x = spec.get("x_field")
    y = spec.get("y_field")
    y_fields = spec.get("y_fields")
    series = spec.get("series_field")
    title = spec.get("title") or ""

    # Multi-metric line
    if y_fields and len(y_fields) > 1:
        fig = go.Figure()
        df_sorted = df.sort_values(x)
        for metric in y_fields:
            fig.add_trace(go.Scatter(
                x=df_sorted[x], y=df_sorted[metric],
                mode="lines+markers", name=metric,
            ))
        fig.update_layout(title=title)
        return fig

    df_sorted = df.sort_values(x)
    return px.line(df_sorted, x=x, y=y, color=series, title=title, markers=True)


def _build_pie(df: pd.DataFrame, spec: dict) -> go.Figure:
    x = spec.get("x_field")
    y = spec.get("y_field")
    title = spec.get("title") or ""

    # top_n already applied in preprocessing, but if >10 rows still remain, group
    if len(df) > 10 and not spec.get("top_n"):
        top = df.nlargest(9, y)
        other_sum = df[~df.index.isin(top.index)][y].sum()
        other_row = pd.DataFrame([{x: "Diger", y: other_sum}])
        df = pd.concat([top, other_row], ignore_index=True)

    return px.pie(df, names=x, values=y, title=title)


def _build_scatter(df: pd.DataFrame, spec: dict) -> go.Figure:
    return px.scatter(
        df, x=spec.get("x_field"), y=spec.get("y_field"),
        color=spec.get("series_field"), title=spec.get("title") or "",
    )


def _build_sunburst(df: pd.DataFrame, spec: dict) -> go.Figure:
    path = spec.get("hierarchy_fields")
    if not path:
        s = spec.get("series_field")
        x = spec.get("x_field")
        path = [p for p in [s, x] if p]
    return px.sunburst(df, path=path, values=spec.get("y_field"), title=spec.get("title") or "")


def _build_treemap(df: pd.DataFrame, spec: dict) -> go.Figure:
    path = spec.get("hierarchy_fields")
    if not path:
        s = spec.get("series_field")
        x = spec.get("x_field")
        path = [p for p in [s, x] if p]
    return px.treemap(df, path=path, values=spec.get("y_field"), title=spec.get("title") or "")


def _build_comparison(df: pd.DataFrame, spec: dict) -> go.Figure:
    return px.bar(
        df, x=spec.get("x_field"), y=spec.get("y_field"),
        color=spec.get("series_field"), barmode="group",
        title=spec.get("title") or "",
    )


_BUILDERS = {
    "bar_chart": _build_bar,
    "line_chart": _build_line,
    "pie_chart": _build_pie,
    "scatter_chart": _build_scatter,
    "scatter": _build_scatter,
    "sunburst": _build_sunburst,
    "treemap": _build_treemap,
    "comparison": _build_comparison,
}


# ---------------------------------------------------------------------------
# Layout & Formatting
# ---------------------------------------------------------------------------

def _get_label(field: Optional[str], column_metadata: dict) -> str:
    if not field:
        return ""
    meta = column_metadata.get(field, "")
    if isinstance(meta, dict):
        return meta.get("description", field)
    if isinstance(meta, str) and meta:
        return meta
    return field


def _apply_labels(fig: go.Figure, spec: dict, column_metadata: dict) -> go.Figure:
    x = spec.get("x_field")
    y = spec.get("y_field")
    x_label = _get_label(x, column_metadata)
    y_label = _get_label(y, column_metadata)

    orientation = spec.get("orientation")
    is_horizontal = orientation == "h" or (
        len(fig.data) > 0
        and hasattr(fig.data[0], "orientation")
        and fig.data[0].orientation == "h"
    )

    update = {}
    if is_horizontal:
        if y_label:
            update["xaxis_title"] = y_label
        if x_label:
            update["yaxis_title"] = x_label
    else:
        if x_label:
            update["xaxis_title"] = x_label
        if y_label:
            update["yaxis_title"] = y_label

    if update:
        fig.update_layout(**update)
    return fig


def _detect_number_format(df: pd.DataFrame, col: str) -> Optional[str]:
    if col not in df.columns:
        return None
    try:
        sample = df[col].dropna()
        if sample.empty:
            return None
        max_val = sample.max()
        if max_val > 1000:
            return "currency"
        if 0 <= sample.min() and max_val <= 1 and pd.api.types.is_float_dtype(df[col]):
            return "percentage"
    except (TypeError, ValueError):
        pass
    return None


def _apply_number_format(fig: go.Figure, df: pd.DataFrame, spec: dict) -> go.Figure:
    y = spec.get("y_field")
    if not y:
        return fig
    fmt = _detect_number_format(df, y)

    is_horizontal = (
        len(fig.data) > 0
        and hasattr(fig.data[0], "orientation")
        and fig.data[0].orientation == "h"
    )
    axis = "x" if is_horizontal else "y"

    if fmt == "currency":
        fig.update_layout(**{f"{axis}axis_tickformat": ","})
    elif fmt == "percentage":
        fig.update_layout(**{f"{axis}axis_tickformat": ".0%"})
    return fig


def _apply_layout(fig: go.Figure, spec: dict) -> go.Figure:
    fig.update_layout(
        autosize=True,
        margin=dict(l=40, r=40, t=60, b=40),
        template="plotly_white",
    )
    return fig
```

**Step 4: Run tests**

Run: `pytest tests/test_visualization_v2/test_chart_renderer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py \
        tests/test_visualization_v2/test_chart_renderer.py
git commit -m "feat(viz-v2): add deterministic chart renderer, no exec()"
```

---

### Task 4: Prompts and DataAnalyzer

**Files:**
- Create: `src/graphs/report_agent/subagents/visualization_v2/prompts.py`
- Copy: `src/graphs/report_agent/subagents/visualization_v2/data_analyzer.py` (from v1, unchanged)

**Step 1: Write prompts.py**

```python
# src/graphs/report_agent/subagents/visualization_v2/prompts.py
"""
Visualization V2 — LLM Prompts

Karar katmani: LLM'e column_metadata ile birlikte kolon bilgisi verilir.
LLM ChartSpec JSON uretir, kod uretmez.
"""

VIZ_DECIDER_PROMPT = """Sen bir veri gorselleştirme uzmanisin.
Kullanici sorusu ve veri profiline gore en uygun gorselleştirmeyi belirle.

## KULLANICI SORUSU
{user_query}

## SORGU TIPI
{query_type}

## GRAFIK TALEBI
wants_visualization: {wants_visualization}
⚠️ wants_visualization=True → needs_graph MUTLAKA True olmali.

## KOLON BILGILERI
{column_info}

## ORNEK VERI (ilk 3 satir)
{sample_rows}

## FIELD MAPPING KURALLARI

### x_field ve y_field SECIMI (KRITIK)
- SADECE ornek verideki gercek kolon adlarini kullan
- x_field: Dimension kolonu (kategori, sube, tarih gibi GRUPLAMA kolonu)
- y_field: Metric kolonu (tutar, miktar gibi SAYISAL DEGER kolonu)
- ⚠️ ASLA x_field'e metric, y_field'e dimension koyma
- Birden fazla metric varsa y_fields listesi kullan

### series_field
- Karsilastirma varsa ikinci dimension kolonu (renk/grup ayirimi)
- Yoksa null birak

### chart_type SECIMI
Kullanici grafik turu belirtmisse onu kullan:
- "cubuk/bar grafik" → bar_chart
- "cizgi/line grafik" → line_chart
- "pasta/pie/daire grafik" → pie_chart
- "scatter/dagilim" → scatter_chart
- "sunburst/hiyerarsik" → sunburst
- "treemap/agac harita" → treemap

Belirtmemisse veri profiline gore:
- Tek sayi → single_value (needs_graph=False)
- Kisa liste → simple_list (needs_graph=False)
- Detayli tablo → table (needs_graph=False)
- Zaman serisi → line_chart
- Kategori karsilastirmasi → bar_chart
- Oran/pay dagilimi → pie_chart
- 2+ dimension hiyerarsi → sunburst veya treemap

### orientation
- Kategori sayisi fazlaysa (10+) → "h" (yatay bar daha okunur)
- Azsa veya zaman serisi → "v" veya null

### top_n
- Pie chart icin 10'dan fazla kategori varsa → top_n=10 oner
- Ranking sorgusu ise kullanicinin istedigi N'i kullan
"""
```

**Step 2: Copy data_analyzer.py from v1 (unchanged)**

```bash
cp src/graphs/report_agent/subagents/visualization/data_analyzer.py \
   src/graphs/report_agent/subagents/visualization_v2/data_analyzer.py
```

No changes needed — DataAnalyzer is pure Python and works correctly.

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/prompts.py \
        src/graphs/report_agent/subagents/visualization_v2/data_analyzer.py
git commit -m "feat(viz-v2): add LLM prompt with column_info and copy data_analyzer"
```

---

### Task 5: Graph Nodes (Karar + Cizim katmani birlestirme)

**Files:**
- Create: `src/graphs/report_agent/subagents/visualization_v2/nodes.py`
- Test: `tests/test_visualization_v2/test_nodes.py`

**Step 1: Write failing tests**

```python
# tests/test_visualization_v2/test_nodes.py
"""Node-level tests for visualization_v2 — unit tests with mocked LLM."""
import pytest


@pytest.fixture
def sample_state():
    return {
        "results": [
            {"BranchName": "Istanbul", "RowAmount": 50000},
            {"BranchName": "Ankara", "RowAmount": 35000},
        ],
        "user_query": "subelere gore satis",
        "query_type": "RANKING",
        "wants_visualization": True,
        "viz_request": None,
    }


@pytest.fixture
def config_with_metadata():
    return {
        "configurable": {
            "column_metadata": {
                "BranchName": "Sube adi",
                "RowAmount": "Satis tutari (TL)",
            }
        }
    }


# --- data_analyzer_node ---

@pytest.mark.asyncio
async def test_data_analyzer_produces_profile(sample_state):
    from src.graphs.report_agent.subagents.visualization_v2.nodes import data_analyzer_node
    result = await data_analyzer_node(sample_state)
    profile = result["data_profile"]
    assert profile is not None
    assert profile["row_count"] == 2
    assert "BranchName" in profile["dimension_columns"]
    assert "RowAmount" in profile["metric_columns"]


@pytest.mark.asyncio
async def test_data_analyzer_empty_results():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import data_analyzer_node
    result = await data_analyzer_node({"results": []})
    assert result["data_profile"] is None


# --- rule_based_decision ---

def test_rule_based_ranking():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
    profile = {
        "dimension_columns": ["BranchName"],
        "metric_columns": ["RowAmount"],
        "time_column": None,
        "row_count": 5,
    }
    result = _rule_based_decision("RANKING", True, profile)
    assert result is not None
    assert result["chart_type"] == "bar_chart"
    assert result["needs_graph"] is True
    # Rule-based does NOT set x_field/y_field — validator fills them
    assert result.get("x_field") is None


def test_rule_based_time_series():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
    profile = {
        "dimension_columns": ["BranchName"],
        "metric_columns": ["RowAmount"],
        "time_column": "DocumentDate",
        "row_count": 10,
    }
    result = _rule_based_decision("TIME_SERIES", True, profile)
    assert result is not None
    assert result["chart_type"] == "line_chart"


def test_rule_based_no_viz_returns_none():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
    result = _rule_based_decision("RANKING", False, {})
    assert result is None


# --- spec_validator_node ---

@pytest.mark.asyncio
async def test_spec_validator_fixes_fields(config_with_metadata):
    from src.graphs.report_agent.subagents.visualization_v2.nodes import spec_validator_node
    state = {
        "results": [
            {"BranchName": "Istanbul", "RowAmount": 50000},
        ],
        "viz_decision": {
            "needs_graph": True, "chart_type": "bar_chart",
            "x_field": None, "y_field": None,
            "series_field": None, "reason": "test",
        },
        "data_profile": {
            "dimension_columns": ["BranchName"],
            "metric_columns": ["RowAmount"],
            "time_column": None,
            "columns": [
                {"name": "BranchName", "role": "dimension", "type": "text"},
                {"name": "RowAmount", "role": "metric", "type": "numeric"},
            ],
        },
    }
    result = await spec_validator_node(state, config_with_metadata)
    viz = result["viz_decision"]
    assert viz["x_field"] == "BranchName"
    assert viz["y_field"] == "RowAmount"


# --- template_renderer_node ---

@pytest.mark.asyncio
async def test_template_renderer_produces_html(config_with_metadata):
    from src.graphs.report_agent.subagents.visualization_v2.nodes import template_renderer_node
    state = {
        "results": [
            {"BranchName": "Istanbul", "RowAmount": 50000},
            {"BranchName": "Ankara", "RowAmount": 35000},
        ],
        "viz_decision": {
            "needs_graph": True, "chart_type": "bar_chart",
            "x_field": "BranchName", "y_field": "RowAmount",
            "title": "Test",
        },
    }
    result = await template_renderer_node(state, config_with_metadata)
    assert result.get("plotly_html_snippet") is not None
    assert "plotly" in result["plotly_html_snippet"].lower()


@pytest.mark.asyncio
async def test_template_renderer_fallback_to_table(config_with_metadata):
    from src.graphs.report_agent.subagents.visualization_v2.nodes import template_renderer_node
    state = {
        "results": [{"A": 1}],
        "viz_decision": {
            "needs_graph": True, "chart_type": "exotic_unsupported",
            "x_field": "A", "y_field": "A", "title": "Test",
        },
    }
    result = await template_renderer_node(state, config_with_metadata)
    assert result["plotly_html_snippet"] is None
    assert result["viz_decision"]["chart_type"] == "table"
    assert result["viz_decision"]["needs_graph"] is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_visualization_v2/test_nodes.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write nodes.py**

```python
# src/graphs/report_agent/subagents/visualization_v2/nodes.py
"""
Visualization V2 — Graph Nodes

5 node:
    data_analyzer      - Pure Python: results -> DataProfile
    viz_decider        - Rule-based fast path + LLM fallback -> ChartSpec
    spec_validator     - Pure Python: ChartSpec validation/fix (5 rules)
    template_renderer  - Pure Python: ChartSpec -> Plotly HTML (deterministic)
    response_builder   - Pure Python: pack outputs -> visualization_output

KARAR KATMANI: data_analyzer, viz_decider, spec_validator
CIZIM KATMANI: template_renderer, response_builder
"""
import datetime as _dt
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from langchain_core.runnables import RunnableConfig

from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
from src.graphs.report_agent.subagents.visualization_v2.prompts import VIZ_DECIDER_PROMPT
from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

logger = logging.getLogger(__name__)

NO_GRAPH_TYPES = {"single_value", "simple_list", "table"}


def _get_configurable(config: Optional[RunnableConfig], key: str, fallback):
    if not config:
        return fallback
    configurable = config.get("configurable", {})
    if hasattr(configurable, key):
        val = getattr(configurable, key)
    elif isinstance(configurable, dict):
        val = configurable.get(key)
    else:
        return fallback
    if val is None or val == "" or val == {}:
        return fallback
    return val


# =========================================================================
# HELPERS (date normalization — copied from v1)
# =========================================================================

def _infer_date_column_from_metadata(config: Optional[RunnableConfig]) -> Optional[str]:
    column_metadata = _get_configurable(config, "column_metadata", None)
    if not column_metadata or not isinstance(column_metadata, dict):
        return None
    _DATE_HINTS = {"date", "tarih", "datetime", "zaman"}
    date_cols = [
        col for col, desc in column_metadata.items()
        if any(h in col.lower() for h in _DATE_HINTS)
        or any(h in str(desc).lower() for h in _DATE_HINTS)
    ]
    return date_cols[0] if len(date_cols) == 1 else None


def _normalize_results(
    results: List[Dict[str, Any]],
    date_column_hint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not results:
        return results

    column_renames: Dict[str, str] = {}
    if "" in results[0]:
        column_renames[""] = date_column_hint or "Date"

    normalized = []
    for row in results:
        new_row: Dict[str, Any] = {}
        for key, val in row.items():
            new_key = column_renames.get(key, key)
            if isinstance(val, _dt.datetime):
                val = val.date().isoformat()
            elif isinstance(val, _dt.date):
                val = val.isoformat()
            elif (
                isinstance(val, list)
                and len(val) == 3
                and all(isinstance(x, int) for x in val)
            ):
                try:
                    val = _dt.date(val[0], val[1], val[2]).isoformat()
                except (ValueError, TypeError):
                    pass
            new_row[new_key] = val
        normalized.append(new_row)
    return normalized


# =========================================================================
# NODE 1: DATA ANALYZER (Karar Katmani)
# =========================================================================

async def data_analyzer_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
    results = state.get("results") or []
    if not results:
        logger.info("[V2:DATA_ANALYZER] No results, skipping")
        return {"data_profile": None}

    date_hint = _infer_date_column_from_metadata(config)
    normalized = _normalize_results(results, date_column_hint=date_hint)

    analyzer = DataAnalyzer()
    profile_state = analyzer.analyze({"raw_data": normalized})
    profile = profile_state.get("data_profile")

    if profile:
        logger.info(
            f"[V2:DATA_ANALYZER] {profile['row_count']} rows, "
            f"dims={profile['dimension_columns']}, "
            f"metrics={profile['metric_columns']}, "
            f"time={profile.get('time_column')}"
        )
    return {"data_profile": profile, "results": normalized}


# =========================================================================
# NODE 2: VIZ DECIDER (Karar Katmani)
# =========================================================================

def _rule_based_decision(
    query_type: str,
    wants_viz: bool,
    profile: dict,
) -> Optional[dict]:
    """
    Deterministic chart type selection.
    Field mapping yapmaz (x_field, y_field = None) — validator doldurur.
    """
    if not wants_viz:
        return None

    metric_cols = profile.get("metric_columns", [])
    time_col = profile.get("time_column")
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

    if query_type in ("TIME_SERIES", "TIME_SERIES_COMPARISON"):
        return {
            "needs_graph": True, "chart_type": "line_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Time series -> line chart",
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


def _build_column_info(profile: dict, column_metadata: dict) -> str:
    """Format column info for LLM prompt: name (role, type): description."""
    lines = []
    for col_info in profile.get("columns", []):
        name = col_info.get("name", "")
        role = col_info.get("role", "unknown")
        col_type = col_info.get("type", "unknown")
        desc = column_metadata.get(name, "")
        if isinstance(desc, dict):
            desc = desc.get("description", "")
        lines.append(f"- {name} ({role}, {col_type}): {desc}")
    return "\n".join(lines) or "Kolon bilgisi yok"


def create_viz_decider_node(llm) -> Callable:
    structured_llm = llm.with_structured_output(ChartSpec)

    async def viz_decider_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        results = state.get("results") or []
        data_profile = state.get("data_profile")

        # Fast exit: no data
        if not results:
            return {"viz_decision": ChartSpec(
                needs_graph=False, chart_type="table", reason="Veri yok"
            ).model_dump()}

        # Fast exit: no viz requested
        if not state.get("wants_visualization", False):
            return {"viz_decision": ChartSpec(
                needs_graph=False, chart_type="table", reason="Grafik talep edilmedi"
            ).model_dump()}

        # Fast exit: single value
        if len(results) == 1 and data_profile and data_profile.get("column_count", 0) == 1:
            return {"viz_decision": ChartSpec(
                needs_graph=False, chart_type="single_value", reason="Tek deger"
            ).model_dump()}

        # Rule-based fast path
        rule_decision = _rule_based_decision(
            query_type=state.get("query_type", ""),
            wants_viz=state.get("wants_visualization", False),
            profile=data_profile or {},
        )
        if rule_decision is not None:
            logger.info(f"[V2:VIZ_DECIDER] Rule-based: {rule_decision['chart_type']}")
            return {"viz_decision": rule_decision}

        # LLM fallback
        wants_viz = state.get("wants_visualization", False)
        profile = data_profile or {}
        column_metadata = _get_configurable(config, "column_metadata", {})
        if isinstance(column_metadata, str):
            try:
                column_metadata = json.loads(column_metadata)
            except (json.JSONDecodeError, TypeError):
                column_metadata = {}

        effective_query = state.get("viz_request") or state.get("user_query", "")
        column_info = _build_column_info(profile, column_metadata)

        prompt = VIZ_DECIDER_PROMPT.format(
            user_query=effective_query,
            query_type=state.get("query_type", "SINGLE"),
            wants_visualization=wants_viz,
            column_info=column_info,
            sample_rows=json.dumps(results[:3], ensure_ascii=False, indent=2),
        )

        decision: ChartSpec = await structured_llm.ainvoke(prompt)

        # Guard: user wants viz but LLM says no
        if wants_viz and not decision.needs_graph:
            safe_chart = decision.chart_type
            if safe_chart in NO_GRAPH_TYPES:
                safe_chart = "bar_chart"
            decision = decision.model_copy(update={
                "needs_graph": True,
                "chart_type": safe_chart,
                "reason": decision.reason + " [override: user requested chart]",
            })

        logger.info(
            f"[V2:VIZ_DECIDER] LLM: {decision.chart_type}, "
            f"x={decision.x_field}, y={decision.y_field}"
        )
        return {"viz_decision": decision.model_dump()}

    return viz_decider_node


# =========================================================================
# NODE 3: SPEC VALIDATOR (Karar Katmani)
# =========================================================================

async def spec_validator_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
    viz_decision = state.get("viz_decision") or {}
    results = state.get("results") or []
    profile = state.get("data_profile") or {}

    if not results or not viz_decision.get("needs_graph", False):
        return {}  # No validation needed for non-graph outputs

    validated = validate_spec(viz_decision, results, profile)
    logger.info(
        f"[V2:VALIDATOR] {validated.get('chart_type')}, "
        f"x={validated.get('x_field')}, y={validated.get('y_field')}"
    )
    return {"viz_decision": validated}


# =========================================================================
# NODE 4: TEMPLATE RENDERER (Cizim Katmani)
# =========================================================================

async def template_renderer_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
    viz_decision = state.get("viz_decision") or {}
    results = state.get("results") or []

    if not viz_decision.get("needs_graph", False):
        return {}

    column_metadata = _get_configurable(config, "column_metadata", {})
    if isinstance(column_metadata, str):
        try:
            column_metadata = json.loads(column_metadata)
        except (json.JSONDecodeError, TypeError):
            column_metadata = {}

    html = render_chart(viz_decision, results, column_metadata)

    if html is None:
        logger.warning("[V2:RENDERER] Template failed, falling back to table")
        return {
            "plotly_html_snippet": None,
            "viz_decision": {**viz_decision, "needs_graph": False, "chart_type": "table"},
        }

    logger.info(f"[V2:RENDERER] HTML: {len(html)} chars")
    return {"plotly_html_snippet": html}


# =========================================================================
# NODE 5: RESPONSE BUILDER (Cizim Katmani)
# =========================================================================

async def response_builder_node(state: dict) -> dict:
    results = state.get("results") or []
    viz_decision = state.get("viz_decision") or {}
    data_profile = state.get("data_profile") or {}
    html_snippet = state.get("plotly_html_snippet")

    chart_type = viz_decision.get("chart_type", "table")
    needs_graph = viz_decision.get("needs_graph", False)

    summary = _build_summary(chart_type, results, html_snippet)

    visualization_output = {
        "needs_graph": needs_graph,
        "chart_type": chart_type,
        "plotly_html_snippet": html_snippet,
        "summary": summary,
        "x_field": viz_decision.get("x_field"),
        "y_field": viz_decision.get("y_field"),
        "title": viz_decision.get("title"),
    }

    logger.info(f"[V2:RESPONSE] chart_type={chart_type}, has_html={bool(html_snippet)}")
    return {"visualization_output": visualization_output}


def _build_summary(chart_type: str, data: list, html_snippet: Optional[str]) -> str:
    if not data:
        return "Sonuc bulunamadi."
    row_count = len(data)
    if chart_type == "single_value":
        return str(list(data[0].values())[0]) if data else ""
    if chart_type == "simple_list":
        return _format_as_markdown_list(data)
    if chart_type == "table":
        col_count = len(data[0]) if data else 0
        return f"{row_count} satir, {col_count} kolon"
    if html_snippet:
        return f"{row_count} veri noktasi gosteriliyor."
    return f"{row_count} kayit"


def _format_as_markdown_list(data: List[Dict[str, Any]]) -> str:
    if not data:
        return "Sonuc bulunamadi."
    columns = list(data[0].keys())
    MAX_ROWS = 20
    if len(columns) == 1:
        items = [str(list(row.values())[0]) for row in data[:MAX_ROWS]]
        result = "\n".join(f"- {item}" for item in items)
    elif len(columns) == 2:
        items = [
            f"- **{list(row.values())[0]}**: {list(row.values())[1]}"
            for row in data[:MAX_ROWS]
        ]
        result = "\n".join(items)
    else:
        return f"{len(data)} kayit listelendi."
    if len(data) > MAX_ROWS:
        result += f"\n\n*({len(data)} kayittan ilk {MAX_ROWS}'i gosteriliyor)*"
    return result
```

**Step 4: Run tests**

Run: `pytest tests/test_visualization_v2/test_nodes.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py \
        tests/test_visualization_v2/test_nodes.py
git commit -m "feat(viz-v2): add graph nodes — karar + cizim katmani"
```

---

### Task 6: Graph Definition

**Files:**
- Create: `src/graphs/report_agent/subagents/visualization_v2/graph.py`
- Update: `src/graphs/report_agent/subagents/visualization_v2/__init__.py`
- Test: `tests/test_visualization_v2/test_graph.py`

**Step 1: Write failing test**

```python
# tests/test_visualization_v2/test_graph.py
"""Graph compilation and routing tests."""
import pytest


def test_graph_compiles():
    """Graph should compile without errors using a mock LLM."""
    from unittest.mock import MagicMock
    from src.graphs.report_agent.subagents.visualization_v2.graph import build_visualization_graph

    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_llm)

    graph = build_visualization_graph(mock_llm)
    assert graph is not None


def test_graph_has_5_nodes():
    from unittest.mock import MagicMock
    from src.graphs.report_agent.subagents.visualization_v2.graph import build_visualization_graph

    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_llm)

    graph = build_visualization_graph(mock_llm)
    # StateGraph compiled graph has nodes attribute
    node_names = set(graph.get_graph().nodes.keys())
    expected = {"data_analyzer", "viz_decider", "spec_validator", "template_renderer", "response_builder"}
    assert expected.issubset(node_names)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_visualization_v2/test_graph.py -v`
Expected: FAIL

**Step 3: Write graph.py**

```python
# src/graphs/report_agent/subagents/visualization_v2/graph.py
"""
Visualization V2 — Graph Definition

START -> data_analyzer -> viz_decider -> spec_validator -> [conditional]
  ├── needs_graph=True  -> template_renderer -> response_builder -> END
  └── needs_graph=False -> response_builder -> END
"""
import logging

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.visualization_v2.nodes import (
    data_analyzer_node,
    create_viz_decider_node,
    spec_validator_node,
    template_renderer_node,
    response_builder_node,
)
from src.graphs.report_agent.subagents.visualization_v2.state import VisualizationState

logger = logging.getLogger(__name__)


def _route_after_validator(state: dict) -> str:
    viz = state.get("viz_decision") or {}
    if viz.get("needs_graph", False):
        return "template_renderer"
    return "response_builder"


def build_visualization_graph(llm):
    """
    Visualization V2 subagent graph.

    5 nodes, 1 conditional edge, max 1 LLM call/turn.
    Karar katmani: data_analyzer -> viz_decider -> spec_validator
    Cizim katmani: template_renderer -> response_builder
    """
    graph = StateGraph(VisualizationState)

    graph.add_node("data_analyzer", data_analyzer_node)
    graph.add_node("viz_decider", create_viz_decider_node(llm))
    graph.add_node("spec_validator", spec_validator_node)
    graph.add_node("template_renderer", template_renderer_node)
    graph.add_node("response_builder", response_builder_node)

    graph.add_edge(START, "data_analyzer")
    graph.add_edge("data_analyzer", "viz_decider")
    graph.add_edge("viz_decider", "spec_validator")
    graph.add_conditional_edges(
        "spec_validator",
        _route_after_validator,
        {"template_renderer": "template_renderer", "response_builder": "response_builder"},
    )
    graph.add_edge("template_renderer", "response_builder")
    graph.add_edge("response_builder", END)

    compiled = graph.compile()
    logger.info("[V2:VISUALIZATION] Built: 5 nodes, max 1 LLM call/turn")
    return compiled
```

**Step 4: Update __init__.py**

```python
# src/graphs/report_agent/subagents/visualization_v2/__init__.py
from .graph import build_visualization_graph

__all__ = ["build_visualization_graph"]
```

**Step 5: Run tests**

Run: `pytest tests/test_visualization_v2/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/graph.py \
        src/graphs/report_agent/subagents/visualization_v2/__init__.py \
        tests/test_visualization_v2/test_graph.py
git commit -m "feat(viz-v2): add graph definition with 5 nodes"
```

---

### Task 7: Integration — Switch Import in Report Agent

**Files:**
- Modify: `src/graphs/report_agent/graph.py` (import path change)

**Step 1: Update import**

In `src/graphs/report_agent/graph.py`, find:
```python
from src.graphs.report_agent.subagents.visualization.graph import build_visualization_graph
```
Replace with:
```python
from src.graphs.report_agent.subagents.visualization_v2.graph import build_visualization_graph
```

**Step 2: Run all tests**

Run: `pytest tests/ -v --timeout=30`
Expected: All existing + new tests PASS

**Step 3: Manual smoke test**

Start the app and test these scenarios:
1. "subelere gore satis grafigi goster" → bar_chart expected
2. "aylik satis trendi" → line_chart expected
3. "kategori dagilimi pasta grafik" → pie_chart expected
4. "toplam ciro nedir" → single_value, no graph expected

**Step 4: Commit**

```bash
git add src/graphs/report_agent/graph.py
git commit -m "feat(viz-v2): switch report agent to visualization_v2"
```

---

## Summary

| Task | Description | Files | Tests |
|------|-------------|-------|-------|
| 1 | ChartSpec model + state | 4 create | 6 tests |
| 2 | Spec validator (5 rules) | 1 create | 10 tests |
| 3 | Chart renderer (deterministic) | 1 create | 15 tests |
| 4 | Prompts + DataAnalyzer copy | 2 create | — |
| 5 | Graph nodes (karar + cizim) | 1 create | 7 tests |
| 6 | Graph definition | 1 create, 1 update | 2 tests |
| 7 | Integration (import switch) | 1 modify | smoke test |

**Total:** 11 new files, 1 modified file, ~40 tests, 7 commits
**Eski kod korunur:** `visualization/` dizini aynen kalir, silinmez
