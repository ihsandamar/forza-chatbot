# Feature 1.2 — SSE Progress Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/chat/stream` SSE endpoint that emits Turkish-language node-level progress events during report generation, then delivers the final result in the same stream.

**Architecture:** LangGraph's native `astream_events(version="v2")` drives progress emission; a new `astream_events()` method is added to `BaseGraph`; `Chatbot.astream_events_async()` translates LangGraph events to raw dicts; `ChatService.stream_message()` converts raw dicts to `StreamEvent` Pydantic objects and handles session/HITL management; `sse-starlette`'s `EventSourceResponse` wraps the async generator. No node files are modified.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, sse-starlette>=1.6.1, Pydantic v2, pytest-asyncio

---

## File Structure

| File | Action |
|---|---|
| `requirements.txt` | Modify — add `sse-starlette>=1.6.1` |
| `src/graphs/report_agent/progress_mapper.py` | Create — node→Türkçe mesaj mapping + helpers |
| `src/api/models/responses/chat.py` | Modify — add `StreamEvent` Pydantic model |
| `src/graphs/base/base_graph.py` | Modify — add `astream_events()` async generator |
| `src/core/chatbot.py` | Modify — add `astream_events_async()` method |
| `src/api/services/chat_service.py` | Modify — add `_prepare_graph_state()` + `stream_message()` |
| `src/api/routes/chat.py` | Modify — add `POST /api/chat/stream` route |
| `tests/unit/test_progress_mapper.py` | Create |
| `tests/core/test_chatbot_astream_events.py` | Create |
| `tests/api/services/test_stream_message.py` | Create |

---

## Task 1: Add sse-starlette Dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add dependency**

Open `requirements.txt` and add the following line (place near other FastAPI-related deps):
```
sse-starlette>=1.6.1
```

- [ ] **Step 2: Verify it installs**

```bash
pip install sse-starlette>=1.6.1
```
Expected: `Successfully installed sse-starlette-X.X.X`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat(deps): add sse-starlette for SSE progress notifications"
```

---

## Task 2: Create progress_mapper.py (TDD)

**Files:**
- Create: `src/graphs/report_agent/progress_mapper.py`
- Create: `tests/unit/test_progress_mapper.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_progress_mapper.py`:

```python
import pytest
from src.graphs.report_agent.progress_mapper import (
    normalize_node_name,
    get_progress_info,
    TOTAL_STEPS,
    NODE_PROGRESS_MESSAGES,
)


def test_normalize_strips_subgraph_prefix():
    assert normalize_node_name("text2sql:sql_executor") == "sql_executor"


def test_normalize_leaves_plain_name_unchanged():
    assert normalize_node_name("sql_executor") == "sql_executor"


def test_normalize_handles_deep_prefix():
    assert normalize_node_name("a:b:c") == "c"


def test_get_progress_info_known_node_returns_tuple():
    result = get_progress_info("sql_executor")
    assert result is not None
    node_name, message, index = result
    assert node_name == "sql_executor"
    assert "çekiliyor" in message
    assert index == 9


def test_get_progress_info_unknown_node_returns_none():
    assert get_progress_info("__graph_start__") is None


def test_get_progress_info_normalizes_prefix():
    plain = get_progress_info("sql_executor")
    prefixed = get_progress_info("text2sql:sql_executor")
    assert plain == prefixed


def test_get_progress_info_retry_message_on_second_occurrence():
    _, message, _ = get_progress_info("semantic_extractor", occurrence_count=2)
    assert "yeniden" in message


def test_total_steps_is_thirteen():
    assert TOTAL_STEPS == 13


def test_all_expected_nodes_present():
    expected = {
        "classify_intent", "modify_sql", "report_chat",
        "create_table", "business_rules", "semantic_extractor",
        "term_resolver", "term_validator", "schema_builder",
        "value_resolver", "sql_generator", "sql_executor",
        "data_analyzer", "template_renderer", "build_response",
    }
    assert expected == set(NODE_PROGRESS_MESSAGES.keys())
```

- [ ] **Step 2: Run tests — expect ImportError/failure**

```bash
pytest tests/unit/test_progress_mapper.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.graphs.report_agent.progress_mapper'`

- [ ] **Step 3: Create `src/graphs/report_agent/progress_mapper.py`**

