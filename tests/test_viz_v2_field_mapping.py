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


class TestValidatorSeriesField:
    def test_auto_fill_series_field_for_multi_dim(self):
        spec = {
            "needs_graph": True,
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": None,
        }
        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 40, "ToplamSatis": 100},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 40, "ToplamSatis": 200},
        ]
        profile = {
            "dimension_columns": ["ProductName", "Yil"],
            "metric_columns": ["ToplamSatis"],
            "time_column": "Hafta",
            "columns": [
                {"name": "ProductName", "role": "dimension", "type": "text"},
                {"name": "Yil", "role": "time", "type": "numeric"},
                {"name": "Hafta", "role": "time", "type": "numeric"},
                {"name": "ToplamSatis", "role": "metric", "type": "numeric"},
            ],
        }
        validated = validate_spec(spec, results, profile)
        assert validated["series_field"] == "ProductName"

    def test_no_auto_fill_when_series_already_set(self):
        spec = {
            "needs_graph": True,
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": "Yil",
        }
        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 40, "ToplamSatis": 100},
        ]
        profile = {
            "dimension_columns": ["ProductName", "Yil"],
            "metric_columns": ["ToplamSatis"],
            "time_column": "Hafta",
            "columns": [
                {"name": "ProductName", "role": "dimension", "type": "text"},
                {"name": "Yil", "role": "time", "type": "numeric"},
                {"name": "Hafta", "role": "time", "type": "numeric"},
                {"name": "ToplamSatis", "role": "metric", "type": "numeric"},
            ],
        }
        validated = validate_spec(spec, results, profile)
        assert validated["series_field"] == "Yil"

    def test_no_auto_fill_for_pie_chart(self):
        spec = {
            "needs_graph": True,
            "chart_type": "pie_chart",
            "x_field": "ProductName",
            "y_field": "ToplamSatis",
            "series_field": None,
        }
        results = [
            {"ProductName": "LATTE", "ToplamSatis": 100},
        ]
        profile = {
            "dimension_columns": ["ProductName"],
            "metric_columns": ["ToplamSatis"],
            "time_column": None,
            "columns": [
                {"name": "ProductName", "role": "dimension", "type": "text"},
                {"name": "ToplamSatis", "role": "metric", "type": "numeric"},
            ],
        }
        validated = validate_spec(spec, results, profile)
        assert validated["series_field"] is None


class TestCompositeTimeAxis:
    def test_yil_hafta_composite(self):
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
        spec = {
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": "ProductName",
            "needs_graph": True,
        }
        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 52, "ToplamSatis": 100},
            {"ProductName": "LATTE", "Yil": 2026, "Hafta": 1, "ToplamSatis": 200},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 52, "ToplamSatis": 150},
            {"ProductName": "AMERICANO", "Yil": 2026, "Hafta": 1, "ToplamSatis": 250},
        ]
        html = render_chart(spec, results, {})
        assert html is not None
        assert "2025" in html

    def test_yil_ay_composite(self):
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
        spec = {
            "chart_type": "line_chart",
            "x_field": "Ay",
            "y_field": "Tutar",
            "series_field": None,
            "needs_graph": True,
        }
        results = [
            {"Yil": 2025, "Ay": 12, "Tutar": 100},
            {"Yil": 2026, "Ay": 1, "Tutar": 200},
        ]
        html = render_chart(spec, results, {})
        assert html is not None
        assert "2025" in html

    def test_no_composite_without_yil(self):
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
        spec = {
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": None,
            "needs_graph": True,
        }
        results = [
            {"Hafta": 40, "ToplamSatis": 100},
            {"Hafta": 41, "ToplamSatis": 200},
        ]
        html = render_chart(spec, results, {})
        assert html is not None


class TestEndToEndFieldMapping:
    def test_full_pipeline_multi_product_weekly(self):
        """ProductName x Hafta x Yil -> multi-trace line chart with composite axis."""
        from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
        from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 50, "ToplamSatis": 312095.1},
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 51, "ToplamSatis": 364080.046},
            {"ProductName": "LATTE", "Yil": 2026, "Hafta": 1, "ToplamSatis": 263765.32},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 50, "ToplamSatis": 132010.1},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 51, "ToplamSatis": 178270.131},
            {"ProductName": "AMERICANO", "Yil": 2026, "Hafta": 1, "ToplamSatis": 129130.28},
        ]

        # Step 1: Data Analyzer
        analyzer = DataAnalyzer()
        profile = analyzer.analyze({"raw_data": results})["data_profile"]

        assert profile["time_column"] == "Hafta", f"Expected Hafta, got {profile['time_column']}"
        assert "ProductName" in profile["dimension_columns"]

        # Step 2: Simulate LLM decision (what LLM should produce)
        llm_spec = {
            "needs_graph": True,
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": "ProductName",
        }

        # Step 3: Validator
        validated = validate_spec(llm_spec, results, profile)

        assert validated["x_field"] == "Hafta"
        assert validated["y_field"] == "ToplamSatis"
        assert validated["series_field"] == "ProductName"
        assert validated["chart_type"] == "line_chart"

        # Step 4: Renderer
        html = render_chart(validated, results, {})

        assert html is not None
        assert "LATTE" in html
        assert "AMERICANO" in html
        assert "2025" in html

    def test_validator_safety_net_when_llm_misses_series(self):
        """LLM forgets series_field -> validator auto-fills it."""
        from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
        from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
        from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 50, "ToplamSatis": 100},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 50, "ToplamSatis": 200},
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 51, "ToplamSatis": 150},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 51, "ToplamSatis": 250},
        ]

        analyzer = DataAnalyzer()
        profile = analyzer.analyze({"raw_data": results})["data_profile"]

        # LLM forgot series_field
        llm_spec = {
            "needs_graph": True,
            "chart_type": "line_chart",
            "x_field": "Hafta",
            "y_field": "ToplamSatis",
            "series_field": None,
        }

        validated = validate_spec(llm_spec, results, profile)

        # Validator safety net: ProductName auto-filled
        assert validated["series_field"] == "ProductName"

        # Render should produce multi-trace
        html = render_chart(validated, results, {})
        assert html is not None
        assert "LATTE" in html
        assert "AMERICANO" in html

    def test_rule_based_returns_none_for_this_scenario(self):
        """Verify the rule-based path correctly falls back to LLM for this data."""
        from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

        results = [
            {"ProductName": "LATTE", "Yil": 2025, "Hafta": 50, "ToplamSatis": 100},
            {"ProductName": "AMERICANO", "Yil": 2025, "Hafta": 50, "ToplamSatis": 200},
        ]

        analyzer = DataAnalyzer()
        profile = analyzer.analyze({"raw_data": results})["data_profile"]

        rule_result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
        )
        # Should return None = LLM fallback
        assert rule_result is None
