"""
Unit tests for chart type keyword detection in viz_decider.

These symbols were moved from report_agent/nodes.py to
visualization_v2/nodes.py as part of Task 11 (SRP: grafik kararı tek yerde).
"""


def test_chart_keyword_map_in_viz_decider():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _CHART_KEYWORD_MAP
    assert "sunburst" in _CHART_KEYWORD_MAP
    assert "pasta" in _CHART_KEYWORD_MAP


def test_detect_chart_type_from_query_in_viz_decider():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _detect_chart_type_from_query
    assert _detect_chart_type_from_query("pasta grafik istiyorum") == "pie_chart"
    assert _detect_chart_type_from_query("sunbrust") == "sunburst"
    assert _detect_chart_type_from_query("normal tablo") is None
