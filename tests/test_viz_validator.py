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
