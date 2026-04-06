# Graph Build Caching - Performance Optimization Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate redundant graph rebuilding and LLM client re-instantiation on every request by caching at instance level.

**Architecture:** Two independent, non-breaking changes:
1. Cache compiled graph at `BaseGraph` instance level via `_get_compiled_graph()` helper (lazy build once, reuse forever)
2. Cache LLM client instance in `LLM.get_chat()` (create once per LLM instance, reuse forever)

Both are safe because compiled LangGraph graphs are stateless executors and LLM clients (`ChatOpenAI`, `ChatAnthropic`) are stateless HTTP wrappers. Per-invocation state is isolated via `config["configurable"]["thread_id"]` and the `MemorySaver` checkpointer.

**Tech Stack:** Python, LangGraph, pytest, pytest-asyncio

**Why caching is safe:**
- Compiled graphs are stateless executors — state is per-thread_id in checkpointer
- LLM clients are stateless HTTP wrappers — no per-request state stored
- Config is passed per-invocation, not baked into the compiled graph
- Under concurrent threads, a benign double-build may occur (check-then-act race), but this is harmless — both `build_graph()` and `ChatOpenAI()` are idempotent
- The singleton `_chatbot_instance` in `dependencies.py` means one `BaseGraph` instance per lifetime

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/graphs/base/base_graph.py` | Add `_compiled_graph` cache + `_get_compiled_graph()` helper |
| Modify | `src/models/llm.py` | Cache LLM client instance in `get_chat()` |
| Create | `tests/unit/test_graph_build_caching.py` | Tests for graph caching behavior |
| Create | `tests/unit/test_llm_client_caching.py` | Tests for LLM client caching |

---

## Chunk 1: Graph Build Caching

### Task 1: Write failing tests for graph build caching

**Files:**
- Create: `tests/unit/test_graph_build_caching.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for BaseGraph compiled graph caching."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Dict, Any, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_metadata import GraphMetadata


class _DummyState:
    """Minimal state for testing."""
    pass


class _DummyConfig:
    """Minimal config for testing."""
    pass


class ConcreteTestGraph(BaseGraph):
    """Concrete implementation for testing build_graph caching."""

    def __init__(self):
        self.build_count = 0
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {}
        super().__init__(
            llm=MagicMock(),
            state_class=dict,
            config=mock_config,
            metadata=MagicMock(spec=GraphMetadata),
        )

    def _get_default_config(self):
        return MagicMock()

    def get_metadata(self) -> GraphMetadata:
        return MagicMock(spec=GraphMetadata)

    def build_graph(self) -> StateGraph:
        self.build_count += 1
        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {"result": "ok"}
        return mock_compiled


class TestGraphBuildCaching:
    """Test that compiled graph is cached after first build."""

    def test_invoke_caches_compiled_graph(self):
        """First invoke builds graph, second invoke reuses cache."""
        graph = ConcreteTestGraph()

        graph.invoke({"messages": []})
        assert graph.build_count == 1

        graph.invoke({"messages": []})
        assert graph.build_count == 1, "build_graph() should NOT be called again"

    def test_multiple_invokes_single_build(self):
        """N invocations should only build the graph once."""
        graph = ConcreteTestGraph()

        for _ in range(5):
            graph.invoke({"messages": []})

        assert graph.build_count == 1

    @pytest.mark.asyncio
    async def test_ainvoke_caches_compiled_graph(self):
        """Async invoke also uses cache."""
        graph = ConcreteTestGraph()

        await graph.ainvoke({"messages": []})
        assert graph.build_count == 1

        await graph.ainvoke({"messages": []})
        assert graph.build_count == 1, "build_graph() should NOT be called again on ainvoke"

    @pytest.mark.asyncio
    async def test_astream_caches_compiled_graph(self):
        """Async stream also uses cache."""
        graph = ConcreteTestGraph()
        mock_compiled = graph.build_graph()
        graph.build_count = 0  # reset after manual build
        graph._compiled_graph = None  # reset cache

        # astream uses _get_compiled_graph internally
        async for _ in graph.astream({"messages": []}):
            pass
        assert graph.build_count == 1

        async for _ in graph.astream({"messages": []}):
            pass
        assert graph.build_count == 1, "build_graph() should NOT be called again on astream"

    def test_cache_is_per_instance(self):
        """Different instances maintain separate caches."""
        graph1 = ConcreteTestGraph()
        graph2 = ConcreteTestGraph()

        graph1.invoke({"messages": []})
        graph2.invoke({"messages": []})

        assert graph1.build_count == 1
        assert graph2.build_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_graph_build_caching.py -v`
Expected: FAIL — `build_count` will be 2+ because caching doesn't exist yet.

---

### Task 2: Implement compiled graph caching in BaseGraph

**Files:**
- Modify: `src/graphs/base/base_graph.py:91-108` (`__init__`)
- Modify: `src/graphs/base/base_graph.py:365-400` (`ainvoke`)
- Modify: `src/graphs/base/base_graph.py:402-426` (`astream`)
- Modify: `src/graphs/base/base_graph.py:428-452` (`invoke`)

- [ ] **Step 3: Add `_compiled_graph` field to `__init__`**

In `BaseGraph.__init__()` (around line 108), add after `self.memory = memory or MemorySaver()`:

```python
self._compiled_graph = None
```

- [ ] **Step 4: Add `_get_compiled_graph()` helper method**

Add this method right before the `ainvoke` method (before line 365):

```python
def _get_compiled_graph(self):
    """Return cached compiled graph, building on first call."""
    if self._compiled_graph is None:
        self._compiled_graph = self.build_graph()
    return self._compiled_graph
