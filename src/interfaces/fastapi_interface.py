"""
FastAPI Interface - Phase 2.2 Implementation

A production-ready REST API interface built with FastAPI.
Wraps the existing src/api/main.py application.

Features:
  - Uses existing well-designed API from src/api/main.py
  - REST API endpoints for chat, configuration, history
  - OpenAPI/Swagger documentation
  - Request/response validation with Pydantic
  - CORS configuration for multi-origin access
  - Comprehensive error handling with standard HTTP status codes
  - Health check endpoints
  - Session management with ChatService
  - Integrates with BaseInterface for compatibility
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from src.core.chatbot import Chatbot
from src.interfaces.base_interface import BaseInterface
from src.models.standard_types import StandardState, StandardResponse, ResponseType
from src.api.main import app as api_app


class FastAPIInterface(BaseInterface):
    """
    FastAPI-based REST API for the chatbot.

    Wraps the existing API application from src/api/main.py while providing
    BaseInterface compatibility.

    Provides:
    - Chat endpoints via ChatService
    - Configuration management
    - History management
    - Session tracking
    - Health checks
    - Comprehensive error handling

    Architecture:
        HTTP Request → API Router → ChatService → Chatbot → Response
    """

    def __init__(
        self,
        chatbot: "Chatbot",
        title: str = "Forza Chatbot API",
        version: str = "2.0",
        description: str = "Multi-agent AI Assistant REST API",
        docs_url: str = "/docs",
        openapi_url: str = "/openapi.json",
        cors_origins: Optional[List[str]] = None,
    ):
        """
        Initialize FastAPI interface.

        Args:
            chatbot: Configured Chatbot instance
            title: API title for OpenAPI docs (informational)
            version: API version (informational)
            description: API description (informational)
            docs_url: URL for Swagger UI (informational)
            openapi_url: URL for OpenAPI schema (informational)
            cors_origins: List of allowed CORS origins (not used - API already configured)

        Raises:
            TypeError: If chatbot is invalid

        Note:
            This interface uses the existing FastAPI app from src/api/main.py.
            CORS and middleware are already configured in that app.
            The chatbot instance passed is used by the API through dependency injection.
        """
        super().__init__(chatbot)

        self.title = title
        self.version = version
        self.description = description

        # Use the existing FastAPI app from src/api/main.py
        self.app = api_app

        # Set the chatbot instance in the dependencies so the API uses the same instance
        self._set_api_chatbot_instance(chatbot)

        self.logger.info(
            "FastAPIInterface initialized (using src/api/main.py)",
            title=title,
            version=version,
            note="Uses existing API application with ChatService",
        )

    def _set_api_chatbot_instance(self, chatbot: "Chatbot") -> None:
        """
        Set the chatbot instance in the API dependencies.

        This ensures the existing FastAPI app uses the same chatbot instance
        that was passed to this interface.

        Args:
            chatbot: The Chatbot instance to use
        """
        try:
            from src.api import dependencies
            # Set the global singleton to use our chatbot instance
            dependencies._chatbot_instance = chatbot
            # Also reset chat service to use the new chatbot
            dependencies._chat_service_instance = None
            self.logger.debug("Set chatbot instance in API dependencies")
        except Exception as e:
            self.logger.warning(
                f"Could not set chatbot in API dependencies: {str(e)}. "
                "API will create its own chatbot instance."
            )

    # ========== ABSTRACT METHODS (implements BaseInterface) ==========

    def chat(self, state: StandardState) -> StandardResponse:
        """
        Process chat message via chatbot.

        Note: The actual API endpoints use ChatService directly from src/api.
        This method is for BaseInterface compatibility.

        Args:
            state: StandardState with messages

        Returns:
            StandardResponse with text and metadata
        """
        try:
            self._validate_state(state)
            return self._safe_chat(state)
        except Exception as e:
            self.logger.error(f"Chat error: {str(e)}")
            return self._handle_error(e, context="chat")

    def configure(self, config: Dict[str, Any]) -> None:
        """
        Reconfigure assistant at runtime.

        Args:
            config: Configuration dict with updates
        """
        try:
            self.chatbot.configure(config)
            self.logger.info("Configuration updated via FastAPI", config=config)
        except Exception as e:
            self.logger.error(f"Configuration error: {str(e)}")
            raise

    def get_history(self) -> List[Dict[str, Any]]:
        """Get conversation history."""
        return self.chatbot.get_history()

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.chatbot.clear_history()
        self.logger.info("History cleared via FastAPI")

    def run(self, host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
        """
        Launch FastAPI server.

        Starts the existing FastAPI app from src/api/main.py using uvicorn.

        Args:
            host: Server host
            port: Server port
            reload: Whether to reload on code changes
        """
        import uvicorn

        self.logger.info(f"Starting FastAPI server on {host}:{port}")
        self.logger.info("Using existing API from src/api/main.py with ChatService")
        uvicorn.run(self.app, host=host, port=port, reload=reload)

    # ========== STRING REPRESENTATIONS ==========

    def __str__(self) -> str:
        """String representation."""
        return (
            f"FastAPIInterface(title={self.title}, version={self.version}, "
            f"session={self._get_session_id()})"
        )

    def __repr__(self) -> str:
        """Detailed representation."""
        return (
            f"<FastAPIInterface {self._get_session_id()} at {hex(id(self))}>"
        )


__all__ = ["FastAPIInterface"]
