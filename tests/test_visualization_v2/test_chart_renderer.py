"""Deterministic chart renderer tests — no LLM, no exec()."""
import pytest


@pytest.fixture
def bar_results():
    return [
        {"BranchName": "Istanbul", "TotalSales": 50000},
        {"BranchName": "Ankara", "TotalSales": 35000},
        {"BranchName": "Izmir", "TotalSales": 28000},
    ]


@pytest.fixture
def col_meta():
    return {
        "BranchName": "Sube adi",
        "TotalSales": "Toplam satis (TL)",
    }


def test_bar_chart_basic(bar_results, col_meta):
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    spec = {
        "chart_type": "bar_chart", "x_field": "BranchName", "y_field": "TotalSales",
        "title": "Sube Satis",
    }
    html = render_chart(spec, bar_results, col_meta)
    assert html is not None
    assert "plotly" in html.lower()


def test_bar_chart_horizontal():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [{"Name": f"Item{i}", "Val": i * 10} for i in range(20)]
    spec = {
        "chart_type": "bar_chart", "x_field": "Name", "y_field": "Val",
        "orientation": "h", "title": "Horizontal",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_bar_chart_multi_metric():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Branch": "A", "Sales": 100, "Qty": 5},
        {"Branch": "B", "Sales": 200, "Qty": 10},
    ]
    spec = {
        "chart_type": "bar_chart", "x_field": "Branch",
        "y_fields": ["Sales", "Qty"], "title": "Multi",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_line_chart():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Month": "2026-01", "Revenue": 5000},
        {"Month": "2026-02", "Revenue": 6000},
    ]
    spec = {
        "chart_type": "line_chart", "x_field": "Month", "y_field": "Revenue",
        "title": "Trend",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_line_chart_multi_metric():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Month": "2026-01", "Sales": 100, "Qty": 5},
        {"Month": "2026-02", "Sales": 200, "Qty": 10},
    ]
    spec = {
        "chart_type": "line_chart", "x_field": "Month",
        "y_fields": ["Sales", "Qty"], "title": "Multi line",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_pie_chart():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Category": "A", "Count": 30},
        {"Category": "B", "Count": 50},
        {"Category": "C", "Count": 20},
    ]
    spec = {
        "chart_type": "pie_chart", "x_field": "Category", "y_field": "Count",
        "title": "Dagilim",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_pie_chart_topn():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [{"Cat": f"C{i}", "Val": i} for i in range(20)]
    spec = {
        "chart_type": "pie_chart", "x_field": "Cat", "y_field": "Val",
        "top_n": 5, "title": "Top 5",
    }
    html = render_chart(spec, results, {})
    assert html is not None
    # top_n=5 filters to top 5 items only
    assert "C19" in html


def test_scatter_chart():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [{"X": i, "Y": i ** 2} for i in range(5)]
    spec = {"chart_type": "scatter_chart", "x_field": "X", "y_field": "Y", "title": "Scatter"}
    html = render_chart(spec, results, {})
    assert html is not None


def test_sunburst_with_hierarchy():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Category": "A", "Product": "P1", "Sales": 100},
        {"Category": "A", "Product": "P2", "Sales": 200},
        {"Category": "B", "Product": "P3", "Sales": 300},
    ]
    spec = {
        "chart_type": "sunburst",
        "hierarchy_fields": ["Category", "Product"],
        "y_field": "Sales", "title": "Hierarchy",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_treemap():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Category": "A", "Sales": 100},
        {"Category": "B", "Sales": 200},
    ]
    spec = {
        "chart_type": "treemap", "x_field": "Category", "y_field": "Sales",
        "title": "Treemap",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_comparison():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Branch": "A", "Period": "Q1", "Sales": 100},
        {"Branch": "A", "Period": "Q2", "Sales": 150},
        {"Branch": "B", "Period": "Q1", "Sales": 200},
    ]
    spec = {
        "chart_type": "comparison", "x_field": "Branch", "y_field": "Sales",
        "series_field": "Period", "title": "Compare",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_sort_by_applied():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    results = [
        {"Name": "C", "Val": 10},
        {"Name": "A", "Val": 30},
        {"Name": "B", "Val": 20},
    ]
    spec = {
        "chart_type": "bar_chart", "x_field": "Name", "y_field": "Val",
        "sort_by": "Val", "sort_order": "desc", "title": "Sorted",
    }
    html = render_chart(spec, results, {})
    assert html is not None


def test_unsupported_chart_type_returns_none():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    spec = {"chart_type": "unknown_type", "x_field": "A", "y_field": "B", "title": ""}
    html = render_chart(spec, [{"A": 1, "B": 2}], {})
    assert html is None


def test_empty_results_returns_none():
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    spec = {"chart_type": "bar_chart", "x_field": "A", "y_field": "B", "title": ""}
    html = render_chart(spec, [], {})
    assert html is None


def test_column_metadata_used_as_labels(bar_results, col_meta):
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
    spec = {
        "chart_type": "bar_chart", "x_field": "BranchName", "y_field": "TotalSales",
        "title": "Test",
    }
    html = render_chart(spec, bar_results, col_meta)
    assert "Sube adi" in html or "Sube" in html


def test_turkey_map_renders_with_mock_geojson():
    """turkey_map renders choropleth HTML when GeoJSON is available."""
    from unittest.mock import patch
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    _MINIMAL_GEOJSON = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[28.0, 41.0], [29.0, 41.0], [29.0, 42.0], [28.0, 42.0], [28.0, 41.0]]]
                },
                "properties": {"name": "İstanbul"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[32.0, 39.0], [33.0, 39.0], [33.0, 40.0], [32.0, 40.0], [32.0, 39.0]]]
                },
                "properties": {"name": "Ankara"},
            },
        ],
    }

    results = [
        {"BranchCityName": "Istanbul", "TotalSales": 50000},
        {"BranchCityName": "Ankara", "TotalSales": 35000},
    ]
    spec = {
        "chart_type": "turkey_map",
        "x_field": "BranchCityName",
        "y_field": "TotalSales",
        "title": "İl Bazında Satışlar",
    }

    with patch(
        "src.graphs.report_agent.subagents.visualization_v2.turkey_geo.load_turkey_geojson",
        return_value=_MINIMAL_GEOJSON,
    ):
        html = render_chart(spec, results, {})

    assert html is not None
    assert "plotly" in html.lower()


