"""Tests for extract_entity_node — modify_context path."""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_llm_mock(entity_name: str, entity_type: str, new_query_seed: str):
    """EntityExtractionResult döndüren mock LLM oluştur."""
    from src.graphs.report_agent.prompts import EntityExtractionResult
    mock_result = EntityExtractionResult(
        entity_name=entity_name,
        entity_type=entity_type,
        new_query_seed=new_query_seed,
    )
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=mock_result)
    mock_llm.with_structured_output = MagicMock(return_value=structured)
    return mock_llm


@pytest.mark.asyncio
async def test_new_query_path_unchanged():
    """use_result_type=new_query → new_query_seed olarak user_query döner (eski davranış)."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    llm = _make_llm_mock("KLASİK DÜRÜM", "product", "KLASİK DÜRÜM'ün şehirlere göre satışları")
    node = create_extract_entity_node(llm)
    state = {
        "active_results": [{"ProductName": "KLASİK DÜRÜM", "TotalAmount": 34617}],
        "user_query": "bu ürünün detaylarına bak",
        "use_result_type": "new_query",
    }
    result = await node(state)
    assert result["user_query"] == "KLASİK DÜRÜM'ün şehirlere göre satışları"


@pytest.mark.asyncio
async def test_modify_context_enriches_query():
    """use_result_type=modify_context → entity adı user_query'ye inject edilir."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    llm = _make_llm_mock("KLASİK DÜRÜM", "product", "KLASİK DÜRÜM'ün şehirlere göre satışları")
    node = create_extract_entity_node(llm)
    state = {
        "active_results": [{"ProductName": "KLASİK DÜRÜM", "TotalAmount": 34617}],
        "user_query": "bu ürün için şehirlere göre kır",
        "use_result_type": "modify_context",
    }
    result = await node(state)
    # Enriched query hem entity adını hem de orijinal isteği içermeli
    assert "KLASİK DÜRÜM" in result["user_query"]
    assert "şehirlere göre kır" in result["user_query"]


@pytest.mark.asyncio
async def test_empty_results_fallback():
    """active_results boşsa NEW_QUERY'ye fallback."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    llm = _make_llm_mock("X", "product", "X sorgusu")
    node = create_extract_entity_node(llm)
    state = {"active_results": [], "user_query": "test", "use_result_type": "new_query"}
    result = await node(state)
    assert result.get("intent_type") == "NEW_QUERY"
