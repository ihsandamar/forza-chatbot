# src/interfaces/adapters/gradio_adapter.py
"""
GradioAdapter - Gradio-spesifik interface işlemlerini handle eder.

Single Responsibility: Gradio format işleme (history tuple format).
Generic message processing Chatbot sınıfında yapılır.
"""

from typing import List, Tuple
from src.core.chatbot import Chatbot


class GradioAdapter:
    """
    Gradio interface'i için adapter.

    Gradio'nun history format'ını (List[Tuple[str, str]])
    Chatbot'ın generic format'ına dönüştürür ve tersi.

    Single Responsibility: Gradio format dönüşümü sadece.
    """

    def __init__(self, chatbot: Chatbot):
        """
        Initialize Gradio adapter.

        Args:
            chatbot: Chatbot instance
        """
        self.chatbot = chatbot

    def response_handler(
        self,
        history: List[Tuple[str, str]],
        message: str
    ) -> List[Tuple[str, str]]:
        """
        Handle Gradio chat messages.

        Converts Gradio history format to generic format,
        sends to chatbot, converts response back to Gradio format.

        Args:
            history: List of (user_msg, bot_msg) tuples
            message: Current user message

        Returns:
            Updated history with bot response
        """
        # Convert Gradio history to generic messages format
        messages = self._history_to_messages(history)

        # Add new user message
        messages.append({"role": "user", "content": message})

        # Create generic state for chatbot
        state = {"messages": messages}

        # Send to chatbot (generic interface)
        response_text = self.chatbot.send(state)

        # Add to history in Gradio format
        history.append((message, response_text))

        return history

    def _history_to_messages(self, history: List[Tuple[str, str]]) -> list:
        """
        Convert Gradio history format to generic messages format.

        Args:
            history: List of (user_msg, bot_msg) tuples

        Returns:
            List of message dicts with role and content
        """
        messages = []
        for user_msg, bot_msg in history:
            if user_msg:
                messages.append({"role": "user", "content": user_msg})
            if bot_msg:
                messages.append({"role": "assistant", "content": bot_msg})
        return messages
