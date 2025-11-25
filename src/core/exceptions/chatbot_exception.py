"""
Chatbot-specific exception module.

This module defines all chatbot-related exceptions that inherit from ChatbotBaseException.
ChatbotBaseException is the base class for all chatbot-specific errors and inherits from BaseException.

These exceptions are used throughout the chatbot system for:
- Configuration management
- Message processing and validation
- State adaptation
- Graph execution
- Builder operations
- Module management
- LLM operations
- Database operations
- Response formatting

Each exception category handles specific failure scenarios within the chatbot domain.

Exception Hierarchy:
    BaseException
    └── ChatbotBaseException (base for all chatbot errors)
        ├── ConfigurationException
        ├── MessageProcessingException
        ├── AdapterException
        ├── GraphExecutionException
        ├── BuilderException
        ├── ModuleException
        ├── LLMException
        ├── DatabaseException
        └── ResponseException

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

from typing import Optional, Dict, Any, List
from src.core.exceptions import BaseException


# ============================================================================
# Chatbot Base Exception
# ============================================================================

class ChatbotBaseException(BaseException):
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


class InvalidConfigurationException(ConfigurationException):
    """
    Raised when configuration values are invalid or incomplete.

    This is typically raised when:
    - Required keys are missing from config
    - Configuration values don't pass validation
    - Type mismatches occur

    Error Code: INVALID_CONFIG
    """

    def __init__(
        self,
        message: str,
        missing_keys: Optional[List[str]] = None,
        invalid_keys: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if missing_keys:
            full_context["missing_keys"] = missing_keys
        if invalid_keys:
            full_context["invalid_keys"] = invalid_keys

        super().__init__(
            message=message,
            context=full_context,
            **kwargs
        )
        self.error_code = "INVALID_CONFIG"


class ConfigurationFileException(ConfigurationException):
    """
    Raised when configuration file cannot be read or parsed.

    This occurs when:
    - Configuration file not found
    - File is not readable (permissions)
    - File format is invalid (YAML/JSON parsing fails)

    Error Code: CONFIG_FILE_ERROR
    """

    def __init__(
        self,
        file_path: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        full_context["file_path"] = file_path
        full_context["reason"] = reason

        message = f"Configuration file error at {file_path}: {reason}"
        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "CONFIG_FILE_ERROR"


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


class InvalidMessageException(MessageProcessingException):
    """
    Raised when message format or content is invalid.

    Examples:
    - Message is empty or None
    - Message exceeds length limit
    - Message contains invalid characters

    Error Code: INVALID_MESSAGE
    """

    def __init__(
        self,
        message: str,
        message_content: Optional[str] = None,
        validation_errors: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if message_content:
            # Store first 100 chars to avoid logging huge messages
            full_context["message_preview"] = message_content[:100]
        if validation_errors:
            full_context["validation_errors"] = validation_errors

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "INVALID_MESSAGE"


class MessageValidationException(MessageProcessingException):
    """
    Raised when message validation fails.

    This occurs when:
    - Content validation rules are not met
    - Required fields are missing
    - Format validation fails

    Error Code: MESSAGE_VALIDATION_FAILED
    """

    def __init__(
        self,
        message: str,
        errors: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if errors:
            full_context["validation_errors"] = errors

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "MESSAGE_VALIDATION_FAILED"


class MessageExtractionException(MessageProcessingException):
    """
    Raised when message extraction (intent, entities, etc.) fails.

    This occurs when:
    - Intent detection fails
    - Entity extraction fails
    - Context extraction fails

    Error Code: MESSAGE_EXTRACTION_FAILED
    """

    def __init__(
        self,
        message: str,
        extraction_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if extraction_type:
            full_context["extraction_type"] = extraction_type

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "MESSAGE_EXTRACTION_FAILED"


# ============================================================================
# Adapter Exceptions
# ============================================================================

class AdapterException(ChatbotBaseException):
    """
    Raised when there's an error in state adaptation.

    State adapters transform between different message/state formats.
    This includes:
    - State transformation failures
    - Incompatible state formats
    - Adapter initialization failures

    Error Code: ADAPTER_ERROR
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