def test_turkey_map_returns_none_when_no_geojson():
    """turkey_map returns None gracefully when GeoJSON asset is missing."""
    from unittest.mock import patch
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    results = [{"BranchCityName": "Istanbul", "TotalSales": 50000}]
    spec = {
        "chart_type": "turkey_map",
        "x_field": "BranchCityName",
        "y_field": "TotalSales",
    }

    with patch(
        "src.graphs.report_agent.subagents.visualization_v2.turkey_geo.load_turkey_geojson",
        return_value=None,
    ):
        html = render_chart(spec, results, {})

    assert html is None


def test_turkey_map_returns_none_when_x_field_missing():
    """turkey_map returns None when spec has no x_field."""
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    results = [{"BranchCityName": "Istanbul", "TotalSales": 50000}]
    spec = {"chart_type": "turkey_map", "x_field": None, "y_field": "TotalSales"}
    html = render_chart(spec, results, {})
    assert html is None


def test_turkey_map_returns_none_when_no_rows_match_geojson():
    """turkey_map returns None when data city names don't match any GeoJSON province."""
    from unittest.mock import patch
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    _MINIMAL_GEOJSON = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[28.0, 41.0], [29.0, 41.0], [29.0, 42.0], [28.0, 42.0], [28.0, 41.0]]]
                },
                "properties": {"name": "İstanbul"},
            },
        ],
    }

    results = [{"BranchCityName": "XXXXUNKNOWNXXXX", "TotalSales": 100}]
    spec = {
        "chart_type": "turkey_map",
        "x_field": "BranchCityName",
        "y_field": "TotalSales",
    }

    with patch(
        "src.graphs.report_agent.subagents.visualization_v2.turkey_geo.load_turkey_geojson",
        return_value=_MINIMAL_GEOJSON,
    ):
        html = render_chart(spec, results, {})

    assert html is None
