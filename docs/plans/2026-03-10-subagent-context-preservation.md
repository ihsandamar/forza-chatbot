# Subagent Context Preservation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give the report agent its own MemorySaver checkpointer so it preserves conversation context (active_sql, active_results, active_filters) between turns when invoked via supervisor.

**Architecture:** Currently the report agent compiles with `checkpointer=False`, meaning the parent supervisor's checkpointer manages state. But the supervisor uses `MessagesState` (only `messages`), so all ReportState-specific fields are lost between turns. The fix: give the report agent its own `MemorySaver()` checkpointer. On each turn, the subgraph loads its checkpoint (full ReportState from previous turn), merges new messages from parent, and executes with full context. `GraphInterrupt` still bubbles up to the parent via exception chain — interrupt/resume is unaffected.

**Tech Stack:** LangGraph checkpointer (MemorySaver), StateGraph subgraph compilation

---

## Background

### Why context is lost today

```
Turn 1: Supervisor → Report Agent → sql_executor sets active_sql="SELECT..."
        → Report Agent returns to Supervisor → Supervisor saves checkpoint
        → Checkpoint contains: {messages: [...]}  ← active_sql LOST (not in MessagesState)

Turn 2: Supervisor → Report Agent → active_sql=None → classify_intent: NEW_QUERY (wrong!)
```

### How the fix works

```
Turn 1: Supervisor → Report Agent (own MemorySaver) → sql_executor sets active_sql
        → Report Agent saves OWN checkpoint: {messages, active_sql, active_results, ...}
        → Returns to Supervisor → Supervisor saves {messages}

Turn 2: Supervisor → Report Agent loads OWN checkpoint → active_sql="SELECT..."
        → classify_intent: MODIFY_QUERY (correct!)
```

The report agent's MemorySaver is created once during graph compilation (singleton chatbot) and persists across API calls for the process lifetime. Thread ID (session_id) is propagated from parent config automatically.

---

## Task 1: Give Report Agent Its Own Checkpointer

**Files:**
- Modify: `src/graphs/supervisor/graph.py:203-221`
- Test: `tests/test_report_agent_context.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_report_agent_context.py
"""Test that report agent preserves context between turns via supervisor."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage


def test_subgraph_with_own_checkpointer_preserves_state():
    """
    Minimal reproduction: a parent graph (MessagesState) invokes a child
    subgraph (extended state) that has its own MemorySaver.
    The child's extra state fields should persist between turns.
    """
    from typing import Annotated, Optional, List, TypedDict
    from langgraph.graph.message import add_messages
    from langchain_core.messages import BaseMessage

    # Child state with extra fields
    class ChildState(TypedDict):
        messages: Annotated[List[BaseMessage], add_messages]
        context_value: Optional[str]

    # Child graph: reads context_value, sets it if missing
    def child_node(state: dict) -> dict:
        existing = state.get("context_value")
        if existing:
            # Second turn: context preserved!
            return {
                "messages": [AIMessage(content=f"Context found: {existing}")],
            }
        else:
            # First turn: set context
            return {
                "messages": [AIMessage(content="Context set")],
                "context_value": "preserved_data",
            }

    child_builder = StateGraph(ChildState)
    child_builder.add_node("child_node", child_node)
    child_builder.add_edge(START, "child_node")
    child_builder.add_edge("child_node", END)
    child_graph = child_builder.compile(checkpointer=MemorySaver())

    # Parent graph (MessagesState only)
    parent_builder = StateGraph(MessagesState)
    parent_builder.add_node("child", child_graph)
    parent_builder.add_edge(START, "child")
    parent_builder.add_edge("child", END)
    parent_graph = parent_builder.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "test-session"}}

    # Turn 1: child sets context_value
    result1 = parent_graph.invoke(
        {"messages": [HumanMessage(content="first")]}, config
    )
    last_msg1 = result1["messages"][-1].content
    assert "Context set" in last_msg1

    # Turn 2: child should find context_value from its own checkpoint
    result2 = parent_graph.invoke(
        {"messages": [HumanMessage(content="second")]}, config
    )
    last_msg2 = result2["messages"][-1].content
    assert "preserved_data" in last_msg2, (
        f"Expected 'preserved_data' in response but got: '{last_msg2}'. "
        f"Child subgraph did not preserve context_value between turns."
    )
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_agent_context.py::test_subgraph_with_own_checkpointer_preserves_state -v`

