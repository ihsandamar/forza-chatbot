# Forward Tool (Agent Passthrough) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `create_forward_tool()` so subagent responses go directly to END without supervisor LLM re-processing.

**Architecture:** New `create_forward_tool()` in `utilities.py` sets `_passthrough_active=True` in state. Conditional edges after each agent check this flag: True -> END, False -> supervisor. Report uses forward tool, others keep regular handoff.

**Tech Stack:** Python, LangGraph (Command, MessagesState), pytest

---

### Task 1: Add `create_forward_tool()` to utilities.py

**Context:**
`create_handoff_tool()` at `utilities.py:16` creates tools that route `agent -> supervisor`. We need `create_forward_tool()` that does the same routing TO the agent, but also sets `_passthrough_active=True` in state so the conditional edge after the agent routes to END instead of supervisor.

**Files:**
- Modify: `src/graphs/supervisor/utilities.py:16-54`
- Test: `tests/graphs/supervisor/test_forward_tool.py` (create)

**Step 1: Write the failing test**

Create `tests/graphs/supervisor/__init__.py` (empty) if it doesn't exist, then create:

```python
# tests/graphs/supervisor/test_forward_tool.py
"""Tests for create_forward_tool passthrough mechanism."""

import pytest


def test_create_forward_tool_exists():
    """create_forward_tool should be importable from utilities."""
    from src.graphs.supervisor.utilities import create_forward_tool
    assert callable(create_forward_tool)


def test_create_forward_tool_creates_tool():
    """create_forward_tool should return a BaseTool with correct name."""
    from src.graphs.supervisor.utilities import create_forward_tool
    tool = create_forward_tool(agent_name="test_agent")
    assert tool.name == "transfer_to_test_agent"


def test_create_forward_tool_custom_name():
    """create_forward_tool should accept custom name."""
    from src.graphs.supervisor.utilities import create_forward_tool
    tool = create_forward_tool(agent_name="report", name="forward_to_report")
    assert tool.name == "forward_to_report"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/graphs/supervisor/test_forward_tool.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_forward_tool'`

**Step 3: Implement create_forward_tool**

In `src/graphs/supervisor/utilities.py`, add after `create_handoff_tool` (after line 54):

```python
def create_forward_tool(*, agent_name: str, name: str | None = None, description: str | None = None) -> BaseTool:
    """Create a tool that transfers control to an agent and goes directly to END after.

    Unlike create_handoff_tool (agent -> supervisor -> END), this tool sets
    _passthrough_active=True so the conditional edge routes agent -> END directly.
    The agent's response becomes the final response without supervisor re-processing.
    """
    if name is None:
        name = f"transfer_to_{_normalize_agent_name(agent_name)}"
    if description is None:
        description = f"Forward to agent '{agent_name}' — response goes directly to user"

    @tool(name, description=description)
    def forward_to_agent(
        state: Annotated[dict, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ):
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else None
        last_msg_content = getattr(last_msg, "content", str(last_msg))[:100] if last_msg else "No message"

        logger.info(f"[SUPERVISOR] FORWARD TRIGGERED -> {agent_name.upper()} (passthrough=True)")
        logger.debug(f"[SUPERVISOR] User message: '{last_msg_content}...'")

        tool_message = ToolMessage(
            content=dedent(f"""
            Successfully transferred to {agent_name}.
            """),
            name=name,
            tool_call_id=tool_call_id
        )

        return Command(
            goto=agent_name,
            graph=Command.PARENT,
            update={
                "messages": state["messages"] + [tool_message],
                "_passthrough_active": True,
            },
        )
    return forward_to_agent
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/graphs/supervisor/test_forward_tool.py -v`
Expected: All 3 PASS

**Step 5: Commit**

```bash
git add src/graphs/supervisor/utilities.py tests/graphs/supervisor/test_forward_tool.py tests/graphs/supervisor/__init__.py
git commit -m "feat: add create_forward_tool for agent passthrough to END"
```

---

### Task 2: Use forward tool for report agent in tools.py

**Context:**
Currently `assign_to_report_agent` uses `create_handoff_tool()` (tools.py:31). Change it to `create_forward_tool()` so report agent responses go directly to END.

**Files:**
- Modify: `src/graphs/supervisor/tools.py:31-34`
- Test: `tests/graphs/supervisor/test_forward_tool.py` (append)

**Step 1: Write the failing test**

Append to `tests/graphs/supervisor/test_forward_tool.py`:

```python
def test_report_agent_uses_forward_tool():
    """assign_to_report_agent should use create_forward_tool, not create_handoff_tool."""
    from src.graphs.supervisor.tools import assign_to_report_agent
    # Forward tools have passthrough description pattern
    assert "forward" in assign_to_report_agent.description.lower() or "directly" in assign_to_report_agent.description.lower()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/graphs/supervisor/test_forward_tool.py::test_report_agent_uses_forward_tool -v`
Expected: FAIL — current description doesn't contain "forward" or "directly"

**Step 3: Change report tool to forward**

In `src/graphs/supervisor/tools.py`, change:

