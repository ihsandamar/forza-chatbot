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


def test_report_agent_uses_forward_tool():
    """assign_to_report_agent should use create_forward_tool, not create_handoff_tool."""
    from src.graphs.supervisor.tools import assign_to_report_agent
    # Forward tools have passthrough description pattern
    assert "forward" in assign_to_report_agent.description.lower() or "directly" in assign_to_report_agent.description.lower()


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
