"""
Chat Graph State Definition.

Extends GraphState with chat-specific fields.
"""

from typing import Optional
from src.graphs.base.graph_types import GraphState


class ChatState(GraphState):
    """
    Chat-specific state extending GraphState.

    Fields:
        messages: Conversation history (inherited from GraphState)
        session_id: Session identifier (inherited from GraphState)
        user_id: User identifier (inherited from GraphState)
        metadata: Graph metadata (inherited from GraphState)
    """
    pass
