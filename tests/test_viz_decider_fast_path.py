"""Test rule-based viz_decider fast paths that skip LLM."""
import pytest


def test_ranking_query_gets_bar_chart():
    """RANKING query_type should deterministically produce bar_chart without LLM."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    results = [
        {"BranchName": "A", "Total": 1000},
        {"BranchName": "B", "Total": 800},
        {"BranchName": "C", "Total": 600},
    ]
    profile = {
        "row_count": 3, "column_count": 2,
        "dimension_columns": ["BranchName"], "metric_columns": ["Total"],
        "time_column": None, "has_time_series": False,
    }
    decision = _rule_based_viz_decision("RANKING", results, profile, wants_viz=True)
    assert decision is not None
    assert decision["chart_type"] == "bar_chart"
    assert decision["x_field"] == "BranchName"
    assert decision["y_field"] == "Total"
    assert decision["needs_graph"] is True


def test_time_series_query_gets_line_chart():
    """TIME_SERIES query should produce line_chart."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    results = [
        {"Month": "2026-01", "Revenue": 5000},
        {"Month": "2026-02", "Revenue": 6000},
    ]
    profile = {
        "row_count": 2, "column_count": 2,
        "dimension_columns": ["Month"], "metric_columns": ["Revenue"],
        "time_column": "Month", "has_time_series": True,
    }
    decision = _rule_based_viz_decision("TIME_SERIES_COMPARISON", results, profile, wants_viz=True)
    assert decision is not None
    assert decision["chart_type"] == "line_chart"
    assert decision["needs_graph"] is True


def test_listing_query_gets_table():
    """LISTING query should produce table (no graph)."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    results = [{"Name": f"Item {i}", "Value": i} for i in range(15)]
    profile = {
        "row_count": 15, "column_count": 2,
        "dimension_columns": ["Name"], "metric_columns": ["Value"],
        "time_column": None, "has_time_series": False,
    }
    decision = _rule_based_viz_decision("LISTING", results, profile, wants_viz=True)
    assert decision is not None
    assert decision["chart_type"] == "table"
    assert decision["needs_graph"] is False


def test_comparison_query_gets_grouped_bar():
    """COMPARISON query should produce comparison chart."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    results = [
        {"Branch": "A", "Category": "X", "Total": 100},
        {"Branch": "B", "Category": "X", "Total": 200},
    ]
    profile = {
        "row_count": 2, "column_count": 3,
        "dimension_columns": ["Branch", "Category"], "metric_columns": ["Total"],
        "time_column": None, "has_time_series": False,
    }
    decision = _rule_based_viz_decision("COMPARISON", results, profile, wants_viz=True)
    assert decision is not None
    assert decision["needs_graph"] is True
    assert decision["chart_type"] in ("bar_chart", "comparison")


def test_no_viz_requested_returns_none():
    """When wants_viz is False, return None (existing fast paths handle it)."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    decision = _rule_based_viz_decision("RANKING", [{"A": 1}], {
        "row_count": 1, "column_count": 1,
        "dimension_columns": [], "metric_columns": ["A"],
        "time_column": None, "has_time_series": False,
    }, wants_viz=False)
    assert decision is None


def test_no_metrics_returns_none_for_llm_fallback():
    """When no metric columns detected, let LLM handle it."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    decision = _rule_based_viz_decision("RANKING", [{"A": "text"}], {
        "row_count": 1, "column_count": 1,
        "dimension_columns": ["A"], "metric_columns": [],
        "time_column": None, "has_time_series": False,
    }, wants_viz=True)
    assert decision is None
