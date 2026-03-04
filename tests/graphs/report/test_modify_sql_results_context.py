"""modify_sql_node'un active_results'ı prompt'a dahil ettiğini ve
DocumentDate datetime CAST post-processing uyguladığını doğrula."""
import json
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.graphs.report_agent.prompts import SQL_MODIFIER_PROMPT
from src.graphs.report_agent.subagents.text2sql.sql_builder import _resolve_date_filter


def test_modifier_prompt_has_results_placeholder():
    """SQL_MODIFIER_PROMPT, {active_results} placeholder'ı içermeli."""
    assert "{active_results}" in SQL_MODIFIER_PROMPT


def test_modifier_prompt_has_cast_instruction():
    """SQL_MODIFIER_PROMPT, CAST([DocumentDate] AS DATE) talimatı içermeli."""
    assert "CAST([DocumentDate] AS DATE)" in SQL_MODIFIER_PROMPT


# ---------------------------------------------------------------------------
# Helper: mock LLM setup
# ---------------------------------------------------------------------------
def _make_mock_llm(modified_sql: str):
    """Returns (mock_llm, captured_prompt_dict)."""
    captured = {}

    class FakeResult:
        explanation = "test"
        modification_hints = []

    FakeResult.modified_sql = modified_sql

    mock_structured = MagicMock()
    async def capture_invoke(prompt):
        captured["value"] = prompt
        return FakeResult()
    mock_structured.ainvoke = capture_invoke

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    return mock_llm, captured


@pytest.mark.asyncio
async def test_modify_sql_node_includes_results_in_prompt():
    """modify_sql_node, active_results'ı prompt'a dahil etmeli."""
    from src.graphs.report_agent.nodes import create_modify_sql_node

    mock_llm, captured = _make_mock_llm("SELECT 1")
    column_metadata = {"DocumentDate": "Satış tarihi", "ProductName": "Ürün adı"}
    node_fn = create_modify_sql_node(mock_llm, column_metadata)

    state = {
        "active_sql": "SELECT TOP 1 CAST(DocumentDate AS DATE) AS Tarih FROM T ORDER BY X DESC",
        "active_filters": [],
        "active_results": [{"Tarih": "2026-02-15", "ToplamSatis": 50000}],
        "user_query": "bu gün gelen satışları göster",
    }

    await node_fn(state)

    prompt_text = captured["value"]
    assert "2026-02-15" in prompt_text, \
        "active_results'taki tarih değeri prompt'ta görünmeli"
    assert "50000" in prompt_text or "50000" in str(prompt_text), \
        "active_results'taki değer prompt'ta görünmeli"


@pytest.mark.asyncio
async def test_modify_sql_node_casts_document_date_equality():
    """LLM [DocumentDate] = '...' üretirse, post-processing CAST eklemeli."""
    from src.graphs.report_agent.nodes import create_modify_sql_node

    raw_sql = (
        "SELECT [ProductName], SUM([RowAmount]) AS Toplam "
        "FROM [T] WHERE [DocumentDate] = '2026-02-15' "
        "GROUP BY [ProductName]"
    )
    mock_llm, _ = _make_mock_llm(raw_sql)
    node_fn = create_modify_sql_node(mock_llm, {})

    state = {"active_sql": "SELECT 1", "user_query": "test"}
    result = await node_fn(state)

    sql = result["pre_built_sql"]
    assert "CAST([DocumentDate] AS DATE) =" in sql, f"CAST eklenmeli: {sql}"
    assert "[DocumentDate] = " not in sql, f"Raw equality kalmamalı: {sql}"


@pytest.mark.asyncio
async def test_modify_sql_node_casts_document_date_between():
    """LLM [DocumentDate] BETWEEN '...' üretirse, post-processing CAST eklemeli."""
    from src.graphs.report_agent.nodes import create_modify_sql_node

    raw_sql = (
        "SELECT 1 FROM [T] WHERE [DocumentDate] BETWEEN '2026-02-01' AND '2026-02-28'"
    )
    mock_llm, _ = _make_mock_llm(raw_sql)
    node_fn = create_modify_sql_node(mock_llm, {})

    state = {"active_sql": "SELECT 1", "user_query": "test"}
    result = await node_fn(state)

    sql = result["pre_built_sql"]
    assert "CAST([DocumentDate] AS DATE) BETWEEN" in sql, f"CAST eklenmeli: {sql}"


@pytest.mark.asyncio
async def test_modify_sql_node_no_double_cast():
    """Zaten CAST varsa tekrar eklememeli."""
    from src.graphs.report_agent.nodes import create_modify_sql_node

    already_cast = (
        "SELECT 1 FROM [T] WHERE CAST([DocumentDate] AS DATE) = '2026-02-15'"
    )
    mock_llm, _ = _make_mock_llm(already_cast)
    node_fn = create_modify_sql_node(mock_llm, {})

    state = {"active_sql": "SELECT 1", "user_query": "test"}
    result = await node_fn(state)

    sql = result["pre_built_sql"]
    assert sql.count("CAST") == 1, f"Double CAST olmamalı: {sql}"


# ---------------------------------------------------------------------------
# sql_builder: _resolve_date_filter exact type CAST testi
# ---------------------------------------------------------------------------
def test_sql_builder_exact_date_uses_cast():
    """sql_builder _resolve_date_filter exact type CAST([col] AS DATE) kullanmalı."""
    result = _resolve_date_filter(
        "[DocumentDate]",
        {"type": "exact", "value": "2026-02-15"},
        "=",
        date(2026, 3, 4),
    )
    assert "CAST([DocumentDate] AS DATE)" in result, f"CAST olmalı: {result}"
    assert "2026-02-15" in result
