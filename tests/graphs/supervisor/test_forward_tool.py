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
