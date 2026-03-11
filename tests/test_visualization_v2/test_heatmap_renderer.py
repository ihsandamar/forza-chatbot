"""Heatmap chart renderer tests."""
import pytest
from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart


@pytest.fixture
def heatmap_results():
    """Category x DayOfWeek cross-tabulation data (flat rows)."""
    return [
        {"CategoryName": "Durumler", "HaftaGunu": 1, "ToplamCiro": 5000},
        {"CategoryName": "Durumler", "HaftaGunu": 2, "ToplamCiro": 6000},
        {"CategoryName": "Durumler", "HaftaGunu": 3, "ToplamCiro": 5500},
        {"CategoryName": "Icecekler", "HaftaGunu": 1, "ToplamCiro": 2000},
        {"CategoryName": "Icecekler", "HaftaGunu": 2, "ToplamCiro": 2500},
        {"CategoryName": "Icecekler", "HaftaGunu": 3, "ToplamCiro": 3000},
        {"CategoryName": "Tatlilar", "HaftaGunu": 1, "ToplamCiro": 1000},
        {"CategoryName": "Tatlilar", "HaftaGunu": 2, "ToplamCiro": 1200},
        {"CategoryName": "Tatlilar", "HaftaGunu": 3, "ToplamCiro": 1100},
    ]


@pytest.fixture
def hour_product_results():
    """Product x HourOfDay data."""
    return [
        {"ProductName": "Latte", "Saat": h, "ToplamCiro": 100 + h * 10}
        for h in range(8, 12)
    ] + [
        {"ProductName": "Espresso", "Saat": h, "ToplamCiro": 80 + h * 5}
        for h in range(8, 12)
    ]


class TestHeatmapRenderer:

    def test_heatmap_basic_renders_html(self, heatmap_results):
        spec = {
            "chart_type": "heatmap",
            "needs_graph": True,
            "x_field": "HaftaGunu",
            "y_field": "ToplamCiro",
            "series_field": "CategoryName",
            "title": "Kategori x Hafta Gunu Ciro",
        }
        html = render_chart(spec, heatmap_results, {})
        assert html is not None
        assert "plotly" in html.lower()

    def test_heatmap_with_hour_product(self, hour_product_results):
        spec = {
            "chart_type": "heatmap",
            "needs_graph": True,
            "x_field": "Saat",
            "y_field": "ToplamCiro",
            "series_field": "ProductName",
            "title": "Urun x Saat Ciro",
        }
        html = render_chart(spec, hour_product_results, {})
        assert html is not None

    def test_heatmap_empty_results_returns_none(self):
        spec = {
            "chart_type": "heatmap",
            "needs_graph": True,
            "x_field": "HaftaGunu",
            "y_field": "ToplamCiro",
            "series_field": "CategoryName",
        }
        result = render_chart(spec, [], {})
        assert result is None

    def test_heatmap_missing_series_falls_back(self, heatmap_results):
        spec = {
            "chart_type": "heatmap",
            "needs_graph": True,
            "x_field": "HaftaGunu",
            "y_field": "ToplamCiro",
            "series_field": None,
        }
        result = render_chart(spec, heatmap_results, {})
        assert result is None
