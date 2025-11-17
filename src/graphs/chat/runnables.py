"""
Chat Graph Runnables.

Simple runnables with tool binding.
"""
from src.models.llm import LLM
from .tools import CHAT_TOOLS
from .prompts import AgentPrompts


class ChatAgentRunnables:
    """Runnable with tool binding."""

    def __init__(self) -> None:
        llm = LLM()
        chat = llm.get_chat()
        prompt = AgentPrompts().SYSTEM_PROMPT_FORMAL

        # Create runnable: prompt | llm with tools
        self.runnable = prompt | chat.bind_tools(CHAT_TOOLS)
        
