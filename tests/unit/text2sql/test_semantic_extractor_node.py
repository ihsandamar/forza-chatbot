import pytest
from unittest.mock import AsyncMock, MagicMock


def test_semantic_extractor_node_writes_semantic_intent():
    """semantic_extractor_node writes model_dump() to state['semantic_intent']."""
    import asyncio
    from src.graphs.report_agent.subagents.text2sql.nodes import create_semantic_extractor_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    expected_intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="dürümler", entity_type="filter_value")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="dürümler ciro",
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=expected_intent)

    node = create_semantic_extractor_node(mock_llm)
    state = {
        "user_query": "dürümler ciro",
        "query_type": "SINGLE",
        "column_metadata": {},
        "messages": [],
        "sql_error": None,
    }
    result = asyncio.get_event_loop().run_until_complete(node(state))
    assert "semantic_intent" in result
    assert result["semantic_intent"]["raw_query"] == "dürümler ciro"


def test_schema_builder_node_writes_query_schema():
    """schema_builder_node converts semantic_intent + term_resolution → query_schema dict."""
    import asyncio
    from datetime import date
    from src.graphs.report_agent.subagents.text2sql.nodes import create_schema_builder_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticMetric, TermMatch,
    )
    intent = SemanticIntent(
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="ciro",
    )
    term_resolution = {"ciro": TermMatch(column_name="RowAmount", filter_structured=None,
                                         specificity=1.0, similarity=0.95)}
    state = {
        "semantic_intent": intent.model_dump(),
        "term_resolution": {"ciro": {"column_name": "RowAmount", "filter_structured": None,
                                      "specificity": 1.0, "similarity": 0.95}},
        "query_type": "SINGLE",
        "time_breakdown": False,
    }
    node = create_schema_builder_node()
    result = asyncio.get_event_loop().run_until_complete(node(state))
    assert "query_schema" in result
    assert result["query_schema"] is not None
