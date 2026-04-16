"""
Exceptions module for the chatbot application.

This module exports all exception classes for easy importing.

Usage:
    from src.core.exceptions import (
        BaseException,
        ChatbotBaseException,
        ConfigurationException,
        MessageProcessingException,
    )
"""

from src.core.exceptions.exceptions import BaseException, create_exception_context
from src.core.exceptions.chatbot_exception import (
    ChatbotBaseException,
    # Configuration Exceptions
    ConfigurationException,
    # Message Processing Exceptions
    MessageProcessingException,
    # Graph Execution Exceptions
    GraphExecutionException,
    GraphInvocationException,
    InvalidGraphStateException,
    GraphNodeExecutionException,
)

__all__ = [
    # Base exceptions
    "BaseException",
    "create_exception_context",
    # Chatbot base exception
    "ChatbotBaseException",
    # Configuration Exceptions
    "ConfigurationException",
    # Message Processing Exceptions
    "MessageProcessingException",
    # Graph Execution Exceptions
    "GraphExecutionException",
    "GraphInvocationException",
    "InvalidGraphStateException",
    "GraphNodeExecutionException",
]
