# src/builders/chatbot_builder.py
from src.core.chatbot import Chatbot
from src.adapters.base_state_adapter import BaseStateAdapter
from src.adapters.default_state_adapter import DefaultStateAdapter
from src.adapters.vegaforza_state_adapter import VegaforzaStateAdapter
from typing import Optional

class ChatbotBuilder:
    def __init__(self, container):
        self.container = container
        self._llm = None
        self._graph_config = {"configurable": {"thread_id": "1"}}
        self._assistant_configuration = None
        self._adapter: Optional[BaseStateAdapter] = None
        self._graph_type = None

    def with_model(self, model_name: str, temperature: float = 0.0, api_key: str = None):
        def llm_provider():
            from src.models.models import LLM
            return LLM(model=model_name, temperature=temperature, api_key=api_key)

        self.container.register("llm", llm_provider)
        self._llm = self.container.resolve("llm")
        return self

    def with_graph(self, graph_type: str):
        self._graph_type = graph_type
        def repo_provider():
            from src.graphs.graph_repository import GraphRepository
            return GraphRepository(self._llm)
        self.container.register("graph_repo", repo_provider)
        return self

    def with_graph_config(self, config: dict):
        self._graph_config = config
        return self
    
    def with_assistant_configuration(self, config_params=None):
        """
        Assistant configuration parametrelerini ayarlar
        """
        from src.graphs.generic_sql_graph import SQLAgentConfiguration
        from src.services.app_logger import log
        
        # SQLAgentConfiguration oluştur
        self._assistant_configuration = SQLAgentConfiguration.create_from_config(config_params)
        
        # Assistant config'i container'a kaydet
        self.container.register("assistant_config", lambda: self._assistant_configuration)
        
        print(f"INFO: Assistant configuration ayarlandı: {self._assistant_configuration.assistant_name}")

        return self

    def with_adapter(self, adapter: BaseStateAdapter):
        """
        Set custom adapter for state transformation
        """
        self._adapter = adapter
        return self

    def build(self):
        """
        Build Chatbot with appropriate adapter based on graph type
        """
        graph = self.container.resolve("graph_repo").get(self._graph_type)

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
        Automatically select appropriate adapter based on graph type

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