```python
from typing import Optional

NODE_PROGRESS_MESSAGES: dict[str, tuple[str, int]] = {
    # Report Agent level
    "classify_intent":    ("Sorgu analiz ediliyor...",          0),
    "modify_sql":         ("Sorgu güncelleniyor...",            0),
    "report_chat":        ("Sorgu netleştiriliyor...",          0),
    # Text2SQL subgraph
    "create_table":       ("Çalışma tablosu oluşturuluyor...", 1),
    "business_rules":     ("İş kuralları yükleniyor...",        2),
    "semantic_extractor": ("Sorgu anlamı çıkarılıyor...",       3),
    "term_resolver":      ("Terimler çözümleniyor...",          4),
    "term_validator":     ("Terimler doğrulanıyor...",          5),
    "schema_builder":     ("Sorgu şeması oluşturuluyor...",     6),
    "value_resolver":     ("Değerler çözümleniyor...",          7),
    "sql_generator":      ("SQL oluşturuluyor...",              8),
    "sql_executor":       ("Veriler çekiliyor...",              9),
    # Visualization subgraph
    "data_analyzer":      ("Veri analiz ediliyor...",          10),
    "template_renderer":  ("Grafik oluşturuluyor...",          11),
    # Final
    "build_response":     ("Yanıt hazırlanıyor...",            12),
}

TOTAL_STEPS = 13


def normalize_node_name(raw_name: str) -> str:
    """Strip subgraph prefix: 'text2sql:sql_executor' → 'sql_executor'."""
    return raw_name.split(":")[-1] if ":" in raw_name else raw_name


def get_progress_info(
    raw_name: str,
    occurrence_count: int = 1,
) -> Optional[tuple[str, str, int]]:
    """
    Return (node_name, message, index) for the given node, or None if unknown.
    occurrence_count > 1 signals a retry — message changes accordingly.
    """
    node_name = normalize_node_name(raw_name)
    entry = NODE_PROGRESS_MESSAGES.get(node_name)
    if entry is None:
        return None
    message, index = entry
    if occurrence_count > 1:
        message = f"Sorgu yeniden deneniyor... ({occurrence_count}/2)"
    return (node_name, message, index)
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/unit/test_progress_mapper.py -v
```
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/progress_mapper.py tests/unit/test_progress_mapper.py
git commit -m "feat(stream): add progress_mapper for node→Turkish message mapping"
```

---

## Task 3: Add StreamEvent Model (TDD)

**Files:**
- Modify: `src/api/models/responses/chat.py`
- Test: use inline assertions below

- [ ] **Step 1: Write the failing test**

Add `tests/api/services/test_stream_message.py` with just the model test for now (more tests added in Task 6):

```python
import pytest
from src.api.models.responses.chat import StreamEvent


def test_stream_event_progress():
    e = StreamEvent(
        event_type="progress",
        step="sql_executor",
        message="Veriler çekiliyor...",
        index=9,
        total=13,
    )
    assert e.event_type == "progress"
    assert e.step == "sql_executor"
    assert e.index == 9
    assert e.total == 13
    assert e.text is None  # result fields are absent


def test_stream_event_result_report():
    e = StreamEvent(
        event_type="result",
        text="Grafik hazır",
        type="report",
        confidence=0.85,
        action={"type": "chart", "target": "<iframe>", "params": {}},
    )
    assert e.event_type == "result"
    assert e.type == "report"
    assert e.step is None  # progress fields are absent


def test_stream_event_error():
    e = StreamEvent(event_type="error", message="Hata oluştu")
    assert e.event_type == "error"
    assert e.message == "Hata oluştu"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/api/services/test_stream_message.py::test_stream_event_progress -v
```
Expected: `ImportError: cannot import name 'StreamEvent'`

- [ ] **Step 3: Add StreamEvent to `src/api/models/responses/chat.py`**

Add after the existing `SessionHistoryResponse` class (line 56):

```python
class StreamEvent(BaseModel):
    """SSE event payload for POST /api/chat/stream."""
    event_type: Literal["progress", "result", "error"]
    # progress event fields
    step: Optional[str] = None
    message: Optional[str] = None
    index: Optional[int] = None
    total: Optional[int] = None
    # result event fields — same shape as ResponseData
    text: Optional[str] = None
    type: Optional[str] = None
    confidence: Optional[float] = None
    action: Optional[dict] = None
```

Also add `Literal` to the existing import at the top of the file:

```python
from typing import Optional, Dict, Any, List, Literal
```

- [ ] **Step 4: Run tests — expect 3 passed**

```bash
pytest tests/api/services/test_stream_message.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/api/models/responses/chat.py tests/api/services/test_stream_message.py
git commit -m "feat(stream): add StreamEvent Pydantic model for SSE responses"
```

---

## Task 4: Add astream_events() to BaseGraph (TDD)

**Files:**
- Modify: `src/graphs/base/base_graph.py`
- Create: `tests/core/test_chatbot_astream_events.py` (partial — BaseGraph portion)

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_chatbot_astream_events.py`:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock
from src.graphs.base.base_graph import BaseGraph


class ConcreteGraph(BaseGraph):
    def _get_default_metadata(self):
        m = MagicMock()
        m.name = "test"
        m.category = "test"
        m.get_capabilities.return_value = []
        m.input_spec.required = False
        m.input_spec.name = "messages"
        return m

    def build_graph(self):
        return self._mock_compiled


