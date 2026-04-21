"""
Chatbot-specific exception module.

This module defines all chatbot-related exceptions that inherit from ChatbotBaseException.
ChatbotBaseException is the base class for all chatbot-specific errors and inherits from AppBaseException.

These exceptions are used throughout the chatbot system for:
- Configuration management
- Message processing and validation
- Graph execution

Each exception category handles specific failure scenarios within the chatbot domain.

Exception Hierarchy:
    AppBaseException
    └── ChatbotBaseException (base for all chatbot errors)
        ├── ConfigurationException
        ├── MessageProcessingException
        └── GraphExecutionException
            ├── GraphInvocationException
            ├── InvalidGraphStateException
            └── GraphNodeExecutionException

Usage:
    from src.core.exceptions.chatbot_exception import (
        ChatbotBaseException,
        ConfigurationException,
        MessageProcessingException,
        GraphExecutionException
    )

    try:
        process_user_message(message)
    except ChatbotBaseException as e:
        # Catches all chatbot-related errors
        logger.error(f"Chatbot error: {e}")
        return {"error": e.to_dict()}
    except ConfigurationException as e:
        logger.error(f"Config error: {e}")
        return {"error": e.to_dict()}
    except MessageProcessingException as e:
        logger.error(f"Message error: {e}")
        return {"error": e.to_dict()}
"""

from typing import Optional, Dict, Any
from src.core.exceptions import AppBaseException


# ============================================================================
# Chatbot Base Exception
# ============================================================================

class ChatbotBaseException(AppBaseException):
    """
    Base exception for all chatbot-related errors.

    This is the parent exception for all chatbot system errors. All specific
    chatbot exceptions should inherit from this class to allow for unified
    error handling across the chatbot system.

    Example:
        try:
            process_user_message(message)
        except ChatbotBaseException as e:
            logger.error(f"Chatbot error: {e}")
            return {"error": e.to_dict()}
    """

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            context=context,
            **kwargs
        )
        # Set error code after parent init to avoid parameter conflicts
        self.error_code = "CHATBOT_ERROR"


# ============================================================================
# Configuration Exceptions
# ============================================================================

class ConfigurationException(ChatbotBaseException):
    """
    Raised when there's an error in chatbot configuration.

    This includes:
    - Missing required configuration keys
    - Invalid configuration values
    - Configuration file not found or cannot be parsed
    - Type validation failures

    Error Code: CONFIG_ERROR
    """

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            context=context,
            **kwargs
        )
        self.error_code = "CONFIG_ERROR"


# ============================================================================
# Message Processing Exceptions
# ============================================================================

class MessageProcessingException(ChatbotBaseException):
    """
    Raised when there's an error processing user messages.

    This includes:
    - Invalid message format
    - Message validation failures
    - Message extraction failures (intent, entities)
    - Message history corruption

    Error Code: MESSAGE_ERROR
    """

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            context=context,
            **kwargs
        )
        self.error_code = "MESSAGE_ERROR"


# ============================================================================
# Graph Execution Exceptions
# ============================================================================

class GraphExecutionException(ChatbotBaseException):
    """
    Raised when graph execution fails.

    LangGraph is used for orchestrating chatbot workflows.
    This includes:
    - Graph invocation failures
    - Graph node execution failures
    - Invalid graph state

    Error Code: GRAPH_ERROR
    """

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            context=context,
            **kwargs
        )


class GraphInvocationException(GraphExecutionException):
    """
    Raised when graph invocation fails.

    This occurs when:
    - Graph.invoke() call fails
    - Graph state is incompatible
    - Graph configuration is invalid

    Error Code: GRAPH_INVOCATION_FAILED
    """

    def __init__(
        self,
        message: str,
        graph_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if graph_name:
            full_context["graph_name"] = graph_name

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "GRAPH_INVOCATION_FAILED"


class InvalidGraphStateException(GraphExecutionException):
    """
    Raised when graph state is invalid.

    This occurs when:
    - State schema validation fails
    - Required state fields are missing
    - State type mismatch

    Error Code: INVALID_GRAPH_STATE
    """

    def __init__(
        self,
        message: str,
        state_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if state_type:
            full_context["state_type"] = state_type

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "INVALID_GRAPH_STATE"


class GraphNodeExecutionException(GraphExecutionException):
    """
    Raised when a graph node execution fails.

    Graph nodes are processing units within the graph.
    This occurs when:
    - Node function raises exception
    - Node returns invalid output
    - Node timeout occurs

    Error Code: GRAPH_NODE_FAILED
    """

    def __init__(
        self,
        message: str,
        node_name: Optional[str] = None,
        node_error: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if node_name:
            full_context["node_name"] = node_name
        if node_error:
            full_context["node_error"] = node_error

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "GRAPH_NODE_FAILED"
