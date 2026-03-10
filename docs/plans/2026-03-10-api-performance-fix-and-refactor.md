# API Performance Fix & Chat Service Refactor

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix ~2x performance regression in API vs langgraph dev by eliminating message duplication, removing unnecessary state reads, and cleaning up dead code in chat_service.

**Architecture:** The root cause is that chat_service sends full message history on every invoke while the MemorySaver checkpointer already retains it — causing double processing by the `add_messages` reducer. Secondary issues include a redundant `aget_state()` call after every invoke and ~15 dead state fields that never reach the graph.

**Tech Stack:** LangGraph, FastAPI, MemorySaver checkpointer, MessagesState

---

## Phase 1: Performance Fixes (Critical)

### Task 1: Send Only New Message to Graph (Main Performance Fix)

**Problem:** `chat_service.py` sends ALL session messages on every invoke. The MemorySaver checkpointer (keyed by thread_id/session_id) already retains the full conversation. The `add_messages` reducer must process N messages instead of 1 on each call.

In `langgraph dev`, only the new message is sent — checkpointer handles history.

**Files:**
- Modify: `src/api/services/chat_service.py:284-344`
- Test: `tests/test_chat_service_performance.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_chat_service_performance.py
"""Test that chat_service sends only new messages to graph, not full history."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import ChatMessageRequest


@pytest.fixture
def chat_service():
    mock_chatbot = MagicMock()
    mock_chatbot.get_graph_output_async = AsyncMock(return_value={
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "show sales"},
            {"role": "assistant", "content": "here are sales"},
        ]
    })
    mock_chatbot._from_graph_state = MagicMock(return_value="here are sales")
    return ChatService(mock_chatbot)


@pytest.mark.asyncio
async def test_sends_only_new_message_not_full_history(chat_service):
    """After multiple turns, only the NEW user message should be sent to graph."""
    # Setup: create session with existing history
    from src.api.models.requests.chat import SessionStartRequest
    session_resp = await chat_service.start_session(
        SessionStartRequest(user_id="test", token=None)
    )
    session_id = session_resp.session_id

    # Simulate existing conversation in session (2 turns already happened)
    session = chat_service.get_session(session_id)
    session["messages"] = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "show sales"},
        {"role": "assistant", "content": "here are sales"},
    ]

    # Act: send 3rd message
    request = ChatMessageRequest(session_id=session_id, message="add filter")
    await chat_service.send_message(request)

    # Assert: chatbot received ONLY the new message, not full history
    call_args = chat_service.chatbot.get_graph_output_async.call_args
    state_sent = call_args[0][0]  # first positional arg
    messages_sent = state_sent["messages"]

    # Should be ONLY the new message (1 message), not all 5
    assert len(messages_sent) == 1, (
        f"Expected 1 new message, got {len(messages_sent)}. "
        f"Full history should be managed by checkpointer, not sent on every invoke."
    )
    assert messages_sent[0]["content"] == "add filter"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_service_performance.py::test_sends_only_new_message_not_full_history -v`
Expected: FAIL — currently sends all 5 messages

**Step 3: Implement the fix**

Edit `src/api/services/chat_service.py` — change the normal message flow (lines 336-344):

**Before (current):**
```python
else:
    # Normal message - add to conversation history
    messages.append({"role": "user", "content": request.message})
    state["messages"] = messages
    state["user_clarification"] = None
    state["pending_question"] = None
    state["waiting_for_user_input"] = False
```

**After (fixed):**
```python
else:
    # Normal message — send ONLY the new message to graph.
    # MemorySaver checkpointer (keyed by session_id/thread_id) already
    # retains full conversation history. Sending all messages causes
    # the add_messages reducer to re-process N messages instead of 1.
    new_message = {"role": "user", "content": request.message}
    state = {"messages": [new_message]}

    logger.info(f"[CHAT] Normal message received: {request.message[:50]}...")
```

