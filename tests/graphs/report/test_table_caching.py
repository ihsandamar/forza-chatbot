"""Tests for session-based table caching in report_agent/text2sql."""
import pytest

from src.graphs.report_agent.table_registry import TableRegistry


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