```

- [ ] **Step 5: Update `ainvoke()` to use cache**

In `ainvoke()` (line 391), replace:
```python
compiled_graph = self.build_graph()
```
with:
```python
compiled_graph = self._get_compiled_graph()
```

- [ ] **Step 6: Update `astream()` to use cache**

In `astream()` (line 416), replace:
```python
compiled_graph = self.build_graph()
```
with:
```python
compiled_graph = self._get_compiled_graph()
```

- [ ] **Step 7: Update `invoke()` to use cache**

In `invoke()` (line 451), replace:
```python
compiled_graph = self.build_graph()
```
with:
```python
compiled_graph = self._get_compiled_graph()
```

- [ ] **Step 8: Fix deprecated `asyncio.get_event_loop()`**

In `ainvoke()` (line 392), replace:
```python
loop = asyncio.get_event_loop()
```
with:
```python
loop = asyncio.get_running_loop()
```

In `astream()` (line 417), replace:
```python
loop = asyncio.get_event_loop()
```
with:
```python
loop = asyncio.get_running_loop()
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/unit/test_graph_build_caching.py -v`
Expected: ALL PASS

- [ ] **Step 10: Run existing test suite to verify no regressions**

Run: `pytest tests/ -v --timeout=60`
Expected: No new failures. All existing tests should pass as before.

- [ ] **Step 11: Commit**

```bash
git add src/graphs/base/base_graph.py tests/unit/test_graph_build_caching.py
git commit -m "perf: cache compiled graph in BaseGraph to avoid rebuild on every invoke"
```

---

## Chunk 2: LLM Client Caching

### Task 3: Write failing tests for LLM client caching

**Files:**
- Create: `tests/unit/test_llm_client_caching.py`

**Why needed:** `routing/nodes.py` calls `llm.get_chat()` 6 times during execution (lines 158, 355, 470, 947, 1691, 1806). These are NOT covered by graph build caching because they run inside node functions, not inside `build_graph()`. Each call creates a new `ChatOpenAI()` instance (~5ms each = ~30ms/message).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for LLM client caching."""
import pytest
from unittest.mock import patch, MagicMock
from src.models.llm import LLM


class TestLLMClientCaching:
    """Test that get_chat() returns the same instance on repeated calls."""

    @patch("src.models.llm.ChatOpenAI")
    def test_get_chat_returns_same_instance_openai(self, mock_cls):
        """OpenAI client should be created once and reused."""
        mock_cls.return_value = MagicMock(name="openai_client")
        llm = LLM(provider="openai", model="gpt-4o-mini", api_key="test")

        client1 = llm.get_chat()
        client2 = llm.get_chat()

        assert client1 is client2, "get_chat() should return the same instance"
        assert mock_cls.call_count == 1, "ChatOpenAI should be instantiated only once"

    @patch("src.models.llm.ChatAnthropic")
    def test_get_chat_returns_same_instance_anthropic(self, mock_cls):
        """Anthropic client should be created once and reused."""
        mock_cls.return_value = MagicMock(name="anthropic_client")
        llm = LLM(provider="anthropic", model="claude-sonnet-4-20250514", api_key="test")

        client1 = llm.get_chat()
        client2 = llm.get_chat()

        assert client1 is client2
        assert mock_cls.call_count == 1

    @patch("src.models.llm.ChatOpenAI")
    def test_different_llm_instances_have_separate_caches(self, mock_cls):
        """Two LLM instances should maintain independent caches."""
        mock_cls.side_effect = [MagicMock(name="client_a"), MagicMock(name="client_b")]

        llm1 = LLM(provider="openai", model="gpt-4o-mini", api_key="test")
        llm2 = LLM(provider="openai", model="gpt-4o", api_key="test")

        c1 = llm1.get_chat()
        c2 = llm2.get_chat()

        assert c1 is not c2, "Different LLM instances should have different clients"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_llm_client_caching.py -v`
