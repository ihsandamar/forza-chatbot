"""
Conversation Manager

Manage conversations and messages for sessions.
In-memory implementation with support for async operations.
"""

import asyncio
from typing import Optional, Dict, List
from src.core.models import Conversation, Message
from src.models.standard_types import StandardState


class ConversationManager:
    """Manages conversations for sessions."""

    def __init__(self):
        """Initialize conversation manager."""
        # Dict[session_id] -> Conversation
        self._conversations: Dict[str, Conversation] = {}

    def create_conversation(self, session_id: str) -> Conversation:
        """
        Create a new conversation for a session.

        Args:
            session_id: Session identifier

        Returns:
            Created Conversation object
        """
        conversation = Conversation(session_id=session_id)
        self._conversations[session_id] = conversation
        return conversation

    def get_conversation(self, session_id: str) -> Optional[Conversation]:
        """
        Get conversation for a session.

        Args:
            session_id: Session identifier

        Returns:
            Conversation object or None if not found
        """
        return self._conversations.get(session_id)

    def get_or_create(self, session_id: str) -> Conversation:
        """
        Get existing conversation or create new one.

        Args:
            session_id: Session identifier

        Returns:
            Conversation object
        """
        conv = self.get_conversation(session_id)
        if not conv:
            conv = self.create_conversation(session_id)
        return conv

    def add_message(self, session_id: str, role: str,
                   content: str, metadata: dict = None) -> Message:
        """
        Add message to conversation.

        Args:
            session_id: Session identifier
            role: Message role ("user", "assistant", "system")
            content: Message content
            metadata: Optional metadata

        Returns:
            Added Message object

        Raises:
            ValueError: If conversation not found or message invalid
        """
        conv = self.get_conversation(session_id)
        if conv is None:
            raise ValueError(f"Conversation not found: {session_id}")

        return conv.add_message(role, content, metadata)

    def get_messages(self, session_id: str) -> List[dict]:
        """
        Get messages in LangChain format (for graph).

        Args:
            session_id: Session identifier

        Returns:
            List of message dicts

        Raises:
            ValueError: If conversation not found
        """
        conv = self.get_conversation(session_id)
        if conv is None:
            raise ValueError(f"Conversation not found: {session_id}")

        return conv.get_messages()

    def get_all_messages(self, session_id: str) -> List[Message]:
        """
        Get all Message objects.

        Args:
            session_id: Session identifier

        Returns:
            List of Message objects

        Raises:
            ValueError: If conversation not found
        """
        conv = self.get_conversation(session_id)
        if conv is None:
            raise ValueError(f"Conversation not found: {session_id}")

        return conv.get_all_messages()

    def get_state(self, session_id: str) -> StandardState:
        """
        Get conversation as StandardState (for chatbot).

        Args:
            session_id: Session identifier

        Returns:
            StandardState object

        Raises:
            ValueError: If conversation not found
        """
        conv = self.get_conversation(session_id)
        if conv is None:
            raise ValueError(f"Conversation not found: {session_id}")

        return StandardState(
            messages=conv.get_messages(),
            session_id=session_id
        )

    def get_message_count(self, session_id: str) -> int:
        """
        Get message count for a session.

        Args:
            session_id: Session identifier

        Returns:
            Number of messages

        Raises:
            ValueError: If conversation not found
        """
        conv = self.get_conversation(session_id)
        if conv is None:
            raise ValueError(f"Conversation not found: {session_id}")

        return conv.get_message_count()

    def clear_conversation(self, session_id: str) -> int:
        """
        Clear all messages from a conversation.

        Args:
            session_id: Session identifier

        Returns:
            Number of messages cleared

        Raises:
            ValueError: If conversation not found
        """
        conv = self.get_conversation(session_id)
        if conv is None:
            raise ValueError(f"Conversation not found: {session_id}")

        count = len(conv)
        conv.clear()
        return count

    def delete_conversation(self, session_id: str) -> bool:
        """
        Delete entire conversation.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        if session_id in self._conversations:
            del self._conversations[session_id]
            return True
        return False

    # ========== ASYNC METHODS ==========

    async def add_message_async(self, session_id: str, role: str,
                               content: str, metadata: dict = None) -> Message:
        """
        Async wrapper for add_message.

        Args:
            session_id: Session identifier
            role: Message role
            content: Message content
            metadata: Optional metadata

        Returns:
            Added Message object
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.add_message,
            session_id,
            role,
            content,
            metadata
        )

    async def get_messages_async(self, session_id: str) -> List[dict]:
        """
        Async wrapper for get_messages.

        Args:
            session_id: Session identifier

        Returns:
            List of message dicts
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.get_messages,
            session_id
        )

    async def clear_conversation_async(self, session_id: str) -> int:
        """
        Async wrapper for clear_conversation.

        Args:
            session_id: Session identifier

        Returns:
            Number of messages cleared
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.clear_conversation,
            session_id
        )

    # ========== UTILITY METHODS ==========

    def get_stats(self) -> dict:
        """
        Get conversation statistics.

        Returns:
            Dictionary with stats
        """
        total_messages = sum(
            len(conv) for conv in self._conversations.values()
        )

        return {
            "total_conversations": len(self._conversations),
            "total_messages": total_messages,
            "avg_messages_per_conversation": (
                total_messages / len(self._conversations)
                if self._conversations else 0
            )
        }

    def clear_all(self) -> None:
        """Clear all conversations (useful for testing)."""
        self._conversations.clear()


__all__ = ["ConversationManager"]