@pytest.fixture
def base_graph_with_mock_compiled():
    llm = MagicMock()
    g = ConcreteGraph.__new__(ConcreteGraph)
    # Manually init to avoid calling build_graph prematurely
    g.llm = llm
    g.state_class = dict
    g.config = MagicMock()
    g.config.model_dump.return_value = {}
    g.metadata = MagicMock()
    g.memory = MagicMock()
    g._compiled_graph = None

    # Build a mock compiled graph with astream_events
    async def fake_astream_events(input, config=None, **kwargs):
        yield {"event": "on_chain_start", "name": "LangGraph", "run_id": "root-1", "parent_ids": []}
        yield {"event": "on_chain_start", "name": "classify_intent", "run_id": "r2", "parent_ids": ["root-1"]}
        yield {"event": "on_chain_end", "name": "classify_intent", "run_id": "r2", "parent_ids": ["root-1"], "data": {"output": {}}}
        yield {"event": "on_chain_end", "name": "LangGraph", "run_id": "root-1", "parent_ids": [], "data": {"output": {"messages": []}}}

    compiled = MagicMock()
    compiled.astream_events = fake_astream_events
    g._mock_compiled = compiled
    g._compiled_graph = compiled
    return g


@pytest.mark.asyncio
async def test_base_graph_astream_events_yields_all_events(base_graph_with_mock_compiled):
    events = []
    async for event in base_graph_with_mock_compiled.astream_events({"messages": []}, config={}):
        events.append(event)
    assert len(events) == 4
    assert events[0]["event"] == "on_chain_start"
    assert events[0]["name"] == "LangGraph"


@pytest.mark.asyncio
async def test_base_graph_astream_events_passes_kwargs(base_graph_with_mock_compiled):
    received_kwargs = {}

    async def capturing_astream_events(input, config=None, **kwargs):
        received_kwargs.update(kwargs)
        yield {"event": "on_chain_end", "name": "LangGraph", "run_id": "r", "parent_ids": [], "data": {"output": {}}}

    base_graph_with_mock_compiled._compiled_graph.astream_events = capturing_astream_events

    async for _ in base_graph_with_mock_compiled.astream_events({}, config={}, version="v2"):
        pass

    assert received_kwargs.get("version") == "v2"
```

- [ ] **Step 2: Run — expect AttributeError (no astream_events on BaseGraph)**

```bash
pytest tests/core/test_chatbot_astream_events.py::test_base_graph_astream_events_yields_all_events -v
```
Expected: `AttributeError: 'ConcreteGraph' object has no attribute 'astream_events'`

- [ ] **Step 3: Add `astream_events()` to BaseGraph**

In `src/graphs/base/base_graph.py`, add after the `astream` method (after line ~451):

```python
async def astream_events(self, input, config=None, **kwargs):
    """
    Async generator for LangGraph's astream_events API.
    Unlike ainvoke/astream (which wrap blocking methods), astream_events is
    natively async — no executor needed.
    """
    config = self._prepare_config_for_langgraph(config)
    if isinstance(input, dict):
        input = self._inject_config_to_state(input, config)
    compiled_graph = self._get_compiled_graph()
    async for event in compiled_graph.astream_events(input, config=config, **kwargs):
        yield event
```

- [ ] **Step 4: Run tests — expect 2 passed**

```bash
pytest tests/core/test_chatbot_astream_events.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/graphs/base/base_graph.py tests/core/test_chatbot_astream_events.py
git commit -m "feat(stream): add astream_events() to BaseGraph"
```

---

## Task 5: Add astream_events_async() to Chatbot (TDD)

**Files:**
- Modify: `src/core/chatbot.py`
- Modify: `tests/core/test_chatbot_astream_events.py` (add tests)

- [ ] **Step 1: Add failing tests to `tests/core/test_chatbot_astream_events.py`**

Append to the existing test file:

```python
from src.core.chatbot import Chatbot


def _make_chatbot_with_mock_graph(events_list):
    """Helper: chatbot whose graph.astream_events yields events_list."""
    async def fake_astream_events(input, config=None, **kwargs):
        for e in events_list:
            yield e

    graph_mock = MagicMock()
    graph_mock.astream_events = fake_astream_events
    graph_mock._prepare_config_for_langgraph = MagicMock(return_value={})

    llm_mock = MagicMock()
    return Chatbot(llm=llm_mock, graph=graph_mock)


@pytest.mark.asyncio
async def test_astream_events_async_emits_progress_for_known_node():
    events_list = [
        {"event": "on_chain_start", "name": "LangGraph",        "run_id": "root", "parent_ids": [],       "data": {}},
        {"event": "on_chain_start", "name": "classify_intent",  "run_id": "r2",   "parent_ids": ["root"], "data": {}},
        {"event": "on_chain_end",   "name": "classify_intent",  "run_id": "r2",   "parent_ids": ["root"], "data": {"output": {}}},
        {"event": "on_chain_end",   "name": "LangGraph",        "run_id": "root", "parent_ids": [],
         "data": {"output": {"messages": [], "final_response": "done"}}},
    ]
    chatbot = _make_chatbot_with_mock_graph(events_list)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    progress = [e for e in collected if e["event_type"] == "progress"]
    assert len(progress) == 1
    assert progress[0]["step"] == "classify_intent"
    assert progress[0]["index"] == 0
    assert progress[0]["total"] == 13

    result = [e for e in collected if e["event_type"] == "_result_raw"]
    assert len(result) == 1
    assert result[0]["_graph_output"]["final_response"] == "done"


