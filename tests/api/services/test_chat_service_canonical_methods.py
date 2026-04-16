"""Verify canonical async methods work after alias removal."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import SessionStartRequest


@pytest.fixture
def chat_service():
    chatbot = MagicMock()
    chatbot.send_async = AsyncMock(return_value="test response")
    chatbot.get_graph_output_async = AsyncMock(return_value={"messages": []})
    return ChatService(chatbot=chatbot)


@pytest.mark.asyncio
async def test_start_session_is_callable(chat_service):
    response = await chat_service.start_session(SessionStartRequest())
    assert response.session_id is not None


@pytest.mark.asyncio
async def test_get_session_history_is_callable(chat_service):
    session = await chat_service.start_session(SessionStartRequest())
    response = await chat_service.get_session_history(session.session_id)
    assert hasattr(response, "messages")


def test_clear_conversation_is_callable(chat_service):
    import asyncio
    session = asyncio.run(chat_service.start_session(SessionStartRequest()))
    count = chat_service.clear_conversation(session.session_id)
    assert isinstance(count, int)


def test_alias_methods_removed():
    """The 4 alias methods must not exist on ChatService after cleanup."""
    service = ChatService.__new__(ChatService)
    for alias in ("start_session_async", "send_message_async", "get_history_async", "clear_history_async"):
        assert not hasattr(ChatService, alias), f"ChatService.{alias} should have been removed"
