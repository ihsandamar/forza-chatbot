"""
Core module - Domain models and business logic.

Exports:
- Models: Session, Conversation, Message, etc.
- Config: ChatbotConfig, AssistantConfig
- Managers: SessionManager, ConversationManager, AssistantManager
- Chatbot: Core chatbot class
"""

from src.core.models import (
    Message,
    Session,
    Conversation,
    AssistantConfig,
    ChatbotConfig
)
from src.core.config import Config
from src.core.session_manager import SessionManager
from src.core.conversation import ConversationManager
from src.core.assistant_manager import AssistantManager
from src.core.chatbot import Chatbot

__all__ = [
    # Models
    "Message",
    "Session",
    "Conversation",
    "AssistantConfig",
    "ChatbotConfig",
    # Config
    "Config",
    # Managers
    "SessionManager",
    "ConversationManager",
    "AssistantManager",
    # Chatbot
    "Chatbot"
]
