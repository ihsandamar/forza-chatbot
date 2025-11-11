"""
Chat Graph Runnables.

LangGraph ReAct agent with automatic tool execution.
"""

from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from src.models.models import LLM
from .prompts import AgentPrompts
from .tools import CHAT_TOOLS


class ChatAgentRunnables:
    """ReAct agent with automatic tool execution."""

    def __init__(self) -> None:
        llm = LLM()
        chat = llm.get_chat()

        # Create ReAct agent - automatically handles tool execution
        self.runnable = create_react_agent(
            model=chat,
            tools=CHAT_TOOLS,
            checkpointer=MemorySaver()
        )




