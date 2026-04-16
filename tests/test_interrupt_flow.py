"""
End-to-end integration tests for the GraphInterrupt → HITL → Command(resume) flow.

Tests the full interrupt lifecycle:
1. Graph raises GraphInterrupt → ChatService catches it → returns type="question" response
2. User responds → ChatService creates Command(resume=answer) → resumes graph
3. Different interrupt types (choice, input, clarification) produce correct output formatting

Run with: pytest tests/test_interrupt_flow.py -v
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt, Command

from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import SessionStartRequest, ChatMessageRequest
from src.core.chatbot import Chatbot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_interrupt(interrupt_value: dict) -> GraphInterrupt:
    """Build a GraphInterrupt with a single Interrupt object."""
    interrupt_obj = Interrupt(value=interrupt_value)
    return GraphInterrupt((interrupt_obj,))


def _make_chatbot_mock() -> Chatbot:
    """Create a Chatbot mock with the attributes ChatService relies on."""
    chatbot = MagicMock(spec=Chatbot)
    chatbot.get_graph_output_async = AsyncMock()
    chatbot.extract_response = MagicMock(return_value="Bot response text")
    return chatbot


async def _create_session(chat_service: ChatService, user_id: str = "test-user") -> str:
    """Start a session and return its ID."""
    req = SessionStartRequest(user_id=user_id, token="test-token")
    resp = await chat_service.start_session(req)
    return resp.session_id


# ===========================================================================
# Test 1: GraphInterrupt propagates to ChatService and produces a HITL response
# ===========================================================================

class TestGraphInterruptPropagatesToChatService:
    """Verify that a GraphInterrupt raised during graph invocation is caught
    by ChatService.send_message() and turned into a type='question' response
    with the correct HITL data stored on the session."""

    @pytest.mark.asyncio
    async def test_choice_interrupt_returns_question_response(self):
        # Arrange
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "choice",
            "question": "Hangi raporu istersiniz?",
            "options": ["Satış raporu", "Stok raporu"],
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)

        request = ChatMessageRequest(session_id=session_id, message="Rapor ver")

        # Act
        response = await chat_service.send_message(request)

        # Assert — response shape
        assert response.response.type == "question"
        assert response.session_id == session_id
        assert "Hangi raporu istersiniz?" in response.response.text
        assert "Satış raporu" in response.response.text
        assert "Stok raporu" in response.response.text

        # Assert — action metadata
        action = response.response.action
        assert action.type == "hitl"
        assert action.params["type"] == "choice"
        assert action.params["question"] == "Hangi raporu istersiniz?"
        assert action.params["options"] == ["Satış raporu", "Stok raporu"]

    @pytest.mark.asyncio
    async def test_session_hitl_pending_set_after_interrupt(self):
        # Arrange
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "choice",
            "question": "Soru?",
            "options": ["A", "B"],
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)

        request = ChatMessageRequest(session_id=session_id, message="test")

        # Act
        await chat_service.send_message(request)

        # Assert — session state
        session = chat_service.get_session(session_id)
        assert session["hitl_pending"] is True
        assert session["hitl_question"]["question"] == "Soru?"
        assert session["hitl_question"]["options"] == ["A", "B"]
        assert session["hitl_question"]["type"] == "choice"

    @pytest.mark.asyncio
    async def test_confidence_is_set_on_question_response(self):
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "choice",
            "question": "Q?",
            "options": ["X"],
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)
        request = ChatMessageRequest(session_id=session_id, message="test")

        response = await chat_service.send_message(request)

        assert response.response.confidence == 0.9


# ===========================================================================
# Test 2: HITL resume uses Command(resume=answer)
# ===========================================================================

class TestHITLResumeUsesCommand:
    """Verify that when a session has hitl_pending=True and the user sends
    a follow-up message, ChatService creates a Command(resume=answer) and
    passes it to the chatbot, then clears the HITL state."""

    @pytest.mark.asyncio
    async def test_resume_passes_command_to_chatbot(self):
        # Arrange
        chatbot = _make_chatbot_mock()

        # First call: raise interrupt
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "choice",
            "question": "Hangi rapor?",
            "options": ["Satış", "Stok"],
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)

        # Trigger the interrupt
        req1 = ChatMessageRequest(session_id=session_id, message="Rapor ver")
        await chat_service.send_message(req1)

        # Verify HITL is pending
        assert chat_service.get_session(session_id)["hitl_pending"] is True

        # Second call: user responds — graph returns normal output
        chatbot.get_graph_output_async.side_effect = None
        chatbot.get_graph_output_async.return_value = {
            "messages": [
                {"role": "user", "content": "Rapor ver"},
                {"role": "assistant", "content": "Satış raporu hazırlanıyor."},
            ]
        }

        # Act
        req2 = ChatMessageRequest(session_id=session_id, message="Satış")
        response = await chat_service.send_message(req2)

        # Assert — Command(resume=...) was passed
        call_args = chatbot.get_graph_output_async.call_args
        state_arg = call_args[0][0]  # first positional argument
        assert isinstance(state_arg, Command), (
            f"Expected Command, got {type(state_arg).__name__}: {state_arg!r}"
        )
        assert state_arg.resume == "Satış"

    @pytest.mark.asyncio
    async def test_hitl_state_cleared_after_resume(self):
        # Arrange
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "input",
            "question": "Tarih aralığı girin",
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)

        req1 = ChatMessageRequest(session_id=session_id, message="Rapor")
        await chat_service.send_message(req1)

        # Reset mock for resume call
        chatbot.get_graph_output_async.side_effect = None
        chatbot.get_graph_output_async.return_value = {
            "messages": [{"role": "assistant", "content": "OK"}]
        }

        # Act
        req2 = ChatMessageRequest(session_id=session_id, message="Son 3 ay")
        await chat_service.send_message(req2)

        # Assert — HITL state is cleared
        session = chat_service.get_session(session_id)
        assert session["hitl_pending"] is False
        assert session["hitl_question"] is None

    @pytest.mark.asyncio
    async def test_resume_response_is_normal_text(self):
        """After resuming, the response should be a normal text response."""
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "choice",
            "question": "Seçin",
            "options": ["A", "B"],
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)

        req1 = ChatMessageRequest(session_id=session_id, message="Rapor")
        await chat_service.send_message(req1)

        # Resume
        chatbot.get_graph_output_async.side_effect = None
        chatbot.get_graph_output_async.return_value = {
            "messages": [{"role": "assistant", "content": "Rapor hazır."}]
        }
        chatbot.extract_response.return_value = "Rapor hazır."

        req2 = ChatMessageRequest(session_id=session_id, message="A")
        response = await chat_service.send_message(req2)

        assert response.response.type == "text"
        assert response.response.text == "Rapor hazır."

    @pytest.mark.asyncio
    async def test_thread_id_passed_on_resume(self):
        """thread_id must be forwarded during resume so the graph can locate the checkpoint."""
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "choice",
            "question": "Q?",
            "options": ["X"],
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)

        req1 = ChatMessageRequest(session_id=session_id, message="Go")
        await chat_service.send_message(req1)

        chatbot.get_graph_output_async.side_effect = None
        chatbot.get_graph_output_async.return_value = {
            "messages": [{"role": "assistant", "content": "Done"}]
        }

        req2 = ChatMessageRequest(session_id=session_id, message="X")
        await chat_service.send_message(req2)

        call_kwargs = chatbot.get_graph_output_async.call_args[1]
        assert call_kwargs.get("thread_id") == session_id


# ===========================================================================
# Test 3: Interrupt data extraction — all 3 types
# ===========================================================================

class TestInterruptDataExtraction:
    """Verify that the 3 interrupt types (choice, input, clarification) are
    extracted and formatted correctly in the response text."""

    @pytest.mark.asyncio
    async def test_choice_type_renders_numbered_options(self):
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "choice",
            "question": "Hangi kategori?",
            "options": ["Gıda", "Teknoloji", "Tekstil"],
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)
        request = ChatMessageRequest(session_id=session_id, message="test")

        response = await chat_service.send_message(request)

        text = response.response.text
        assert "Hangi kategori?" in text
        assert "1. Gıda" in text
        assert "2. Teknoloji" in text
        assert "3. Tekstil" in text
        assert "Seçenekler:" in text

    @pytest.mark.asyncio
    async def test_input_type_no_options_rendered(self):
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "input",
            "question": "Tarih aralığı girin",
            # No options for input type
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)
        request = ChatMessageRequest(session_id=session_id, message="test")

        response = await chat_service.send_message(request)

        text = response.response.text
        assert "Tarih aralığı girin" in text
        # No options block should appear
        assert "Seçenekler:" not in text

        # Action params should have empty options list
        assert response.response.action.params["options"] == []
        assert response.response.action.params["type"] == "input"

    @pytest.mark.asyncio
    async def test_clarification_type_with_options_and_context(self):
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "clarification",
            "question": "Hangi şubeyi kastediyorsunuz?",
            "options": ["İstanbul Merkez", "İstanbul Anadolu"],
            "context": "Birden fazla İstanbul şubesi bulundu",
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)
        request = ChatMessageRequest(session_id=session_id, message="test")

        response = await chat_service.send_message(request)

        text = response.response.text
        assert "Hangi şubeyi kastediyorsunuz?" in text
        assert "1. İstanbul Merkez" in text
        assert "2. İstanbul Anadolu" in text
        assert "Birden fazla İstanbul şubesi bulundu" in text

        # Action params
        params = response.response.action.params
        assert params["type"] == "clarification"
        assert params["context"] == "Birden fazla İstanbul şubesi bulundu"

    @pytest.mark.asyncio
    async def test_missing_question_uses_default(self):
        """When the interrupt value has no 'question' key, a default is used."""
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            "type": "choice",
            # question key omitted
            "options": ["A"],
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)
        request = ChatMessageRequest(session_id=session_id, message="test")

        response = await chat_service.send_message(request)

        # Should use default question text
        assert "Açıklama gerekiyor" in response.response.text

    @pytest.mark.asyncio
    async def test_missing_type_defaults_to_choice(self):
        """When interrupt value has no 'type' key, it defaults to 'choice'."""
        chatbot = _make_chatbot_mock()
        chatbot.get_graph_output_async.side_effect = _make_interrupt({
            # type key omitted
            "question": "Bir soru?",
            "options": ["Evet", "Hayır"],
        })

        chat_service = ChatService(chatbot=chatbot)
        session_id = await _create_session(chat_service)
        request = ChatMessageRequest(session_id=session_id, message="test")

        response = await chat_service.send_message(request)

        assert response.response.action.params["type"] == "choice"


# ===========================================================================
# Run
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
