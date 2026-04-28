"""Tests for intent resolver changes: time_breakdown field and chart_type parallel LLM removal."""


def test_intent_classification_result_has_time_breakdown():
    from src.graphs.report_agent.prompts import IntentClassificationResult
    result = IntentClassificationResult(
        intent_type="NEW_QUERY",
        query_type="TIME_SERIES_COMPARISON",
        confidence=0.95,
        time_breakdown=True,
    )
    assert result.time_breakdown is True


def test_intent_classification_result_time_breakdown_defaults_false():
    from src.graphs.report_agent.prompts import IntentClassificationResult
    result = IntentClassificationResult(
        intent_type="NEW_QUERY", query_type="SINGLE", confidence=0.9,
    )
    assert result.time_breakdown is False
