"""
FastAPI Interface - Phase 2.2 Implementation

A production-ready REST API interface built with FastAPI.
Supports real-time chat, runtime configuration, and comprehensive error handling.

Features:
  - REST API endpoints for chat, configuration, history
  - OpenAPI/Swagger documentation
  - Request/response validation with Pydantic
  - Background tasks and streaming support
  - CORS configuration for multi-origin access
  - Comprehensive error handling with standard HTTP status codes
  - Request logging and tracing
  - Health check endpoints
  - Rate limiting ready (can be added with middleware)
  - Session management
"""

from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, status, BackgroundTasks, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from datetime import datetime
import logging
import json

from src.interfaces.base_interface import BaseInterface
from src.models.standard_types import StandardState, StandardResponse, ResponseType


# ========== REQUEST/RESPONSE MODELS ==========

class ChatRequest(BaseModel):
    """Chat request model"""
    message: str = Field(..., min_length=1, max_length=10000, description="User message")
    session_id: Optional[str] = Field(None, description="Optional session ID")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        schema_extra = {
            "example": {
                "message": "Hello, how can you help?",
                "session_id": "user-123",
                "metadata": {"source": "mobile"}
            }
        }


class ConfigureRequest(BaseModel):
    """Configuration update request"""
    system_prompt: Optional[str] = Field(None, description="System prompt")
    temperature: Optional[float] = Field(None, ge=0, le=2, description="Temperature (0-2)")
    assistant_name: Optional[str] = Field(None, description="Assistant name")
    model: Optional[str] = Field(None, description="Model name")
    max_tokens: Optional[int] = Field(None, ge=1, description="Max tokens")

    class Config:
        schema_extra = {
            "example": {
                "system_prompt": "You are a helpful assistant.",
                "temperature": 0.7,
                "assistant_name": "Forza Assistant"
            }
        }


class ChatResponse(BaseModel):
    """Chat response model"""
    text: str
    response_type: str
    confidence: float = Field(ge=0, le=1)
    session_id: Optional[str]
    timestamp: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        schema_extra = {
            "example": {
                "text": "I'd be happy to help!",
                "response_type": "text",
                "confidence": 0.95,
                "session_id": "user-123",
                "timestamp": "2025-10-31T10:30:00",
                "metadata": {}
            }
        }


class ErrorResponse(BaseModel):
    """Error response model"""
    error: str
    detail: str
    timestamp: str
    request_id: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "error": "Invalid request",
                "detail": "Message cannot be empty",
                "timestamp": "2025-10-31T10:30:00"
            }
        }


class HealthResponse(BaseModel):
    """Health check response"""
    status: str = "healthy"
    service: str = "Forza Chatbot API"
    version: str = "2.0"
    timestamp: str


class SessionResponse(BaseModel):
    """Session information response"""
    session_id: str
    created_at: str
    message_count: int
    assistant_name: str
    metadata: Dict[str, Any]


class HistoryResponse(BaseModel):
    """Conversation history response"""
    session_id: str
    messages: List[Dict[str, Any]]
    message_count: int


# ========== FASTAPI INTERFACE CLASS ==========

