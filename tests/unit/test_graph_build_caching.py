"""Tests for BaseGraph compiled graph caching."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Dict, Any, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_metadata import GraphMetadata


class _DummyState:
    """Minimal state for testing."""
    pass


class _DummyConfig:
    """Minimal config for testing."""
    pass


class ConcreteTestGraph(BaseGraph):
    """Concrete implementation for testing build_graph caching."""

    def __init__(self):
        self.build_count = 0
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {}
        super().__init__(
            llm=MagicMock(),
            state_class=dict,
            config=mock_config,
            metadata=MagicMock(spec=GraphMetadata),
        )

    def _get_default_config(self):
        return MagicMock()

    def _get_default_metadata(self) -> GraphMetadata:
        return MagicMock(spec=GraphMetadata)

    def build_graph(self) -> StateGraph:
        self.build_count += 1
        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {"result": "ok"}
        return mock_compiled


class TestGraphBuildCaching:
    """Test that compiled graph is cached after first build."""

    def test_invoke_caches_compiled_graph(self):
        """First invoke builds graph, second invoke reuses cache."""
        graph = ConcreteTestGraph()

        graph.invoke({"messages": []})
        assert graph.build_count == 1

        graph.invoke({"messages": []})
        assert graph.build_count == 1, "build_graph() should NOT be called again"

    def test_multiple_invokes_single_build(self):
        """N invocations should only build the graph once."""
        graph = ConcreteTestGraph()

        for _ in range(5):
            graph.invoke({"messages": []})

        assert graph.build_count == 1

    @pytest.mark.asyncio
    async def test_ainvoke_caches_compiled_graph(self):
        """Async invoke also uses cache."""
        graph = ConcreteTestGraph()

        await graph.ainvoke({"messages": []})
        assert graph.build_count == 1

        await graph.ainvoke({"messages": []})
        assert graph.build_count == 1, "build_graph() should NOT be called again on ainvoke"

    @pytest.mark.asyncio
    async def test_astream_caches_compiled_graph(self):
        """Async stream also uses cache."""
        graph = ConcreteTestGraph()
        mock_compiled = graph.build_graph()
        graph.build_count = 0  # reset after manual build
        graph._compiled_graph = None  # reset cache

        # astream uses _get_compiled_graph internally
        async for _ in graph.astream({"messages": []}):
            pass
        assert graph.build_count == 1

        async for _ in graph.astream({"messages": []}):
            pass
        assert graph.build_count == 1, "build_graph() should NOT be called again on astream"

    def test_cache_is_per_instance(self):
        """Different instances maintain separate caches."""
        graph1 = ConcreteTestGraph()
        graph2 = ConcreteTestGraph()

        graph1.invoke({"messages": []})
        graph2.invoke({"messages": []})

        assert graph1.build_count == 1
        assert graph2.build_count == 1
