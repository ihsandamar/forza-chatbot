"""
Critical test: verify that GraphInterrupt propagates correctly from a compiled
subgraph (checkpointer=False) through a parent graph (MemorySaver checkpointer).

Reproduces the exact supervisor -> report agent -> interrupt() flow:
- Parent graph uses MessagesState, compiled with MemorySaver
- "supervisor" node is a create_react_agent with a forward tool
- "report" node is a compiled subgraph (NO checkpointer) that calls interrupt()
- Forward tool returns Command(goto="report", graph=Command.PARENT)

NOTE: In langgraph v1, invoke() does NOT raise GraphInterrupt. Instead it
returns partial state and stores the interrupt in the checkpoint. The interrupt
is surfaced via:
  - stream(): yields {"__interrupt__": ...} chunk
  - get_state(): tasks[].interrupts contains the interrupt data
  - get_state().next: contains the node that was interrupted
"""

import pytest
from typing import Annotated
from textwrap import dedent

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
    BaseMessage,
)
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, interrupt
from langgraph.prebuilt import InjectedState, create_react_agent

from pydantic import Field


# ---------------------------------------------------------------------------
# Fake LLM (reuses pattern from test_command_routing_minimal.py)
# ---------------------------------------------------------------------------
class FakeToolCallingModel(BaseChatModel):
    """A fake chat model that cycles through pre-defined responses and supports bind_tools."""

    responses: list = Field(default_factory=list)
    call_index: int = Field(default=0)
    bound_tools: list = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ) -> ChatResult:
        if self.call_index >= len(self.responses):
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="done"))]
            )
        response = self.responses[self.call_index]
        self.call_index += 1
        return ChatResult(generations=[ChatGeneration(message=response)])

    def bind_tools(self, tools, **kwargs):
        new = self.model_copy()
        new.bound_tools = list(tools)
        return new


