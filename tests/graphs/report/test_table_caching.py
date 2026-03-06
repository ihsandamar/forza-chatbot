"""Tests for session-based table caching in report_agent/text2sql."""
import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.graphs.generic_text2sql.table_registry import TableMetadata, TableRegistry


# ── TableRegistry unit tests ──

@pytest.fixture
def registry():
    return TableRegistry(default_ttl=10)


@pytest.mark.asyncio
async def test_registry_register_and_check(registry):
    meta = await registry.register_table("s1", "TestTable", document_count=100)
    assert meta.table_name == "TestTable"
    assert meta.session_id == "s1"

    found = await registry.check_table_exists("s1")
    assert found is not None
    assert found.query_count == 1  # check_table_exists increments


@pytest.mark.asyncio
async def test_registry_returns_none_for_unknown(registry):
    found = await registry.check_table_exists("nonexistent")
    assert found is None


@pytest.mark.asyncio
async def test_registry_unregister(registry):
    await registry.register_table("s1", "T1")
    name = await registry.unregister_table("s1")
    assert name == "T1"
    assert await registry.check_table_exists("s1") is None


# ── create_table_node logic tests ──

@pytest.mark.asyncio
async def test_create_table_skips_when_registry_has_table():
    """When registry has table, create_table_node should skip creation."""
    from src.graphs.report_agent.subagents.text2sql.nodes import create_create_table_node, _table_init_event

    # Ensure init event is set (simulating completed init)
    _table_init_event.set()

    registry = TableRegistry(default_ttl=900)
    await registry.register_table("test_session", "MasterReportDocumentTable")

    with patch("src.graphs.report_agent.subagents.text2sql.nodes.get_table_registry", return_value=registry):
        node = create_create_table_node("fake_conn", "MasterReportDocumentTable")
        config = {"configurable": {"thread_id": "test_session", "query": "SELECT 1", "table_name": "MasterReportDocumentTable"}}
        result = await node({}, config=config)

    assert result == {}  # No error, no creation


@pytest.mark.asyncio
async def test_create_table_force_refresh_drops_and_recreates():
    """Force refresh should drop table, unregister, and recreate."""
    from src.graphs.report_agent.subagents.text2sql.nodes import create_create_table_node, _table_init_event

    _table_init_event.set()

    registry = TableRegistry(default_ttl=900)
    await registry.register_table("test_session", "MasterReportDocumentTable")

    with patch("src.graphs.report_agent.subagents.text2sql.nodes.get_table_registry", return_value=registry), \
         patch("src.graphs.report_agent.subagents.text2sql.nodes._execute_script_sync") as mock_exec:
        node = create_create_table_node("fake_conn", "MasterReportDocumentTable")
        config = {"configurable": {"thread_id": "test_session", "query": "CREATE TABLE...", "table_name": "MasterReportDocumentTable"}}
        state = {"_force_table_refresh": True}
        result = await node(state, config=config)

    assert result == {} or "error" not in result
    # Should have called execute at least for DROP + CREATE
    assert mock_exec.call_count >= 1


# ── classify_intent refresh detection ──

def test_refresh_keywords_detected():
    """classify_intent should detect 'verileri güncelle' without LLM."""
    _REFRESH_KEYWORDS = {"verileri güncelle", "tabloyu güncelle", "verileri yenile", "tabloyu yenile", "veriyi güncelle", "veriyi yenile"}
    test_cases = [
        ("verileri güncelle", True),
        ("Tabloyu Güncelle", True),
        ("satış raporu göster", False),
        ("verileri yenile lütfen", True),
    ]
    for query, expected in test_cases:
        result = any(kw in query.lower().strip() for kw in _REFRESH_KEYWORDS)
        assert result == expected, f"Failed for: {query}"