Also update post-invoke persistence (lines 417-424) — still save full graph output to session for history endpoint:

**Keep as-is:** Lines 419-424 already correctly save `graph_output["messages"]` to session. This is needed for the `/history` endpoint, NOT for graph input.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_service_performance.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/api/services/chat_service.py tests/test_chat_service_performance.py
git commit -m "perf: send only new message to graph, let checkpointer handle history"
```

---

### Task 2: Remove Redundant `aget_state()` After Every Invoke

**Problem:** `chatbot.py:366-376` calls `aget_state()` after every invoke to check for silent interrupts. This reads the FULL state from the checkpointer — expensive and unnecessary for most requests. `GraphInterrupt` is already caught as an exception at `chat_service.py:358`.

**Files:**
- Modify: `src/core/chatbot.py:326-385`
- Test: `tests/test_chatbot_no_extra_state_read.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_chatbot_no_extra_state_read.py
"""Test that chatbot does not call aget_state() after successful invoke."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.chatbot import Chatbot
from src.models.llm import LLM


@pytest.fixture
def chatbot_with_mock_graph():
    mock_llm = MagicMock(spec=LLM)
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"messages": [{"role": "assistant", "content": "ok"}]})
    mock_graph.aget_state = AsyncMock(return_value=MagicMock(tasks=[]))

    chatbot = Chatbot(llm=mock_llm, graph=mock_graph)
    return chatbot, mock_graph


@pytest.mark.asyncio
async def test_no_aget_state_after_successful_invoke(chatbot_with_mock_graph):
    """aget_state should NOT be called after a successful (non-interrupt) invoke."""
    chatbot, mock_graph = chatbot_with_mock_graph

    state = {"messages": [{"role": "user", "content": "hello"}]}
    await chatbot._invoke_graph_async(state, thread_id="test-session")

    # aget_state should NOT have been called
    mock_graph.aget_state.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chatbot_no_extra_state_read.py -v`
Expected: FAIL — currently calls aget_state after every invoke

**Step 3: Implement the fix**

Edit `src/core/chatbot.py` — remove the `aget_state()` block from `_invoke_graph_async()`.

The interrupt check at lines 366-376 should be removed entirely. Rationale:
- `GraphInterrupt` is raised as an exception by LangGraph when `interrupt()` is called in a node
- `chat_service.py:358` already catches `GraphInterrupt` and handles it
- The "silent interrupt" pattern (stored in checkpoint but not raised) is a LangGraph v0 behavior that no longer applies when using `interrupt()` function (v1 pattern)

**Remove lines 366-376:**
```python
            # DELETE THIS BLOCK:
            # LangGraph v1: invoke()/ainvoke() does NOT raise GraphInterrupt.
            # Interrupts are stored in the checkpoint silently. Check for them.
            if hasattr(self.graph, 'aget_state'):
                state_snapshot = await self.graph.aget_state(full_config)
                if state_snapshot and state_snapshot.tasks:
                    pending_interrupts = []
                    for task in state_snapshot.tasks:
                        for intr in task.interrupts:
                            pending_interrupts.append(intr)
                    if pending_interrupts:
                        raise GraphInterrupt(tuple(pending_interrupts))
```

Also remove the same pattern from sync `_invoke_graph` (lines 198-206).

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chatbot_no_extra_state_read.py -v`
Expected: PASS

**Step 5: Run existing tests to verify no regression**

Run: `pytest tests/ -v --timeout=30`
Expected: All existing tests pass

**Step 6: Commit**

```bash
git add src/core/chatbot.py tests/test_chatbot_no_extra_state_read.py
git commit -m "perf: remove redundant aget_state() call after every invoke"
```

---

## Phase 2: Dead Code Cleanup & Refactor

### Task 3: Remove Dead State Fields From chat_service

**Problem:** `chat_service.py:284-304` builds a state dict with ~15 fields that:
1. Get stripped by `chatbot._to_graph_state()` (only passes `messages`)
2. Don't exist in SupervisorGraph's `MessagesState` schema
3. Don't exist in ReportState (`active_query_context`, `query_history` are not real fields)
4. Are never used — completely dead code

**Files:**
- Modify: `src/api/services/chat_service.py:283-305`
- Modify: `src/api/services/chat_service.py:426-432` (dead persistence code)

**Step 1: Remove dead state fields**

Replace lines 283-305 and 336-344 with the simplified version from Task 1.

The full state construction block should become:

```python
# Prepare state for chatbot
# Only send the new message. MemorySaver checkpointer handles
# full conversation history via thread_id (session_id).
# Report agent context (active_sql, active_results, active_filters)
# is preserved by the checkpointer automatically.
```

**Step 2: Remove dead session persistence**

Lines 426-432 reference `active_query_context` and `query_history` which don't exist in any graph state. Remove:

```python
# DELETE: These fields don't exist in ReportState or MessagesState.
# Report agent context is preserved by MemorySaver checkpointer via thread_id.
if graph_output.get("active_query_context"):
    session["active_query_context"] = graph_output["active_query_context"]

if graph_output.get("query_history"):
    session["query_history"] = graph_output["query_history"]
```

**Step 3: Run tests**

Run: `pytest tests/ -v --timeout=30`
Expected: All tests pass

**Step 4: Commit**

```bash
git add src/api/services/chat_service.py
git commit -m "refactor: remove dead state fields from chat_service"
```

---

### Task 4: Simplify chatbot._to_graph_state and _process_message_async

**Problem:** `_to_graph_state()` always wraps messages in `{"messages": messages}` but chat_service already sends the state dict with a `messages` key. The extra transformation is redundant and confusing — it also strips any non-message fields that might be needed in the future.

**Files:**
- Modify: `src/core/chatbot.py:109-119, 387-440`

**Step 1: Simplify _process_message_async**

Currently (lines 401-433):
```python
# Current: extracts messages, then re-wraps them
messages = state.get("messages", [])
# ... validation ...
graph_state = self._to_graph_state(messages)  # {"messages": messages}
if 'token' in adapter_kwargs:
    graph_state['token'] = adapter_kwargs['token']
```

After:
```python
# Simplified: state already has correct structure, pass it through
if not isinstance(state, (dict, Command)):
    raise MessageProcessingException(...)

if isinstance(state, Command):
    thread_id = adapter_kwargs.get('thread_id')
    return await self._invoke_graph_async(state, thread_id=thread_id)

messages = state.get("messages", [])
if not isinstance(messages, list) or not messages:
    raise MessageProcessingException(...)

# Pass state directly — chat_service already builds correct structure
graph_state = state
if 'token' in adapter_kwargs:
    graph_state['token'] = adapter_kwargs['token']

thread_id = adapter_kwargs.get('thread_id')
return await self._invoke_graph_async(graph_state, thread_id=thread_id)
```

**Step 2: Run tests**

Run: `pytest tests/ -v --timeout=30`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/core/chatbot.py
git commit -m "refactor: simplify chatbot message processing, remove redundant state wrapping"
```

---

### Task 5: Remove copy.deepcopy From Config Preparation

**Problem:** `chatbot.py:91` does `copy.deepcopy(self.config)` on every request. The config dict is small and never mutated by the graph (LangGraph uses its own internal config copy). This is unnecessary overhead.

**Files:**
- Modify: `src/core/chatbot.py:78-107`

**Step 1: Replace deepcopy with shallow construction**

```python
def _prepare_config(self, thread_id: str = None) -> dict:
    try:
        assistant_config_dict = (
            self.assistant_config.to_dict()
            if hasattr(self.assistant_config, 'to_dict')
            else self.assistant_config
        )

        if not isinstance(self.config, dict):
            raise ConfigurationException(
                "Config must be a dictionary",
                context={"config_type": type(self.config).__name__}
            )

        # Build config without deepcopy — LangGraph doesn't mutate this
        configurable = {
            **self.config.get("configurable", {}),
            "assistant_config": assistant_config_dict,
        }
        if thread_id:
            configurable["thread_id"] = thread_id

        return {**self.config, "configurable": configurable}
    except ConfigurationException:
        raise
    except Exception as e:
        raise ConfigurationException(
            f"Failed to prepare configuration: {str(e)}",
            context={"original_error": str(e)}
        ) from e
```

**Step 2: Run tests**

Run: `pytest tests/ -v --timeout=30`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/core/chatbot.py
git commit -m "refactor: replace deepcopy with shallow config construction"
```

---

## Phase 3: Validation & Integration Test

### Task 6: End-to-End Performance Validation

**Step 1: Create integration test that validates the full flow**

```python
# tests/test_api_performance_integration.py
"""Integration test: verify API message flow matches langgraph dev pattern."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import ChatMessageRequest, SessionStartRequest


