import logging
from typing import Annotated
from textwrap import dedent

from langchain_core.tools import tool, BaseTool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.prebuilt import InjectedState

logger = logging.getLogger(__name__)

def _normalize_agent_name(agent_name: str) -> str:
    """Convert an agent name to a valid tool name format (snake_case)."""
    return agent_name.replace(" ", "_").lower()

def create_handoff_tool(*, agent_name: str, name: str | None = None, description: str | None = None) -> BaseTool:
    """Create a tool that transfers control to another agent with specific task instructions."""
    if name is None:
        name = f"transfer_to_{_normalize_agent_name(agent_name)}"
    if description is None:
        description = f"Ask agent '{agent_name}' for help"

    @tool(name, description=description)
    def handoff_to_agent(
        state: Annotated[dict, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ):
        # Log handoff request
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else None
        last_msg_content = getattr(last_msg, "content", str(last_msg))[:100] if last_msg else "No message"

        logger.info(f"[SUPERVISOR] HANDOFF TRIGGERED ➜ {agent_name.upper()}")
        logger.debug(f"[SUPERVISOR] User message: '{last_msg_content}...'")
        logger.debug(f"[SUPERVISOR] Total messages in state: {len(messages)}")

        tool_message = ToolMessage(
            content=dedent(f"""
            Successfully transferred to {agent_name}.
            """),
            name=name,
            tool_call_id=tool_call_id
        )

        logger.debug(f"[SUPERVISOR] Creating Command with goto='{agent_name}'")

        return Command(
            goto=agent_name,
            graph=Command.PARENT,
            update={
                "messages": state["messages"] + [tool_message]
            },
        )
    return handoff_to_agent


def create_forward_tool(*, agent_name: str, name: str | None = None, description: str | None = None) -> BaseTool:
    """Create a tool that transfers control to an agent whose response goes directly to END.

    Unlike create_handoff_tool (agent → supervisor → END), forward agents are
    configured at graph build time with a direct edge to END. This tool simply
    routes to the agent; the graph topology handles the passthrough behavior.
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

        logger.info(f"[SUPERVISOR] FORWARD TRIGGERED -> {agent_name.upper()}")
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
            },
        )
    return forward_to_agent