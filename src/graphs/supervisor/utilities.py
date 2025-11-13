from typing import Annotated
from textwrap import dedent

from langchain_core.tools import tool, BaseTool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.prebuilt import InjectedState

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
                "messages": state["messages"] + [tool_message]
            },
        )
    return handoff_to_agent