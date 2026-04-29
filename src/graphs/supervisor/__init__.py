"""
Supervisor Module - Multi-agent supervisor with dynamic agent routing.

The supervisor reads GRAPH_REGISTRY at build time to discover available agents
and generates handoff/forward tools dynamically. Adding a new agent requires
only registering it with @register_graph — no supervisor changes needed.
"""

from src.graphs.supervisor.utilities import create_handoff_tool, create_forward_tool

__all__ = [
    "create_handoff_tool",
    "create_forward_tool",
]