@pytest.fixture
def service_with_tracking():
    """ChatService with a mock chatbot that tracks what state it receives."""
    received_states = []

    async def track_invoke(state, **kwargs):
        received_states.append(state)
        return {
            "messages": [
                {"role": "assistant", "content": f"response to turn {len(received_states)}"}
            ]
        }

    mock_chatbot = MagicMock()
    mock_chatbot.get_graph_output_async = AsyncMock(side_effect=track_invoke)
    mock_chatbot._from_graph_state = MagicMock(return_value="response")

    service = ChatService(mock_chatbot)
    return service, received_states


@pytest.mark.asyncio
async def test_multi_turn_sends_only_new_messages(service_with_tracking):
    """Over multiple turns, each invoke should receive ONLY the new message."""
    service, received_states = service_with_tracking

    # Start session
    session = await service.start_session(SessionStartRequest(user_id="perf-test", token=None))
    sid = session.session_id

    # Turn 1
    await service.send_message(ChatMessageRequest(session_id=sid, message="hello"))
    assert len(received_states[0]["messages"]) == 1

    # Turn 2
    await service.send_message(ChatMessageRequest(session_id=sid, message="show sales"))
    assert len(received_states[1]["messages"]) == 1

    # Turn 3
    await service.send_message(ChatMessageRequest(session_id=sid, message="add filter"))
    assert len(received_states[2]["messages"]) == 1

    # Each turn should have sent exactly 1 message
    for i, state in enumerate(received_states):
        msg_count = len(state["messages"])
        assert msg_count == 1, f"Turn {i+1}: expected 1 message, got {msg_count}"
