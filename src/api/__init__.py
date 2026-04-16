"""
API module - HTTP layer and service layer.

Exports:
- Models: Request/Response models for HTTP layer
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
]
