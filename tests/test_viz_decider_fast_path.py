"""Test rule-based viz_decider fast paths that skip LLM."""
import pytest


def test_ranking_query_gets_bar_chart():
    """RANKING query_type should deterministically produce bar_chart without LLM."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import (
        _rule_based_decision,
    )

    profile = {
        "row_count": 3, "column_count": 2,
        "dimension_columns": ["BranchName"], "metric_columns": ["Total"],
        "time_column": None, "has_time_series": False,
    }
    decision = _rule_based_decision("RANKING", wants_viz=True, profile=profile)
    assert decision is not None
    assert decision["chart_type"] == "bar_chart"
    assert decision["needs_graph"] is True


def test_time_series_query_gets_line_chart():
    """TIME_SERIES query should produce line_chart."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import (
        _rule_based_decision,
    )

    profile = {
        "row_count": 2, "column_count": 2,
        "dimension_columns": ["Month"], "metric_columns": ["Revenue"],
        "time_column": "Month", "has_time_series": True,
    }
    # TIME_SERIES always produces line_chart via rule
    decision = _rule_based_decision("TIME_SERIES", wants_viz=True, profile=profile)
    assert decision is not None
    assert decision["chart_type"] == "line_chart"
    assert decision["needs_graph"] is True

    # TIME_SERIES_COMPARISON with a comparison_dimension also produces line_chart
    decision = _rule_based_decision(
        "TIME_SERIES_COMPARISON", wants_viz=True, profile=profile,
        comparison_dimension="Branch",
    )
    assert decision is not None
    assert decision["chart_type"] == "line_chart"
    assert decision["needs_graph"] is True


def test_listing_query_gets_table():
    """LISTING query should produce table (no graph)."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import (
        _rule_based_decision,
    )

    profile = {
        "row_count": 15, "column_count": 2,
        "dimension_columns": ["Name"], "metric_columns": ["Value"],
        "time_column": None, "has_time_series": False,
    }
    decision = _rule_based_decision("LISTING", wants_viz=True, profile=profile)
    assert decision is not None
    assert decision["chart_type"] == "table"
    assert decision["needs_graph"] is False


def test_comparison_query_gets_grouped_bar():
    """COMPARISON query with multiple dimensions -> sunburst; single dimension -> bar_chart."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import (
        _rule_based_decision,
    )

    profile = {
        "row_count": 2, "column_count": 3,
        "dimension_columns": ["Branch", "Category"], "metric_columns": ["Total"],
        "time_column": None, "has_time_series": False,
    }
    decision = _rule_based_decision("COMPARISON", wants_viz=True, profile=profile)
    assert decision is not None
    assert decision["needs_graph"] is True
    assert decision["chart_type"] in ("bar_chart", "comparison", "sunburst")


def test_no_viz_requested_returns_none():
    """When wants_viz is False, return None (existing fast paths handle it)."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import (
        _rule_based_decision,
    )

    decision = _rule_based_decision("RANKING", wants_viz=False, profile={
        "row_count": 1, "column_count": 1,
        "dimension_columns": [], "metric_columns": ["A"],
        "time_column": None, "has_time_series": False,
    })
    assert decision is None


def test_no_metrics_returns_none_for_llm_fallback():
    """When no metric columns detected, let LLM handle it."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import (
        _rule_based_decision,
    )

    decision = _rule_based_decision("RANKING", wants_viz=True, profile={
        "row_count": 1, "column_count": 1,
        "dimension_columns": ["A"], "metric_columns": [],
        "time_column": None, "has_time_series": False,
    })
    assert decision is None


def test_time_series_comparison_without_dimension_returns_none():
    """TIME_SERIES_COMPARISON without comparison_dimension should return None (LLM fallback)."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

    profile = {
        "row_count": 10, "column_count": 3,
        "dimension_columns": ["BranchName"], "metric_columns": ["Total"],
        "time_column": "DocumentDate", "has_time_series": True,
    }
    # No comparison_dimension → should fall through to LLM
    result = _rule_based_decision("TIME_SERIES_COMPARISON", wants_viz=True, profile=profile)
    assert result is None
