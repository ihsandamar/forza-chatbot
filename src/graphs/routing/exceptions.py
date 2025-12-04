"""
Forza Routing Graph Exception Definitions.

Custom exceptions for the Forza navigation and routing graph.
Provides structured error handling with error codes for better logging and debugging.
"""

from src.core.exceptions.chatbot_exception import ChatbotBaseException


class ForzaRoutingBaseException(ChatbotBaseException):
    """Base exception for Forza routing graph errors."""
    pass


class VectorStoreNotFoundError(ForzaRoutingBaseException):
    """Exception raised when vectorstore is not available."""

    def __init__(self, message: str = "Vectorstore not found in Forza routing graph.", **kwargs):
        super().__init__(message, error_code="FORZA_VECTORSTORE_NOT_FOUND", **kwargs)


class UserInputExtractionError(ForzaRoutingBaseException):
    """Exception raised when user input cannot be extracted from messages."""

    def __init__(self, message: str = "Failed to extract user input from messages.", **kwargs):
        super().__init__(message, error_code="FORZA_USER_INPUT_EXTRACTION_ERROR", **kwargs)


class DocumentRetrievalError(ForzaRoutingBaseException):
    """Exception raised during document retrieval from vectorstore."""

    def __init__(self, message: str = "Error retrieving documents from vectorstore.", **kwargs):
        super().__init__(message, error_code="FORZA_DOCUMENT_RETRIEVAL_ERROR", **kwargs)


class DocumentSelectionError(ForzaRoutingBaseException):
    """Exception raised when no documents are available for selection."""

    def __init__(self, message: str = "No documents available for selection.", **kwargs):
        super().__init__(message, error_code="FORZA_DOCUMENT_SELECTION_ERROR", **kwargs)


class ParameterDetectionError(ForzaRoutingBaseException):
    """Exception raised when parameter detection fails."""

    def __init__(self, message: str = "Failed to detect page parameters.", **kwargs):
        super().__init__(message, error_code="FORZA_PARAMETER_DETECTION_ERROR", **kwargs)


class ParameterExtractionError(ForzaRoutingBaseException):
    """Exception raised when parameter extraction fails."""

    def __init__(self, message: str = "Failed to extract page parameters.", **kwargs):
        super().__init__(message, error_code="FORZA_PARAMETER_EXTRACTION_ERROR", **kwargs)


class ToolExecutionError(ForzaRoutingBaseException):
    """Exception raised when tool execution fails."""

    def __init__(self, message: str = "Error executing tools for parameter filling.", **kwargs):
        super().__init__(message, error_code="FORZA_TOOL_EXECUTION_ERROR", **kwargs)


class URLUpdateError(ForzaRoutingBaseException):
    """Exception raised when URL update with parameters fails."""

    def __init__(self, message: str = "Failed to update URL with parameters.", **kwargs):
        super().__init__(message, error_code="FORZA_URL_UPDATE_ERROR", **kwargs)


class OutputFormattingError(ForzaRoutingBaseException):
    """Exception raised when output formatting fails."""

    def __init__(self, message: str = "Failed to format navigation output.", **kwargs):
        super().__init__(message, error_code="FORZA_OUTPUT_FORMATTING_ERROR", **kwargs)


class AlternativePageSearchError(ForzaRoutingBaseException):
    """Exception raised when alternative page search fails."""

    def __init__(self, message: str = "Failed to search for alternative pages.", **kwargs):
        super().__init__(message, error_code="FORZA_ALTERNATIVE_PAGE_SEARCH_ERROR", **kwargs)


class InvalidStateError(ForzaRoutingBaseException):
    """Exception raised when state is invalid or missing required fields."""

    def __init__(self, message: str = "Invalid or incomplete state.", **kwargs):
        super().__init__(message, error_code="FORZA_INVALID_STATE_ERROR", **kwargs)
