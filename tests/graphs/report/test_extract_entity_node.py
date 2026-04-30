"""Tests for extract_entity_node — modify_context path."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_llm_mock(entity_names: list, entity_type: str, new_query_seed: str):
    """EntityExtractionResult döndüren mock LLM oluştur."""
    from src.graphs.report_agent.prompts import EntityExtractionResult
    mock_result = EntityExtractionResult(
        entity_names=entity_names,
        entity_type=entity_type,
        new_query_seed=new_query_seed,
    )
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=mock_result)
    mock_llm.with_structured_output = MagicMock(return_value=structured)
    return mock_llm


@pytest.fixture
def make_node_with_result():
    """EntityExtractionResult ile mock LLM oluşturup node döndüren fixture."""
    from src.graphs.report_agent.nodes import create_extract_entity_node

    def _factory(result):
        mock_llm = MagicMock()
        structured = MagicMock()
        structured.ainvoke = AsyncMock(return_value=result)
        mock_llm.with_structured_output = MagicMock(return_value=structured)
        return create_extract_entity_node(mock_llm)

    return _factory


@pytest.mark.asyncio
async def test_new_query_path_unchanged():
    """use_result_type=new_query => new_query_seed olarak user_query döner (eski davranis)."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    llm = _make_llm_mock(["KLASIK DURUM"], "product", "KLASIK DURUM'un sehirlere gore satislari")
    node = create_extract_entity_node(llm)
    state = {
        "active_results": [{"ProductName": "KLASIK DURUM", "TotalAmount": 34617}],
        "user_query": "bu urunun detaylarina bak",
        "use_result_type": "new_query",
    }
    result = await node(state)
    assert result["user_query"] == "KLASIK DURUM'un sehirlere gore satislari"


@pytest.mark.asyncio
async def test_modify_context_enriches_query():
    """use_result_type=modify_context => entity adi user_query'ye inject edilir."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    llm = _make_llm_mock(["KLASIK DURUM"], "product", "KLASIK DURUM'un sehirlere gore satislari")
    node = create_extract_entity_node(llm)
    state = {
        "active_results": [{"ProductName": "KLASIK DURUM", "TotalAmount": 34617}],
        "user_query": "bu urun icin sehirlere gore kir",
        "use_result_type": "modify_context",
    }
    result = await node(state)
    # Enriched query hem entity adini hem de orijinal istegi icermeli
    assert "KLASIK DURUM" in result["user_query"]
    assert "sehirlere gore kir" in result["user_query"]


@pytest.mark.asyncio
async def test_empty_results_fallback():
    """active_results bossa NEW_QUERY'ye fallback."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    llm = _make_llm_mock(["X"], "product", "X sorgusu")
    node = create_extract_entity_node(llm)
    state = {"active_results": [], "user_query": "test", "use_result_type": "new_query"}
    result = await node(state)
    assert result.get("intent_type") == "NEW_QUERY"


def test_extract_entity_plural_new_query_uses_seed(make_node_with_result):
    """Cogul entity seciminde new_query_seed oldugu gibi user_query olmali."""
    from src.graphs.report_agent.prompts import EntityExtractionResult

    result = EntityExtractionResult(
        entity_names=["LATTE", "FINCAN CAY", "LAS VEGAS UC PEYNIRLI BAGEL"],
        entity_type="product",
        new_query_seed="LATTE, FINCAN CAY ve LAS VEGAS UC PEYNIRLI BAGEL urunlerinin gunluk satisi",
    )
    # make_node_with_result fixture'ini kullanarak node olustur (dosyada zaten var)
    node = make_node_with_result(result)
    state = {
        "active_results": [
            {"ProductName": "LATTE", "ToplamCiro": 45000.0},
        ],
        "user_query": "bu 3 urunu grafik olarak goster",
        "use_result_type": "new_query",
    }
    output = asyncio.run(node(state))
    assert output["user_query"] == "LATTE, FINCAN CAY ve LAS VEGAS UC PEYNIRLI BAGEL urunlerinin gunluk satisi"
