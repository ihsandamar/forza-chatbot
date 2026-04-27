"""modify_sql_node'un SqlDelta akışını ve DocumentDate CAST davranışını doğrula."""
import pytest
from unittest.mock import MagicMock

from src.graphs.report_agent.prompts import SQL_MODIFIER_PROMPT


def test_modifier_prompt_has_query_context_placeholder():
    assert "{query_context}" in SQL_MODIFIER_PROMPT


def test_modifier_prompt_no_longer_has_raw_results_placeholder():
    assert "{active_results}" not in SQL_MODIFIER_PROMPT


def test_modifier_prompt_has_cast_instruction():
    assert "CAST" in SQL_MODIFIER_PROMPT


def _make_mock_llm(delta_overrides: dict | None = None):
    """SqlDelta döndüren mock LLM oluştur."""
    captured: dict = {}

    class FakeDelta:
        explanation = "test"
        confidence = 0.9
        add_filters = []
        remove_filter_columns = []
        change_limit = None
        change_orderby = None
        change_groupby = None
        change_select = None

    if delta_overrides:
        for k, v in delta_overrides.items():
            setattr(FakeDelta, k, v)

    mock_structured = MagicMock()

    async def capture_invoke(prompt):
        captured["prompt"] = prompt
        return FakeDelta()

    mock_structured.ainvoke = capture_invoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    return mock_llm, captured


@pytest.mark.asyncio
async def test_modify_sql_node_includes_context_in_prompt():
    from src.graphs.report_agent.nodes import create_modify_sql_node

    mock_llm, captured = _make_mock_llm()
    node_fn = create_modify_sql_node(mock_llm, {"DocumentDate": "Tarih"})

    state = {
        "active_sql": "SELECT TOP 1 * FROM T ORDER BY X DESC",
        "active_filters": [{"field": "CategoryName", "value": "Kahve"}],
        "active_results": [{"ProductName": "Latte"}],
        "user_query": "bu ürünü listele",
        "messages": [],
    }
    await node_fn(state)

    assert "CategoryName = 'Kahve'" in captured["prompt"]
    assert "Latte" in captured["prompt"]


@pytest.mark.asyncio
async def test_modify_sql_node_returns_pre_built_sql():
    from src.graphs.report_agent.nodes import create_modify_sql_node
    from src.graphs.report_agent.prompts import FilterDelta

    mock_llm, _ = _make_mock_llm(
        delta_overrides={"add_filters": [FilterDelta(column="BranchName", operator="=", value="'Ankara'")]}
    )
    node_fn = create_modify_sql_node(mock_llm, {})

    state = {
        "active_sql": "SELECT TOP 10 [BranchName] FROM T WHERE [CategoryName] = 'Kahve' ORDER BY 1",
        "active_filters": [],
        "active_results": [],
        "user_query": "Ankara şubesi ekle",
        "messages": [],
    }
    result = await node_fn(state)

    assert "pre_built_sql" in result
    assert "[BranchName] = 'Ankara'" in result["pre_built_sql"]
    assert "[CategoryName] = 'Kahve'" in result["pre_built_sql"]


@pytest.mark.asyncio
async def test_modify_sql_node_derives_modification_hints():
    from src.graphs.report_agent.nodes import create_modify_sql_node
    from src.graphs.report_agent.prompts import FilterDelta

    mock_llm, _ = _make_mock_llm(
        delta_overrides={"add_filters": [FilterDelta(column="CategoryName", operator="=", value="'Dürümler'")]}
    )
    node_fn = create_modify_sql_node(mock_llm, {})

    state = {
        "active_sql": "SELECT TOP 10 * FROM T",
        "active_filters": [],
        "active_results": [],
        "user_query": "dürümler kategorisi",
        "messages": [],
    }
    result = await node_fn(state)

    hints = result.get("modification_hints", [])
    assert len(hints) == 1
    assert hints[0]["column"] == "CategoryName"
    assert hints[0]["embedded_value"] == "Dürümler"
