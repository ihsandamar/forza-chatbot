"""
End-to-end integration tests for multi-dimensional visualization routing.
Tests the full pipeline: data_analyzer -> rule-based decision -> validator -> renderer.
No LLM calls -- uses rule-based path only.
"""
import pytest
from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
from src.graphs.report_agent.subagents.text2sql.nodes import AGGREGATE_PERIOD_GRANULARITIES


class TestHeatmapEndToEnd:
    """Category x DayOfWeek -> heatmap pipeline."""

    @pytest.fixture
    def category_dayofweek_data(self):
        """Simulates SQL output: CategoryName x HaftaGunu x ToplamCiro."""
        rows = []
        categories = ["Durumler", "Icecekler", "Tatlilar"]
        for cat in categories:
            for day in range(1, 8):
                rows.append({
                    "CategoryName": cat,
                    "HaftaGunu": day,
                    "ToplamCiro": 1000 + day * 100 + hash(cat) % 500,
                })
        return rows

    def test_full_pipeline_produces_heatmap_html(self, category_dayofweek_data):
        # Step 1: Analyze data
        analyzer = DataAnalyzer()
        profile_state = analyzer.analyze({"raw_data": category_dayofweek_data})
        profile = profile_state["data_profile"]

        # Step 2: Rule-based decision
        decision = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="day_of_week",
            comparison_dimension="CategoryName",
        )
        assert decision is not None
        assert decision["chart_type"] == "heatmap"

        # Step 3: Validate spec
        validated = validate_spec(decision, category_dayofweek_data, profile)
        assert validated["chart_type"] == "heatmap"
        assert validated["series_field"] == "CategoryName"

        # Step 4: Render
        html = render_chart(validated, category_dayofweek_data, {})
        assert html is not None
        assert "plotly" in html.lower()
        assert len(html) > 100


class TestMultiLineEndToEnd:
    """Category x weekly -> multi-line chart pipeline."""

    @pytest.fixture
    def category_weekly_data(self):
        rows = []
        for cat in ["Durumler", "Icecekler"]:
            for week in range(1, 5):
                rows.append({
                    "CategoryName": cat,
                    "Yil": 2026,
                    "Hafta": week,
                    "ToplamCiro": 5000 + week * 200,
                })
        return rows

    def test_full_pipeline_produces_multiline(self, category_weekly_data):
        analyzer = DataAnalyzer()
        profile_state = analyzer.analyze({"raw_data": category_weekly_data})
        profile = profile_state["data_profile"]

        decision = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="weekly",
            comparison_dimension="CategoryName",
        )
        assert decision is not None
        assert decision["chart_type"] == "line_chart"
        assert decision["series_field"] == "CategoryName"

        validated = validate_spec(decision, category_weekly_data, profile)
        assert validated["chart_type"] == "line_chart"

        html = render_chart(validated, category_weekly_data, {})
        assert html is not None


class TestSunburstEndToEnd:
    """Category + Product hierarchy -> sunburst pipeline."""

    @pytest.fixture
    def hierarchy_data(self):
        return [
            {"CategoryName": "Durumler", "ProductName": "Tavuk Durum", "ToplamCiro": 15000},
            {"CategoryName": "Durumler", "ProductName": "Et Durum", "ToplamCiro": 12000},
            {"CategoryName": "Icecekler", "ProductName": "Kola", "ToplamCiro": 8000},
            {"CategoryName": "Icecekler", "ProductName": "Ayran", "ToplamCiro": 5000},
            {"CategoryName": "Tatlilar", "ProductName": "Kunefe", "ToplamCiro": 6000},
        ]

    def test_full_pipeline_produces_sunburst(self, hierarchy_data):
        analyzer = DataAnalyzer()
        profile_state = analyzer.analyze({"raw_data": hierarchy_data})
        profile = profile_state["data_profile"]

        decision = _rule_based_decision(
            query_type="COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity=None,
            comparison_dimension=None,
        )
        assert decision is not None
        assert decision["chart_type"] == "sunburst"
        assert "CategoryName" in decision["hierarchy_fields"]
        assert "ProductName" in decision["hierarchy_fields"]

        validated = validate_spec(decision, hierarchy_data, profile)
        html = render_chart(validated, hierarchy_data, {})
        assert html is not None