class StateAdaptationException(AdapterException):
    """
    Raised when state transformation fails.

    This occurs when:
    - Converting from standard format to graph-specific format
    - Converting graph output back to standard format
    - State structure mismatch

    Error Code: STATE_ADAPTATION_FAILED
    """

    def __init__(
        self,
        message: str,
        source_format: Optional[str] = None,
        target_format: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if source_format:
            full_context["source_format"] = source_format
        if target_format:
            full_context["target_format"] = target_format

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "STATE_ADAPTATION_FAILED"


class InvalidAdapterException(AdapterException):
    """
    Raised when adapter is invalid or not properly initialized.

    This occurs when:
    - Adapter class is not properly implemented
    - Required adapter methods are missing
    - Adapter initialization fails

    Error Code: INVALID_ADAPTER
    """

    def __init__(
        self,
        adapter_name: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        full_context["adapter_name"] = adapter_name

        message = f"Invalid adapter '{adapter_name}': {reason}"
        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "INVALID_ADAPTER"


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


# ============================================================================
# Builder Exceptions
# ============================================================================

class BuilderException(ChatbotBaseException):
    """
    Raised when there's an error building chatbot components.

    The builder pattern is used to construct Chatbot instances.
    This includes:
    - Incomplete builder state
    - Invalid build parameters
    - Build validation failures

    Error Code: BUILDER_ERROR
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


class BuilderValidationException(BuilderException):
    """
    Raised when builder validation fails.

    Validation occurs before building to ensure all required components are set.
    This occurs when:
    - LLM is not configured
    - Graph is not selected
    - Required dependencies are missing

    Error Code: BUILDER_VALIDATION_FAILED
    """

    def __init__(
        self,
        message: str,
        missing_components: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if missing_components:
            full_context["missing_components"] = missing_components

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "BUILDER_VALIDATION_FAILED"


class InvalidBuilderStateException(BuilderException):
    """
    Raised when builder is in an invalid state for an operation.

    This occurs when:
    - Attempting to build without setting required components
    - Operation order is incorrect
    - Builder has been reset and reused incorrectly

    Error Code: INVALID_BUILDER_STATE
    """

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if operation:
            full_context["operation"] = operation

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "INVALID_BUILDER_STATE"


# ============================================================================
# Module Exceptions
# ============================================================================

class ModuleException(ChatbotBaseException):
    """
    Raised when there's an error with module operations.

    The chatbot uses modular architecture with specialized modules
    (text2sql, customer service, etc.).
    This includes:
    - Module initialization failures
    - Module not found
    - Module processing failures

    Error Code: MODULE_ERROR
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


class ModuleNotFoundException(ModuleException):
    """
    Raised when a required module is not found.

    This occurs when:
    - Module is requested but not available
    - Module not registered in module registry
    - Module dependency is missing

    Error Code: MODULE_NOT_FOUND
    """

    def __init__(
        self,
        module_name: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        full_context["module_name"] = module_name

        message = f"Module '{module_name}' not found"
        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "MODULE_NOT_FOUND"


class ModuleInitializationException(ModuleException):
    """
    Raised when module initialization fails.

    Each module needs initialization which might involve:
    - LLM setup
    - Database connection
    - External service connection

    Error Code: MODULE_INIT_FAILED
    """

    def __init__(
        self,
        module_name: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        full_context["module_name"] = module_name

        message = f"Failed to initialize module '{module_name}': {reason}"
        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "MODULE_INIT_FAILED"


class ModuleProcessingException(ModuleException):
    """
    Raised when module processing fails.

    Processing occurs when a module handles a user request.
    This occurs when:
    - Module processing logic fails
    - Module produces invalid output
    - Module dependency fails

    Error Code: MODULE_PROCESSING_FAILED
    """

    def __init__(
        self,
        module_name: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        full_context["module_name"] = module_name

        full_message = f"Module '{module_name}' processing error: {message}"
        super().__init__(message=full_message, context=full_context, **kwargs)
        self.error_code = "MODULE_PROCESSING_FAILED"


# ============================================================================
# LLM Exceptions
# ============================================================================

class LLMException(ChatbotBaseException):
    """
    Raised when there's an error with LLM operations.

    The chatbot uses Large Language Models for understanding and generation.
    This includes:
    - LLM invocation failures
    - Invalid LLM response
    - LLM connection/rate limit failures
    - API key errors

    Error Code: LLM_ERROR
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


class LLMInvocationException(LLMException):
    """
    Raised when LLM invocation fails.

    This occurs when:
    - API call to LLM fails
    - LLM service is unavailable
    - Rate limit exceeded
    - Invalid API key

    Error Code: LLM_INVOCATION_FAILED
    """

    def __init__(
        self,
        message: str,
        model_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if model_name:
            full_context["model_name"] = model_name

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "LLM_INVOCATION_FAILED"


class InvalidLLMResponseException(LLMException):
    """
    Raised when LLM response is invalid or unexpected.

    This occurs when:
    - Response format doesn't match expected schema
    - Response is empty or malformed
    - Response content validation fails

    Error Code: INVALID_LLM_RESPONSE
    """

    def __init__(
        self,
        message: str,
        expected_format: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if expected_format:
            full_context["expected_format"] = expected_format

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "INVALID_LLM_RESPONSE"


# ============================================================================
# Database Exceptions
# ============================================================================

class DatabaseException(ChatbotBaseException):
    """
    Raised when there's an error with database operations.

    The chatbot can interact with databases for text2sql and data retrieval.
    This includes:
    - Database connection failures
    - Query execution failures
    - Schema validation failures
    - Transaction failures

    Error Code: DB_ERROR
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


class DatabaseConnectionException(DatabaseException):
    """
    Raised when database connection fails.

    This occurs when:
    - Cannot connect to database
    - Credentials are invalid
    - Database server is unreachable
    - Connection timeout

    Error Code: DB_CONNECTION_FAILED
    """

    def __init__(
        self,
        message: str,
        db_uri: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if db_uri:
            # Mask sensitive parts of URI for security
            try:
                masked_uri = db_uri.split("@")[-1] if "@" in db_uri else "***"
                full_context["db_host"] = masked_uri
            except Exception:
                full_context["db_host"] = "***"

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "DB_CONNECTION_FAILED"


class QueryExecutionException(DatabaseException):
    """
    Raised when database query execution fails.

    This occurs when:
    - SQL syntax error
    - Query references non-existent table/column
    - Permission denied
    - Constraint violation

    Error Code: QUERY_EXECUTION_FAILED
    """

    def __init__(
        self,
        message: str,
        query: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if query:
            # Store first 200 chars of query to avoid logging huge queries
            full_context["query_preview"] = query[:200]

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "QUERY_EXECUTION_FAILED"


# ============================================================================
# Response Exceptions
# ============================================================================

class ResponseException(ChatbotBaseException):
    """
    Raised when there's an error formatting or processing response.

    Responses are formatted based on the interface (Gradio, API, CLI, etc.).
    This includes:
    - Response formatting failures
    - Invalid response type
    - Response serialization failures

    Error Code: RESPONSE_ERROR
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


class ResponseFormattingException(ResponseException):
    """
    Raised when response formatting fails.

    This occurs when:
    - Cannot format response for target interface
    - Response object is invalid
    - Serialization fails (JSON, etc.)

    Error Code: RESPONSE_FORMAT_FAILED
    """

    def __init__(
        self,
        message: str,
        response_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        full_context = context or {}
        if response_type:
            full_context["response_type"] = response_type

        super().__init__(message=message, context=full_context, **kwargs)
        self.error_code = "RESPONSE_FORMAT_FAILED"
