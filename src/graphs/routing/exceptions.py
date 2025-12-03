from src.core.exceptions.chatbot_exception import ChatbotBaseException


class RotuingAgentBaseException(ChatbotBaseException):
    """Base exception for routing agent errors."""
    pass

class VectorStoreNotFoundError(RotuingAgentBaseException):
    """Exception raised when the vectorstore is not found in the routing graph."""

    def __init__(self, message: str = "Vectorstore not found in the routing graph.", **kwargs):
        super().__init__(message, error_code="VECTORSTORE_NOT_FOUND", **kwargs)


class MessageNotFoundError(RotuingAgentBaseException):
    """Exception raised when the message is not found in the routing state."""

    def __init__(self, message: str = "Message not found in the routing state.", **kwargs):
        super().__init__(message, error_code="MESSAGE_NOT_FOUND", **kwargs)


class DocumentRetrievalError(RotuingAgentBaseException):
    """Exception raised during document retrieval from the vectorstore."""

    def __init__(self, message: str = "Error retrieving documents from vectorstore.", **kwargs):
        super().__init__(message, error_code="DOCUMENT_RETRIEVAL_ERROR", **kwargs)