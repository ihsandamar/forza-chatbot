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


# --- Rule 3: Heatmap validation ---

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