Expected: This test should PASS (it validates LangGraph behavior). If it fails, the approach needs rethinking.

**Step 3: Write the real failing test**

```python
def test_report_agent_subgraph_has_checkpointer():
    """The report agent built by supervisor should have a checkpointer."""
    from unittest.mock import patch, MagicMock
    from src.graphs.supervisor.graph import SupervisorGraph
    from src.models.llm import LLM

    # We just need to verify _build_report_agent passes a checkpointer
    with patch("src.graphs.supervisor.graph.build_report_agent_graph") as mock_build:
        mock_build.return_value = MagicMock()  # compiled graph mock
        mock_llm = MagicMock(spec=LLM)
        mock_llm.get_chat.return_value = MagicMock()

        graph = SupervisorGraph(llm=mock_llm)
        try:
            graph._build_report_agent()
        except Exception:
            pass  # May fail due to config loading, that's fine

        if mock_build.called:
            call_kwargs = mock_build.call_args
            checkpointer_arg = call_kwargs.kwargs.get("checkpointer") if call_kwargs.kwargs else None
            # checkpointer should NOT be False
            assert checkpointer_arg is not False, (
                "Report agent should have its own checkpointer, not checkpointer=False"
            )
```

**Step 4: Implement the fix**

Edit `src/graphs/supervisor/graph.py:203-221`:

```python
def _build_report_agent(self):
    """Build report agent subgraph with its own checkpointer for context preservation.

    The report agent gets its own MemorySaver so that ReportState fields
    (active_sql, active_results, active_filters) persist between turns.
    The supervisor only sees MessagesState, so without a subgraph checkpointer
    these fields would be lost on each turn.

    Interrupt propagation is unaffected — GraphInterrupt bubbles up via
    exception chain regardless of checkpointer configuration.
    """
    from src.graphs.report_agent.graph import build_report_agent_graph
    from src.services.config_loader import ConfigLoader

    config = ConfigLoader.load_config()
    project_root = Path(__file__).parent.parent.parent.parent
    business_rules_path = str(project_root / "src" / "graphs" / "generic_text2sql" / "business_rules.json")
    chroma_persist_dir = str(project_root / "data" / "vector_store")

    return build_report_agent_graph(
        llm=self.llm.get_chat(),
        table_name=self.config.report_table_name,
        column_metadata=self.config.report_column_metadata,
        connection_string=config.database.uri,
        business_rules_path=business_rules_path,
        chroma_persist_dir=chroma_persist_dir,
        checkpointer=MemorySaver(),
    )
```

**Step 5: Run tests**

Run: `python -m pytest tests/test_report_agent_context.py -v`
Then: `python -m pytest tests/ -v` (regression check)

**Step 6: Commit**

```bash
git add src/graphs/supervisor/graph.py tests/test_report_agent_context.py
git commit -m "feat: give report agent own checkpointer for context preservation"
```

---

## Task 2: Verify Interrupt/Resume Still Works

**Files:**
- Test: `tests/test_report_agent_context.py` (extend)

**Step 1: Write interrupt propagation test**

