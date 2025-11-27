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

        # Pass session_id as thread_id for LangGraph conversation persistence
        adapter_kwargs["thread_id"] = request.session_id

        # Get full graph output with all messages (including agent responses)
        # Only invoke graph ONCE - this is the source of truth
        graph_output = await self.chatbot.get_graph_output_async(state, **adapter_kwargs)

        # Extract all messages from graph output and persist to session
        # This ensures all agent-generated messages are saved
        graph_messages = graph_output.get("messages", [])
        if graph_messages:
            session["messages"] = graph_messages
        else:
            # Fallback: just keep the messages we have
            session["messages"] = messages

        # Extract text response from graph output (last message)
        # Don't invoke graph again - use the output we already have
        bot_response_text = self.chatbot._from_graph_state(graph_output)

        # Build response from graph output
        response_data = ResponseData(
            text=bot_response_text,
            type="text",
            confidence=0.95,
            action=ActionResponse(
                type="none",
                target="",
                params={}
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

    def _parse_message(self, msg) -> tuple:
        """
        Parse message from dict or LangChain message object.

        Handles both:
        - Dict format: {"role": "...", "content": "..."}
        - LangChain objects: HumanMessage, AIMessage, etc.

        Returns:
            Tuple of (role, content)
        """
        if isinstance(msg, dict):
            return msg.get("role", "unknown"), msg.get("content", "")

        # Handle LangChain message objects
        msg_type = getattr(msg, "type", None)

        # Map LangChain message types to role names
        type_to_role = {
            "human": "user",
            "ai": "assistant",
            "tool": "tool",
            "system": "system"
        }

        role = type_to_role.get(msg_type, msg_type or "unknown")
        content = getattr(msg, "content", "")

        return role, content

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
        # Handles both dict and LangChain message objects
        messages = []
        for msg in session.get("messages", []):
            role, content = self._parse_message(msg)
            messages.append(MessageHistoryItem(role=role, content=content))

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
