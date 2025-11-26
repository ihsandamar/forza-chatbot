"""
API Models for HTTP layer

Request/Response dataclasses for clear contracts between API and service layer.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from src.core.models import Message


# ============ REQUEST MODELS ============

@dataclass
class SessionStartRequest:
    """Request to start a new chat session."""
    user_id: Optional[str] = None
    token: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> Optional[str]:
        """Validate request."""
        # All fields are optional for now
        return None


@dataclass
class ChatMessageRequest:
    """Request to send a message."""
    session_id: str
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> Optional[str]:
        """Validate request."""
        if not self.session_id.strip():
            return "session_id cannot be empty"
        if not self.message.strip():
            return "message cannot be empty"
        return None


@dataclass
class SessionEndRequest:
    """Request to end a session."""
    session_id: str

    def validate(self) -> Optional[str]:
        """Validate request."""
        if not self.session_id.strip():
            return "session_id cannot be empty"
        return None


@dataclass
class HistoryRequest:
    """Request to get conversation history."""
    session_id: str

    def validate(self) -> Optional[str]:
        """Validate request."""
        if not self.session_id.strip():
            return "session_id cannot be empty"
        return None


@dataclass
class ClearHistoryRequest:
    """Request to clear conversation history."""
    session_id: str

    def validate(self) -> Optional[str]:
        """Validate request."""
        if not self.session_id.strip():
            return "session_id cannot be empty"
        return None


@dataclass
class ReconfigureAssistantRequest:
    """Request to reconfigure assistant."""
    system_prompt: Optional[str] = None
    assistant_name: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    def validate(self) -> Optional[str]:
        """Validate request."""
        if self.temperature is not None:
            if not (0.0 <= self.temperature <= 2.0):
                return "temperature must be between 0.0 and 2.0"
        if self.max_tokens is not None:
            if self.max_tokens < 1:
                return "max_tokens must be positive"
        return None

    def to_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs for AssistantManager.reconfigure()."""
        kwargs = {}
        if self.system_prompt is not None:
            kwargs["system_prompt"] = self.system_prompt
        if self.assistant_name is not None:
            kwargs["assistant_name"] = self.assistant_name
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        return kwargs


# ============ RESPONSE MODELS ============

@dataclass
class SessionStartResponse:
    """Response from starting a session."""
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)
    user_id: Optional[str] = None


@dataclass
class ChatMessageResponse:
    """Response from sending a message."""
    session_id: str
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 0.95
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionEndResponse:
    """Response from ending a session."""
    session_id: str
    ended_at: datetime = field(default_factory=datetime.now)


@dataclass
class HistoryResponse:
    """Response with conversation history."""
    session_id: str
    messages: List[Message] = field(default_factory=list)
    message_count: int = 0
    created_at: Optional[datetime] = None

    def __post_init__(self):
        """Auto-calculate message_count."""
        if not self.message_count:
            self.message_count = len(self.messages)


@dataclass
class ClearHistoryResponse:
    """Response from clearing history."""
    session_id: str
    cleared_count: int
    cleared_at: datetime = field(default_factory=datetime.now)


@dataclass
class ReconfigureAssistantResponse:
    """Response from reconfiguring assistant."""
    success: bool
    message: str
    new_config: Dict[str, Any] = field(default_factory=dict)
    reconfigured_at: datetime = field(default_factory=datetime.now)


# ============ ERROR RESPONSE ============

@dataclass
class ErrorResponse:
    """Standard error response."""
    error_code: str
    error_message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    @staticmethod
    def from_exception(exc: Exception, error_code: str = "INTERNAL_ERROR") -> "ErrorResponse":
        """Create error response from exception."""
        return ErrorResponse(
            error_code=error_code,
            error_message=str(exc),
            details={"exception_type": type(exc).__name__}
        )


__all__ = [
    # Requests
    "SessionStartRequest",
    "ChatMessageRequest",
    "SessionEndRequest",
    "HistoryRequest",
    "ClearHistoryRequest",
    "ReconfigureAssistantRequest",
    # Responses
    "SessionStartResponse",
    "ChatMessageResponse",
    "SessionEndResponse",
    "HistoryResponse",
    "ClearHistoryResponse",
    "ReconfigureAssistantResponse",
    # Errors
    "ErrorResponse"
]