# ---------------------------------------------------------------------------
# Forward tool: routes supervisor -> report node in parent graph
# ---------------------------------------------------------------------------
@tool("transfer_to_report")
def transfer_to_report(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Transfer control to the report agent."""
    tool_message = ToolMessage(
        content="Successfully transferred to report.",
        name="transfer_to_report",
        tool_call_id=tool_call_id,
    )
    return Command(
        goto="report",
        graph=Command.PARENT,
        update={"messages": state["messages"] + [tool_message]},
    )


# ---------------------------------------------------------------------------
# Report subgraph: compiled with NO checkpointer, calls interrupt()
# ---------------------------------------------------------------------------
def _build_report_subgraph():
    """Build a minimal report subgraph that always calls interrupt()."""

    def report_entry_node(state: MessagesState):
        """Node that calls interrupt() to ask user a clarifying question."""
        answer = interrupt({
            "type": "choice",
            "question": "Test question?",
            "options": ["A", "B"],
        })
        return {
            "messages": [AIMessage(content=f"REPORT_COMPLETED with answer: {answer}")],
        }

    builder = StateGraph(MessagesState)
    builder.add_node("report_entry", report_entry_node)
    builder.add_edge(START, "report_entry")
    builder.add_edge("report_entry", END)

    # Compile WITHOUT checkpointer -- parent's checkpointer handles state
    return builder.compile()


# ---------------------------------------------------------------------------
# Helper: build the full parent graph (supervisor + report subgraph)
# ---------------------------------------------------------------------------
def _build_parent_graph():
    """Build the parent graph matching production architecture."""
    fake_llm = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_001",
                        "name": "transfer_to_report",
                        "args": {},
                    }
                ],
            ),
            AIMessage(content="supervisor done"),
        ]
    )

    supervisor_agent = create_react_agent(
        model=fake_llm,
        tools=[transfer_to_report],
        name="supervisor",
    )

    report_subgraph = _build_report_subgraph()

    builder = StateGraph(MessagesState)
    builder.add_node("supervisor", supervisor_agent, destinations=["report"])
    builder.add_node("report", report_subgraph)
    builder.add_edge(START, "supervisor")
    builder.add_edge("report", END)
    builder.add_edge("supervisor", END)

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    return graph


# ---------------------------------------------------------------------------
# Helpers: extract interrupt info from graph state
# ---------------------------------------------------------------------------
def _get_interrupts(graph, config):
    """Return list of interrupt values from the graph state."""
    state = graph.get_state(config)
    interrupts = []
    for task in state.tasks:
        for intr in task.interrupts:
            interrupts.append(intr.value)
    return interrupts, state


def _get_stream_interrupts(chunks):
    """Extract interrupt data from stream chunks."""
    for chunk in chunks:
        if "__interrupt__" in chunk:
            return [intr.value for intr in chunk["__interrupt__"]]
    return []


# ---------------------------------------------------------------------------
# Test 1: interrupt from subgraph propagates through parent
# ---------------------------------------------------------------------------
def test_interrupt_from_subgraph_propagates_through_parent():
    """
    Parent graph (MemorySaver) -> supervisor (create_react_agent with forward tool)
    -> report subgraph (NO checkpointer, calls interrupt()).

    The interrupt raised by the report subgraph must be visible in the parent
    graph's checkpoint state and surfaced via stream().
    """
    graph = _build_parent_graph()
    config = {"configurable": {"thread_id": "test-interrupt-propagation-1"}}

    # Use stream to capture interrupt chunks
    chunks = list(graph.stream(
        {"messages": [HumanMessage(content="Show me a report")]},
        config=config,
    ))

    # Check stream output contains interrupt
    stream_interrupts = _get_stream_interrupts(chunks)
    assert len(stream_interrupts) > 0, (
        f"No __interrupt__ chunk found in stream output. Chunks: {chunks}"
    )

    interrupt_value = stream_interrupts[0]
    assert interrupt_value["type"] == "choice", f"Expected type='choice', got {interrupt_value}"
    assert interrupt_value["question"] == "Test question?", f"Unexpected question: {interrupt_value}"
    assert interrupt_value["options"] == ["A", "B"], f"Unexpected options: {interrupt_value}"

    # Also verify via get_state
    state_interrupts, state = _get_interrupts(graph, config)
    assert len(state_interrupts) > 0, "No interrupts found in graph state"
    assert state.next, "Expected graph to have pending next nodes (interrupted)"

    print("\n[Test 1] PASSED: GraphInterrupt propagated correctly from subgraph!")
    print(f"  Interrupt data: {interrupt_value}")
    print(f"  State.next: {state.next}")


# ---------------------------------------------------------------------------
# Test 2: interrupt + resume from subgraph
# ---------------------------------------------------------------------------
def test_interrupt_resume_from_subgraph():
    """
    First invoke: interrupt is triggered from report subgraph.
    Second invoke: Command(resume="A") resumes the subgraph, which completes.
    The graph should finish normally with the resume value.
    """
    graph = _build_parent_graph()
    config = {"configurable": {"thread_id": "test-interrupt-resume-1"}}

    # First invoke: triggers interrupt (invoke doesn't raise, stores in checkpoint)
    result = graph.invoke(
        {"messages": [HumanMessage(content="Show me a report")]},
        config=config,
    )

    # Verify interrupt is pending
    state_interrupts, state = _get_interrupts(graph, config)
    assert len(state_interrupts) > 0, (
        f"Expected interrupt after first invoke. State.next={state.next}, "
        f"tasks={state.tasks}"
    )
    assert state.next, "Expected pending next nodes after interrupt"

    print("\n[Test 2] First invoke: interrupt captured in checkpoint")
    print(f"  Interrupts: {state_interrupts}")
    print(f"  State.next: {state.next}")

    # Second invoke: resume with answer "A"
    result = graph.invoke(
        Command(resume="A"),
        config=config,
    )

    # Verify the graph completed with the resume value
    messages = result.get("messages", [])
    completed = any(
        hasattr(msg, "content") and "REPORT_COMPLETED with answer: A" in str(msg.content)
        for msg in messages
    )

    # Verify no more pending interrupts
    _, final_state = _get_interrupts(graph, config)
    assert not final_state.next, f"Graph still has pending nodes: {final_state.next}"

    print(f"[Test 2] After resume - Messages:")
    for msg in messages:
        print(f"  {type(msg).__name__}: {str(msg.content)[:120]}")

    assert completed, (
        "Report subgraph did not complete with resume value 'A'. "
        f"Messages: {[str(m.content)[:80] for m in messages]}"
    )

    print("[Test 2] PASSED: Resume completed successfully!")


# ---------------------------------------------------------------------------
# Test 3: simple subgraph without checkpointer interrupt propagation
# ---------------------------------------------------------------------------
def test_subgraph_without_checkpointer_interrupt():
    """
    Minimal test: a compiled subgraph (no checkpointer) that calls interrupt()
    is added as a node in a parent graph (with MemorySaver).
    Interrupt must be captured in the parent's checkpoint and resumable.
    """

    def interrupting_node(state: MessagesState):
        answer = interrupt({
            "type": "choice",
            "question": "Simple test?",
            "options": ["X", "Y"],
        })
        return {
            "messages": [AIMessage(content=f"Got answer: {answer}")],
        }

    # Build subgraph with NO checkpointer
    sub_builder = StateGraph(MessagesState)
    sub_builder.add_node("ask", interrupting_node)
    sub_builder.add_edge(START, "ask")
    sub_builder.add_edge("ask", END)
    subgraph = sub_builder.compile()

    # Build parent graph with MemorySaver
    parent_builder = StateGraph(MessagesState)
    parent_builder.add_node("sub", subgraph)
    parent_builder.add_edge(START, "sub")
    parent_builder.add_edge("sub", END)
    parent = parent_builder.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "test-simple-interrupt-1"}}

    # Stream to capture interrupt
    chunks = list(parent.stream(
        {"messages": [HumanMessage(content="Hello")]},
        config=config,
    ))

    # Verify interrupt via stream
    stream_interrupts = _get_stream_interrupts(chunks)
    assert len(stream_interrupts) > 0, f"No interrupt in stream. Chunks: {chunks}"

    interrupt_value = stream_interrupts[0]
    assert interrupt_value["type"] == "choice"
    assert interrupt_value["question"] == "Simple test?"
    assert interrupt_value["options"] == ["X", "Y"]

    # Verify interrupt via get_state
    state_interrupts, state = _get_interrupts(parent, config)
    assert len(state_interrupts) > 0, "No interrupts in state"
    assert state.next == ("sub",), f"Expected next=('sub',), got {state.next}"

    print("\n[Test 3] Interrupt propagated from simple subgraph!")
    print(f"  Interrupt data: {interrupt_value}")

    # Resume and verify completion
    result = parent.invoke(Command(resume="X"), config=config)
    messages = result.get("messages", [])
    completed = any(
        hasattr(msg, "content") and "Got answer: X" in str(msg.content)
        for msg in messages
    )
    assert completed, f"Resume failed. Messages: {[str(m.content)[:80] for m in messages]}"

    # Verify graph is done
    _, final_state = _get_interrupts(parent, config)
    assert not final_state.next, f"Graph still pending: {final_state.next}"

    print(f"[Test 3] PASSED: Resume completed successfully!")
