"""
Domain Models for Forza Chatbot

Core data structures that represent business concepts:
- Message: Single message in conversation
- Session: Chat session (user + metadata)
- Conversation: Collection of messages
- AssistantConfig: Assistant behavior configuration
- ChatbotConfig: System-wide configuration
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any


@dataclass
class Message:
    """Represents a single message in a conversation."""
    role: str           # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, str]:
        """Convert to LangChain-compatible format."""
        return {
            "role": self.role,
            "content": self.content
        }

    def validate(self) -> Optional[str]:
        """Validate message."""
        if self.role not in ["user", "assistant", "system", "tool"]:
            return f"Invalid role: {self.role}"
        if not self.content.strip():
            return "Message content cannot be empty"
        return None


@dataclass
class Session:
    """Represents a chat session."""
    session_id: str
    user_id: Optional[str]
    created_at: datetime = field(default_factory=datetime.now)
    last_interaction: datetime = field(default_factory=datetime.now)
    token: Optional[str] = None
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        """Session duration in seconds."""
        return (self.last_interaction - self.created_at).total_seconds()

    @property
    def is_expired(self) -> bool:
        """Check if session expired (default: 1 hour)."""
        return self.duration_seconds > 3600

    def update_interaction(self) -> None:
        """Update last interaction timestamp."""
        self.last_interaction = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "last_interaction": self.last_interaction.isoformat(),
            "duration_seconds": self.duration_seconds,
            "token": self.token,
            "config_snapshot": self.config_snapshot,
            "metadata": self.metadata
        }


@dataclass
class Conversation:
    """Represents a conversation with multiple messages."""
    session_id: str
    messages: List[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def add_message(self, role: str, content: str,
                    metadata: Dict[str, Any] = None) -> Message:
        """Add message to conversation."""
        error = Message(role, content).validate()
        if error:
            raise ValueError(error)

        msg = Message(
            role=role,
            content=content,
            timestamp=datetime.now(),
            metadata=metadata or {}
        )
        self.messages.append(msg)
        return msg

    def get_messages(self) -> List[Dict[str, str]]:
        """Get messages in LangChain format for graph."""
        return [msg.to_dict() for msg in self.messages]

    def get_all_messages(self) -> List[Message]:
        """Get all Message objects."""
        return self.messages.copy()

    def get_message_count(self) -> int:
        """Get total message count."""
        return len(self.messages)

    def clear(self) -> None:
        """Clear all messages."""
        self.messages.clear()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize conversation."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "message_count": self.get_message_count(),
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "metadata": msg.metadata
                }
                for msg in self.messages
            ]
        }

    def __len__(self) -> int:
        """Get message count."""
        return len(self.messages)


@dataclass
class AssistantConfig:
    """Assistant behavior configuration."""
    system_prompt: str
    assistant_name: str
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    def validate(self) -> Optional[str]:
        """Validate assistant config."""
        if not self.system_prompt.strip():
            return "system_prompt cannot be empty"
        if not self.assistant_name.strip():
            return "assistant_name cannot be empty"
        if self.temperature is not None:
            if not (0.0 <= self.temperature <= 2.0):
                return "temperature must be between 0.0 and 2.0"
        if self.max_tokens is not None:
            if self.max_tokens < 1:
                return "max_tokens must be positive"
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    def update(self, **kwargs) -> "AssistantConfig":
        """Create updated copy."""
        data = self.to_dict()
        data.update(kwargs)
        return AssistantConfig(**data)


@dataclass
class ChatbotConfig:
    """System-wide configuration."""
    # LLM (required)
    llm_provider: str
    llm_model: str
    llm_temperature: float
    graph_name: str

    # LLM (optional)
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None

    # Graph (optional)
    graph_config: Dict[str, Any] = field(default_factory=dict)

    # Assistant (with defaults)
    system_prompt: str = "You are a helpful assistant."
    assistant_name: str = "Assistant"

    # Runtime (with defaults)
    session_timeout: int = 3600  # 1 hour
    max_conversation_length: int = 100
    debug_mode: bool = False
    enable_logging: bool = True

    def validate(self) -> List[str]:
        """Validate entire configuration."""
        errors = []

        # LLM validation
        if self.llm_provider not in ["openai", "anthropic", "ollama", "azure"]:
            errors.append(f"Unknown LLM provider: {self.llm_provider}")

        if not (0.0 <= self.llm_temperature <= 2.0):
            errors.append("llm_temperature must be between 0.0 and 2.0")

        # Graph validation
        if not self.graph_name.strip():
            errors.append("graph_name cannot be empty")

        # Assistant validation
        if not self.system_prompt.strip():
            errors.append("system_prompt cannot be empty")
        if not self.assistant_name.strip():
            errors.append("assistant_name cannot be empty")

        # Runtime validation
        if self.session_timeout < 60:
            errors.append("session_timeout must be at least 60 seconds")

        if self.max_conversation_length < 1:
            errors.append("max_conversation_length must be positive")

        return errors

    def is_valid(self) -> bool:
        """Check if configuration is valid."""
        return len(self.validate()) == 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "ChatbotConfig":
        """Create from dictionary."""
        return cls(**config_dict)


__all__ = [
    "Message",
    "Session",
    "Conversation",
    "AssistantConfig",
    "ChatbotConfig"
]
