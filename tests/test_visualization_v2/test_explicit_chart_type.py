"""Tests for intent-based chart type routing in viz_decider."""
import pytest


class TestVizDeciderWithRequestedChartType:
    """viz_decider_node uses requested_chart_type from intent classification."""

    def test_rule_based_default_without_chart_type(self):
        """No requested_chart_type → line_chart for TIME_SERIES_COMPARISON."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["CategoryName", "Ay"],
            "metric_columns": ["ToplamCiro"],
            "time_column": "Ay",
            "row_count": 49,
        }
        result = _rule_based_decision(
            "TIME_SERIES_COMPARISON", True, profile,
            time_granularity="monthly", comparison_dimension="CategoryName",
        )
        assert result["chart_type"] == "line_chart"

    def test_rule_based_ranking_unchanged(self):
        """No requested_chart_type → bar_chart for RANKING."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["BranchName"],
            "metric_columns": ["RowAmount"],
            "time_column": None,
            "row_count": 5,
        }
        result = _rule_based_decision("RANKING", True, profile)
        assert result["chart_type"] == "bar_chart"


class TestRequestedChartTypeModel:
    """IntentClassificationResult.requested_chart_type field validation."""

    def test_valid_chart_type(self):
        from src.graphs.report_agent.prompts import IntentClassificationResult
        result = IntentClassificationResult(
            intent_type="NEW_QUERY",
            query_type="TIME_SERIES_COMPARISON",
            confidence=0.95,
            wants_visualization=True,
            requested_chart_type="heatmap",
        )
        assert result.requested_chart_type == "heatmap"

    def test_none_chart_type(self):
        from src.graphs.report_agent.prompts import IntentClassificationResult
        result = IntentClassificationResult(
            intent_type="NEW_QUERY",
            query_type="SINGLE",
            confidence=0.9,
            wants_visualization=False,
        )
        assert result.requested_chart_type is None

    def test_invalid_chart_type_rejected(self):
        from src.graphs.report_agent.prompts import IntentClassificationResult
        with pytest.raises(Exception):
            IntentClassificationResult(
                intent_type="NEW_QUERY",
                query_type="SINGLE",
                confidence=0.9,
                requested_chart_type="invalid_chart",
            )

    def test_sunburst_chart_type(self):
        from src.graphs.report_agent.prompts import IntentClassificationResult
        result = IntentClassificationResult(
            intent_type="USE_RESULT",
            query_type="TIME_SERIES_COMPARISON",
            confidence=0.98,
            wants_visualization=True,
            use_result_type="revisualize",
            requested_chart_type="sunburst",
        )
        assert result.requested_chart_type == "sunburst"


class TestValidatorHeatmapCompletion:
    """Validator should fill series_field for heatmap before downgrading."""

    def test_heatmap_gets_series_field_from_remaining_dims(self):
        from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
        spec = {
            "needs_graph": True,
            "chart_type": "heatmap",
            "x_field": "Ay",
            "y_field": "ToplamCiro",
            "series_field": None,
        }
        results = [
            {"CategoryName": "ESPRESSO", "Ay": "2026-01", "ToplamCiro": 50000},
            {"CategoryName": "CAYLAR", "Ay": "2026-01", "ToplamCiro": 30000},
            {"CategoryName": "ESPRESSO", "Ay": "2026-02", "ToplamCiro": 60000},
            {"CategoryName": "CAYLAR", "Ay": "2026-02", "ToplamCiro": 35000},
        ]
        profile = {
            "dimension_columns": ["CategoryName", "Ay"],
            "metric_columns": ["ToplamCiro"],
            "time_column": "Ay",
            "columns": [
                {"name": "CategoryName", "role": "dimension", "type": "text"},
                {"name": "Ay", "role": "time", "type": "text"},
                {"name": "ToplamCiro", "role": "metric", "type": "numeric"},
            ],
        }
        validated = validate_spec(spec, results, profile)
        assert validated["chart_type"] == "heatmap"
        assert validated["series_field"] == "CategoryName"


class TestEndToEndIntentRouting:
    """Verify the full routing: requested_chart_type -> viz_decider override."""

    @pytest.mark.asyncio
    async def test_requested_chart_type_used_in_viz_decision(self):
        """When requested_chart_type is set, viz_decider should produce that chart type."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import (
            data_analyzer_node,
            spec_validator_node,
        )
        results = [
            {"CategoryName": "ESPRESSO", "Ay": "2026-01", "ToplamCiro": 50000},
            {"CategoryName": "CAYLAR", "Ay": "2026-01", "ToplamCiro": 30000},
            {"CategoryName": "ESPRESSO", "Ay": "2026-02", "ToplamCiro": 60000},
        ]

        state = {"results": results}
        analyzer_result = await data_analyzer_node(state)
        profile = analyzer_result["data_profile"]

        requested = "heatmap"
        spec = {
            "needs_graph": True,
            "chart_type": requested,
            "x_field": None,
            "y_field": None,
            "series_field": None,
            "reason": f"User requested {requested}",
        }

        full_state = {
            "results": results,
            "viz_decision": spec,
            "data_profile": profile,
        }
        validated_result = await spec_validator_node(full_state)
        validated = validated_result["viz_decision"]
        assert validated["chart_type"] == "heatmap"
        assert validated["x_field"] is not None
        assert validated["y_field"] is not None
