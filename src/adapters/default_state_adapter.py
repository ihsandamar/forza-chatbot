"""
Default State Adapter

Adapter for graphs that use the standard messages-based state format.
This is a pass-through adapter with minimal transformation.
"""

from typing import Any, Dict, List
from src.adapters.base_state_adapter import BaseStateAdapter


class DefaultStateAdapter(BaseStateAdapter):
    """
    Default adapter for message-based graphs.

    Used by graphs that expect state in this format:
    {
        "messages": [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ]
    }

    This is the standard format used by most LangGraph chat applications.
    """

    def to_graph_state(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """
        Convert messages to standard state format.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Ignored for default adapter

        Returns:
            State dict with messages key

        Example:
            >>> adapter = DefaultStateAdapter()
            >>> messages = [{"role": "user", "content": "Hello"}]
            >>> state = adapter.to_graph_state(messages)
            >>> print(state)
            {"messages": [{"role": "user", "content": "Hello"}]}
        """
        return {"messages": messages}

    def from_graph_state(self, graph_output: Any) -> str:
        """
        Extract response from message-based graph output.

        Args:
            graph_output: Graph output with 'messages' key

        Returns:
            Content of the last assistant message

        Example:
            >>> output = {
            ...     "messages": [
            ...         {"role": "user", "content": "Hello"},
            ...         {"role": "assistant", "content": "Hi!"}
            ...     ]
            ... }
            >>> response = adapter.from_graph_state(output)
            >>> print(response)
            "Hi!"
        """
        if not isinstance(graph_output, dict):
            return str(graph_output)

        messages = graph_output.get("messages", [])
        if not messages:
            return "Bir hata oluştu, lütfen tekrar deneyin."

        # Get last message
        last_message = messages[-1]

        # Handle both dict format and LangChain message objects
        if hasattr(last_message, "content"):
            return last_message.content

        if isinstance(last_message, dict):
            return last_message.get("content", "")

        return str(last_message)

    def to_api_response(self, graph_output: Any) -> Dict[str, Any]:
        """
        Convert graph output to API response format.

        Args:
            graph_output: Graph output with 'messages' key

        Returns:
            API-friendly response dict
        """
        text_response = self.from_graph_state(graph_output)

        return {
            "text": text_response,
            "type": "text",
            "confidence": 0.95,
            "action": {"type": "none", "target": "", "params": {}},
        }
