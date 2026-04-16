"""Test that chat_service sends only new messages to graph, not full history."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import SessionStartRequest, ChatMessageRequest


@pytest.fixture
def chat_service():
    mock_chatbot = MagicMock()
    mock_chatbot.get_graph_output_async = AsyncMock(return_value={
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "show sales"},
            {"role": "assistant", "content": "here are sales"},
        ]
    })
    mock_chatbot.extract_response = MagicMock(return_value="here are sales")
    return ChatService(mock_chatbot)


@pytest.mark.asyncio
async def test_sends_only_new_message_not_full_history(chat_service):
    """After multiple turns, only the NEW user message should be sent to graph."""
    session_resp = await chat_service.start_session(
        SessionStartRequest(user_id="test", token=None)
    )
    session_id = session_resp.session_id

    # Simulate existing conversation in session (2 turns already happened)
    session = chat_service.get_session(session_id)
    session["messages"] = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "show sales"},
        {"role": "assistant", "content": "here are sales"},
    ]

    # Act: send 3rd message
    request = ChatMessageRequest(session_id=session_id, message="add filter")
    await chat_service.send_message(request)

    # Assert: chatbot received ONLY the new message, not full history
    call_args = chat_service.chatbot.get_graph_output_async.call_args
    state_sent = call_args[0][0]  # first positional arg
    messages_sent = state_sent["messages"]

    # Should be ONLY the new message (1 message), not all 5
    assert len(messages_sent) == 1, (
        f"Expected 1 new message, got {len(messages_sent)}. "
        f"Full history should be managed by checkpointer, not sent on every invoke."
    )
    assert messages_sent[0]["content"] == "add filter"