@pytest.mark.asyncio
async def test_astream_events_async_skips_unknown_node():
    events_list = [
        {"event": "on_chain_start", "name": "LangGraph",    "run_id": "root", "parent_ids": [],       "data": {}},
        {"event": "on_chain_start", "name": "__unknown__",  "run_id": "r2",   "parent_ids": ["root"], "data": {}},
        {"event": "on_chain_end",   "name": "LangGraph",    "run_id": "root", "parent_ids": [],
         "data": {"output": {"messages": []}}},
    ]
    chatbot = _make_chatbot_with_mock_graph(events_list)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    progress = [e for e in collected if e["event_type"] == "progress"]
    assert len(progress) == 0


@pytest.mark.asyncio
async def test_astream_events_async_retry_message_on_second_occurrence():
    events_list = [
        {"event": "on_chain_start", "name": "LangGraph",          "run_id": "root", "parent_ids": [],       "data": {}},
        {"event": "on_chain_start", "name": "semantic_extractor", "run_id": "r2",   "parent_ids": ["root"], "data": {}},
        {"event": "on_chain_start", "name": "semantic_extractor", "run_id": "r3",   "parent_ids": ["root"], "data": {}},
        {"event": "on_chain_end",   "name": "LangGraph",          "run_id": "root", "parent_ids": [],
         "data": {"output": {"messages": []}}},
    ]
    chatbot = _make_chatbot_with_mock_graph(events_list)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    progress = [e for e in collected if e["event_type"] == "progress"]
    assert len(progress) == 2
    assert "yeniden" in progress[1]["message"]


