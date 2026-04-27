"""Tests for visualization v2 validator rules."""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_results(col_a, col_b, pairs):
    """Build a list-of-dicts result set from two column names and value pairs."""
    return [{col_a: a, col_b: b} for a, b in pairs]


def _base_profile(**overrides):
    base = {
        "dimension_columns": [],
        "metric_columns": [],
        "time_column": None,
        "columns": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Rule 4: Missing x_field / y_field are filled from profile
# ---------------------------------------------------------------------------

def test_missing_x_and_y_fields_are_filled_from_profile():
    """
    Rule 4: when spec has needs_graph=True but x_field/y_field are None,
    validate_spec should fill them from dimension_columns / metric_columns.
    """
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec

    results = _make_results("BranchName", "Total", [("A", 100), ("B", 200)])
    profile = _base_profile(
        dimension_columns=["BranchName"],
        metric_columns=["Total"],
    )
    spec = {
        "needs_graph": True,
        "chart_type": "bar_chart",
        "x_field": None,
        "y_field": None,
        "series_field": None,
    }

    validated = validate_spec(spec, results, profile)

    assert validated["x_field"] == "BranchName"
    assert validated["y_field"] == "Total"
    assert validated["needs_graph"] is True


def test_missing_fields_with_no_profile_info_falls_back_to_table():
    """
    Rule 4: if neither x nor y can be filled (empty profile), spec degrades to table.
    """
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec

    results = [{"Total": 100}]
    profile = _base_profile(dimension_columns=[], metric_columns=[])
    spec = {
        "needs_graph": True,
        "chart_type": "bar_chart",
        "x_field": None,
        "y_field": None,
        "series_field": None,
    }

    validated = validate_spec(spec, results, profile)

    assert validated["needs_graph"] is False
    assert validated["chart_type"] == "table"


# ---------------------------------------------------------------------------
# Rule 3 (Chart-data compatibility): line_chart -> bar_chart when no time col
# ---------------------------------------------------------------------------

def test_line_chart_without_time_column_downgraded_to_bar_chart():
    """
    Rule 3: line_chart with no time_column in profile and x_field not typed
    as time should be downgraded to bar_chart.
    """
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec

    results = _make_results("BranchName", "Total", [("A", 100), ("B", 200)])
    profile = _base_profile(
        dimension_columns=["BranchName"],
        metric_columns=["Total"],
        time_column=None,   # no time column
    )
    spec = {
        "needs_graph": True,
        "chart_type": "line_chart",
        "x_field": "BranchName",
        "y_field": "Total",
        "series_field": None,
    }

    validated = validate_spec(spec, results, profile)

    assert validated["chart_type"] == "bar_chart"


def test_line_chart_with_time_column_stays_line_chart():
    """
    Rule 3: line_chart with a valid time_column in profile should NOT be downgraded.
    """
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec

    results = _make_results("DocumentDate", "Total", [("2026-01", 100), ("2026-02", 200)])
    profile = _base_profile(
        dimension_columns=["DocumentDate"],
        metric_columns=["Total"],
        time_column="DocumentDate",
    )
    spec = {
        "needs_graph": True,
        "chart_type": "line_chart",
        "x_field": "DocumentDate",
        "y_field": "Total",
        "series_field": None,
    }

    validated = validate_spec(spec, results, profile)

    assert validated["chart_type"] == "line_chart"


# ---------------------------------------------------------------------------
# Rule 3: pie_chart top_n capping
# ---------------------------------------------------------------------------

def test_pie_chart_with_many_categories_gets_top_n():
    """
    Rule 3: pie_chart with more than 15 unique x_field values and no top_n
    should have top_n set to 10 automatically.
    """
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec

    # 20 unique categories -> exceeds the 15-category threshold
    results = [{"Cat": f"Category{i}", "Val": i * 10} for i in range(20)]
    profile = _base_profile(
        dimension_columns=["Cat"],
        metric_columns=["Val"],
    )
    spec = {
        "needs_graph": True,
        "chart_type": "pie_chart",
        "x_field": "Cat",
        "y_field": "Val",
        "series_field": None,
    }

    validated = validate_spec(spec, results, profile)

    assert validated["chart_type"] == "pie_chart"
    assert validated.get("top_n") == 10


def test_pie_chart_with_few_categories_no_top_n():
    """
    Rule 3: pie_chart with 15 or fewer unique categories should NOT get top_n.
    """
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec

    results = [{"Cat": f"C{i}", "Val": i} for i in range(10)]
    profile = _base_profile(
        dimension_columns=["Cat"],
        metric_columns=["Val"],
    )
    spec = {
        "needs_graph": True,
        "chart_type": "pie_chart",
        "x_field": "Cat",
        "y_field": "Val",
        "series_field": None,
    }

    validated = validate_spec(spec, results, profile)

    assert validated.get("top_n") is None


# ---------------------------------------------------------------------------
# Rule 3: treemap hierarchy_fields auto-build
# ---------------------------------------------------------------------------

def test_treemap_hierarchy_fields_auto_built_from_dims():
    """
    Rule 3: treemap with two dimension columns and no hierarchy_fields should
    auto-build hierarchy_fields = [dim0, dim1] in validate_spec.
    This mirrors sunburst Rule 3 (line 139 in validator.py).
    """
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec

    results = [
        {"CategoryName": "ESPRESSO", "ProductName": "LATTE", "ToplamCiro": 45670088.322},
        {"CategoryName": "CAYLAR", "ProductName": "FINCAN CAY", "ToplamCiro": 26019640.035},
        {"CategoryName": "ESPRESSO", "ProductName": "AMERICANO", "ToplamCiro": 22954983.834},
    ]
    profile = _base_profile(
        dimension_columns=["CategoryName", "ProductName"],
        metric_columns=["ToplamCiro"],
    )
    spec = {
        "needs_graph": True,
        "chart_type": "treemap",
        "x_field": "CategoryName",   # validator already filled this
        "y_field": "ToplamCiro",
        "hierarchy_fields": None,
        "series_field": None,
    }

    validated = validate_spec(spec, results, profile)

    assert validated["chart_type"] == "treemap"
    assert validated.get("hierarchy_fields") == ["CategoryName", "ProductName"], (
        "validate_spec must auto-build hierarchy_fields for treemap from dimension_columns"
    )


def test_treemap_single_dim_no_hierarchy_fields_built():
    """
    If only one dimension column exists, hierarchy_fields should NOT be auto-built
    (single-level treemap via x_field fallback is fine).
    """
    from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec

    results = [
        {"CategoryName": "ESPRESSO", "ToplamCiro": 45670088.322},
        {"CategoryName": "CAYLAR", "ToplamCiro": 26019640.035},
    ]
    profile = _base_profile(
        dimension_columns=["CategoryName"],
        metric_columns=["ToplamCiro"],
    )
    spec = {
        "needs_graph": True,
        "chart_type": "treemap",
        "x_field": "CategoryName",
        "y_field": "ToplamCiro",
        "hierarchy_fields": None,
        "series_field": None,
    }

    validated = validate_spec(spec, results, profile)

    # Single dim: hierarchy_fields should stay None (x_field fallback handles it)
    assert validated.get("hierarchy_fields") is None


def test_treemap_renderer_with_two_dim_columns():
    """
    _build_treemap with hierarchy_fields=["CategoryName","ProductName"] and
    values="ToplamCiro" must render a valid treemap figure (no exception, non-None).
    """
    import pandas as pd
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    results = [
        {"CategoryName": "ESPRESSO", "ProductName": "LATTE", "ToplamCiro": 45670088.322},
        {"CategoryName": "CAYLAR", "ProductName": "FINCAN CAY", "ToplamCiro": 26019640.035},
        {"CategoryName": "ESPRESSO", "ProductName": "AMERICANO", "ToplamCiro": 22954983.834},
        {"CategoryName": "ESPRESSO", "ProductName": "WHITE CHOCOLATE MOCHA", "ToplamCiro": 19879734.984},
    ]
    spec = {
        "needs_graph": True,
        "chart_type": "treemap",
        "hierarchy_fields": ["CategoryName", "ProductName"],
        "x_field": None,
        "y_field": "ToplamCiro",
        "series_field": None,
        "title": "Kategori > Ürün Ciro",
        "top_n": None,
        "sort_by": None,
        "sort_order": None,
        "orientation": None,
        "y_fields": None,
    }

    html = render_chart(spec, results, {})

    assert html is not None, (
        "_build_treemap must return a figure for valid hierarchy_fields + values"
    )
    assert "plotly" in html.lower()


def test_treemap_renderer_drops_invalid_path_columns():
    """
    _build_treemap must not crash if a path column doesn't exist in the DataFrame.
    Instead it should filter it out and render with the valid columns, or return None
    gracefully if no valid path columns remain.
    """
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    results = [
        {"CategoryName": "ESPRESSO", "ToplamCiro": 45670088.322},
        {"CategoryName": "CAYLAR", "ToplamCiro": 26019640.035},
    ]
    spec = {
        "needs_graph": True,
        "chart_type": "treemap",
        "hierarchy_fields": ["CategoryName", "NonExistentColumn"],  # one invalid
        "x_field": None,
        "y_field": "ToplamCiro",
        "series_field": None,
        "title": None,
        "top_n": None,
        "sort_by": None,
        "sort_order": None,
        "orientation": None,
        "y_fields": None,
    }

    # Must not raise — either renders (with valid columns only) or gracefully returns None
    try:
        html = render_chart(spec, results, {})
        # If it renders, it must be valid HTML
        if html is not None:
            assert "plotly" in html.lower()
    except Exception as e:
        pytest.fail(f"render_chart must not raise, got: {e}")


def test_treemap_renderer_handles_null_path_values():
    """
    _build_treemap must handle NULL values in path columns without crashing.
    Real data often has rows with NULL CategoryName or ProductName.
    Plotly raises 'None entries cannot have not-None children' — same as sunburst.
    The fix: dropna on path columns before calling px.treemap (mirror _build_sunburst).
    """
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    results = [
        {"CategoryName": "ESPRESSO", "ProductName": "LATTE", "ToplamCiro": 45670088.322},
        {"CategoryName": None, "ProductName": "UNKNOWN", "ToplamCiro": 5000.0},  # NULL category
        {"CategoryName": "CAYLAR", "ProductName": "FINCAN CAY", "ToplamCiro": 26019640.035},
        {"CategoryName": "ESPRESSO", "ProductName": None, "ToplamCiro": 3000.0},  # NULL product
    ]
    spec = {
        "needs_graph": True,
        "chart_type": "treemap",
        "hierarchy_fields": ["CategoryName", "ProductName"],
        "x_field": None,
        "y_field": "ToplamCiro",
        "series_field": None,
        "title": "Test",
        "top_n": None,
        "sort_by": None,
        "sort_order": None,
        "orientation": None,
        "y_fields": None,
    }

    html = render_chart(spec, results, {})

    # Must render (non-null rows are enough) — must NOT crash and return None
    assert html is not None, (
        "_build_treemap must drop null path rows and render the valid subset, "
        "not crash silently and fall back to table"
    )
