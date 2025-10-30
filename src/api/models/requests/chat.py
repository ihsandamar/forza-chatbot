from pydantic import BaseModel, Field
from typing import Optional


class SessionStartRequest(BaseModel):
    """Request model for starting a new chat session"""
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    token: Optional[str] = Field(None, description="Authentication token for graph operations")


class ChatMessageRequest(BaseModel):
    """Request model for sending a chat message"""
    session_id: str = Field(..., description="Session identifier")
    message: str = Field(..., description="User message text", min_length=1)
