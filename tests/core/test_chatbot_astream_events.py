import pytest
from unittest.mock import MagicMock, AsyncMock
from src.graphs.base.base_graph import BaseGraph


class ConcreteGraph(BaseGraph):
    def _get_default_metadata(self):
        m = MagicMock()
        m.name = "test"
        m.category = "test"
        m.get_capabilities.return_value = []
        m.input_spec.required = False
        m.input_spec.name = "messages"
        return m

    def build_graph(self):
        return self._mock_compiled


@pytest.fixture
def base_graph_with_mock_compiled():
    llm = MagicMock()
    g = ConcreteGraph.__new__(ConcreteGraph)
    g.llm = llm
    g.state_class = dict
    g.config = MagicMock()
    g.config.model_dump.return_value = {}
    g.metadata = MagicMock()
    g.memory = MagicMock()
    g._compiled_graph = None

    async def fake_astream_events(input, config=None, **kwargs):
        yield {"event": "on_chain_start", "name": "LangGraph", "run_id": "root-1", "parent_ids": []}
        yield {"event": "on_chain_start", "name": "classify_intent", "run_id": "r2", "parent_ids": ["root-1"]}
        yield {"event": "on_chain_end", "name": "classify_intent", "run_id": "r2", "parent_ids": ["root-1"], "data": {"output": {}}}
        yield {"event": "on_chain_end", "name": "LangGraph", "run_id": "root-1", "parent_ids": [], "data": {"output": {"messages": []}}}

    compiled = MagicMock()
    compiled.astream_events = fake_astream_events
    g._mock_compiled = compiled
    g._compiled_graph = compiled
    return g


@pytest.mark.asyncio
async def test_base_graph_astream_events_yields_all_events(base_graph_with_mock_compiled):
    events = []
    async for event in base_graph_with_mock_compiled.astream_events({"messages": []}, config={}):
        events.append(event)
    assert len(events) == 4
    assert events[0]["event"] == "on_chain_start"
    assert events[0]["name"] == "LangGraph"


@pytest.mark.asyncio
async def test_base_graph_astream_events_passes_kwargs(base_graph_with_mock_compiled):
    received_kwargs = {}

    async def capturing_astream_events(input, config=None, **kwargs):
        received_kwargs.update(kwargs)
        yield {"event": "on_chain_end", "name": "LangGraph", "run_id": "r", "parent_ids": [], "data": {"output": {}}}

    base_graph_with_mock_compiled._compiled_graph.astream_events = capturing_astream_events

    async for _ in base_graph_with_mock_compiled.astream_events({}, config={}, version="v2"):
        pass

    assert received_kwargs.get("version") == "v2"
