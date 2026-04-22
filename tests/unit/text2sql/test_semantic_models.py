import pytest


def test_semantic_intent_defaults():
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticIntent
    intent = SemanticIntent(raw_query="test sorgusu")
    assert intent.entities == []
    assert intent.metrics == []
    assert intent.time is None
    assert intent.order_direction == "DESC"
    assert intent.limit is None


def test_semantic_entity_validation():
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity
    e = SemanticEntity(raw_text="dürümler", entity_type="filter_value")
    assert e.column_hint is None


def test_term_match_dataclass():
    from src.graphs.report_agent.subagents.text2sql.semantic_models import TermMatch
    m = TermMatch(column_name="CategoryName", filter_structured=None,
                  specificity=1.0, similarity=0.92)
    assert m.column_name == "CategoryName"
    assert m.filter_structured is None
