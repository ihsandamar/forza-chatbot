"""
Chat Graph Node Implementations.

Simple node using ReAct agent with automatic tool execution.
"""

import logging
from typing import Any

from .state import ChatState
from .runnables import ChatAgentRunnables

logger = logging.getLogger(__name__)


def chat_node(state: ChatState) -> ChatState:
    """
    Chat node using ReAct agent.

    The ReAct agent automatically handles:
    - Tool invocation decision
    - Tool execution
    - Response generation
    - Agentic loop

    Args:
        state: Current chat state (with messages)

    Returns:
        Updated state with final response
    """
    try:
        agent = ChatAgentRunnables().runnable
        messages = state.get("messages", [])

        logger.debug("Processing message with ReAct agent...")

        # Invoke agent - it handles everything (tools, loop, etc)
        # Agent expects {"messages": [...]}
        result = agent.invoke(
            {"messages": messages},
            config={"recursion_limit": 20}
        )

        # Update state with final messages from agent
        if isinstance(result, dict) and "messages" in result:
            state["messages"] = result["messages"]
        elif isinstance(result, list):
            state["messages"] = result
        else:
            state["messages"] = messages

        logger.info(f"Chat complete with ReAct agent")
        return state

    except Exception as e:
        logger.error(f"Error in chat_node: {e}", exc_info=True)
        from langchain_core.messages import AIMessage
        messages = list(state.get("messages", []))
        fallback = "Çok özür dilerim, şu anda yanıt veremiyor. Lütfen daha sonra tekrar deneyin."
        messages.append(AIMessage(content=fallback))
        state["messages"] = messages
        return state
