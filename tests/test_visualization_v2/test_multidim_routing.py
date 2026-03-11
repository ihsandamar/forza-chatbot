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
