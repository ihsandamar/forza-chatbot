"""
Standard Types Module

Defines unified request/response types used across all interfaces.
This ensures consistency between CLI, Gradio, FastAPI, and other interfaces.

Key Types:
- StandardState: Input format (messages + metadata)
- StandardResponse: Output format (text + type + action)
- ResponseType: Enum for response types
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field


# ========== ENUMS ==========

class ResponseType(str, Enum):
    """Types of responses from the chatbot"""

    TEXT = "text"  # Simple text response
    NAVIGATION = "navigation"  # Navigation/routing response
    TABLE = "table"  # Tabular data response
    FORM = "form"  # Form with fields response
    ERROR = "error"  # Error response
    STRUCTURED = "structured"  # Complex structured response


# ========== REQUEST TYPES ==========

@dataclass
class StandardState:
    """
    Standard state format used across all interfaces.

    All interfaces convert their input to this format before sending to chatbot.

    Example:
        state = StandardState(
            messages=[
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "2+2 equals 4"},
                {"role": "user", "content": "And 3+3?"}
            ],
            metadata={
                "session_id": "abc123",
                "token": "xyz789",
                "source": "gradio"
            }
        )
    """

    messages: List[Dict[str, str]]  # [{"role": "user" | "assistant", "content": "..."}, ...]
    metadata: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None

    @classmethod
    def from_message(
        cls,
        message: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> "StandardState":
        """
        Helper to create StandardState from a single message.

        Args:
            message: User message text
            session_id: Optional session identifier
            metadata: Optional additional metadata

        Returns:
            StandardState instance

        Example:
            state = StandardState.from_message("Hello there!")
        """
        return cls(
            messages=[{"role": "user", "content": message}],
            session_id=session_id,
            metadata=metadata or {}
        )

    def get_user_message(self) -> Optional[str]:
        """
        Get the last user message from the conversation.

        Returns:
            Last user message content, or None if no user messages
        """
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return msg.get("content")
        return None

    def get_last_message(self) -> Optional[Dict[str, str]]:
        """
        Get the very last message (regardless of role).

        Returns:
            Last message dict, or None if messages empty
        """
        return self.messages[-1] if self.messages else None

    def get_conversation_summary(self) -> str:
        """
        Get a summary of the conversation.

        Returns:
            String with role: content format
        """
        lines = []
        for msg in self.messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")[:50]  # First 50 chars
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "messages": self.messages,
            "metadata": self.metadata,
            "session_id": self.session_id
        }

    def to_json(self) -> str:
        """Convert to JSON string"""
        import json
        return json.dumps(self.to_dict(), default=str)

    def __len__(self) -> int:
        """Number of messages in state"""
        return len(self.messages)

    def __bool__(self) -> bool:
        """True if has messages"""
        return bool(self.messages)


# ========== RESPONSE TYPES ==========

@dataclass
class StandardAction:
    """
    Action for the interface to perform after response.

    The interface can use this to trigger additional behavior:
    - Navigation to a URL
    - Submitting a form
    - Filtering a table
    - etc.

    Example:
        action = StandardAction(
            type="routing",
            target="https://example.com/page",
            params={"id": "123"}
        )
    """

    type: str  # "none", "routing", "form_submit", "table_filter", "execute", etc.
    target: Optional[str] = None  # URL, form ID, table name, etc.
    params: Dict[str, Any] = field(default_factory=dict)  # Action parameters

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "type": self.type,
            "target": self.target,
            "params": self.params
        }

    def __bool__(self) -> bool:
        """True if action is non-trivial"""
        return self.type != "none"


@dataclass
class StandardResponse:
    """
    Standard response format from chatbot to all interfaces.

    All interfaces receive this format and convert to their display format.

    Attributes:
        text: Human-readable response text (always present)
        response_type: Type of response (text, navigation, table, form, error, etc.)
        confidence: Confidence score 0.0-1.0
        action: Optional action for interface to perform
        metadata: Additional metadata (intent, entities, debug info, etc.)
        session_id: Session identifier (for tracking)
        timestamp: When response was generated

    Example:
        response = StandardResponse(
            text="Dolaşım Raporu sayfasına yönlendiriyorum...",
            response_type=ResponseType.NAVIGATION,
            confidence=0.92,
            action=StandardAction(
                type="routing",
                target="https://test.vegaforza.com/reports/circulation",
                params={"start_date": "2025-01-01"}
            ),
            metadata={
                "intent": "navigation",
                "page_id": "CIRCULATION_REPORT",
                "parameters": {"start_date": "required", "end_date": "required"}
            }
        )
    """

    text: str  # Required: human-readable text response
    response_type: ResponseType = ResponseType.TEXT
    confidence: float = 0.95  # 0.0 = no confidence, 1.0 = full confidence
    action: StandardAction = field(default_factory=lambda: StandardAction(type="none"))
    metadata: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert response to dictionary for JSON serialization.

        Returns:
            Dictionary with all response fields
        """
        return {
            "text": self.text,
            "type": self.response_type.value,
            "confidence": self.confidence,
            "action": self.action.to_dict(),
            "metadata": self.metadata,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat()
        }

    def to_json(self) -> str:
        """
        Convert response to JSON string.

        Returns:
            JSON-formatted response
        """
        import json
        return json.dumps(self.to_dict(), default=str)

    def __str__(self) -> str:
        """String representation (just the text)"""
        return self.text


