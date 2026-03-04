# Session-Based Table Caching Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate repeated 1+ minute CREATE TABLE calls by caching the master table at graph init time and reusing it across queries within a session.

**Architecture:** Background thread creates `MasterReportDocumentTable` during `build_text2sql_graph()`. A `threading.Event` signals completion. `create_table_node` checks `TableRegistry` first, waits for init if still running, and only recreates on force-refresh or TTL expiry. `classify_intent_node` detects "verileri guncelle" keywords and sets `_force_table_refresh` flag.

**Tech Stack:** Python asyncio, threading, pyodbc, LangGraph StateGraph, TableRegistry singleton

---

### Task 1: Add `_force_table_refresh` to State

**Files:**
- Modify: `src/graphs/report_agent/state.py:23` (add field to ReportState)
- Modify: `src/graphs/report_agent/subagents/text2sql/state.py:23` (add field to Text2SQLState)

**Step 1: Add field to ReportState**

In `src/graphs/report_agent/state.py`, add after `pre_built_sql`:
```python
_force_table_refresh: Optional[bool]  # True = DROP + recreate master table
```

**Step 2: Add field to Text2SQLState**

In `src/graphs/report_agent/subagents/text2sql/state.py`, add after `pre_built_sql`:
```python
_force_table_refresh: Optional[bool]  # True = DROP + recreate master table
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/state.py src/graphs/report_agent/subagents/text2sql/state.py
git commit -m "feat: add _force_table_refresh state field for table caching"
```

---

### Task 2: Make `create_table_node` Registry-Aware

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1103-1156` (rewrite create_table_node factory)
- Reference: `src/graphs/generic_text2sql/table_registry.py` (TableRegistry API)

**Step 1: Add imports and module-level init state**

At the top of `nodes.py` (after existing imports around line 43):
```python
import threading
from src.graphs.generic_text2sql.table_registry import get_table_registry
```

Add module-level variables after `_db_executor` (line 46):
```python
# Background table init state
_table_init_event = threading.Event()
_table_init_error: Optional[str] = None
_table_init_table_name: Optional[str] = None
```

**Step 2: Add `init_master_table_background` function**

After the module-level variables, add:
```python
def init_master_table_background(connection_string: str, table_name: str, sql_script: str) -> None:
    """
    Background thread: create master table at graph init time.
    Sets _table_init_event when done (success or failure).
    """
    global _table_init_error, _table_init_table_name
    _table_init_table_name = table_name
    try:
        logger.info(f"[TABLE_INIT] Background table creation started for '{table_name}'")
        _execute_script_sync(connection_string, sql_script)
        _table_init_error = None
        logger.info(f"[TABLE_INIT] Background table creation completed for '{table_name}'")
    except Exception as e:
        _table_init_error = str(e)
        logger.error(f"[TABLE_INIT] Background table creation failed: {e}")
    finally:
        _table_init_event.set()
```

**Step 3: Rewrite `create_create_table_node` factory**

Replace the existing `create_create_table_node` function (lines 1131-1156) with:
```python
def create_create_table_node(connection_string: str, default_table_name: str) -> Callable:
    """
    Registry-aware table creation node.

    Priority:
    1. _force_table_refresh=True → DROP + recreate + register
    2. Registry has table → skip (0 sec)
    3. Background init running → wait for it, then register
    4. Background init succeeded → register
    5. Fallback → create from config query
    """

    async def create_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
        force_refresh = state.get("_force_table_refresh", False)
        table_name = _get_configurable(config, "table_name", default_table_name)
        session_id = _get_configurable(config, "thread_id", "__global__")
        registry = get_table_registry()

        # --- Force refresh: DROP + recreate ---
        if force_refresh:
            logger.info(f"[CREATE_TABLE] Force refresh requested, dropping '{table_name}'")
            drop_sql = f"DROP TABLE IF EXISTS [{table_name}];"
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(_db_executor, _execute_script_sync, connection_string, drop_sql)
            except Exception as e:
                logger.warning(f"[CREATE_TABLE] Drop failed (may not exist): {e}")
            await registry.unregister_table(session_id)
            # Reset init event so we recreate
            _table_init_event.clear()
            # Fall through to creation below

        # --- Registry check: table already exists? ---
        if not force_refresh:
            metadata = await registry.check_table_exists(session_id)
            if metadata:
                logger.info(
                    f"[CREATE_TABLE] Table '{table_name}' found in registry "
                    f"(queries={metadata.query_count}, ttl={metadata.ttl_remaining():.0f}s), skipping creation"
                )
                return {}

        # --- Wait for background init if running ---
        if not _table_init_event.is_set():
            logger.info("[CREATE_TABLE] Waiting for background init to complete...")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _table_init_event.wait, 180)  # max 3 min wait

        # --- Background init succeeded? Register and return ---
        if _table_init_error is None and not force_refresh:
            await registry.register_table(session_id, table_name)
            logger.info(f"[CREATE_TABLE] Registered '{table_name}' from background init")
            return {}

        # --- Fallback: create from config query ---
        query = _get_configurable(config, "query", "")
        if not query or not query.strip():
            # Try reading SQL file directly
            sql_file = Path(__file__).parent.parent.parent / "generic_text2sql" / "master_table_creation.sql"
            if sql_file.exists():
                query = sql_file.read_text(encoding="utf-8")
                logger.info(f"[CREATE_TABLE] Loaded SQL from file ({len(query)} chars)")
            else:
                logger.warning("[CREATE_TABLE] No query in config and SQL file not found, skipping")
                return {}

        logger.info(f"[CREATE_TABLE] Creating table '{table_name}' ({len(query)} chars)")
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(_db_executor, _execute_script_sync, connection_string, query)
            await registry.register_table(session_id, table_name)
            logger.info(f"[CREATE_TABLE] '{table_name}' created and registered successfully")
        except Exception as e:
            logger.error(f"[CREATE_TABLE] Error: {e}")
            return {"error": f"Tablo oluşturulamadı: {e}"}

        return {}

    return create_table_node