class FastAPIInterface(BaseInterface):
    """
    FastAPI-based REST API for the chatbot.

    Provides a production-ready API with:
    - Chat endpoints
    - Configuration management
    - History management
    - Session tracking
    - Health checks
    - Comprehensive error handling

    Architecture:
        HTTP Request → FastAPI → StandardState → Chatbot → StandardResponse → HTTP Response
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
            title: API title for OpenAPI docs
            version: API version
            description: API description
            docs_url: URL for Swagger UI
            openapi_url: URL for OpenAPI schema
            cors_origins: List of allowed CORS origins

        Raises:
            TypeError: If chatbot is invalid
        """
        super().__init__(chatbot)

        self.title = title
        self.version = version
        self.description = description

        # Create FastAPI app
        self.app = FastAPI(
            title=title,
            version=version,
            description=description,
            docs_url=docs_url,
            openapi_url=openapi_url,
        )

        # Configure CORS
        if cors_origins is None:
            cors_origins = ["*"]  # Allow all origins (configure as needed)

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Register routes
        self._register_routes()

        self.logger.info(
            "FastAPIInterface initialized",
            title=title,
            version=version,
            cors_origins=cors_origins,
        )

    # ========== ABSTRACT METHODS (implements BaseInterface) ==========

    def chat(self, state: StandardState) -> StandardResponse:
        """
        Process chat message via chatbot.

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

        Args:
            host: Server host
            port: Server port
            reload: Whether to reload on code changes
        """
        import uvicorn

        self.logger.info(f"Starting FastAPI server on {host}:{port}")
        uvicorn.run(self.app, host=host, port=port, reload=reload)

    # ========== ROUTE REGISTRATION ==========

    def _register_routes(self) -> None:
        """Register all FastAPI routes."""

        # Health check
        @self.app.get("/health", response_model=HealthResponse, tags=["Health"])
        async def health_check():
            """Check API health status."""
            return HealthResponse(timestamp=datetime.now().isoformat())

        # Chat endpoint
        @self.app.post("/chat", response_model=ChatResponse, tags=["Chat"])
        async def chat_endpoint(request: ChatRequest):
            """
            Send a message and get a response.

            **Request:**
            - `message`: The user message
            - `session_id`: Optional session ID
            - `metadata`: Optional metadata

            **Response:**
            - `text`: The assistant's response
            - `response_type`: Type of response (text, navigation, table, form, error)
            - `confidence`: Confidence score (0-1)
            """
            try:
                # Convert request to StandardState
                messages = [{"role": "user", "content": request.message}]
                state = StandardState(
                    messages=messages,
                    session_id=self._get_session_id() or request.session_id,
                    metadata=request.metadata,
                )

                # Get response from chatbot
                response = self.chat(state)

                # Log interaction
                self._log_interaction(request.message, response)

                # Convert to API response
                return ChatResponse(
                    text=response.text,
                    response_type=response.response_type.value,
                    confidence=response.confidence,
                    session_id=response.session_id,
                    timestamp=response.timestamp.isoformat(),
                    metadata=response.metadata,
                )

            except ValueError as e:
                self.logger.error(f"Validation error: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
            except Exception as e:
                self.logger.error(f"Chat error: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Internal server error",
                )

        # Configuration endpoint
        @self.app.post("/configure", tags=["Configuration"])
        async def configure_endpoint(request: ConfigureRequest):
            """
            Update assistant configuration at runtime.

            **Parameters:**
            - `system_prompt`: System prompt for the assistant
            - `temperature`: Response temperature (0-2)
            - `assistant_name`: Name of the assistant
            - `model`: Model name to use
            - `max_tokens`: Maximum response tokens
            """
            try:
                # Build config dict (only include non-None values)
                config = {
                    k: v for k, v in request.dict().items() if v is not None
                }

                if not config:
                    raise ValueError("At least one configuration parameter required")

                self.configure(config)

                return {
                    "status": "success",
                    "message": "Configuration updated",
                    "timestamp": datetime.now().isoformat(),
                }

            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
            except Exception as e:
                self.logger.error(f"Configuration error: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update configuration",
                )

        # Get configuration
        @self.app.get("/config", tags=["Configuration"])
        async def get_config():
            """Get current assistant configuration."""
            try:
                config = self.chatbot.get_config()
                return {
                    "status": "success",
                    "config": config,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                self.logger.error(f"Error getting config: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to get configuration",
                )

        # Get history
        @self.app.get(
            "/history", response_model=HistoryResponse, tags=["History"]
        )
        async def get_history_endpoint():
            """Get conversation history."""
            try:
                history = self.get_history()
                session_info = self._get_session_info()

                return HistoryResponse(
                    session_id=session_info["session_id"],
                    messages=history,
                    message_count=len(history),
                )

            except Exception as e:
                self.logger.error(f"Error getting history: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to get history",
                )

        # Clear history
        @self.app.delete("/history", tags=["History"])
        async def clear_history_endpoint():
            """Clear conversation history."""
            try:
                self.clear_history()
                return {
                    "status": "success",
                    "message": "History cleared",
                    "timestamp": datetime.now().isoformat(),
                }

            except Exception as e:
                self.logger.error(f"Error clearing history: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to clear history",
                )

        # Get session info
        @self.app.get(
            "/session", response_model=SessionResponse, tags=["Session"]
        )
        async def get_session_endpoint():
            """Get current session information."""
            try:
                info = self._get_session_info()
                return SessionResponse(
                    session_id=info["session_id"],
                    created_at=info.get("created_at", datetime.now().isoformat()),
                    message_count=info.get("message_count", 0),
                    assistant_name=info.get("assistant_name", "Assistant"),
                    metadata=info.get("metadata", {}),
                )

            except Exception as e:
                self.logger.error(f"Error getting session: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to get session info",
                )

        # Get stats
        @self.app.get("/stats", tags=["Stats"])
        async def get_stats_endpoint():
            """Get conversation statistics."""
            try:
                stats = self.get_stats()
                return {
                    "status": "success",
                    "stats": stats,
                    "timestamp": datetime.now().isoformat(),
                }

            except Exception as e:
                self.logger.error(f"Error getting stats: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to get statistics",
                )

        # Export history
        @self.app.get("/export", tags=["Export"])
        async def export_history_endpoint(format: str = "json"):
            """
            Export conversation history in specified format.

            **Parameters:**
            - `format`: Export format (json, csv - currently only json supported)
            """
            try:
                if format != "json":
                    raise ValueError(f"Format '{format}' not supported")

                exported = self.export_history(format="json")

                return {
                    "status": "success",
                    "format": format,
                    "data": json.loads(exported),
                    "timestamp": datetime.now().isoformat(),
                }

            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
            except Exception as e:
                self.logger.error(f"Error exporting history: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to export history",
                )

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


__all__ = ["FastAPIInterface", "ChatRequest", "ChatResponse", "ConfigureRequest"]
