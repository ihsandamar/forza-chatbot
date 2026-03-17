"""Tests for LLM-based chart type detection routing.

Replaces the old regex-based TestDetectExplicitChartType and TestExplicitChartTypeOverride.
The LLM now handles chart type understanding — these tests verify the routing logic.
"""
import pytest


class TestHasVizPreference:
    """_has_viz_preference detects when user mentions a chart type, triggering LLM path."""

    def _check(self, query):
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _has_viz_preference
        return _has_viz_preference(query)

    # --- Should detect preference (broad keyword match) ---
    def test_heatmap(self):
        assert self._check("heatmap grafik ver") is True

    def test_sunburst_typo(self):
        """'sunbrust' contains 'sunbr' (5-char fragment in _VIZ_HINT_KEYWORDS) — typo tolerance."""
        assert self._check("sunbrust olarak goster") is True

    def test_turkish_grafik(self):
        """'grafik' is a generic viz keyword — triggers LLM regardless of chart type."""
        assert self._check("bunu grafik ver") is True

    def test_chart_english(self):
        assert self._check("show as pie chart") is True

    def test_turkish_harita(self):
        assert self._check("ısı haritası olarak göster") is True

    def test_diagram(self):
        assert self._check("diagram olarak goster") is True

    def test_cubuk(self):
        assert self._check("çubuk grafik göster") is True

    def test_treemap(self):
        assert self._check("treemap ver") is True

    def test_plot(self):
        assert self._check("scatter plot goster") is True

    # --- Should NOT detect preference (no chart type signal) ---
    def test_plain_data_query(self):
        assert self._check("son 3 aydaki satislari goster") is False

    def test_empty(self):
        assert self._check("") is False

    def test_none(self):
        assert self._check(None) is False

    def test_filter_query(self):
        assert self._check("sadece espresso kategorisini filtrele") is False


class TestShouldUseLLM:
    """_should_use_llm decides when to skip rule-based and route to LLM."""

    def _check(self, viz_request, user_query):
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _should_use_llm
        return _should_use_llm(viz_request, user_query)

    def test_viz_request_set_always_triggers_llm(self):
        """REVISUALIZE (viz_request set) always goes to LLM."""
        assert self._check("sunburst olarak ver", "sunburst olarak ver") is True

    def test_viz_request_with_any_text(self):
        """Any non-empty viz_request triggers LLM."""
        assert self._check("baska turlu goster", "baska turlu goster") is True

    def test_user_query_with_chart_keyword(self):
        """user_query with chart keyword -> LLM."""
        assert self._check(None, "kategorileri heatmap grafik olarak goster") is True

    def test_plain_query_uses_rule_based(self):
        """No chart preference -> rule-based path."""
        assert self._check(None, "son 3 aydaki satislari goster") is False

    def test_typo_sunbrust_triggers_llm(self):
        """'sunbrust' contains 'sunbur' fragment -> LLM."""
        assert self._check(None, "sunbrust grafik ver") is True

    def test_none_query_uses_rule_based(self):
        assert self._check(None, "") is False


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


class TestEndToEndLLMRouting:
    """Verify routing + rule-based still works for non-preference queries."""

    def test_plain_query_still_gets_rule_based_line_chart(self):
        """No chart keyword -> rule-based -> line_chart for TIME_SERIES_COMPARISON."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import (
            _should_use_llm,
            _rule_based_decision,
        )
        assert _should_use_llm(None, "son 3 aydaki satislari goster") is False

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

    @pytest.mark.asyncio
    async def test_validator_still_fills_fields_for_sunburst(self):
        """Validator field completion works regardless of routing path."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import spec_validator_node

        state = {
            "results": [
                {"CategoryName": "ESPRESSO", "Ay": "2026-01", "ToplamCiro": 50000},
                {"CategoryName": "CAYLAR", "Ay": "2026-01", "ToplamCiro": 30000},
            ],
            "viz_decision": {
                "needs_graph": True,
                "chart_type": "sunburst",
                "x_field": "Ay",
                "y_field": "ToplamCiro",
                "series_field": "CategoryName",
                "hierarchy_fields": ["CategoryName", "Ay"],
            },
            "data_profile": {
                "dimension_columns": ["CategoryName", "Ay"],
                "metric_columns": ["ToplamCiro"],
                "time_column": "Ay",
                "columns": [
                    {"name": "CategoryName", "role": "dimension", "type": "text"},
                    {"name": "Ay", "role": "time", "type": "text"},
                    {"name": "ToplamCiro", "role": "metric", "type": "numeric"},
                ],
            },
        }
        result = await spec_validator_node(state)
        validated = result["viz_decision"]
        assert validated["chart_type"] == "sunburst"
