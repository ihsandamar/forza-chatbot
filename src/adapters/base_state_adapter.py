"""
Base State Adapter

Abstract interface for adapting between standard message format
and graph-specific state formats.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseStateAdapter(ABC):
    """
    Abstract base class for state adapters.

    Adapters translate between the standard messages format and
    graph-specific state formats, enabling graphs to use their
    own state structures while maintaining a consistent interface.
    """

    @abstractmethod
    def to_graph_state(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """
        Convert standard messages format to graph-specific state.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            **kwargs: Additional parameters needed for state creation

        Returns:
            Graph-specific state dictionary

        Example:
            messages = [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"}
            ]
            state = adapter.to_graph_state(messages)
        """
        pass

    @abstractmethod
    def from_graph_state(self, graph_output: Any) -> str:
        """
        Convert graph output to standard response format.

        Args:
            graph_output: Graph-specific output (can be dict, object, or any type)

        Returns:
            String response to be sent back to user

        Example:
            output = graph.invoke(state)
            response = adapter.from_graph_state(output)
        """
        pass

    def get_required_params(self) -> List[str]:
        """
        Get list of required parameters for to_graph_state method.

        Returns:
            List of parameter names required in kwargs

        Override this if your adapter needs specific parameters.
        """
        return []
