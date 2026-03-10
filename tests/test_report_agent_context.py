"""Test that report agent preserves context between turns via supervisor."""
import pytest
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage
from typing import Annotated, Optional, List, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


def test_subgraph_with_own_checkpointer_preserves_state():
    """
    Minimal reproduction: a parent graph (MessagesState) invokes a child
    subgraph (extended state) that has checkpointer=True (inherits parent's).
    The child's extra state fields should persist between turns.

    When checkpointer=True, the parent's checkpointer saves the child's full
    state, including fields not present in the parent's own state schema.
    This is the pattern needed for the report agent to preserve ReportState
    fields (active_sql, active_results, etc.) between turns.
    """
    class ChildState(TypedDict):
        messages: Annotated[List[BaseMessage], add_messages]
        context_value: Optional[str]

    def child_node(state: dict) -> dict:
        existing = state.get("context_value")
        if existing:
            return {
                "messages": [AIMessage(content=f"Context found: {existing}")],
            }
        else:
            return {
                "messages": [AIMessage(content="Context set")],
                "context_value": "preserved_data",
            }

    child_builder = StateGraph(ChildState)
    child_builder.add_node("child_node", child_node)
    child_builder.add_edge(START, "child_node")
    child_builder.add_edge("child_node", END)
    # checkpointer=True means child inherits parent's checkpointer
    child_graph = child_builder.compile(checkpointer=True)

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

    # Turn 2: child should find context_value from its checkpoint
    result2 = parent_graph.invoke(
        {"messages": [HumanMessage(content="second")]}, config
    )
    last_msg2 = result2["messages"][-1].content
    assert "preserved_data" in last_msg2, (
        f"Expected 'preserved_data' in response but got: '{last_msg2}'. "
        f"Child subgraph did not preserve context_value between turns."
    )


def test_subgraph_without_checkpointer_loses_state():
    """
    Verify that checkpointer=False causes the child to lose state between turns.
    This is the current (broken) behavior we're fixing.
    """
    class ChildState(TypedDict):
        messages: Annotated[List[BaseMessage], add_messages]
        context_value: Optional[str]

    def child_node(state: dict) -> dict:
        existing = state.get("context_value")
        if existing:
            return {
                "messages": [AIMessage(content=f"Context found: {existing}")],
            }
        else:
            return {
                "messages": [AIMessage(content="Context set")],
                "context_value": "preserved_data",
            }

    child_builder = StateGraph(ChildState)
    child_builder.add_node("child_node", child_node)
    child_builder.add_edge(START, "child_node")
    child_builder.add_edge("child_node", END)
    # checkpointer=False means child state is not persisted
    child_graph = child_builder.compile(checkpointer=False)

    parent_builder = StateGraph(MessagesState)
    parent_builder.add_node("child", child_graph)
    parent_builder.add_edge(START, "child")
    parent_builder.add_edge("child", END)
    parent_graph = parent_builder.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "test-session-no-cp"}}

    # Turn 1
    result1 = parent_graph.invoke(
        {"messages": [HumanMessage(content="first")]}, config
    )
    assert "Context set" in result1["messages"][-1].content

    # Turn 2: context_value is lost, so child sets it again
    result2 = parent_graph.invoke(
        {"messages": [HumanMessage(content="second")]}, config
    )
    last_msg2 = result2["messages"][-1].content
    assert "Context set" in last_msg2, (
        f"Expected state to be lost (got 'Context set') but got: '{last_msg2}'"
    )
