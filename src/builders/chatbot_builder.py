# src/builders/chatbot_builder.py
"""
Chatbot Builder - Dependency Injection Factory pattern kullanarak Chatbot oluşturur.

Single Responsibility: Sadece Chatbot örneği oluşturmak.
DI işlemi DependencyFactory'ye taşındı.
"""

from typing import Optional
from src.core.chatbot import Chatbot
from src.adapters.base_state_adapter import BaseStateAdapter
from src.adapters.default_state_adapter import DefaultStateAdapter
from src.adapters.vegaforza_state_adapter import VegaforzaStateAdapter
from src.builders.dependency_factory import DependencyFactory


class ChatbotBuilder:
    """
    Chatbot örnekleri oluşturmak için builder.

    Single Responsibility: Chatbot construction ve orchestration.
    Dependency creation DependencyFactory'ye taşındı.

    Args:
        factory: DependencyFactory instance (dependencies oluşturur)
    """

    def __init__(self, factory: DependencyFactory):
        """
        Initialize builder with dependency factory.

        Args:
            factory: DependencyFactory instance
        """
        self.factory = factory
        self._llm = None
        self._graph_config = {"configurable": {"thread_id": "1"}}
        self._assistant_configuration = None
        self._adapter: Optional[BaseStateAdapter] = None
        self._graph_type = None
        self._graph_repository = None

    def with_model(
        self,
        model_name: str,
        temperature: float = 0.0,
        api_key: Optional[str] = None
    ):
        """
        Set LLM model configuration.

        Args:
            model_name: Model name
            temperature: Temperature parameter
            api_key: API key

        Returns:
            Self for method chaining
        """
        # Factory'yi kullanarak LLM oluştur
        self._llm = self.factory.create_llm(model_name, temperature, api_key)
        return self

    def with_graph(self, graph_type: str):
        """
        Set graph type and create graph repository.

        Args:
            graph_type: Type of graph to use

        Returns:
            Self for method chaining
        """
        self._graph_type = graph_type
        # LLM ayarlandığından sonra repository oluştur
        if self._llm is None:
            raise ValueError("LLM must be configured before graph. Call with_model() first.")
        self._graph_repository = self.factory.create_graph_repository(self._llm)
        return self

    def with_graph_config(self, config: dict):
        """
        Set graph configuration.

        Args:
            config: Graph configuration dictionary

        Returns:
            Self for method chaining
        """
        self._graph_config = config
        return self

    def with_assistant_configuration(self, config_params=None):
        """
        Set assistant configuration parameters.

        Args:
            config_params: Configuration parameters for SQL agent

        Returns:
            Self for method chaining
        """
        from src.graphs.generic_sql_graph import SQLAgentConfiguration

        # SQLAgentConfiguration oluştur
        self._assistant_configuration = SQLAgentConfiguration.create_from_config(config_params)

        print(f"INFO: Assistant configuration ayarlandı: {self._assistant_configuration.assistant_name}")

        return self

    def with_adapter(self, adapter: BaseStateAdapter):
        """
        Set custom adapter for state transformation.

        Args:
            adapter: Custom adapter instance

        Returns:
            Self for method chaining
        """
        self._adapter = adapter
        return self

    def build(self) -> Chatbot:
        """
        Build Chatbot instance with all configured dependencies.

        Returns:
            Configured Chatbot instance

        Raises:
            ValueError: If required dependencies are not configured
        """
        # Validate configuration
        if self._llm is None:
            raise ValueError("LLM is not configured. Call with_model() first.")
        if self._graph_repository is None:
            raise ValueError("Graph repository is not configured. Call with_graph() first.")

        # Get graph from repository
        graph = self._graph_repository.get(self._graph_type)

        # Auto-select adapter based on graph type if not explicitly set
        if self._adapter is None:
            self._adapter = self._auto_select_adapter(self._graph_type)

        return Chatbot(
            llm=self._llm,
            config=self._graph_config,
            graph=graph,
            assistant_config=self._assistant_configuration,
            adapter=self._adapter
        )

    def _auto_select_adapter(self, graph_type: str) -> BaseStateAdapter:
        """
        Automatically select appropriate adapter based on graph type.

        Args:
            graph_type: Type of graph being used

        Returns:
            Appropriate adapter instance
        """
        # Map graph types to their adapters
        adapter_mapping = {
            "vegaforza_navigation": VegaforzaStateAdapter(),
            # Add more mappings as needed
            # "custom_graph": CustomAdapter(),
        }

        # Return specific adapter if mapped, otherwise default
        adapter = adapter_mapping.get(graph_type, DefaultStateAdapter())

        print(f"INFO: Auto-selected adapter: {adapter.__class__.__name__} for graph type: {graph_type}")

        return adapter
