"""
Chat Graph Node Implementations.

Contains node functions for chat processing.
"""

from src.models.models import LLM
from .state import ChatState


class ChatNodes:
    """Node implementations for Chat graph."""

    def __init__(self, llm: LLM):
        """
        Initialize ChatNodes.

        Args:
            llm: Language model instance
        """
        self.llm = llm

    def process_message(self, state: ChatState) -> ChatState:
        """
        Process user message and generate response.

        Args:
            state: Current chat state with messages

        Returns:
            Updated state with assistant response added
        """
        # Get the chat model
        chat = self.llm.get_chat()

        # Invoke the model with messages
        response = chat.invoke(state["messages"])

        # Add response to messages
        state["messages"].append(response)

        return state
