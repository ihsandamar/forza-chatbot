import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import HumanMessage

from src.graphs.report_agent.prompts import IntentClassificationResult


def _make_llm_mock(intent_type: str, query_type: str = "RANKING", wants_viz: bool = False) -> MagicMock:
    result = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=0.95,
        wants_visualization=wants_viz,
    )
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result)
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


@pytest.mark.asyncio
async def test_active_filters_preserved_on_modify_query():
    """MODIFY_QUERY'de active_filters state'den taşınmalı."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("MODIFY_QUERY")
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Ankara'yı ekle")],
        "active_sql": "SELECT * FROM T",
        "active_results": [{"BranchName": "Ankara", "RowAmount": 100}],
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["active_filters"] == [{"field": "CategoryName", "value": "Dürüm"}]


@pytest.mark.asyncio
async def test_active_filters_cleared_on_new_query():
    """NEW_QUERY'de active_filters temizlenmeli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("NEW_QUERY")
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Tüm şubeleri listele")],
        "active_sql": "SELECT * FROM T WHERE CategoryName='Dürüm'",
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["active_filters"] is None


@pytest.mark.asyncio
async def test_active_filters_none_when_state_empty():
    """State'de active_filters yoksa MODIFY_QUERY'de de None gelmeli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("MODIFY_QUERY")
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Limit'i 20 yap")],
        "active_sql": "SELECT * FROM T",
        "active_filters": None,
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["active_filters"] is None
