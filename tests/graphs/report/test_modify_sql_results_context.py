"""modify_sql_node'un active_results'ı prompt'a dahil ettiğini doğrula."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.graphs.report_agent.prompts import SQL_MODIFIER_PROMPT


def test_modifier_prompt_has_results_placeholder():
    """SQL_MODIFIER_PROMPT, {active_results} placeholder'ı içermeli."""
    assert "{active_results}" in SQL_MODIFIER_PROMPT


@pytest.mark.asyncio
async def test_modify_sql_node_includes_results_in_prompt():
    """modify_sql_node, active_results'ı prompt'a dahil etmeli."""
    from src.graphs.report_agent.nodes import create_modify_sql_node

    captured_prompt = {}

    class FakeResult:
        modified_sql = "SELECT 1"
        explanation = "test"
        modification_hints = []

    mock_structured_llm = MagicMock()
    async def capture_invoke(prompt):
        captured_prompt["value"] = prompt
        return FakeResult()
    mock_structured_llm.ainvoke = capture_invoke

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured_llm

    column_metadata = {"DocumentDate": "Satış tarihi", "ProductName": "Ürün adı"}
    node_fn = create_modify_sql_node(mock_llm, column_metadata)

    state = {
        "active_sql": "SELECT TOP 1 CAST(DocumentDate AS DATE) AS Tarih FROM T ORDER BY X DESC",
        "active_filters": [],
        "active_results": [{"Tarih": "2026-02-15", "ToplamSatis": 50000}],
        "user_query": "bu gün gelen satışları göster",
    }

    await node_fn(state)

    prompt_text = captured_prompt["value"]
    assert "2026-02-15" in prompt_text, \
        "active_results'taki tarih değeri prompt'ta görünmeli"
    assert "50000" in prompt_text or "50000" in str(prompt_text), \
        "active_results'taki değer prompt'ta görünmeli"
