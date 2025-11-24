# src/builders/adapter_factory.py
"""
Adapter Factory - State adapter seçimi ve oluşturmasından sorumlu.

Bu factory, graph type'ına göre uygun adapter'ı seçer.
Builder'dan adapter selection logic'i ayrı tutar.
"""

from src.adapters.base_state_adapter import BaseStateAdapter
from src.adapters.default_state_adapter import DefaultStateAdapter
from src.adapters.vegaforza_state_adapter import VegaforzaStateAdapter


class AdapterFactory:
    """
    State adapter selection ve creation factory.

    Graph type'ına göre uygun adapter'ı seçer.
    Adapter mapping'i centralized tutarak extensibility sağlar.
    """

    # Adapter mapping - graph type -> adapter class
    ADAPTER_MAPPING = {
        "vegaforza_navigation": VegaforzaStateAdapter,
        # Add more mappings as needed
        # "custom_graph": CustomAdapter,
    }

    def create_adapter(self, graph_type: str) -> BaseStateAdapter:
        """
        Create appropriate adapter for graph type.

        Args:
            graph_type: Type of graph being used

        Returns:
            Appropriate adapter instance

        Raises:
            ValueError: If graph_type is None
        """
        if graph_type is None:
            raise ValueError("graph_type cannot be None")

        # Get adapter class from mapping, default to DefaultStateAdapter
        adapter_class = self.ADAPTER_MAPPING.get(graph_type, DefaultStateAdapter)
        adapter = adapter_class()

        print(f"INFO: Auto-selected adapter: {adapter.__class__.__name__} for graph type: {graph_type}")

        return adapter

    def register_adapter(self, graph_type: str, adapter_class) -> None:
        """
        Register custom adapter for graph type.

        Args:
            graph_type: Type of graph
            adapter_class: Adapter class to use
        """
        self.ADAPTER_MAPPING[graph_type] = adapter_class
        print(f"INFO: Registered adapter {adapter_class.__name__} for graph type: {graph_type}")
