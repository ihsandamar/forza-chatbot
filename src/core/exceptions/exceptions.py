"""
Base exception module for the entire project.

This module defines the base exception class used throughout the entire application.
All custom exceptions across the project should inherit from BaseException to enable
consistent error handling and standardized error response formatting.

Usage:
    try:
        # some operation
        pass
    except BaseException as e:
        # handle any project-related error
        logger.error(f"Error: {e}")
        error_dict = e.to_dict()  # Convert to JSON
"""

from typing import Optional, Dict, Any
from datetime import datetime


class BaseException(Exception):
    """
    Base exception class for the entire project.

    All custom exceptions throughout the application should inherit from this class
    to ensure consistent error handling, logging, and standardized error responses.

    Attributes:
        message: Human-readable error message
        error_code: Machine-readable error code for categorization and routing
        context: Additional context information about the error (session_id, user_id, etc.)
        timestamp: UTC timestamp when the error occurred
    """

    def __init__(
        self,
        message: str,
        error_code: str = "GENERAL_ERROR",
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """
        Initialize BaseException.

        Args:
            message: Descriptive error message
            error_code: Unique error code for categorization and routing
            context: Additional context dictionary (e.g., user_id, session_id, file_path)
            **kwargs: Additional arguments passed to Exception base class
        """
        self.message = message
        self.error_code = error_code
        self.context = context or {}
        self.timestamp = datetime.utcnow()

        # Call parent with just the message
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return formatted error message with error code and context."""
        context_str = ""
        if self.context:
            context_str = f" | Context: {self.context}"
        return f"[{self.error_code}] {self.message}{context_str}"

    def __repr__(self) -> str:
        """Return detailed representation for debugging."""
        return (
            f"{self.__class__.__name__}("
            f"message='{self.message}', "
            f"error_code='{self.error_code}', "
            f"context={self.context})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to dictionary for JSON serialization.

        This method is useful for converting exceptions to API response format
        or for structured logging.

        Returns:
            Dictionary representation of the exception with all relevant information
        """
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "context": self.context,
            "timestamp": self.timestamp.isoformat()
        }


# ============================================================================
# Utility Functions
# ============================================================================

def create_exception_context(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Create a context dictionary for exception initialization.

    This utility function simplifies creating context dictionaries with
    commonly used fields (session_id, user_id, request_id) plus any additional
    custom context information.

    Args:
        session_id: Session identifier
        user_id: User identifier
        request_id: Request/transaction identifier
        **kwargs: Additional context key-value pairs

    Returns:
        Dictionary with context information

    Example:
        context = create_exception_context(
            session_id="xyz123",
            user_id="user456",
            request_id="req789"
        )
        raise SomeException(message="Error details", context=context)
    """
    context = {}
    if session_id:
        context["session_id"] = session_id
    if user_id:
        context["user_id"] = user_id
    if request_id:
        context["request_id"] = request_id
    context.update(kwargs)
    return context
