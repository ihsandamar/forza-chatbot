import pytest
from matplotlib.figure import Figure

from src.graphs.report_agent.subagents.export_v1.chart_bridge import build_chart_figure

SAMPLE_BAR = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
    {"BranchName": "Izmir", "RowAmount": 28000},
]

SAMPLE_TIME = [
    {"DocumentDate": "2024-01-01", "RowAmount": 10000},
    {"DocumentDate": "2024-01-02", "RowAmount": 12000},
    {"DocumentDate": "2024-01-03", "RowAmount": 9000},
]


def test_build_bar_chart_returns_figure():
    viz = {"chart_type": "bar_chart", "x_field": "BranchName", "y_field": "RowAmount", "series_field": None, "title": "Şube Satışları"}
    fig = build_chart_figure(viz, SAMPLE_BAR)
    assert isinstance(fig, Figure)


def test_build_line_chart_returns_figure():
    viz = {"chart_type": "line_chart", "x_field": "DocumentDate", "y_field": "RowAmount", "series_field": None, "title": "Trend"}
    fig = build_chart_figure(viz, SAMPLE_TIME)
    assert isinstance(fig, Figure)


def test_empty_results_returns_none():
    viz = {"chart_type": "bar_chart", "x_field": "BranchName", "y_field": "RowAmount", "series_field": None}
    assert build_chart_figure(viz, []) is None


def test_none_viz_decision_returns_none():
    assert build_chart_figure(None, SAMPLE_BAR) is None


def test_fallback_chart_type_still_produces_figure():
    viz = {"chart_type": "sunburst", "x_field": "BranchName", "y_field": "RowAmount", "series_field": None}
    fig = build_chart_figure(viz, SAMPLE_BAR)
    assert isinstance(fig, Figure)
