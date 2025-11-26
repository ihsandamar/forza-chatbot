"""
Session Manager

Manage session lifecycle: create, retrieve, update, delete.
In-memory implementation (can be extended to Redis/DB later).
"""

import asyncio
from typing import Optional, List, Dict
from datetime import datetime
from src.core.models import Session, AssistantConfig


class SessionManager:
    """Manages chat sessions."""

    def __init__(self):
        """Initialize session manager."""
        self._sessions: Dict[str, Session] = {}

    def create_session(
        self,
        session_id: str,
        user_id: Optional[str],
        token: Optional[str],
        config_snapshot: dict,
        metadata: Optional[Dict] = None
    ) -> Session:
        """
        Create a new session.

        Args:
            session_id: Unique session identifier
            user_id: Optional user identifier
            token: Optional authentication token
            config_snapshot: Assistant config snapshot at session creation
            metadata: Optional session metadata

        Returns:
            Created Session object
        """
        session = Session(
            session_id=session_id,
            user_id=user_id,
            created_at=datetime.now(),
            last_interaction=datetime.now(),
            token=token,
            config_snapshot=config_snapshot,
            metadata=metadata or {}
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Retrieve a session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session object or None if not found
        """
        return self._sessions.get(session_id)

    def get_or_raise(self, session_id: str) -> Session:
        """
        Get session or raise ValueError.

        Args:
            session_id: Session identifier

        Returns:
            Session object

        Raises:
            ValueError: If session not found
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return session

    def update_session(self, session: Session) -> None:
        """
        Update an existing session.

        Args:
            session: Updated Session object
        """
        self._sessions[session.session_id] = session

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def list_sessions_by_user(self, user_id: str) -> List[Session]:
        """
        Get all sessions for a user.

        Args:
            user_id: User identifier

        Returns:
            List of Session objects
        """
        return [
            s for s in self._sessions.values()
            if s.user_id == user_id
        ]

    def get_session_count(self) -> int:
        """Get total session count."""
        return len(self._sessions)

    def cleanup_expired(self, timeout_seconds: int) -> int:
        """
        Clean up expired sessions.

        Args:
            timeout_seconds: Session timeout in seconds

        Returns:
            Number of sessions deleted
        """
        expired_ids = [
            sid for sid, session in self._sessions.items()
            if session.duration_seconds > timeout_seconds
        ]

        for sid in expired_ids:
            del self._sessions[sid]

        return len(expired_ids)

    async def cleanup_expired_async(self, timeout_seconds: int) -> int:
        """
        Async wrapper for cleanup_expired.

        Args:
            timeout_seconds: Session timeout in seconds

        Returns:
            Number of sessions deleted
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.cleanup_expired,
            timeout_seconds
        )

    def clear_all(self) -> None:
        """Clear all sessions (useful for testing)."""
        self._sessions.clear()

    def get_stats(self) -> Dict[str, int]:
        """
        Get session statistics.

        Returns:
            Dictionary with stats
        """
        user_sessions = {}
        for session in self._sessions.values():
            if session.user_id:
                user_sessions[session.user_id] = user_sessions.get(session.user_id, 0) + 1

        return {
            "total_sessions": len(self._sessions),
            "sessions_by_user": user_sessions
        }


__all__ = ["SessionManager"]
