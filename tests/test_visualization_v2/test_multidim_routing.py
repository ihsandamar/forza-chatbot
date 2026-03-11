"""Multi-dimensional visualization routing tests."""
import pytest


class TestComparisonDimensionPropagation:
    """comparison_dimension flows from text2sql → ReportState → VisualizationState."""

    def test_report_state_has_comparison_dimension_field(self):
        from src.graphs.report_agent.state import ReportState, create_initial_state
        state = create_initial_state()
        assert "comparison_dimension" in state
        assert state["comparison_dimension"] is None

    def test_visualization_state_accepts_comparison_dimension(self):
        from src.graphs.report_agent.subagents.visualization_v2.state import VisualizationState
        state: VisualizationState = {
            "results": [],
            "user_query": "test",
            "comparison_dimension": "CategoryName",
        }
        assert state["comparison_dimension"] == "CategoryName"


class TestSqlGeneratorPropagation:
    """sql_generator_node returns comparison_dimension in state output."""

    def test_text2sql_state_has_comparison_dimension_field(self):
        from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
        import typing
        hints = typing.get_type_hints(Text2SQLState)
        assert "comparison_dimension" in hints


# =========================================================================
# Task 6: _rule_based_decision routing tests
# =========================================================================

from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision


class TestAggregateWithEntity:
    """Aggregate period + comparison_dimension -> heatmap instead of bar_chart."""

    def test_aggregate_period_with_entity_returns_heatmap(self):
        """day_of_week + CategoryName -> heatmap (entity x period matrix)."""
        profile = {
            "row_count": 21,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": ["CategoryName"],
            "time_column": "HaftaGunu",
            "has_multiple_dimensions": True,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="day_of_week",
            comparison_dimension="CategoryName",
        )
        assert result is not None
        assert result["chart_type"] == "heatmap"
        assert result["x_field"] == "HaftaGunu"
        assert result["series_field"] == "CategoryName"

    def test_aggregate_period_without_entity_stays_bar(self):
        """day_of_week without entity -> bar_chart (simple distribution)."""
        profile = {
            "row_count": 7,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": [],
            "time_column": "HaftaGunu",
            "has_multiple_dimensions": False,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="day_of_week",
            comparison_dimension=None,
        )
        assert result is not None
        assert result["chart_type"] == "bar_chart"
        assert result["x_field"] == "HaftaGunu"


class TestTimeSeriesWithEntity:
    """TIME_SERIES_COMPARISON + entity -> multi-line chart."""

    def test_weekly_with_entity_returns_line_with_series(self):
        """weekly + CategoryName -> line_chart with series_field."""
        profile = {
            "row_count": 40,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": ["CategoryName"],
            "time_column": "Hafta",
            "has_multiple_dimensions": True,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="weekly",
            comparison_dimension="CategoryName",
        )
        assert result is not None
        assert result["chart_type"] == "line_chart"
        assert result["series_field"] == "CategoryName"

    def test_monthly_without_entity_returns_simple_line(self):
        """monthly without entity -> line_chart, no series_field."""
        profile = {
            "row_count": 12,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": [],
            "time_column": "Ay",
            "has_multiple_dimensions": False,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="monthly",
            comparison_dimension=None,
        )
        assert result is not None
        assert result["chart_type"] == "line_chart"
        assert result["series_field"] is None


class TestMultiDimensionHierarchy:
    """2+ non-time dimensions without time -> sunburst."""

    def test_two_dimensions_no_time_returns_sunburst(self):
        """CategoryName + ProductName -> sunburst (hierarchy)."""
        profile = {
            "row_count": 50,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": ["CategoryName", "ProductName"],
            "time_column": None,
            "has_multiple_dimensions": True,
        }
        result = _rule_based_decision(
            query_type="COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity=None,
            comparison_dimension=None,
        )
        assert result is not None
        assert result["chart_type"] == "sunburst"
        assert result["hierarchy_fields"] == ["CategoryName", "ProductName"]


class TestBackwardCompatibility:
    """Existing behavior preserved when new params are not provided."""

    def test_ranking_still_works_without_new_params(self):
        profile = {
            "row_count": 10,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": ["ProductName"],
            "time_column": None,
        }
        result = _rule_based_decision("RANKING", True, profile)
        assert result is not None
        assert result["chart_type"] == "bar_chart"

    def test_comparison_still_works_without_new_params(self):
        profile = {
            "row_count": 5,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": ["CategoryName"],
            "time_column": None,
        }
        result = _rule_based_decision("COMPARISON", True, profile)
        assert result is not None
        assert result["chart_type"] == "bar_chart"

    def test_time_series_comparison_without_comp_dim_with_dims_falls_to_llm(self):
        """When comparison_dimension=None but dimensions exist, fall to LLM."""
        profile = {
            "row_count": 40,
            "metric_columns": ["ToplamCiro"],
            "dimension_columns": ["CategoryName"],
            "time_column": "Hafta",
            "has_multiple_dimensions": True,
        }
        result = _rule_based_decision(
            query_type="TIME_SERIES_COMPARISON",
            wants_viz=True,
            profile=profile,
            time_granularity="weekly",
            comparison_dimension=None,
        )
        # Should return None = LLM fallback (dimensions exist but no comparison_dimension)
        assert result is None
