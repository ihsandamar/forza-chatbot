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

    async def start_session_async(self, request: SessionStartRequest) -> SessionStartResponse:
        """
        Async wrapper for start_session (alias for compatibility)

        Args:
            request: SessionStartRequest with optional user_id and token

        Returns:
            SessionStartResponse with session_id and metadata
        """
        return await self.start_session(request)

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

        # Get structured response from chatbot (using async version)
        structured_response = await self.chatbot.send_structured_async(state, **adapter_kwargs)

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

    async def send_message_async(self, request: ChatMessageRequest) -> ChatMessageResponse:
        """
        Async wrapper for send_message (alias for compatibility)

        Args:
            request: ChatMessageRequest with session_id and message

        Returns:
            ChatMessageResponse with bot response
        """
        return await self.send_message(request)

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

    async def get_history_async(self, session_id: str) -> SessionHistoryResponse:
        """
        Async wrapper for get_session_history (alias for compatibility)

        Args:
            session_id: Session identifier

        Returns:
            SessionHistoryResponse with message history
        """
        return await self.get_session_history(session_id)

    def clear_conversation(self, session_id: str) -> int:
        """
        Clear conversation history for a session

        Args:
            session_id: Session identifier

        Returns:
            Number of messages cleared

        Raises:
            ValueError: If session not found
        """
        if not self.session_exists(session_id):
            raise ValueError(f"Session not found: {session_id}")

        session = self.get_session(session_id)
        cleared_count = len(session.get("messages", []))
        session["messages"] = []
        return cleared_count

    async def clear_history_async(self, session_id: str) -> int:
        """
        Async wrapper for clear_conversation (alias for compatibility)

        Args:
            session_id: Session identifier

        Returns:
            Number of messages cleared
        """
        return self.clear_conversation(session_id)

    def get_session_stats(self) -> dict:
        """
        Get session statistics.

        Returns:
            Dictionary with session stats
        """
        return {
            "total_sessions": len(self.sessions),
            "active_sessions": len([s for s in self.sessions.values() if s.get("messages")])
        }

    def get_conversation_stats(self) -> dict:
        """
        Get conversation statistics.

        Returns:
            Dictionary with conversation stats
        """
        total_messages = sum(len(s.get("messages", [])) for s in self.sessions.values())
        return {
            "total_conversations": len(self.sessions),
            "total_messages": total_messages
        }

    def get_assistant_config(self) -> dict:
        """
        Get assistant configuration.

        Returns:
            Dictionary with assistant config
        """
        return {
            "assistant_name": "Forza Chatbot",
            "version": "2.0"
        }

    def list_sessions(self) -> list:
        """
        Get list of all sessions with their metadata.

        Returns:
            List of session dictionaries containing session_id, created_at, and message_count
        """
        sessions_list = []
        for session_id, session_data in self.sessions.items():
            sessions_list.append({
                "session_id": session_id,
                "created_at": session_data.get("created_at"),
                "user_id": session_data.get("user_id"),
                "message_count": len(session_data.get("messages", []))
            })

        # Sort by creation time (newest first)
        sessions_list.sort(key=lambda x: x.get("created_at") or datetime.min, reverse=True)
        return sessions_list

    async def create_new_session(self, user_id: Optional[str] = None) -> SessionStartResponse:
        """
        Create a new chat session.

        Args:
            user_id: Optional user identifier

        Returns:
            SessionStartResponse with session_id and metadata
        """
        request = SessionStartRequest(user_id=user_id, token=None)
        return await self.start_session(request)