# ========== ERROR/VALIDATION TYPES ==========

@dataclass
class ValidationError:
    """
    Validation error details.

    Used when input validation fails.
    """

    field: str  # Field name that failed validation
    message: str  # Error message
    value: Any = None  # The invalid value
    suggestion: Optional[str] = None  # How to fix it

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "field": self.field,
            "message": self.message,
            "value": self.value,
            "suggestion": self.suggestion
        }


@dataclass
class ValidationResult:
    """
    Validation result for a state/message.

    Attributes:
        is_valid: Whether validation passed
        errors: List of validation errors
        warnings: List of warnings (non-blocking)
    """

    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, field: str, message: str, value: Any = None, suggestion: Optional[str] = None):
        """Add a validation error"""
        self.errors.append(ValidationError(field, message, value, suggestion))
        self.is_valid = False

    def add_warning(self, message: str):
        """Add a warning"""
        self.warnings.append(message)

    def __bool__(self) -> bool:
        """True if validation passed"""
        return self.is_valid


# ========== CONFIGURATION TYPES ==========

class AssistantConfigBase(BaseModel):
    """
    Base configuration for assistants.

    Can be extended for specific agent types (SQL, Navigation, etc.)

    Attributes:
        system_prompt: System prompt/instructions for the model
        assistant_name: Display name for the assistant
        model: Optional model name (if different from default)
        temperature: Optional temperature override
        max_tokens: Optional max tokens override
    """

    system_prompt: str = Field(
        default="Sen yardımcı bir asistansın.",
        description="System prompt for the LLM"
    )
    assistant_name: str = Field(
        default="Assistant",
        description="Display name for the assistant"
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional model name override"
    )
    temperature: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Optional temperature override (0.0-2.0)"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        ge=1,
        description="Optional max tokens override"
    )

    class Config:
        """Pydantic configuration"""
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excluding None values)"""
        return self.model_dump(exclude_none=True)

    def update(self, **kwargs) -> "AssistantConfigBase":
        """
        Create updated copy with new values.

        Args:
            **kwargs: Fields to update

        Returns:
            New instance with updated values

        Example:
            new_config = config.update(system_prompt="New prompt", temperature=0.8)
        """
        data = self.to_dict()
        data.update(kwargs)
        return self.__class__(**data)

    def merge(self, other: "AssistantConfigBase") -> "AssistantConfigBase":
        """
        Merge with another config (other takes precedence).

        Args:
            other: Config to merge with

        Returns:
            Merged config
        """
        data = self.to_dict()
        data.update(other.to_dict())
        return self.__class__(**data)


# ========== SESSION TYPES ==========

@dataclass
class SessionInfo:
    """
    Session metadata and information.

    Tracks conversation session state.

    Attributes:
        session_id: Unique session identifier
        created_at: When session was created
        last_interaction: Last interaction timestamp
        message_count: Number of messages in conversation
        assistant_name: Name of assistant
        configuration: Current assistant configuration
    """

    session_id: str
    created_at: datetime
    last_interaction: datetime
    message_count: int
    assistant_name: str
    configuration: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_interaction": self.last_interaction.isoformat(),
            "message_count": self.message_count,
            "assistant_name": self.assistant_name,
            "configuration": self.configuration
        }

    def duration_seconds(self) -> float:
        """Get session duration in seconds"""
        return (self.last_interaction - self.created_at).total_seconds()


__all__ = [
    "ResponseType",
    "StandardState",
    "StandardAction",
    "StandardResponse",
    "ValidationError",
    "ValidationResult",
    "AssistantConfigBase",
    "SessionInfo"
]
