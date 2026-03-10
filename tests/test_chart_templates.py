"""Test dynamic Plotly chart template engine."""
import pytest


@pytest.fixture
def sample_results():
    return [
        {"BranchName": "İstanbul", "TotalSales": 50000},
        {"BranchName": "Ankara", "TotalSales": 35000},
        {"BranchName": "İzmir", "TotalSales": 28000},
    ]


@pytest.fixture
def column_metadata():
    return {
        "BranchName": {"description": "Şube Adı", "type": "string"},
        "TotalSales": {"description": "Toplam Satış (₺)", "type": "numeric"},
    }


def test_bar_chart_template(sample_results, column_metadata):
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    viz_decision = {
        "chart_type": "bar_chart", "x_field": "BranchName", "y_field": "TotalSales",
        "series_field": None, "title": "Şube Satış Raporu",
    }
    html = build_chart(viz_decision, sample_results, column_metadata)
    assert html is not None
    assert "plotly" in html.lower()
    assert "Şube Satış Raporu" in html


def test_line_chart_template():
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    results = [
        {"Month": "2026-01", "Revenue": 5000},
        {"Month": "2026-02", "Revenue": 6000},
        {"Month": "2026-03", "Revenue": 7500},
    ]
    viz_decision = {
        "chart_type": "line_chart", "x_field": "Month", "y_field": "Revenue",
        "series_field": None, "title": "Aylık Gelir",
    }
    html = build_chart(viz_decision, results, {})
    assert html is not None
    assert "plotly" in html.lower()


def test_pie_chart_template():
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    results = [
        {"Category": "A", "Count": 30},
        {"Category": "B", "Count": 50},
        {"Category": "C", "Count": 20},
    ]
    viz_decision = {
        "chart_type": "pie_chart", "x_field": "Category", "y_field": "Count",
        "series_field": None, "title": "Kategori Dağılımı",
    }
    html = build_chart(viz_decision, results, {})
    assert html is not None
    assert "plotly" in html.lower()


def test_grouped_bar_with_series():
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    results = [
        {"Branch": "A", "Category": "X", "Total": 100},
        {"Branch": "A", "Category": "Y", "Total": 150},
        {"Branch": "B", "Category": "X", "Total": 200},
        {"Branch": "B", "Category": "Y", "Total": 250},
    ]
    viz_decision = {
        "chart_type": "bar_chart", "x_field": "Branch", "y_field": "Total",
        "series_field": "Category", "title": "Karşılaştırma",
    }
    html = build_chart(viz_decision, results, {})
    assert html is not None
    assert "plotly" in html.lower()


def test_horizontal_bar_for_many_rows():
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    results = [{"Name": f"Item {i}", "Value": i * 10} for i in range(20)]
    viz_decision = {
        "chart_type": "bar_chart", "x_field": "Name", "y_field": "Value",
        "series_field": None, "title": "Top 20",
    }
    html = build_chart(viz_decision, results, {})
    assert html is not None


def test_unsupported_chart_type_returns_none():
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    viz_decision = {
        "chart_type": "unknown_exotic_chart", "x_field": "A", "y_field": "B",
        "series_field": None, "title": "Test",
    }
    html = build_chart(viz_decision, [{"A": 1, "B": 2}], {})
    assert html is None


def test_column_metadata_used_as_labels(sample_results, column_metadata):
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    viz_decision = {
        "chart_type": "bar_chart", "x_field": "BranchName", "y_field": "TotalSales",
        "series_field": None, "title": "Test",
    }
    html = build_chart(viz_decision, sample_results, column_metadata)
    assert "Şube Adı" in html or "Şube" in html
    assert "Toplam Satış" in html


def test_scatter_chart_template():
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    results = [{"X": i, "Y": i**2} for i in range(5)]
    viz_decision = {
        "chart_type": "scatter", "x_field": "X", "y_field": "Y",
        "series_field": None, "title": "Scatter",
    }
    html = build_chart(viz_decision, results, {})
    assert html is not None


def test_treemap_template():
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    results = [
        {"Category": "A", "Value": 100},
        {"Category": "B", "Value": 200},
        {"Category": "C", "Value": 300},
    ]
    viz_decision = {
        "chart_type": "treemap", "x_field": "Category", "y_field": "Value",
        "series_field": None, "title": "Treemap Test",
    }
    html = build_chart(viz_decision, results, {})
    assert html is not None
    assert "plotly" in html.lower()


def test_sunburst_template():
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    results = [
        {"Category": "A", "Value": 100},
        {"Category": "B", "Value": 200},
    ]
    viz_decision = {
        "chart_type": "sunburst", "x_field": "Category", "y_field": "Value",
        "series_field": None, "title": "Sunburst Test",
    }
    html = build_chart(viz_decision, results, {})
    assert html is not None
    assert "plotly" in html.lower()


def test_comparison_template():
    from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart
    results = [
        {"Branch": "A", "Category": "X", "Total": 100},
        {"Branch": "B", "Category": "Y", "Total": 200},
    ]
    viz_decision = {
        "chart_type": "comparison", "x_field": "Branch", "y_field": "Total",
        "series_field": "Category", "title": "Comparison Test",
    }
    html = build_chart(viz_decision, results, {})
    assert html is not None
    assert "plotly" in html.lower()
