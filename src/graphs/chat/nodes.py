"""
Chat Graph Node Implementations.

Simple node using chat assistant.
"""

import logging

from .state import ChatState
from .runnables import ChatAgentRunnables
from .assistant import ChatAssistant

logger = logging.getLogger(__name__)


async def chat_node(state: ChatState) -> ChatState:
    """
    Chat node using assistant with tool-bound runnable.

    Args:
        state: Current chat state (with messages)

    Returns:
        Updated state with response
    """
    try:
        logger.debug("Processing message...")

        # Create assistant with runnable
        runnable = ChatAgentRunnables().runnable
        assistant = ChatAssistant(runnable)

        # Invoke assistant - handles validation
        result = await assistant(state, config={"recursion_limit": 20})

        # Update state
        state["messages"] = result.get("messages", state.get("messages", []))

        logger.info("Chat complete")
        return state

    except Exception as e:
        logger.error(f"Error in chat_node: {e}", exc_info=True)
        from langchain_core.messages import AIMessage
        messages = list(state.get("messages", []))
        fallback = "Çok özür dilerim, şu anda yanıt veremiyor. Lütfen daha sonra tekrar deneyin."
        messages.append(AIMessage(content=fallback))
        state["messages"] = messages
        return state
