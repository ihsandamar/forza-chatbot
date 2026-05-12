import pytest
from src.api.models.responses.chat import StreamEvent


def test_stream_event_progress():
    e = StreamEvent(
        event_type="progress",
        step="sql_executor",
        message="Veriler çekiliyor...",
        index=9,
        total=13,
    )
    assert e.event_type == "progress"
    assert e.step == "sql_executor"
    assert e.index == 9
    assert e.total == 13
    assert e.text is None  # result fields are absent


def test_stream_event_result_report():
    e = StreamEvent(
        event_type="result",
        text="Grafik hazır",
        type="report",
        confidence=0.85,
        action={"type": "chart", "target": "<iframe>", "params": {}},
    )
    assert e.event_type == "result"
    assert e.type == "report"
    assert e.step is None  # progress fields are absent
    assert e.action == {"type": "chart", "target": "<iframe>", "params": {}}
    assert e.confidence == 0.85


def test_stream_event_error():
    e = StreamEvent(event_type="error", message="Hata oluştu")
    assert e.event_type == "error"
    assert e.message == "Hata oluştu"
    assert e.text is None
    assert e.step is None


# ---------------------------------------------------------------------------
# stream_message() tests (Task 6)
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, AsyncMock
from datetime import datetime
from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import ChatMessageRequest


def _make_service_with_session(session_id="sess-1", hitl_pending=False):
    """Helper: ChatService with one pre-loaded session."""
    chatbot = MagicMock()
    chatbot._prepare_config = MagicMock(return_value={"configurable": {}})
    service = ChatService(chatbot=chatbot)
    service.sessions[session_id] = {
        "session_id": session_id,
        "user_id": None,
        "token": None,
        "created_at": datetime.now(),
        "messages": [],
        "metadata": {},
        "settings": {"max_messages": 100, "response_format": "ALL_MESSAGES"},
        "hitl_pending": hitl_pending,
        "hitl_question": None,
    }
    return service


@pytest.mark.asyncio
async def test_stream_message_raises_if_session_missing():
    service = _make_service_with_session()
    request = ChatMessageRequest(session_id="no-such-session", message="test")
    with pytest.raises(ValueError, match="Session not found"):
        async for _ in service.stream_message(request):
            pass


@pytest.mark.asyncio
async def test_stream_message_yields_progress_then_text_result():
    service = _make_service_with_session(session_id="s1")

    async def mock_raw_events(state, config):
        yield {"event_type": "progress", "step": "classify_intent", "message": "Sorgu analiz ediliyor...", "index": 0, "total": 13}
        yield {
            "event_type": "_result_raw",
            "_graph_output": {
                "messages": [],
                "final_response": "İşte sonuç",
            },
        }

    service.chatbot.astream_events_async = mock_raw_events
    service.chatbot.extract_response = MagicMock(return_value="İşte sonuç")

    request = ChatMessageRequest(session_id="s1", message="Satışları göster")
    collected = []
    async for event in service.stream_message(request):
        collected.append(event)

    assert len(collected) == 2
    assert isinstance(collected[0], StreamEvent)
    assert collected[0].event_type == "progress"
    assert collected[0].step == "classify_intent"
    assert collected[1].event_type == "result"
    assert collected[1].type == "text"
    assert collected[1].text == "İşte sonuç"


@pytest.mark.asyncio
async def test_stream_message_yields_report_result_when_chart_present():
    service = _make_service_with_session(session_id="s2")

    from langchain_core.messages import AIMessage
    ai_msg = AIMessage(content="Grafik başlığı", additional_kwargs={"chart_html": "<iframe>chart</iframe>"})

    async def mock_raw_events(state, config):
        yield {
            "event_type": "_result_raw",
            "_graph_output": {"messages": [ai_msg]},
        }

    service.chatbot.astream_events_async = mock_raw_events
    service.chatbot.extract_response = MagicMock(return_value="Grafik başlığı")

    request = ChatMessageRequest(session_id="s2", message="Grafik yap")
    collected = []
    async for event in service.stream_message(request):
        collected.append(event)

    assert len(collected) == 1
    assert collected[0].event_type == "result"
    assert collected[0].type == "report"
    assert "<iframe>" in collected[0].action["target"]


@pytest.mark.asyncio
async def test_stream_message_stores_hitl_state_and_yields_question():
    service = _make_service_with_session(session_id="s3")

    async def mock_raw_events(state, config):
        yield {
            "event_type": "result",
            "text": "❓ Hangi şube?",
            "type": "question",
            "confidence": 0.9,
            "action": {"type": "hitl", "target": "", "params": {"question": "Hangi şube?", "options": ["A", "B"], "context": ""}},
            "_hitl_info": {"type": "choice", "question": "Hangi şube?", "options": ["A", "B"], "context": ""},
        }

    service.chatbot.astream_events_async = mock_raw_events

    request = ChatMessageRequest(session_id="s3", message="Satışlar")
    collected = []
    async for event in service.stream_message(request):
        collected.append(event)

    assert collected[0].type == "question"
    assert service.sessions["s3"]["hitl_pending"] is True


@pytest.mark.asyncio
async def test_stream_message_passes_error_through():
    service = _make_service_with_session(session_id="s4")

    async def mock_raw_events(state, config):
        yield {"event_type": "error", "message": "Zaman aşımı"}

    service.chatbot.astream_events_async = mock_raw_events

    request = ChatMessageRequest(session_id="s4", message="test")
    collected = []
    async for event in service.stream_message(request):
        collected.append(event)

    assert collected[0].event_type == "error"
    assert "Zaman aşımı" in collected[0].message


@pytest.mark.asyncio
async def test_stream_message_uses_command_resume_for_hitl():
    """When HITL is pending, stream_message passes Command(resume=...) to chatbot."""
    from langgraph.types import Command
    service = _make_service_with_session(session_id="s5", hitl_pending=True)
    service.sessions["s5"]["hitl_question"] = {"type": "choice", "question": "Q?", "options": [], "context": ""}

    received_states = []

    async def mock_raw_events(state, config):
        received_states.append(state)
        yield {
            "event_type": "_result_raw",
            "_graph_output": {"messages": []},
        }

    service.chatbot.astream_events_async = mock_raw_events
    service.chatbot.extract_response = MagicMock(return_value="ok")

    request = ChatMessageRequest(session_id="s5", message="Şube A")
    async for _ in service.stream_message(request):
        pass

    assert isinstance(received_states[0], Command)
    assert service.sessions["s5"]["hitl_pending"] is False
