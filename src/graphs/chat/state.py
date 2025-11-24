"""
Chat Graph State - LangGraph Compatible.

Simple messages-only state for chat agent.
"""

from langgraph.graph import MessagesState


class ChatState(MessagesState):
    """
    Chat Graph State - LangGraph compatible.

    Includes:
    - messages: Conversation history (with add_messages reducer)
    """
    pass
