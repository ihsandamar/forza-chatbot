"""
API module - HTTP layer and service layer.

Exports:
- Models: Request/Response models for HTTP layer
- ChatService: Service layer orchestration
"""

from src.api.models import (
    # Requests
    SessionStartRequest,
    ChatMessageRequest,
    SessionEndRequest,
    HistoryRequest,
    ClearHistoryRequest,
    ReconfigureAssistantRequest,
    # Responses
    SessionStartResponse,
    ChatMessageResponse,
    SessionEndResponse,
    HistoryResponse,
    ClearHistoryResponse,
    ReconfigureAssistantResponse,
    # Errors
    ErrorResponse
)
from src.api.chat_service import ChatService

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
    "ErrorResponse",
    # Service
    "ChatService"
]
