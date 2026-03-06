"""
Supervisor Module - Multi-agent supervisor with research and portfolio agents

This module provides a supervisor system using the handoff pattern:
- tools: Supervisor tools (time, status, and handoff assignments)
- agents: Agent definitions and system prompts for supervisor, research, and portfolio
- graph: Multi-agent graph with handoff routing between agents
- utilities: Helper functions like create_handoff_tool

The supervisor routes requests between:
- research: For analysis, investigations, and research tasks
- portfolio: For investment management, asset tracking, and financial planning

Example:
    from src.models.models import LLM
    from src.graphs.supervisor import create_supervisor_graph
    from langchain_core.messages import HumanMessage
    import uuid

    llm = LLM()
    graph = create_supervisor_graph(llm)

    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = graph.invoke(
        {"messages": [HumanMessage(content="Research AI companies")]},
        config=config
    )
"""

from src.graphs.supervisor.tools import (
    get_current_time,
    get_supervisor_status,
    assign_to_routing_agent,
    assign_to_chat_agent
)

from src.graphs.supervisor.graph import create_supervisor_graph
from src.graphs.supervisor.utilities import create_handoff_tool, create_forward_tool

__all__ = [
    # Tools
    "get_current_time",
    "get_supervisor_status",
    "assign_to_routing_agent",
    "assign_to_chat_agent",
    # Agents & Prompts
    "get_supervisor_system_message",
    "get_research_system_message",
    "get_portfolio_system_message",
    "SUPERVISOR_SYSTEM_PROMPT",
    "RESEARCH_AGENT_PROMPT",
    "PORTFOLIO_AGENT_PROMPT",
    # Graph
    "create_supervisor_graph",
    # Utilities
    "create_handoff_tool",
    "create_forward_tool",
]