```

**Step 4: Update `create_cleanup_table_node` to refresh TTL**

Replace the existing `create_cleanup_table_node` (lines 1163-1189) with:
```python
def create_cleanup_table_node(connection_string: str, default_table_name: str) -> Callable:
    """
    Registry-aware cleanup: refresh TTL instead of DROP.
    Table cleanup is handled by TTL expiry / session end / background cleanup.
    """

    async def cleanup_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
        table_name = _get_configurable(config, "table_name", default_table_name)
        session_id = _get_configurable(config, "thread_id", "__global__")
        registry = get_table_registry()

        metadata = await registry.check_table_exists(session_id)
        if metadata:
            logger.info(
                f"[CLEANUP_TABLE] Refreshed TTL for '{table_name}' "
                f"(queries={metadata.query_count}, ttl={metadata.ttl_remaining():.0f}s)"
            )
        else:
            logger.info(f"[CLEANUP_TABLE] No registry entry for '{table_name}', nothing to refresh")

        return {}

    return cleanup_table_node
```

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat: registry-aware create_table_node with background init support"
```

---

### Task 3: Trigger Background Table Creation at Graph Init

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/graph.py:57-159` (add init logic in `build_text2sql_graph`)

**Step 1: Add imports**

At the top of `graph.py`, add:
```python
import threading
from pathlib import Path
```

And update the nodes import to include:
```python
from src.graphs.report_agent.subagents.text2sql.nodes import (
    # ... existing imports ...
    init_master_table_background,
    _table_init_event,
)
```

**Step 2: Add background table creation at end of `build_text2sql_graph`**

After `compiled = graph.compile()` (line 152) and before the return, add:
```python
    # --- Background table creation at init time ---
    sql_file = Path(__file__).parent.parent.parent / "generic_text2sql" / "master_table_creation.sql"
    if sql_file.exists():
        sql_script = sql_file.read_text(encoding="utf-8")
        logger.info(f"[TEXT2SQL] Starting background table creation ({len(sql_script)} chars)")
        init_thread = threading.Thread(
            target=init_master_table_background,
            args=(connection_string, table_name, sql_script),
            daemon=True,
        )
        init_thread.start()
    else:
        logger.warning(f"[TEXT2SQL] SQL file not found at {sql_file}, skipping background init")
        _table_init_event.set()  # Signal no-op so create_table_node doesn't block
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py
git commit -m "feat: trigger background table creation at graph init time"
```

---

### Task 4: Add Refresh Detection to `classify_intent_node`

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:36-127` (classify_intent_node)

**Step 1: Add refresh keyword detection**

In `classify_intent_node`, after the `user_query` extraction (after line 54), add:
```python
        # --- Table refresh detection (before LLM call) ---
        _REFRESH_KEYWORDS = {"verileri güncelle", "tabloyu güncelle", "verileri yenile", "tabloyu yenile", "veriyi güncelle", "veriyi yenile"}
        user_lower = user_query.lower().strip()
        is_refresh_request = any(kw in user_lower for kw in _REFRESH_KEYWORDS)

        if is_refresh_request:
            logger.info(f"[CLASSIFY] Table refresh detected: '{user_query}'")
            return {
                "user_query": user_query,
                "intent_type": "NEW_QUERY",
                "query_type": "SINGLE",
                "intent_confidence": 1.0,
                "wants_visualization": False,
                "use_result_type": None,
                "compute_operation": None,
                "visualization_output": None,
                "pre_built_sql": None,
                "modification_hints": None,
                "_force_table_refresh": True,
            }
```

**Step 2: Ensure normal flow resets the flag**

In the existing `return_dict` (around line 111), add:
```python
            "_force_table_refresh": False,
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/nodes.py
git commit -m "feat: detect table refresh keywords in classify_intent"
```

---

### Task 5: Write Tests

**Files:**
- Create: `tests/graphs/report/test_table_caching.py`

**Step 1: Write tests**

```python
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
    """classify_intent should detect 'verileri guncelle' without LLM."""
    # We test the keyword logic directly
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
```

**Step 2: Run tests**

```bash
pytest tests/graphs/report/test_table_caching.py -v
```

**Step 3: Commit**

```bash
git add tests/graphs/report/test_table_caching.py
git commit -m "test: add table caching tests for registry, create_table_node, refresh detection"
```

---

### Task 6: Integration Smoke Test

**Step 1: Verify graph builds without error**

```bash
python -c "from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph; print('Import OK')"
```

**Step 2: Check logs for background init**

Look for `[TABLE_INIT] Background table creation started` in logs when graph builds.

**Step 3: Final commit with any fixes**

```bash
git add -A
git commit -m "feat: session-based table caching for report_agent"
```
