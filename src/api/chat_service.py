"""
Chat Service Layer

Orchestration layer that coordinates:
- Session management
- Conversation management
- Chatbot processing
- Assistant configuration

Responsibilities:
- Handle incoming requests (start_session, send_message, etc)
- Manage session/conversation lifecycle
- Coordinate between layers
- Return API response models
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional

from src.core.chatbot import Chatbot
from src.core.session_manager import SessionManager
from src.core.conversation import ConversationManager
from src.core.assistant_manager import AssistantManager
from src.api.models import (
    SessionStartRequest,
    SessionStartResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    SessionEndRequest,
    SessionEndResponse,
    HistoryRequest,
    HistoryResponse,
    ClearHistoryRequest,
    ClearHistoryResponse,
    ReconfigureAssistantRequest,
    ReconfigureAssistantResponse,
    ErrorResponse
)


class ChatService:
    """
    Service layer for chat operations.

    Orchestrates all components:
    - SessionManager: session lifecycle
    - ConversationManager: message storage
    - Chatbot: message processing
    - AssistantManager: configuration

    All dependencies are injected (Dependency Inversion Principle).
    """

    def __init__(
        self,
        chatbot: Chatbot,
        session_manager: SessionManager,
        conversation_manager: ConversationManager,
        assistant_manager: AssistantManager
    ):
        """
        Initialize chat service with dependencies.

        Args:
            chatbot: Configured Chatbot instance
            session_manager: Session lifecycle manager
            conversation_manager: Conversation/message manager
            assistant_manager: Assistant configuration manager
        """
        self.chatbot = chatbot
        self.session_mgr = session_manager
        self.conv_mgr = conversation_manager
        self.assistant_mgr = assistant_manager

    # ========== SESSION MANAGEMENT ==========

    def start_session(
        self,
        request: SessionStartRequest
    ) -> SessionStartResponse:
        """
        Start a new chat session.

        Args:
            request: SessionStartRequest with user_id and token

        Returns:
            SessionStartResponse with session_id and created_at

        Raises:
            ValueError: If request is invalid
        """
        # Validate request
        error = request.validate()
        if error:
            raise ValueError(f"Invalid request: {error}")

        # Generate session ID
        session_id = str(uuid.uuid4())

        # Create session
        session = self.session_mgr.create_session(
            session_id=session_id,
            user_id=request.user_id,
            token=request.token,
            config_snapshot=self.assistant_mgr.get_snapshot(),
            metadata=request.metadata
        )

        # Create conversation for session
        self.conv_mgr.create_conversation(session_id)

        return SessionStartResponse(
            session_id=session.session_id,
            created_at=session.created_at,
            user_id=session.user_id
        )

    def end_session(
        self,
        request: SessionEndRequest
    ) -> SessionEndResponse:
        """
        End a chat session.

        Args:
            request: SessionEndRequest with session_id

        Returns:
            SessionEndResponse with session_id and ended_at

        Raises:
            ValueError: If request is invalid or session not found
        """
        # Validate request
        error = request.validate()
        if error:
            raise ValueError(f"Invalid request: {error}")

        # Get session
        session = self.session_mgr.get_or_raise(request.session_id)

        # Delete session and conversation
        self.session_mgr.delete_session(request.session_id)
        self.conv_mgr.delete_conversation(request.session_id)

        return SessionEndResponse(
            session_id=request.session_id,
            ended_at=datetime.now()
        )

    async def start_session_async(
        self,
        request: SessionStartRequest
    ) -> SessionStartResponse:
        """
        Async wrapper for start_session.

        Args:
            request: SessionStartRequest

        Returns:
            SessionStartResponse
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.start_session,
            request
        )

    async def end_session_async(
        self,
        request: SessionEndRequest
    ) -> SessionEndResponse:
        """
        Async wrapper for end_session.

        Args:
            request: SessionEndRequest

        Returns:
            SessionEndResponse
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.end_session,
            request
        )

    # ========== MESSAGE HANDLING ==========

    def send_message(
        self,
        request: ChatMessageRequest
    ) -> ChatMessageResponse:
        """
        Send a message and get response.

        Flow:
        1. Validate request
        2. Get/create conversation
        3. Add user message
        4. Get conversation state
        5. Process through chatbot
        6. Add assistant response
        7. Update session
        8. Return response

        Args:
            request: ChatMessageRequest with session_id and message

        Returns:
            ChatMessageResponse with response text

        Raises:
            ValueError: If request invalid or session not found
        """
        # Validate request
        error = request.validate()
        if error:
            raise ValueError(f"Invalid request: {error}")

        # Ensure session and conversation exist
        self.session_mgr.get_or_raise(request.session_id)
        conversation = self.conv_mgr.get_or_create(request.session_id)

        # Add user message to conversation
        self.conv_mgr.add_message(
            request.session_id,
            role="user",
            content=request.message,
            metadata=request.metadata
        )

        # Get conversation state
        try:
            state = self.conv_mgr.get_state(request.session_id)
        except ValueError as e:
            raise ValueError(f"Failed to get conversation state: {str(e)}")

        # Send to chatbot
        try:
            response_text = self.chatbot.send(
                {"messages": state.messages},
                thread_id=request.session_id,  # Use session_id as thread_id
                system_prompt=self.assistant_mgr.get_config().system_prompt
            )
        except Exception as e:
            raise ValueError(f"Chatbot processing failed: {str(e)}")

        # Add assistant response
        self.conv_mgr.add_message(
            request.session_id,
            role="assistant",
            content=response_text
        )

        # Update session interaction time
        session = self.session_mgr.get_session(request.session_id)
        if session:
            session.update_interaction()
            self.session_mgr.update_session(session)

        return ChatMessageResponse(
            session_id=request.session_id,
            text=response_text,
            timestamp=datetime.now()
        )

    async def send_message_async(
        self,
        request: ChatMessageRequest
    ) -> ChatMessageResponse:
        """
        Async wrapper for send_message.

        Args:
            request: ChatMessageRequest

        Returns:
            ChatMessageResponse
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.send_message,
            request
        )

    # ========== HISTORY MANAGEMENT ==========

    def get_history(
        self,
        request: HistoryRequest
    ) -> HistoryResponse:
        """
        Get conversation history.

        Args:
            request: HistoryRequest with session_id

        Returns:
            HistoryResponse with messages and count

        Raises:
            ValueError: If request invalid or conversation not found
        """
        # Validate request
        error = request.validate()
        if error:
            raise ValueError(f"Invalid request: {error}")

        # Get messages
        try:
            messages = self.conv_mgr.get_all_messages(request.session_id)
            conversation = self.conv_mgr.get_conversation(request.session_id)
        except ValueError as e:
            raise ValueError(f"Failed to get history: {str(e)}")

        return HistoryResponse(
            session_id=request.session_id,
            messages=messages,
            message_count=len(messages),
            created_at=conversation.created_at if conversation else None
        )

    def clear_history(
        self,
        request: ClearHistoryRequest
    ) -> ClearHistoryResponse:
        """
        Clear conversation history.

        Args:
            request: ClearHistoryRequest with session_id

        Returns:
            ClearHistoryResponse with cleared count

        Raises:
            ValueError: If request invalid or conversation not found
        """
        # Validate request
        error = request.validate()
        if error:
            raise ValueError(f"Invalid request: {error}")

        # Clear messages
        try:
            cleared_count = self.conv_mgr.clear_conversation(request.session_id)
        except ValueError as e:
            raise ValueError(f"Failed to clear history: {str(e)}")

        return ClearHistoryResponse(
            session_id=request.session_id,
            cleared_count=cleared_count,
            cleared_at=datetime.now()
        )

    async def get_history_async(
        self,
        request: HistoryRequest
    ) -> HistoryResponse:
        """
        Async wrapper for get_history.

        Args:
            request: HistoryRequest

        Returns:
            HistoryResponse
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.get_history,
            request
        )

    async def clear_history_async(
        self,
        request: ClearHistoryRequest
    ) -> ClearHistoryResponse:
        """
        Async wrapper for clear_history.

        Args:
            request: ClearHistoryRequest

        Returns:
            ClearHistoryResponse
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.clear_history,
            request
        )

    # ========== CONFIGURATION MANAGEMENT ==========

    def reconfigure_assistant(
        self,
        request: ReconfigureAssistantRequest
    ) -> ReconfigureAssistantResponse:
        """
        Reconfigure assistant at runtime.

        Args:
            request: ReconfigureAssistantRequest with config updates

        Returns:
            ReconfigureAssistantResponse with success status

        Raises:
            ValueError: If configuration is invalid
        """
        # Validate request
        error = request.validate()
        if error:
            raise ValueError(f"Invalid request: {error}")

        # Get update kwargs
        kwargs = request.to_kwargs()

        # Reconfigure
        try:
            new_config = self.assistant_mgr.reconfigure(**kwargs)
        except ValueError as e:
            return ReconfigureAssistantResponse(
                success=False,
                message=f"Configuration error: {str(e)}",
                new_config={}
            )

        return ReconfigureAssistantResponse(
            success=True,
            message="Assistant reconfigured successfully",
            new_config=new_config.to_dict(),
            reconfigured_at=datetime.now()
        )

    async def reconfigure_assistant_async(
        self,
        request: ReconfigureAssistantRequest
    ) -> ReconfigureAssistantResponse:
        """
        Async wrapper for reconfigure_assistant.

        Args:
            request: ReconfigureAssistantRequest

        Returns:
            ReconfigureAssistantResponse
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.reconfigure_assistant,
            request
        )

    # ========== UTILITY METHODS ==========

    def get_session_stats(self) -> dict:
        """
        Get session statistics.

        Returns:
            Dictionary with session stats
        """
        return self.session_mgr.get_stats()

    def get_conversation_stats(self) -> dict:
        """
        Get conversation statistics.

        Returns:
            Dictionary with conversation stats
        """
        return self.conv_mgr.get_stats()

    def get_assistant_config(self) -> dict:
        """
        Get current assistant configuration.

        Returns:
            Dictionary with assistant config
        """
        return self.assistant_mgr.get_config().to_dict()

    def cleanup_expired_sessions(self, timeout_seconds: Optional[int] = None) -> int:
        """
        Clean up expired sessions.

        Args:
            timeout_seconds: Optional custom timeout (uses config if not provided)

        Returns:
            Number of sessions cleaned up
        """
        # Use default timeout from config if not provided
        if timeout_seconds is None:
            # We don't have chatbot config here, so using default 3600
            timeout_seconds = 3600

        return self.session_mgr.cleanup_expired(timeout_seconds)

    async def cleanup_expired_sessions_async(
        self,
        timeout_seconds: Optional[int] = None
    ) -> int:
        """
        Async wrapper for cleanup_expired_sessions.

        Args:
            timeout_seconds: Optional custom timeout

        Returns:
            Number of sessions cleaned up
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.cleanup_expired_sessions,
            timeout_seconds
        )


__all__ = ["ChatService"]