```

**Step 2: Run all tests**

Run: `pytest tests/ -v --timeout=30`
Expected: All pass

**Step 3: Commit**

```bash
git add tests/test_api_performance_integration.py
git commit -m "test: add integration test for API message flow performance"
```

---

## Summary of Changes

| Task | Type | Impact | Files |
|------|------|--------|-------|
| 1 | **Perf fix** | ~50-60% of slowdown | `chat_service.py` |
| 2 | **Perf fix** | ~20-30% of slowdown | `chatbot.py` |
| 3 | **Cleanup** | Dead code removal | `chat_service.py` |
| 4 | **Refactor** | Code clarity | `chatbot.py` |
| 5 | **Refactor** | Minor perf + clarity | `chatbot.py` |
| 6 | **Validation** | Regression prevention | `tests/` |

**Expected outcome:** API performance should approach langgraph dev levels after Task 1 and Task 2. The remaining tasks clean up the codebase for maintainability.

**Risk:** Task 1 changes how messages are sent to the graph. If any code path outside the checkpointer relies on receiving full message history, it would break. The supervisor graph uses `MessagesState` with `add_messages` reducer + MemorySaver — this is the standard LangGraph pattern and should work correctly with single-message input.

**Verification:** After all tasks, test with the same queries you used to measure the 2x slowdown and compare timing.
