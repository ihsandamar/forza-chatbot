def test_intent_type_includes_insight_request():
    from src.graphs.report_agent.prompts import IntentClassificationResult
    field = IntentClassificationResult.model_fields["intent_type"]
    annotation_str = str(field.annotation)
    assert "INSIGHT_REQUEST" in annotation_str