```python
# BEFORE:
from src.graphs.supervisor.utilities import create_handoff_tool

assign_to_report_agent = create_handoff_tool(
    agent_name="report",
    description="Assign task to report agent for data analysis, SQL queries, reports, visualizations, charts, and master report queries.",
)

# AFTER:
from src.graphs.supervisor.utilities import create_handoff_tool, create_forward_tool

assign_to_report_agent = create_forward_tool(
    agent_name="report",
    description="Forward to report agent for data analysis, SQL queries, reports, visualizations, charts — response goes directly to user.",
)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/graphs/supervisor/test_forward_tool.py -v`
Expected: All 4 PASS

**Step 5: Commit**

```bash
git add src/graphs/supervisor/tools.py tests/graphs/supervisor/test_forward_tool.py
git commit -m "feat: use create_forward_tool for report agent passthrough"
```

---

### Task 3: Add conditional edges in graph.py

**Context:**
Currently `graph.py:667` has `builder.add_edge("chat", "supervisor")` and line 671 has `builder.add_edge("report", "supervisor")` — both are fixed edges back to supervisor. We need conditional edges that check `state["_passthrough_active"]`: True -> END, False -> supervisor.

The `_passthrough_active` flag is set by `create_forward_tool` in the state update. After routing to END, the flag should be reset so subsequent turns don't accidentally passthrough.

**Files:**
- Modify: `src/graphs/supervisor/graph.py:660-673`
- Test: `tests/graphs/supervisor/test_forward_tool.py` (append)

**Step 1: Write the failing test**

Append to `tests/graphs/supervisor/test_forward_tool.py`:

```python
def test_post_agent_router_passthrough():
    """When _passthrough_active=True, router should return '__end__'."""
    from src.graphs.supervisor.graph import _post_agent_router
    state = {"_passthrough_active": True}
    assert _post_agent_router(state) == "__end__"


def test_post_agent_router_normal():
    """When _passthrough_active is False/missing, router should return 'supervisor'."""
    from src.graphs.supervisor.graph import _post_agent_router
    assert _post_agent_router({}) == "supervisor"
    assert _post_agent_router({"_passthrough_active": False}) == "supervisor"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/graphs/supervisor/test_forward_tool.py::test_post_agent_router_passthrough -v`
Expected: FAIL — `ImportError: cannot import name '_post_agent_router'`

**Step 3: Implement router function and conditional edges**

In `src/graphs/supervisor/graph.py`, add the router function near the top (after line 38, before the existing functions):

```python
def _post_agent_router(state: dict) -> str:
    """Route after agent: passthrough -> END, otherwise -> supervisor."""
    if state.get("_passthrough_active"):
        return "__end__"
    return "supervisor"
```

Then in `build_graph()`, replace the fixed edges (around lines 665-671):

```python
# BEFORE:
builder.add_edge("routing", "process_routing_output")
builder.add_edge("process_routing_output", "supervisor")
builder.add_edge("chat", "supervisor")

if report_agent_wrapper:
    builder.add_edge("report", "supervisor")

# AFTER:
builder.add_edge("routing", "process_routing_output")
builder.add_conditional_edges(
    "process_routing_output",
    _post_agent_router,
    {"__end__": END, "supervisor": "supervisor"},
)
builder.add_conditional_edges(
    "chat",
    _post_agent_router,
    {"__end__": END, "supervisor": "supervisor"},
)

if report_agent_wrapper:
    builder.add_conditional_edges(
        "report",
        _post_agent_router,
        {"__end__": END, "supervisor": "supervisor"},
    )
```

**Step 4: Run all tests**

Run: `python -m pytest tests/graphs/supervisor/test_forward_tool.py -v`
Expected: All 6 PASS

**Step 5: Commit**

```bash
git add src/graphs/supervisor/graph.py tests/graphs/supervisor/test_forward_tool.py
git commit -m "feat: add conditional edges for agent passthrough routing"
```

---

### Task 4: Export create_forward_tool from __init__.py

**Context:**
`src/graphs/supervisor/__init__.py` exports `create_handoff_tool`. Add `create_forward_tool` for external consumers.

**Files:**
- Modify: `src/graphs/supervisor/__init__.py`

**Step 1: Add export**

In `src/graphs/supervisor/__init__.py`, add `create_forward_tool` to the import from utilities and to `__all__`:

```python
# Add to imports:
from src.graphs.supervisor.utilities import create_handoff_tool, create_forward_tool

# Add to __all__:
"create_forward_tool",
```

**Step 2: Run all tests**

Run: `python -m pytest tests/graphs/supervisor/test_forward_tool.py -v`
Expected: All 6 PASS

**Step 3: Commit**

```bash
git add src/graphs/supervisor/__init__.py
git commit -m "chore: export create_forward_tool from supervisor package"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | `create_forward_tool()` function | `utilities.py`, test file |
| 2 | Report uses forward tool | `tools.py` |
| 3 | Conditional edges (passthrough -> END) | `graph.py` |
| 4 | Export from `__init__.py` | `__init__.py` |

**Result:** `supervisor -> report -> END` (no redundant supervisor LLM call). Any agent can be switched to passthrough by changing `create_handoff_tool` -> `create_forward_tool` in `tools.py`.
