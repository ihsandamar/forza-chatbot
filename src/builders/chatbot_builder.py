# src/builders/chatbot_builder.py
"""
Chatbot Builder - Dependency Injection Factory pattern kullanarak Chatbot oluşturur.

Single Responsibility: Sadece Chatbot örneği oluşturmak.
DI işlemi DependencyFactory ve AdapterFactory'ye taşındı.

Runtime Configuration Support:
- Accepts RuntimeConfiguration for dynamic configuration
- Supports both traditional method chaining and runtime config
"""

from typing import Optional
from src.core.chatbot import Chatbot
from src.core.runtime_config import RuntimeConfiguration
from src.adapters.base_state_adapter import BaseStateAdapter
from src.builders.dependency_factory import DependencyFactory
from src.builders.adapter_factory import AdapterFactory


class ChatbotBuilder:
    """
    Chatbot örnekleri oluşturmak için builder.

    Single Responsibility: Chatbot construction ve orchestration.
    Dependencies:
        - DependencyFactory: LLM ve GraphRepository oluşturma
        - AdapterFactory: State adapter seçimi

    Args:
        factory: DependencyFactory instance (LLM, GraphRepository creation)
        adapter_factory: AdapterFactory instance (adapter selection)
    """

    def __init__(self, factory: DependencyFactory, adapter_factory: AdapterFactory):
        """
        Initialize builder with dependency factories.

        Args:
            factory: DependencyFactory instance
            adapter_factory: AdapterFactory instance
        """
        self.factory = factory
        self.adapter_factory = adapter_factory
        self._llm = None
        self._graph_config = {"configurable": {"thread_id": "1"}}
        self._assistant_configuration = None
        self._adapter: Optional[BaseStateAdapter] = None
        self._graph_type = None
        self._graph_repository = None
        self._runtime_config: Optional[RuntimeConfiguration] = None

    def with_model(
        self,
        model_name: str,
        temperature: float = 0.0,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """
        Set LLM model configuration.

        Args:
            model_name: Model name
            temperature: Temperature parameter
            api_key: API key
            provider: LLM provider (openai, anthropic, ollama)
            base_url: Base URL for LLM API

        Returns:
            Self for method chaining
        """
        # Factory'yi kullanarak LLM oluştur
        self._llm = self.factory.create_llm(model_name, temperature, api_key, provider, base_url)
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
        # TODO: SQLAgentConfiguration sınıfı generic_sql_graph.py dosyasından silindiği için
        # bu method yeniden tasarlanması gerekiyor.
        # Şimdilik configuration yoksa devam et
        if config_params is not None:
            self._assistant_configuration = config_params
            print(f"INFO: Assistant configuration ayarlandı")

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

    def with_runtime_config(self, runtime_config: RuntimeConfiguration):
        """
        Configure builder with RuntimeConfiguration.

        This method provides a convenient way to configure the builder
        with all settings at once using RuntimeConfiguration.

        Args:
            runtime_config: RuntimeConfiguration instance

        Returns:
            Self for method chaining

        Example:
            from src.graphs.routing.assistant_configuration import RoutingAssistantConfiguration

            config = RuntimeConfiguration(
                llm=LLMRuntimeConfig(model="gpt-4o-mini"),
                graph_type="supervisor"
            )
            config = config.add_subagent(
                "routing",
                RoutingAssistantConfiguration(
                    system_prompt="You are a routing assistant",
                    token="secret-token",
                    assistant_name="RoutingAssistant"
                )
            )

            chatbot = (
                ChatbotBuilder(factory, adapter_factory)
                .with_runtime_config(config)
                .build()
            )
        """
        self._runtime_config = runtime_config

        # Configure LLM
        self.with_model(
            model_name=runtime_config.llm.model,
            temperature=runtime_config.llm.temperature,
            api_key=runtime_config.llm.api_key,
            provider=runtime_config.llm.provider,
            base_url=runtime_config.llm.base_url
        )

        # Configure graph
        self.with_graph(runtime_config.graph_type)

        # Configure graph config with runtime configurable params
        graph_config = {"configurable": runtime_config.to_graph_configurable()}
        self.with_graph_config(graph_config)

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
            self._adapter = self.adapter_factory.create_adapter(self._graph_type)

        return Chatbot(
            llm=self._llm,
            config=self._graph_config,
            graph=graph,
            assistant_config=self._assistant_configuration,
            runtime_config=self._runtime_config
        )
