"""Integration test: verify API message flow matches langgraph dev pattern."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import ChatMessageRequest, SessionStartRequest


@pytest.fixture
def service_with_tracking():
    """ChatService with a mock chatbot that tracks what state it receives."""
    received_states = []

    async def track_invoke(state, **kwargs):
        received_states.append(state)
        return {
            "messages": [
                {"role": "assistant", "content": f"response to turn {len(received_states)}"}
            ]
        }

    mock_chatbot = MagicMock()
    mock_chatbot.get_graph_output_async = AsyncMock(side_effect=track_invoke)
    mock_chatbot.extract_response = MagicMock(return_value="response")

    service = ChatService(mock_chatbot)
    return service, received_states


@pytest.mark.asyncio
async def test_multi_turn_sends_only_new_messages(service_with_tracking):
    """Over multiple turns, each invoke should receive ONLY the new message."""
    service, received_states = service_with_tracking

    # Start session
    session = await service.start_session(SessionStartRequest(user_id="perf-test", token=None))
    sid = session.session_id

    # Turn 1
    await service.send_message(ChatMessageRequest(session_id=sid, message="hello"))
    assert len(received_states[0]["messages"]) == 1
    assert received_states[0]["messages"][0]["content"] == "hello"

    # Turn 2
    await service.send_message(ChatMessageRequest(session_id=sid, message="show sales"))
    assert len(received_states[1]["messages"]) == 1
    assert received_states[1]["messages"][0]["content"] == "show sales"

    # Turn 3
    await service.send_message(ChatMessageRequest(session_id=sid, message="add filter"))
    assert len(received_states[2]["messages"]) == 1
    assert received_states[2]["messages"][0]["content"] == "add filter"

    # Each turn should have sent exactly 1 message
    for i, state in enumerate(received_states):
        msg_count = len(state["messages"])
        assert msg_count == 1, f"Turn {i+1}: expected 1 message, got {msg_count}"


@pytest.mark.asyncio
async def test_first_message_sends_single_message(service_with_tracking):
    """First message in a brand new session should also send only 1 message."""
    service, received_states = service_with_tracking

    session = await service.start_session(SessionStartRequest(user_id="first-msg", token=None))
    sid = session.session_id

    await service.send_message(ChatMessageRequest(session_id=sid, message="first message"))

    assert len(received_states) == 1
    assert len(received_states[0]["messages"]) == 1
    assert received_states[0]["messages"][0]["content"] == "first message"


@pytest.mark.asyncio
async def test_no_dead_state_fields_sent(service_with_tracking):
    """State sent to graph should not contain dead fields like _intent_type."""
    service, received_states = service_with_tracking

    session = await service.start_session(SessionStartRequest(user_id="clean-state", token=None))
    sid = session.session_id

    await service.send_message(ChatMessageRequest(session_id=sid, message="test"))

    state = received_states[0]
    dead_fields = [
        "active_query_context", "query_history", "text2sql_output",
        "visualization_output", "_intent_type", "_confidence",
        "_extracted_entities", "_modification_action"
    ]
    for field in dead_fields:
        assert field not in state, f"Dead field '{field}' should not be in state"
