"""
Minimal reproduction tests to verify Command(goto="report", graph=Command.PARENT)
routing behavior from a tool inside an agent node to a sibling node in the parent graph.

Test 1: create_react_agent (langgraph.prebuilt) - known-working baseline
Test 2: create_agent (langchain.agents) - actual production pattern
"""

import pytest
from typing import Annotated, Iterator
from textwrap import dedent

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
    BaseMessage,
)
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from langgraph.prebuilt import InjectedState, create_react_agent

from pydantic import Field


# ---------------------------------------------------------------------------
# Fake LLM that supports bind_tools and returns pre-scripted responses
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
            # Default fallback: just say done
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="done"))]
            )
        response = self.responses[self.call_index]
        self.call_index += 1
        return ChatResult(generations=[ChatGeneration(message=response)])

    def bind_tools(self, tools, **kwargs):
        """Return a copy with tools bound (needed by create_react_agent / create_agent)."""
        new = self.model_copy()
        new.bound_tools = list(tools)
        return new


# ---------------------------------------------------------------------------
# The tool that returns a Command to route to sibling "report" node
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
# Simple "report" node
# ---------------------------------------------------------------------------
def report_node(state: MessagesState) -> MessagesState:
    """A simple node that marks itself as executed."""
    return {
        "messages": [AIMessage(content="REPORT_EXECUTED")],
    }


# ---------------------------------------------------------------------------
# Helper: check whether the report node actually ran
# ---------------------------------------------------------------------------
def _report_executed(result: dict) -> bool:
    """Return True if any message contains 'REPORT_EXECUTED'."""
    for msg in result.get("messages", []):
        if hasattr(msg, "content") and "REPORT_EXECUTED" in str(msg.content):
            return True
    return False


# ---------------------------------------------------------------------------
# Test 1 - create_react_agent (langgraph.prebuilt)
# ---------------------------------------------------------------------------
def test_command_routing_with_create_react_agent():
    """
    Baseline test using create_react_agent from langgraph.prebuilt.
    The supervisor agent calls transfer_to_report which returns
    Command(goto='report', graph=Command.PARENT). The parent graph
    should then execute the 'report' node.
    """
    # Fake LLM: first call -> tool call, second call (if any) -> done
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

    # Build supervisor using create_react_agent
    supervisor_agent = create_react_agent(
        model=fake_llm,
        tools=[transfer_to_report],
        name="supervisor",
    )

    # Build parent graph
    builder = StateGraph(MessagesState)
    builder.add_node("supervisor", supervisor_agent, destinations=["report"])
    builder.add_node("report", report_node)

    builder.add_edge(START, "supervisor")
    builder.add_edge("report", END)
    builder.add_edge("supervisor", END)

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    # Invoke
    config = {"configurable": {"thread_id": "test-react-1"}}
    result = graph.invoke(
        {"messages": [HumanMessage(content="Show me a report")]},
        config=config,
    )

    # Verify
    executed = _report_executed(result)
    print(f"\n[create_react_agent] Report node executed: {executed}")
    print(f"[create_react_agent] Messages:")
    for msg in result.get("messages", []):
        print(f"  {type(msg).__name__}: {str(msg.content)[:100]}")

    assert executed, (
        "Report node was NOT executed. Command(goto='report', graph=Command.PARENT) "
        "did not route to the sibling 'report' node in the parent graph when using "
        "create_react_agent."
    )


# ---------------------------------------------------------------------------
# Test 2 - create_agent (langchain.agents)
# ---------------------------------------------------------------------------
def test_command_routing_with_create_agent():
    """
    Test using create_agent from langchain.agents (production pattern).
    The supervisor agent calls transfer_to_report which returns
    Command(goto='report', graph=Command.PARENT). The parent graph
    should then execute the 'report' node.
    """
    from langchain.agents import create_agent

    # Fake LLM: first call -> tool call, second call (if any) -> done
    fake_llm = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_002",
                        "name": "transfer_to_report",
                        "args": {},
                    }
                ],
            ),
            AIMessage(content="supervisor done"),
        ]
    )

    # Build supervisor using create_agent (langchain.agents)
    supervisor_agent = create_agent(
        model=fake_llm,
        tools=[transfer_to_report],
        system_prompt="You are a supervisor.",
        name="supervisor",
    )

    # Build parent graph
    builder = StateGraph(MessagesState)
    builder.add_node("supervisor", supervisor_agent, destinations=["report"])
    builder.add_node("report", report_node)

    builder.add_edge(START, "supervisor")
    builder.add_edge("report", END)
    builder.add_edge("supervisor", END)

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    # Invoke
    config = {"configurable": {"thread_id": "test-agent-1"}}
    result = graph.invoke(
        {"messages": [HumanMessage(content="Show me a report")]},
        config=config,
    )

    # Verify
    executed = _report_executed(result)
    print(f"\n[create_agent] Report node executed: {executed}")
    print(f"[create_agent] Messages:")
    for msg in result.get("messages", []):
        print(f"  {type(msg).__name__}: {str(msg.content)[:100]}")

    assert executed, (
        "Report node was NOT executed. Command(goto='report', graph=Command.PARENT) "
        "did not route to the sibling 'report' node in the parent graph when using "
        "create_agent from langchain.agents."
    )


# ---------------------------------------------------------------------------
# Test 3 - Side-by-side comparison (informational)
# ---------------------------------------------------------------------------
def test_command_routing_comparison():
    """
    Run both patterns and compare results side-by-side.
    This test always passes but prints diagnostic info.
    """
    from langchain.agents import create_agent as lc_create_agent

    results = {}

    for label, factory in [
        ("create_react_agent", lambda llm: create_react_agent(
            model=llm, tools=[transfer_to_report], name="supervisor"
        )),
        ("create_agent", lambda llm: lc_create_agent(
            model=llm, tools=[transfer_to_report],
            system_prompt="You are a supervisor.", name="supervisor"
        )),
    ]:
        fake_llm = FakeToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": f"call_{label}",
                            "name": "transfer_to_report",
                            "args": {},
                        }
                    ],
                ),
                AIMessage(content="supervisor done"),
            ]
        )

        supervisor_agent = factory(fake_llm)

        builder = StateGraph(MessagesState)
        builder.add_node("supervisor", supervisor_agent, destinations=["report"])
        builder.add_node("report", report_node)
        builder.add_edge(START, "supervisor")
        builder.add_edge("report", END)
        builder.add_edge("supervisor", END)

        graph = builder.compile(checkpointer=MemorySaver())

        try:
            result = graph.invoke(
                {"messages": [HumanMessage(content="Show me a report")]},
                config={"configurable": {"thread_id": f"compare-{label}"}},
            )
            executed = _report_executed(result)
            results[label] = {"executed": executed, "error": None}
        except Exception as e:
            results[label] = {"executed": False, "error": str(e)}

    print("\n" + "=" * 60)
    print("COMMAND ROUTING COMPARISON")
    print("=" * 60)
    for label, info in results.items():
        status = "PASS" if info["executed"] else "FAIL"
        err = f" (error: {info['error']})" if info["error"] else ""
        print(f"  {label:25s} -> {status}{err}")
    print("=" * 60)
