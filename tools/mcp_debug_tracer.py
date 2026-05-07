#!/usr/bin/env python
"""MCP server: exposes read_trace as a Claude tool."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastmcp import FastMCP
from tools.read_trace import _read_trace_data

mcp = FastMCP("forza-debug-tracer")


@mcp.tool()
def read_trace(
    session_id: str,
    node: str | None = None,
    turn: int | None = None,
    full: bool = False,
) -> dict:
    """Read a local debug trace JSONL file.

    Returns events list and human-readable summary.
    Use node/turn to filter. Set full=True for complete state JSON.
    """
    return _read_trace_data(session_id, node=node, turn=turn, full=full)


if __name__ == "__main__":
    mcp.run()
