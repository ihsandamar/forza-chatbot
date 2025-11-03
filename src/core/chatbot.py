"""
Chatbot - Single Responsibility: Generic message sending and session management.

Single Responsibility:
- Generic message processing
- Graph orchestration
- Adapter-based state transformation

Interface-specific handling moved to interface adapters (GradioAdapter, etc).
"""

from typing import Optional
from src.graphs.base_graph import BaseGraph
from src.models.models import LLM
from src.adapters.base_state_adapter import BaseStateAdapter
from src.adapters.default_state_adapter import DefaultStateAdapter


class Chatbot:
    """
    Generic chatbot for message processing and graph orchestration.

    Single Responsibility: Generic message sending, NOT interface-specific logic.
    Interface adapters handle Gradio, API, CLI-specific formatting.
    """

    def __init__(
        self,
        llm: LLM,
        graph: BaseGraph,
        config: dict = None,
        assistant_config: dict = None,
        adapter: Optional[BaseStateAdapter] = None
    ):
        """
        Initialize chatbot.

        Args:
            llm: Language model instance
            graph: LangGraph instance
            config: Graph configuration
            assistant_config: Assistant-specific configuration
            adapter: State adapter for graph transformation
        """
        self.llm = llm
        self.graph = graph
        self.config = config if config else {}
        self.assistant_config = assistant_config if assistant_config else {}
        # Use provided adapter or default to DefaultStateAdapter
        self.adapter = adapter if adapter else DefaultStateAdapter()

    def _prepare_config(self) -> dict:
        """
        Prepare full configuration with assistant_config.

        DRY: Extracted common config preparation logic.

        Returns:
            Full config dict with configurable section
        """
        assistant_config_dict = (
            self.assistant_config.to_dict()
            if hasattr(self.assistant_config, 'to_dict')
            else self.assistant_config
        )
        full_config = self.config.copy()
        if "configurable" not in full_config:
            full_config["configurable"] = {}
        full_config["configurable"]["assistant_config"] = assistant_config_dict
        return full_config

    def _invoke_graph(self, graph_state: dict) -> dict:
        """
        Invoke graph with prepared configuration.

        DRY: Extracted common graph invocation logic.

        Args:
            graph_state: State prepared by adapter

        Returns:
            Graph output
        """
        full_config = self._prepare_config()
        return self.graph.invoke(graph_state, config=full_config)

    def _process_message(self, state: dict, **adapter_kwargs) -> dict:
        """
        Common message processing logic.

        DRY: Extracted repeated message processing from send() and send_structured().

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional adapter parameters

        Returns:
            Graph output
        """
        messages = state.get("messages", [])
        graph_state = self.adapter.to_graph_state(messages, **adapter_kwargs)
        return self._invoke_graph(graph_state)

    def send(self, state: dict, **adapter_kwargs) -> str:
        """
        Generic message sending for all interfaces.

        SRP: Delegates interface-specific formatting to adapter.
        If adapter implements send(), uses that. Otherwise uses from_graph_state().

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional adapter parameters (token, etc)

        Returns:
            String response
        """
        # SRP: Let adapter handle interface-specific formatting if it can
        if hasattr(self.adapter, 'send'):
            return self.adapter.send(state, **adapter_kwargs)

        # Fallback: Use standard processing pipeline
        graph_output = self._process_message(state, **adapter_kwargs)
        response_text = self.adapter.from_graph_state(graph_output)
        return response_text

    def send_structured(self, state: dict, **adapter_kwargs) -> dict:
        """
        Structured response for API/programmatic use.

        SRP: Delegates interface-specific formatting to adapter.
        If adapter implements send_structured(), uses that.
        Otherwise tries to_api_response(), with fallback formatting.

        Args:
            state: {"messages": [{"role": "user", "content": "..."}]}
            **adapter_kwargs: Additional adapter parameters

        Returns:
            Dict with text, type, confidence, action, metadata
        """
        # SRP: Let adapter handle interface-specific formatting if it can
        if hasattr(self.adapter, 'send_structured'):
            return self.adapter.send_structured(state, **adapter_kwargs)

        # Process message through adapter and graph
        graph_output = self._process_message(state, **adapter_kwargs)

        # Use adapter's to_api_response if available
        if hasattr(self.adapter, 'to_api_response'):
            return self.adapter.to_api_response(graph_output)
        else:
            # Fallback: Create standard structured response
            response_text = self.adapter.from_graph_state(graph_output)
            return {
                "text": response_text,
                "type": "text",
                "confidence": 0.95,
                "action": {"type": "none", "target": "", "params": {}}
            }