Expected: FAIL — `mock_cls.call_count` will be 2 because no caching exists.

---

### Task 4: Implement LLM client caching

**Files:**
- Modify: `src/models/llm.py:6-11` (`__init__`)
- Modify: `src/models/llm.py:13-23` (`get_chat`)

- [ ] **Step 3: Add `_chat_instance` field to `__init__`**

In `LLM.__init__()` (line 11), add after `self.base_url = base_url`:

```python
self._chat_instance = None
```

- [ ] **Step 4: Update `get_chat()` to cache the client**

Replace the entire `get_chat` method (lines 13-23) with:

```python
def get_chat(self):
    if self._chat_instance is not None:
        return self._chat_instance
    if self.provider == "openai":
        self._chat_instance = ChatOpenAI(model=self.model, temperature=self.temperature, api_key=self.api_key)
    elif self.provider == "anthropic":
        self._chat_instance = ChatAnthropic(model=self.model, temperature=self.temperature, api_key=self.api_key)
    elif self.provider == "ollama":
        from langchain_ollama import ChatOllama
        self._chat_instance = ChatOllama(model=self.model, temperature=self.temperature, base_url=self.base_url)
    else:
        raise ValueError(f"Unsupported provider: {self.provider}")
    return self._chat_instance
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_llm_client_caching.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite for regression**

Run: `pytest tests/ -v --timeout=60`
Expected: No new failures.

- [ ] **Step 7: Commit**

```bash
git add src/models/llm.py tests/unit/test_llm_client_caching.py
git commit -m "perf: cache LLM client instance to avoid re-instantiation per call"
```

---

## Impact Analysis

### Before (per message through FastAPI):
```
BaseGraph.ainvoke()
  ├── build_graph() EVERY TIME              ~285ms  ← Chunk 1 eliminates
  │   ├── SupervisorGraph compile            ~50ms
  │   ├── RoutingGraph compile               ~30ms
  │   ├── ChatGraph compile                  ~5ms
  │   └── ReportAgent compile                ~200ms
  │       ├── 11x get_chat() at build time   ~50ms  ← Chunk 1 eliminates (indirect)
  │       ├── text2sql services              ~80ms
  │       └── visualization compile          ~10ms
  └── Node execution
      └── 6x get_chat() in routing nodes     ~30ms  ← Chunk 2 eliminates
                                   OVERHEAD: ~365ms per message
```

### After (both chunks applied):
```
BaseGraph.ainvoke()
  ├── _get_compiled_graph() → cache hit      ~0ms ✓
  └── Node execution
      └── 6x get_chat() → cached instance    ~0ms ✓
                                   OVERHEAD: ~0ms per message (after first)
```

**Expected improvement:** ~365ms saved per message after the first invocation.

### What this does NOT change:
- Graph structure (no nodes/edges modified)
- State flow (no state schema changes)
- Checkpointing behavior (MemorySaver still per thread_id)
- API endpoints (no route changes)
- Config passing (still per-invocation via config parameter)
- LLM API call latency (network time unchanged — only client instantiation eliminated)
- Existing tests (all should pass unchanged)
