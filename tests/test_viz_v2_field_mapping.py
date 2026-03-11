import pytest
from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec


class TestTimeColumnGranularity:
    def test_hafta_preferred_over_yil(self):
        data = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 40, "ToplamSatis": 73360.02},
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 41, "ToplamSatis": 140550},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 40, "ToplamSatis": 28132.72},
        ]
        analyzer = DataAnalyzer()
        result = analyzer.analyze({"raw_data": data})
        profile = result["data_profile"]
        assert profile["time_column"] == "Hafta"
        assert "Yil" in profile.get("time_columns", [])

    def test_ay_preferred_over_yil(self):
        data = [
            {"Yil": 2025, "Ay": 1, "Tutar": 100},
            {"Yil": 2025, "Ay": 2, "Tutar": 200},
        ]
        analyzer = DataAnalyzer()
        result = analyzer.analyze({"raw_data": data})
        profile = result["data_profile"]
        assert profile["time_column"] == "Ay"

    def test_single_time_column_unchanged(self):
        data = [
            {"ProductName": "LATTE", "Hafta": 40, "ToplamSatis": 100},
            {"ProductName": "LATTE", "Hafta": 41, "ToplamSatis": 200},
        ]
        analyzer = DataAnalyzer()
        result = analyzer.analyze({"raw_data": data})
        profile = result["data_profile"]
        assert profile["time_column"] == "Hafta"

    def test_date_type_still_preferred_over_numeric_time(self):
        data = [
            {"Tarih": "2025-01-15", "Yil": 2025, "Tutar": 100},
            {"Tarih": "2025-02-15", "Yil": 2025, "Tutar": 200},
        ]
        analyzer = DataAnalyzer()
        result = analyzer.analyze({"raw_data": data})
        profile = result["data_profile"]
        assert profile["time_column"] == "Tarih"


class TestRuleBasedDecision:
    def test_time_series_comparison_falls_to_llm(self):
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "metric_columns": ["ToplamSatis"],
            "time_column": "Hafta",
            "time_columns": ["Hafta", "Yil"],
            "dimension_columns": ["ProductName", "Yil"],
            "has_multiple_dimensions": True,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
        )
        assert result is None

    def test_simple_time_series_still_rule_based(self):
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "metric_columns": ["ToplamSatis"],
            "time_column": "Hafta",
            "dimension_columns": [],
            "has_multiple_dimensions": False,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES",
            wants_viz=True,
            profile=profile,
        )
        assert result is not None
        assert result["chart_type"] == "line_chart"

    def test_ranking_still_rule_based(self):
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "metric_columns": ["ToplamSatis"],
            "time_column": None,
            "dimension_columns": ["ProductName"],
            "has_multiple_dimensions": False,
        }
        result = _rule_based_decision(
            query_type="RANKING",
            wants_viz=True,
            profile=profile,
        )
        assert result is not None
        assert result["chart_type"] == "bar_chart"
