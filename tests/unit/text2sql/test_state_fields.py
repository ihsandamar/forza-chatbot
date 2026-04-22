"""Tests for Task 9 — state field additions/removals for NLU pipeline redesign."""


def test_text2sql_state_has_semantic_intent():
    from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState

    annotations = Text2SQLState.__annotations__
    assert "semantic_intent" in annotations, "semantic_intent missing from Text2SQLState"
    assert "term_resolution" in annotations, "term_resolution missing from Text2SQLState"
    assert "time_breakdown" in annotations, "time_breakdown missing from Text2SQLState"


def test_text2sql_state_removed_fields():
    from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState

    annotations = Text2SQLState.__annotations__
    assert "schema_validation" not in annotations, "schema_validation should be removed"
    assert "term_hints" not in annotations, "term_hints should be removed"


def test_report_state_has_semantic_fields():
    from src.graphs.report_agent.state import ReportState

    annotations = ReportState.__annotations__
    assert "semantic_intent" in annotations, "semantic_intent missing from ReportState"
    assert "term_resolution" in annotations, "term_resolution missing from ReportState"
    assert "time_breakdown" in annotations, "time_breakdown missing from ReportState"
