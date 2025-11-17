# src/builders/dependency_factory.py
"""
Dependency Factory - Tüm dependencies'leri oluşturmaktan sorumlu.

Bu factory, Builder'ı container bağımlılığından kurtarıyor.
Her dependency türü için bir factory method var.
"""

from typing import Optional
from src.models.llm import LLM
from src.graphs.graph_repository import GraphRepository


class DependencyFactory:
    """
    Dependencies oluşturmaktan sorumlu factory.

    Single Responsibility: Sadece dependency creation.
    Builder'dan ayrı olması DI işlemini Builder'dan çıkarır.
    """

    def create_llm(
        self,
        model_name: str,
        temperature: float = 0.0,
        api_key: Optional[str] = None
    ) -> LLM:
        """
        LLM instance oluştur.

        Args:
            model_name: Model adı (e.g., "claude-3-5-sonnet")
            temperature: Temperature parametresi
            api_key: API key

        Returns:
            LLM instance
        """
        return LLM(
            model=model_name,
            temperature=temperature,
            api_key=api_key
        )

    def create_graph_repository(self, llm: LLM) -> GraphRepository:
        """
        GraphRepository instance oluştur.

        Args:
            llm: LLM instance

        Returns:
            GraphRepository instance
        """
        return GraphRepository(llm)