@pytest.mark.asyncio
async def test_astream_events_async_interrupt_yields_result_question():
    from langgraph.errors import GraphInterrupt
    from unittest.mock import patch

    async def fake_astream_events_raises(input, config=None, **kwargs):
        yield {"event": "on_chain_start", "name": "LangGraph", "run_id": "root", "parent_ids": [], "data": {}}
        yield {"event": "on_chain_start", "name": "value_resolver", "run_id": "r2", "parent_ids": ["root"], "data": {}}
        raise GraphInterrupt((
            type("Interrupt", (), {"value": {"question": "Hangi şube?", "options": ["A", "B"], "context": "", "type": "choice"}})(),
        ))

    graph_mock = MagicMock()
    graph_mock.astream_events = fake_astream_events_raises
    chatbot = Chatbot(llm=MagicMock(), graph=graph_mock)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    result_events = [e for e in collected if e["event_type"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["type"] == "question"
    assert "Hangi şube?" in result_events[0]["text"]
    assert result_events[0]["_hitl_info"]["question"] == "Hangi şube?"


@pytest.mark.asyncio
async def test_astream_events_async_graph_exception_yields_error():
    async def fake_raises(input, config=None, **kwargs):
        yield {"event": "on_chain_start", "name": "LangGraph", "run_id": "root", "parent_ids": [], "data": {}}
        raise RuntimeError("DB bağlantısı kesildi")

    graph_mock = MagicMock()
    graph_mock.astream_events = fake_raises
    chatbot = Chatbot(llm=MagicMock(), graph=graph_mock)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    errors = [e for e in collected if e["event_type"] == "error"]
    assert len(errors) == 1
    assert "DB bağlantısı" in errors[0]["message"]


@pytest.mark.asyncio
async def test_astream_events_async_hitl_in_final_state():
    """__interrupt__ in final state triggers result(type='question')."""
    interrupt_val = type("IV", (), {"value": {"question": "Filtre?", "options": [], "context": "", "type": "choice"}})()

    events_list = [
        {"event": "on_chain_start", "name": "LangGraph", "run_id": "root", "parent_ids": [], "data": {}},
        {"event": "on_chain_end",   "name": "LangGraph", "run_id": "root", "parent_ids": [],
         "data": {"output": {"messages": [], "__interrupt__": (interrupt_val,)}}},
    ]
    chatbot = _make_chatbot_with_mock_graph(events_list)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    result_events = [e for e in collected if e["event_type"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["type"] == "question"
```

- [ ] **Step 2: Run — expect AttributeError (no astream_events_async)**

```bash
pytest tests/core/test_chatbot_astream_events.py -v -k "astream_events_async"
```
Expected: `AttributeError: 'Chatbot' object has no attribute 'astream_events_async'`

- [ ] **Step 3: Add `astream_events_async()` to `src/core/chatbot.py`**

Add after `get_graph_output_async()` method (after line ~484), before the Runtime Settings section:

```python
async def astream_events_async(
    self,
    state,
    config: dict,
):
    """
    Yields raw dicts for SSE streaming:
      {"event_type": "progress", "step": ..., "message": ..., "index": ..., "total": ...}
      {"event_type": "_result_raw", "_graph_output": {...}}
      {"event_type": "result", "text": ..., "type": "question", ..., "_hitl_info": {...}}
      {"event_type": "error", "message": ...}

    Caller (chat_service) converts raw dicts to StreamEvent objects.
    """
    from src.graphs.report_agent.progress_mapper import get_progress_info, TOTAL_STEPS
    from langgraph.errors import GraphInterrupt

    root_run_id = None
    step_counts: dict[str, int] = {}

    try:
        async for event in self.graph.astream_events(state, config=config, version="v2"):
            event_type = event.get("event", "")
            event_name = event.get("name", "")
            run_id = event.get("run_id", "")
            parent_ids = event.get("parent_ids", [])

            # First on_chain_start is always the root graph
            if root_run_id is None and event_type == "on_chain_start":
                root_run_id = run_id
                continue

            if event_type == "on_chain_start" and parent_ids:
                # A node started (not root)
                count = step_counts.get(event_name, 0) + 1
                step_counts[event_name] = count

                info = get_progress_info(event_name, count)
                if info:
                    node_name, message, index = info
                    yield {
                        "event_type": "progress",
                        "step": node_name,
                        "message": message,
                        "index": index,
                        "total": TOTAL_STEPS,
                    }

            elif event_type == "on_chain_end" and not parent_ids:
                # Root graph completed
                final_output = event.get("data", {}).get("output", {}) or {}

                # Check for interrupt stored in state (same as _invoke_graph_async)
                pending_interrupts = final_output.get("__interrupt__") if isinstance(final_output, dict) else None
                if pending_interrupts:
                    interrupt_data = pending_interrupts[0].value if pending_interrupts else {}
                    question_text = interrupt_data.get("question", "Açıklama gerekiyor")
                    options = interrupt_data.get("options", [])
                    context = interrupt_data.get("context", "")
                    interrupt_type = interrupt_data.get("type", "choice")

                    if options:
                        options_text = "\n".join([f"  {i+1}. {opt}" for i, opt in enumerate(options)])
                        full_text = f"❓ {question_text}\n\nSeçenekler:\n{options_text}"
                    else:
                        full_text = f"❓ {question_text}"
                    if context:
                        full_text += f"\n\nℹ️ {context}"

                    yield {
                        "event_type": "result",
                        "text": full_text,
                        "type": "question",
                        "confidence": 0.9,
                        "action": {
                            "type": "hitl",
                            "target": "",
                            "params": {
                                "type": interrupt_type,
                                "question": question_text,
                                "options": options,
                                "context": context,
                            },
                        },
                        "_hitl_info": {
                            "type": interrupt_type,
                            "question": question_text,
                            "options": options,
                            "context": context,
                        },
                    }
                else:
                    yield {"event_type": "_result_raw", "_graph_output": final_output}

    except GraphInterrupt as e:
        # GraphInterrupt raised as exception (alternative path for some LangGraph versions)
        interrupts = e.args[0] if e.args else []
        interrupt_data = interrupts[0].value if interrupts else {}
        question_text = interrupt_data.get("question", "Açıklama gerekiyor")
        options = interrupt_data.get("options", [])
        context = interrupt_data.get("context", "")
        interrupt_type = interrupt_data.get("type", "choice")

        if options:
            options_text = "\n".join([f"  {i+1}. {opt}" for i, opt in enumerate(options)])
            full_text = f"❓ {question_text}\n\nSeçenekler:\n{options_text}"
        else:
            full_text = f"❓ {question_text}"
        if context:
            full_text += f"\n\nℹ️ {context}"

        yield {
            "event_type": "result",
            "text": full_text,
            "type": "question",
            "confidence": 0.9,
            "action": {
                "type": "hitl",
                "target": "",
                "params": {
                    "type": interrupt_type,
                    "question": question_text,
                    "options": options,
                    "context": context,
                },
            },
            "_hitl_info": {
                "type": interrupt_type,
                "question": question_text,
                "options": options,
                "context": context,
            },
        }

    except Exception as e:
        yield {"event_type": "error", "message": str(e)}
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/core/test_chatbot_astream_events.py -v
```
Expected: `8 passed` (2 BaseGraph tests + 6 chatbot tests)

- [ ] **Step 5: Commit**

```bash
git add src/core/chatbot.py tests/core/test_chatbot_astream_events.py
git commit -m "feat(stream): add astream_events_async() to Chatbot"
```

---

## Task 6: Add stream_message() to ChatService (TDD)

**Files:**
- Modify: `src/api/services/chat_service.py`
- Modify: `tests/api/services/test_stream_message.py` (add stream_message tests)

- [ ] **Step 1: Add failing tests to `tests/api/services/test_stream_message.py`**

Append to the existing test file:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime
from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import ChatMessageRequest
from src.api.models.responses.chat import StreamEvent


def _make_service_with_session(session_id="sess-1", hitl_pending=False):
    """Helper: ChatService with one pre-loaded session."""
    chatbot = MagicMock()
    chatbot._prepare_config = MagicMock(return_value={"configurable": {}})
    service = ChatService(chatbot=chatbot)
    service.sessions[session_id] = {
        "session_id": session_id,
        "user_id": None,
        "token": None,
        "created_at": datetime.now(),
        "messages": [],
        "metadata": {},
        "settings": {"max_messages": 100, "response_format": "ALL_MESSAGES"},
        "hitl_pending": hitl_pending,
        "hitl_question": None,
    }
    return service


@pytest.mark.asyncio
async def test_stream_message_raises_if_session_missing():
    service = _make_service_with_session()
    request = ChatMessageRequest(session_id="no-such-session", message="test")
    with pytest.raises(ValueError, match="Session not found"):
        async for _ in service.stream_message(request):
            pass


@pytest.mark.asyncio
async def test_stream_message_yields_progress_then_text_result():
    service = _make_service_with_session(session_id="s1")

    async def mock_raw_events(state, config):
        yield {"event_type": "progress", "step": "classify_intent", "message": "Sorgu analiz ediliyor...", "index": 0, "total": 13}
        yield {
            "event_type": "_result_raw",
            "_graph_output": {
                "messages": [],
                "final_response": "İşte sonuç",
            },
        }

    service.chatbot.astream_events_async = mock_raw_events
    service.chatbot.extract_response = MagicMock(return_value="İşte sonuç")

    request = ChatMessageRequest(session_id="s1", message="Satışları göster")
    collected = []
    async for event in service.stream_message(request):
        collected.append(event)

    assert len(collected) == 2
    assert isinstance(collected[0], StreamEvent)
    assert collected[0].event_type == "progress"
    assert collected[0].step == "classify_intent"
    assert collected[1].event_type == "result"
    assert collected[1].type == "text"
    assert collected[1].text == "İşte sonuç"


@pytest.mark.asyncio
async def test_stream_message_yields_report_result_when_chart_present():
    service = _make_service_with_session(session_id="s2")

    from langchain_core.messages import AIMessage
    ai_msg = AIMessage(content="Grafik başlığı", additional_kwargs={"chart_html": "<iframe>chart</iframe>"})

    async def mock_raw_events(state, config):
        yield {
            "event_type": "_result_raw",
            "_graph_output": {"messages": [ai_msg]},
        }

    service.chatbot.astream_events_async = mock_raw_events
    service.chatbot.extract_response = MagicMock(return_value="Grafik başlığı")

    request = ChatMessageRequest(session_id="s2", message="Grafik yap")
    collected = []
    async for event in service.stream_message(request):
        collected.append(event)

    assert len(collected) == 1
    assert collected[0].event_type == "result"
    assert collected[0].type == "report"
    assert "<iframe>" in collected[0].action["target"]


@pytest.mark.asyncio
async def test_stream_message_stores_hitl_state_and_yields_question():
    service = _make_service_with_session(session_id="s3")

    async def mock_raw_events(state, config):
        yield {
            "event_type": "result",
            "text": "❓ Hangi şube?",
            "type": "question",
            "confidence": 0.9,
            "action": {"type": "hitl", "target": "", "params": {"question": "Hangi şube?", "options": ["A", "B"], "context": ""}},
            "_hitl_info": {"type": "choice", "question": "Hangi şube?", "options": ["A", "B"], "context": ""},
        }

    service.chatbot.astream_events_async = mock_raw_events

    request = ChatMessageRequest(session_id="s3", message="Satışlar")
    collected = []
    async for event in service.stream_message(request):
        collected.append(event)

    assert collected[0].type == "question"
    assert service.sessions["s3"]["hitl_pending"] is True


@pytest.mark.asyncio
async def test_stream_message_passes_error_through():
    service = _make_service_with_session(session_id="s4")

    async def mock_raw_events(state, config):
        yield {"event_type": "error", "message": "Zaman aşımı"}

    service.chatbot.astream_events_async = mock_raw_events

    request = ChatMessageRequest(session_id="s4", message="test")
    collected = []
    async for event in service.stream_message(request):
        collected.append(event)

    assert collected[0].event_type == "error"
    assert "Zaman aşımı" in collected[0].message


@pytest.mark.asyncio
async def test_stream_message_uses_command_resume_for_hitl():
    """When HITL is pending, stream_message passes Command(resume=...) to chatbot."""
    from langgraph.types import Command
    service = _make_service_with_session(session_id="s5", hitl_pending=True)
    service.sessions["s5"]["hitl_question"] = {"type": "choice", "question": "Q?", "options": [], "context": ""}

    received_states = []

    async def mock_raw_events(state, config):
        received_states.append(state)
        yield {
            "event_type": "_result_raw",
            "_graph_output": {"messages": []},
        }

    service.chatbot.astream_events_async = mock_raw_events
    service.chatbot.extract_response = MagicMock(return_value="ok")

    request = ChatMessageRequest(session_id="s5", message="Şube A")
    async for _ in service.stream_message(request):
        pass

    assert isinstance(received_states[0], Command)
    assert service.sessions["s5"]["hitl_pending"] is False
```

- [ ] **Step 2: Run — expect ImportError / AttributeError**

```bash
pytest tests/api/services/test_stream_message.py -v -k "stream_message"
```
Expected: `AttributeError: 'ChatService' object has no attribute 'stream_message'`

- [ ] **Step 3: Add `_prepare_graph_state()` and `stream_message()` to `src/api/services/chat_service.py`**

Add the following two methods to the `ChatService` class, right before `get_session_history()` (after line ~489):

```python
async def _prepare_graph_state(self, request: "ChatMessageRequest") -> tuple:
    """
    Build (graph_state, full_config) from the incoming request.
    Handles HITL-resume (Command) and normal new-message paths.
    Shared by stream_message(); send_message() has its own equivalent inline.
    """
    session = self.get_session(request.session_id)
    hitl_pending = self._get_hitl_state(request.session_id)

    if hitl_pending:
        from langgraph.types import Command
        state = Command(resume=request.message)
        self._clear_hitl_state(request.session_id)
    else:
        new_message = HumanMessage(content=request.message)
        state = {"messages": [new_message], "session_id": request.session_id}
        if session.get("token"):
            state["token"] = session["token"]

    full_config = self.chatbot._prepare_config(thread_id=request.session_id)
    return state, full_config

async def stream_message(self, request: "ChatMessageRequest"):
    """
    Stream progress events and the final result for a chat message.

    Yields StreamEvent objects:
      - event_type="progress" for each pipeline node that starts
      - event_type="result"   when the graph completes (or is interrupted)
      - event_type="error"    if the graph raises an unhandled exception

    Raises:
        ValueError: If session not found.
    """
    from src.api.models.responses.chat import StreamEvent

    if not self.session_exists(request.session_id):
        raise ValueError(f"Session not found: {request.session_id}")

    session = self.get_session(request.session_id)
    state, config = await self._prepare_graph_state(request)

    async for raw in self.chatbot.astream_events_async(state, config):
        event_type = raw["event_type"]

        if event_type == "progress":
            yield StreamEvent(
                event_type="progress",
                step=raw["step"],
                message=raw["message"],
                index=raw["index"],
                total=raw["total"],
            )

        elif event_type == "_result_raw":
            graph_output = raw["_graph_output"]

            # Persist messages for this turn
            graph_messages = graph_output.get("messages", []) if isinstance(graph_output, dict) else []
            if graph_messages:
                session["messages"] = graph_messages

            # State-based HITL fallback (detect_hitl_question)
            hitl_info = self._detect_hitl_question(graph_output)
            if hitl_info:
                self._store_hitl_state(request.session_id, hitl_info)
                question_text = hitl_info["question"]
                options = hitl_info["options"]
                context = hitl_info.get("context", "")
                if options:
                    options_text = "\n".join([f"  {i+1}. {opt}" for i, opt in enumerate(options)])
                    full_text = f"❓ {question_text}\n\nSeçenekler:\n{options_text}"
                else:
                    full_text = f"❓ {question_text}"
                if context:
                    full_text += f"\n\nℹ️ {context}"
                yield StreamEvent(
                    event_type="result",
                    text=full_text,
                    type="question",
                    confidence=0.9,
                    action={"type": "hitl", "target": "", "params": {
                        "question": question_text, "options": options, "context": context,
                    }},
                )
                return

            # Build response using same detection as send_message
            bot_text = self.chatbot.extract_response(graph_output)
            current_msgs = self._get_current_turn_messages(graph_messages)
            routing_info = self._detect_routing_response(current_msgs)
            report_info = self._detect_report_response(current_msgs)

            if routing_info:
                yield StreamEvent(
                    event_type="result",
                    text=bot_text,
                    type="navigation",
                    confidence=0.85,
                    action={"type": "routing", "target": routing_info["url"], "params": {}},
                )
            elif report_info:
                yield StreamEvent(
                    event_type="result",
                    text=report_info["text"] or "Grafik oluşturuldu",
                    type="report",
                    confidence=0.85,
                    action={"type": "chart", "target": report_info["html"], "params": {}},
                )
            else:
                yield StreamEvent(
                    event_type="result",
                    text=bot_text,
                    type="text",
                    confidence=0.95,
                    action={"type": "none", "target": "", "params": {}},
                )

        elif event_type == "result":
            # HITL question from astream_events_async (interrupt exception path)
            hitl_info = raw.get("_hitl_info")
            if hitl_info:
                self._store_hitl_state(request.session_id, hitl_info)
            yield StreamEvent(
                event_type="result",
                text=raw.get("text", ""),
                type=raw.get("type", "text"),
                confidence=raw.get("confidence", 0.9),
                action=raw.get("action", {"type": "none", "target": "", "params": {}}),
            )

        elif event_type == "error":
            yield StreamEvent(
                event_type="error",
                message=raw.get("message", "Bir hata oluştu"),
            )
```

- [ ] **Step 4: Run all stream_message tests — expect all pass**

```bash
pytest tests/api/services/test_stream_message.py -v
```
Expected: `9 passed` (3 StreamEvent model tests + 6 stream_message tests)

- [ ] **Step 5: Commit**

```bash
git add src/api/services/chat_service.py tests/api/services/test_stream_message.py
git commit -m "feat(stream): add stream_message() and _prepare_graph_state() to ChatService"
```

---

## Task 7: Add POST /api/chat/stream Route

**Files:**
- Modify: `src/api/routes/chat.py`

- [ ] **Step 1: Add the route to `src/api/routes/chat.py`**

Add after the existing imports at the top:

```python
from sse_starlette.sse import EventSourceResponse
```

Add after the existing `send_message` route (after line ~58):

```python
@router.post("/stream")
async def stream_message(
    request: ChatMessageRequest,
    chat_service: ChatService = Depends(get_chat_service)
) -> EventSourceResponse:
    """
    Stream progress events and final result for a chat message via SSE.

    Parameters:
    - **session_id**: Session identifier from /session/start
    - **message**: User message text

    Returns text/event-stream with events:
    - event: progress  data: {"step", "message", "index", "total"}
    - event: result    data: {"text", "type", "confidence", "action"}
    - event: error     data: {"message"}
    """
    async def event_generator():
        try:
            async for stream_event in chat_service.stream_message(request):
                yield {
                    "event": stream_event.event_type,
                    "data": stream_event.model_dump_json(
                        exclude={"event_type"},
                        exclude_none=True,
                    ),
                }
        except ValueError as e:
            yield {
                "event": "error",
                "data": f'{{"message": "{str(e)}"}}',
            }
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                yield {
                    "event": "error",
                    "data": '{"message": "LLM API kotası aşıldı."}',
                }
            else:
                yield {
                    "event": "error",
                    "data": f'{{"message": "Bir hata oluştu: {err[:100]}"}}',
                }

    return EventSourceResponse(event_generator())
```

- [ ] **Step 2: Verify the app starts without errors**

```bash
python -c "from src.api.routes.chat import router; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Smoke test with curl (requires running server)**

Start the server:
```bash
python main.py
```

In a separate terminal, start a session then stream:
```bash
# 1. Start session
curl -X POST http://localhost:8000/api/chat/session/start \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test"}'

# 2. Stream a message (replace SESSION_ID with value from step 1)
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id": "SESSION_ID", "message": "Merhaba"}'
```

Expected output (SSE events scrolling):
```
event: progress
data: {"step":"classify_intent","message":"Sorgu analiz ediliyor...","index":0,"total":13}

event: result
data: {"text":"Merhaba! ...","type":"text","confidence":0.95,"action":{"type":"none","target":"","params":{}}}
```

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/chat.py
git commit -m "feat(stream): add POST /api/chat/stream SSE endpoint"
```

---

## Task 8: Run Full Test Suite

- [ ] **Step 1: Run all new tests together**

```bash
pytest tests/unit/test_progress_mapper.py tests/core/test_chatbot_astream_events.py tests/api/services/test_stream_message.py -v
```
Expected: `~17 passed`, 0 failed

- [ ] **Step 2: Run existing tests to check for regressions**

```bash
pytest tests/ -v --ignore=tests/integration -x -q
```
Expected: no new failures (pre-existing failures if any are not caused by this change)

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(stream): Feature 1.2 complete — SSE progress notifications for report pipeline"
```

---

## Notes for Implementor

1. **LangGraph event structure verification:** The `astream_events(version="v2")` event dict fields used in this plan (`event`, `name`, `run_id`, `parent_ids`, `data.output`) should be verified against the installed LangGraph version. Run `python -c "import langgraph; print(langgraph.__version__)"` to check.

2. **`parent_ids` behavior:** The plan identifies root vs. node events using `parent_ids == []` for root and `parent_ids != []` for nodes. If this doesn't work as expected, fall back to tracking `root_run_id` from the first `on_chain_start` event.

3. **HITL + streaming:** When the user answers a HITL question and calls `POST /api/chat/stream` again, the `_prepare_graph_state()` method detects `hitl_pending=True` and returns `Command(resume=request.message)`. The graph resumes and emits progress events for the remaining nodes. This is the same flow as the existing `send_message()`.

4. **Token (auth) in state:** The plan omits token injection for Command-based HITL resumes (same as current `send_message()` — token is not re-injected on resume). If this causes issues, add token injection in `_prepare_graph_state()` before the Command branch.
