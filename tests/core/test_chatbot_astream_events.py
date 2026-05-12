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


from src.core.chatbot import Chatbot


def _make_chatbot_with_mock_graph(events_list):
    """Helper: chatbot whose graph.astream_events yields events_list."""
    async def fake_astream_events(input, config=None, **kwargs):
        for e in events_list:
            yield e

    graph_mock = MagicMock()
    graph_mock.astream_events = fake_astream_events

    llm_mock = MagicMock()
    return Chatbot(llm=llm_mock, graph=graph_mock)


@pytest.mark.asyncio
async def test_astream_events_async_emits_progress_for_known_node():
    events_list = [
        {"event": "on_chain_start", "name": "LangGraph",        "run_id": "root", "parent_ids": [],       "data": {}},
        {"event": "on_chain_start", "name": "classify_intent",  "run_id": "r2",   "parent_ids": ["root"], "data": {}},
        {"event": "on_chain_end",   "name": "classify_intent",  "run_id": "r2",   "parent_ids": ["root"], "data": {"output": {}}},
        {"event": "on_chain_end",   "name": "LangGraph",        "run_id": "root", "parent_ids": [],
         "data": {"output": {"messages": [], "final_response": "done"}}},
    ]
    chatbot = _make_chatbot_with_mock_graph(events_list)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    progress = [e for e in collected if e["event_type"] == "progress"]
    assert len(progress) == 1
    assert progress[0]["step"] == "classify_intent"
    assert progress[0]["index"] == 0
    assert progress[0]["total"] == 13

    result = [e for e in collected if e["event_type"] == "_result_raw"]
    assert len(result) == 1
    assert result[0]["_graph_output"]["final_response"] == "done"


@pytest.mark.asyncio
async def test_astream_events_async_skips_unknown_node():
    events_list = [
        {"event": "on_chain_start", "name": "LangGraph",    "run_id": "root", "parent_ids": [],       "data": {}},
        {"event": "on_chain_start", "name": "__unknown__",  "run_id": "r2",   "parent_ids": ["root"], "data": {}},
        {"event": "on_chain_end",   "name": "LangGraph",    "run_id": "root", "parent_ids": [],
         "data": {"output": {"messages": []}}},
    ]
    chatbot = _make_chatbot_with_mock_graph(events_list)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    progress = [e for e in collected if e["event_type"] == "progress"]
    assert len(progress) == 0


@pytest.mark.asyncio
async def test_astream_events_async_retry_message_on_second_occurrence():
    events_list = [
        {"event": "on_chain_start", "name": "LangGraph",          "run_id": "root", "parent_ids": [],       "data": {}},
        {"event": "on_chain_start", "name": "semantic_extractor", "run_id": "r2",   "parent_ids": ["root"], "data": {}},
        {"event": "on_chain_start", "name": "semantic_extractor", "run_id": "r3",   "parent_ids": ["root"], "data": {}},
        {"event": "on_chain_end",   "name": "LangGraph",          "run_id": "root", "parent_ids": [],
         "data": {"output": {"messages": []}}},
    ]
    chatbot = _make_chatbot_with_mock_graph(events_list)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    progress = [e for e in collected if e["event_type"] == "progress"]
    assert len(progress) == 2
    assert "yeniden" in progress[1]["message"]


@pytest.mark.asyncio
async def test_astream_events_async_interrupt_yields_result_question():
    from langgraph.errors import GraphInterrupt

    async def fake_astream_events_raises(input, config=None, **kwargs):
        yield {"event": "on_chain_start", "name": "LangGraph", "run_id": "root", "parent_ids": [], "data": {}}
        yield {"event": "on_chain_start", "name": "value_resolver", "run_id": "r2", "parent_ids": ["root"], "data": {}}
        raise GraphInterrupt((
            type("Interrupt", (), {"value": {"question": "Hangi şube?", "options": ["A", "B"], "context": "", "type": "choice"}})(),
        ))

    graph_mock = MagicMock()
    graph_mock.astream_events = fake_astream_events_raises
    chatbot = Chatbot(llm=MagicMock(), graph=graph_mock)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    result_events = [e for e in collected if e["event_type"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["type"] == "question"
    assert "Hangi şube?" in result_events[0]["text"]
    assert result_events[0]["_hitl_info"]["question"] == "Hangi şube?"


@pytest.mark.asyncio
async def test_astream_events_async_graph_exception_yields_error():
    async def fake_raises(input, config=None, **kwargs):
        yield {"event": "on_chain_start", "name": "LangGraph", "run_id": "root", "parent_ids": [], "data": {}}
        raise RuntimeError("DB bağlantısı kesildi")

    graph_mock = MagicMock()
    graph_mock.astream_events = fake_raises
    chatbot = Chatbot(llm=MagicMock(), graph=graph_mock)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    errors = [e for e in collected if e["event_type"] == "error"]
    assert len(errors) == 1
    assert "DB bağlantısı" in errors[0]["message"]


@pytest.mark.asyncio
async def test_astream_events_async_hitl_in_final_state():
    """__interrupt__ in final state triggers result(type='question')."""
    interrupt_val = type("IV", (), {"value": {"question": "Filtre?", "options": [], "context": "", "type": "choice"}})()

    events_list = [
        {"event": "on_chain_start", "name": "LangGraph", "run_id": "root", "parent_ids": [], "data": {}},
        {"event": "on_chain_end",   "name": "LangGraph", "run_id": "root", "parent_ids": [],
         "data": {"output": {"messages": [], "__interrupt__": (interrupt_val,)}}},
    ]
    chatbot = _make_chatbot_with_mock_graph(events_list)

    collected = []
    async for raw in chatbot.astream_events_async({"messages": []}, config={}):
        collected.append(raw)

    result_events = [e for e in collected if e["event_type"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["type"] == "question"
