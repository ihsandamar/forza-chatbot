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
