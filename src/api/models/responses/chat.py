from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any, List


class SessionStartResponse(BaseModel):
    """Response model for session start"""
    success: bool = True
    session_id: str = Field(..., description="Unique session identifier")
    user_id: Optional[str] = Field(None, description="User identifier if provided")
    created_at: datetime = Field(default_factory=datetime.now, description="Session creation timestamp")


class ActionResponse(BaseModel):
    """Response model for action metadata"""
    type: str = Field(default="routing", description="Action type")
    target: str = Field(default="", description="Action target")
    params: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")


class ResponseData(BaseModel):
    """Response model for chat response data"""
    text: str = Field(..., description="Bot response text")
    type: str = Field(default="text", description="Response type")
    confidence: float = Field(default=0.95, description="Confidence score")
    action: ActionResponse = Field(default_factory=ActionResponse, description="Action metadata")


class ChatMessageResponse(BaseModel):
    """Response model for chat message"""
    success: bool = True
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp")
    session_id: str = Field(..., description="Session identifier")
    response: ResponseData = Field(..., description="Bot response data")

    @property
    def text(self) -> str:
        """Convenience property to access response text"""
        return self.response.text


class MessageHistoryItem(BaseModel):
    """Individual message in history"""
    role: str = Field(..., description="Message role (user or assistant)")
    content: str = Field(..., description="Message content")


class SessionHistoryResponse(BaseModel):
    """Response model for session history"""
    success: bool = True
    session_id: str = Field(..., description="Session identifier")
    user_id: Optional[str] = Field(None, description="User identifier if provided")
    created_at: datetime = Field(..., description="Session creation timestamp")
    message_count: int = Field(..., description="Total number of messages")
    messages: List[MessageHistoryItem] = Field(..., description="List of messages in the session")
