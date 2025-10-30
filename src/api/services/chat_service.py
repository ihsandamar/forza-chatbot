import uuid
from datetime import datetime
from typing import Optional, Dict
from src.api.models.requests.chat import SessionStartRequest, ChatMessageRequest
from src.api.models.responses.chat import (
    SessionStartResponse,
    ChatMessageResponse,
    ResponseData,
    ActionResponse,
    SessionHistoryResponse,
    MessageHistoryItem
)
from src.core.chatbot import Chatbot


class ChatService:
    """Service for handling chat-related business logic"""

    def __init__(self, chatbot: Chatbot):
        # In-memory session storage (replace with Redis/DB in production)
        self.sessions: Dict[str, dict] = {}
        self.chatbot = chatbot

    async def start_session(self, request: SessionStartRequest) -> SessionStartResponse:
        """
        Start a new chat session

        Args:
            request: SessionStartRequest with optional user_id and token

        Returns:
            SessionStartResponse with session_id and metadata
        """
        # Generate unique session ID
        session_id = str(uuid.uuid4())
        created_at = datetime.now()

        # Store session data
        self.sessions[session_id] = {
            "session_id": session_id,
            "user_id": request.user_id,
            "token": request.token,  # Store token for graph operations
            "created_at": created_at,
            "messages": [],
            "metadata": {}
        }

        return SessionStartResponse(
            session_id=session_id,
            user_id=request.user_id,
            created_at=created_at
        )

    def get_session(self, session_id: str) -> Optional[dict]:
        """Get session data by session_id"""
        return self.sessions.get(session_id)

    def session_exists(self, session_id: str) -> bool:
        """Check if session exists"""
        return session_id in self.sessions

    async def send_message(self, request: ChatMessageRequest) -> ChatMessageResponse:
        """
        Send a message to the chatbot

        Args:
            request: ChatMessageRequest with session_id and message

        Returns:
            ChatMessageResponse with bot response

        Raises:
            ValueError: If session not found
        """
        # Check if session exists
        if not self.session_exists(request.session_id):
            raise ValueError(f"Session not found: {request.session_id}")

        # Get session data
        session = self.get_session(request.session_id)

        # Build message history from session
        messages = session.get("messages", [])

        # Add user message to messages
        messages.append({"role": "user", "content": request.message})

        # Prepare state for chatbot
        state = {"messages": messages}

        # Prepare adapter kwargs (e.g., token for VegaForza)
        adapter_kwargs = {}
        if session.get("token"):
            adapter_kwargs["token"] = session["token"]

        # Get structured response from chatbot
        structured_response = self.chatbot.send_structured(state, **adapter_kwargs)

        # Extract text for session history
        bot_response_text = structured_response.get("text", "")

        # Add assistant response to session messages
        messages.append({"role": "assistant", "content": bot_response_text})
        session["messages"] = messages

        # Build response from structured data
        action_data = structured_response.get("action", {})
        response_data = ResponseData(
            text=bot_response_text,
            type=structured_response.get("type", "text"),
            confidence=structured_response.get("confidence", 0.95),
            action=ActionResponse(
                type=action_data.get("type", "none"),
                target=action_data.get("target", ""),
                params=action_data.get("params", {})
            )
        )

        return ChatMessageResponse(
            session_id=request.session_id,
            timestamp=datetime.now(),
            response=response_data
        )

    async def get_session_history(self, session_id: str) -> SessionHistoryResponse:
        """
        Get chat history for a session

        Args:
            session_id: Session identifier

        Returns:
            SessionHistoryResponse with message history

        Raises:
            ValueError: If session not found
        """
        # Check if session exists
        if not self.session_exists(session_id):
            raise ValueError(f"Session not found: {session_id}")

        # Get session data
        session = self.get_session(session_id)

        # Convert messages to MessageHistoryItem format
        messages = [
            MessageHistoryItem(role=msg["role"], content=msg["content"])
            for msg in session.get("messages", [])
        ]

        return SessionHistoryResponse(
            session_id=session_id,
            user_id=session.get("user_id"),
            created_at=session.get("created_at"),
            message_count=len(messages),
            messages=messages
        )
