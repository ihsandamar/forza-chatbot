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
    InvalidConfigurationException,
    ConfigurationFileException,
    # Message Processing Exceptions
    MessageProcessingException,
    InvalidMessageException,
    MessageValidationException,
    MessageExtractionException,
    # Adapter Exceptions
    AdapterException,
    StateAdaptationException,
    InvalidAdapterException,
    # Graph Execution Exceptions
    GraphExecutionException,
    GraphInvocationException,
    InvalidGraphStateException,
    GraphNodeExecutionException,
    # Builder Exceptions
    BuilderException,
    BuilderValidationException,
    InvalidBuilderStateException,
    # Module Exceptions
    ModuleException,
    ModuleNotFoundException,
    ModuleInitializationException,
    ModuleProcessingException,
    # LLM Exceptions
    LLMException,
    LLMInvocationException,
    InvalidLLMResponseException,
    # Database Exceptions
    DatabaseException,
    DatabaseConnectionException,
    QueryExecutionException,
    # Response Exceptions
    ResponseException,
    ResponseFormattingException,
)

__all__ = [
    # Base exceptions
    "BaseException",
    "create_exception_context",
    # Chatbot base exception
    "ChatbotBaseException",
    # Configuration Exceptions
    "ConfigurationException",
    "InvalidConfigurationException",
    "ConfigurationFileException",
    # Message Processing Exceptions
    "MessageProcessingException",
    "InvalidMessageException",
    "MessageValidationException",
    "MessageExtractionException",
    # Adapter Exceptions
    "AdapterException",
    "StateAdaptationException",
    "InvalidAdapterException",
    # Graph Execution Exceptions
    "GraphExecutionException",
    "GraphInvocationException",
    "InvalidGraphStateException",
    "GraphNodeExecutionException",
    # Builder Exceptions
    "BuilderException",
    "BuilderValidationException",
    "InvalidBuilderStateException",
    # Module Exceptions
    "ModuleException",
    "ModuleNotFoundException",
    "ModuleInitializationException",
    "ModuleProcessingException",
    # LLM Exceptions
    "LLMException",
    "LLMInvocationException",
    "InvalidLLMResponseException",
    # Database Exceptions
    "DatabaseException",
    "DatabaseConnectionException",
    "QueryExecutionException",
    # Response Exceptions
    "ResponseException",
    "ResponseFormattingException",
]