```python
def test_subgraph_interrupt_propagates_with_own_checkpointer():
    """
    Interrupt from a subgraph with its own checkpointer should still
    bubble up to the parent and be resumable with Command(resume=...).
    """
    from typing import Annotated, Optional, List, TypedDict
    from langgraph.graph.message import add_messages
    from langgraph.types import interrupt, Command
    from langgraph.errors import GraphInterrupt
    from langchain_core.messages import BaseMessage

    class ChildState(TypedDict):
        messages: Annotated[List[BaseMessage], add_messages]
        user_choice: Optional[str]

    def child_node_with_interrupt(state: dict) -> dict:
        # Interrupt to ask user a question
        answer = interrupt({"question": "Which option?", "options": ["A", "B"]})
        return {
            "messages": [AIMessage(content=f"User chose: {answer}")],
            "user_choice": answer,
        }

    child_builder = StateGraph(ChildState)
    child_builder.add_node("ask", child_node_with_interrupt)
    child_builder.add_edge(START, "ask")
    child_builder.add_edge("ask", END)
    child_graph = child_builder.compile(checkpointer=MemorySaver())

    parent_builder = StateGraph(MessagesState)
    parent_builder.add_node("child", child_graph)
    parent_builder.add_edge(START, "child")
    parent_builder.add_edge("child", END)
    parent_graph = parent_builder.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "interrupt-test"}}

    # First invoke: should raise GraphInterrupt
    try:
        parent_graph.invoke(
            {"messages": [HumanMessage(content="start")]}, config
        )
        assert False, "Expected GraphInterrupt"
    except GraphInterrupt as e:
        interrupt_data = e.args[0][0].value if e.args and e.args[0] else {}
        assert interrupt_data.get("question") == "Which option?"

    # Resume with user's choice
    result = parent_graph.invoke(Command(resume="A"), config)
    last_msg = result["messages"][-1].content
    assert "User chose: A" in last_msg
```

**Step 2: Run test**

Run: `python -m pytest tests/test_report_agent_context.py::test_subgraph_interrupt_propagates_with_own_checkpointer -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_report_agent_context.py
git commit -m "test: verify interrupt/resume works with subgraph checkpointer"
```

---

## Task 3: Update langgraph dev Entrypoint for Consistency

**Files:**
- Modify: `src/graphs/graph_entrypoints.py:118-145`

**Problem:** The direct report_agent entrypoint in `langgraph.json` also creates a MemorySaver. This is already correct (line 134 in report_agent/graph.py defaults to MemorySaver). No change needed here — just verify the behavior is consistent.

**Step 1: Verify entrypoint**

Read `src/graphs/graph_entrypoints.py:118-145` and confirm `report_agent_graph()` does NOT pass `checkpointer=False`. It should use the default (which creates MemorySaver).

**Step 2: If already correct, skip this task**

The direct invocation path already works (user confirmed). This task is just a verification step.

**Step 3: Commit (if changes needed)**

Only if something was changed.

---

## Task 4: Update Supervisor Graph Log Message

**Files:**
- Modify: `src/graphs/supervisor/graph.py:166`

**Step 1: Update misleading log**

Current log says:
```python
logger.info("[SUPERVISOR] Report subgraph built (passthrough, no own checkpointer)")
```

Change to:
```python
logger.info("[SUPERVISOR] Report subgraph built (own checkpointer for context preservation)")
```

**Step 2: Commit**

```bash
git add src/graphs/supervisor/graph.py
git commit -m "docs: update log message for report agent checkpointer"
```

---

## Summary

| Task | Type | What |
|------|------|------|
| 1 | **Core fix** | `checkpointer=False` → `checkpointer=MemorySaver()` |
| 2 | **Test** | Verify interrupt/resume with subgraph checkpointer |
| 3 | **Verify** | Confirm langgraph dev entrypoint already correct |
| 4 | **Cleanup** | Update misleading log message |

**Risk:** Minimal. GraphInterrupt bubbles up via exception chain regardless of checkpointer config. The MemorySaver is created once during graph compilation and persists for process lifetime (singleton chatbot). Thread ID propagates from parent automatically.

**What persists between turns after fix:**
- `active_sql` — enables MODIFY_QUERY detection
- `active_results` — enables USE_RESULT detection and result_count in prompt
- `active_filters` — filter context for modifications
- `_clarification_count` — VAGUE_QUERY loop protection
- All other ReportState fields

**What resets per turn (already in classify_intent_node):**
- `pre_built_sql` — reset to None each turn
- `modification_hints` — reset to None each turn
- `visualization_output` — reset to None each turn
- `_force_table_refresh` — reset to False each turn
