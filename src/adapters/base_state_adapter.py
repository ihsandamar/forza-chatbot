"""
Base State Adapter

Abstract interface for adapting between standard message format
and graph-specific state formats.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List
import asyncio


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

    # Async versions for non-blocking execution
    async def to_graph_state_async(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """
        Async version of to_graph_state.

        By default, runs the sync version in an executor.
        Subclasses can override this for true async implementation.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            **kwargs: Additional parameters needed for state creation

        Returns:
            Graph-specific state dictionary
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.to_graph_state(messages, **kwargs)
        )

    async def from_graph_state_async(self, graph_output: Any) -> str:
        """
        Async version of from_graph_state.

        By default, runs the sync version in an executor.
        Subclasses can override this for true async implementation.

        Args:
            graph_output: Graph-specific output

        Returns:
            String response to be sent back to user
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.from_graph_state,
            graph_output
        )
