"""Integration tests verifying all speed optimizations work together."""
import pytest
import time


def test_viz_decider_skips_llm_for_ranking():
    """RANKING query should not trigger viz_decider LLM — rule-based path."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import (
        _rule_based_decision,
    )

    profile = {
        "row_count": 5, "column_count": 2,
        "dimension_columns": ["BranchName"], "metric_columns": ["Total"],
        "time_column": None, "has_time_series": False,
    }

    start = time.perf_counter()
    decision = _rule_based_decision("RANKING", wants_viz=True, profile=profile)
    duration = time.perf_counter() - start

    assert decision is not None
    assert decision["chart_type"] == "bar_chart"
    assert duration < 0.01, f"Rule-based decision took {duration:.4f}s, should be <10ms"


def test_chart_template_generates_fast():
    """Chart template should generate HTML in under 500ms (after warm-up)."""
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import (
        render_chart,
    )

    results = [{"Category": f"Cat{i}", "Amount": i * 1000} for i in range(10)]
    decision = {
        "chart_type": "bar_chart", "x_field": "Category", "y_field": "Amount",
        "series_field": None, "title": "Test Chart",
    }

    # Warm-up call to ensure imports/JIT are not counted
    render_chart(decision, results, {})

    start = time.perf_counter()
    html = render_chart(decision, results, {})
    duration = time.perf_counter() - start

    assert html is not None
    assert duration < 0.5, f"Template generation took {duration:.4f}s, should be <500ms"


def test_all_chart_types_produce_html():
    """Every supported chart type should produce valid HTML."""
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import (
        render_chart,
        _BUILDERS,
    )

    results = [
        {"Dim": "A", "Dim2": "X", "Val": 100},
        {"Dim": "B", "Dim2": "Y", "Val": 200},
        {"Dim": "C", "Dim2": "Z", "Val": 300},
    ]

    for chart_type in _BUILDERS:
        # heatmap requires series_field (entity column) to build pivot table
        needs_series = chart_type in ("comparison", "heatmap")
        decision = {
            "chart_type": chart_type,
            "x_field": "Dim", "y_field": "Val",
            "series_field": "Dim2" if needs_series else None,
            "title": f"Test {chart_type}",
        }
        html = render_chart(decision, results, {})
        assert html is not None, f"{chart_type} returned None"
        assert "plotly" in html.lower(), f"{chart_type} missing plotly reference"


def test_rule_based_and_template_work_together():
    """viz_decider rule path should produce a decision that chart template can render."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import (
        _rule_based_decision,
    )
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import (
        render_chart,
    )

    results = [
        {"Month": "2026-01", "Revenue": 5000},
        {"Month": "2026-02", "Revenue": 6000},
        {"Month": "2026-03", "Revenue": 7500},
    ]
    profile = {
        "row_count": 3, "column_count": 2,
        "dimension_columns": ["Month"], "metric_columns": ["Revenue"],
        "time_column": "Month", "has_time_series": True,
    }

    # Step 1: Rule-based decision
    decision = _rule_based_decision("TIME_SERIES", wants_viz=True, profile=profile)
    assert decision is not None
    assert decision["chart_type"] == "line_chart"

    # Step 2: Fill in x/y fields from profile (spec_validator does this in prod)
    # and render with the chart template
    full_decision = {**decision, "x_field": "Month", "y_field": "Revenue"}
    html = render_chart(full_decision, results, {"Month": {"description": "Ay"}, "Revenue": {"description": "Gelir"}})
    assert html is not None
    assert "plotly" in html.lower()
