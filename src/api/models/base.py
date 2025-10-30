from pydantic import BaseModel
from typing import Optional


class BaseResponse(BaseModel):
    """Base response model for all API responses"""
    success: bool = True
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response model"""
    success: bool = False
    error: str
    details: Optional[str] = None
