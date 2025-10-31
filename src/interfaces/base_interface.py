"""
Base Interface Module

Defines the abstract interface that all UI implementations inherit from.
This ensures consistency across CLI, Gradio, FastAPI, Flask, and other interfaces.

Key Concept:
    All interfaces:
    1. Convert their input format to StandardState
    2. Call chatbot.chat(state) -> StandardResponse
    3. Convert StandardResponse to their output format
    4. No interface-specific logic in Chatbot class

Usage:
    class MyCustomInterface(BaseInterface):
        def chat(self, state: StandardState) -> StandardResponse:
            return self.chatbot.chat(state)

        def configure(self, config: dict) -> None:
            self.chatbot.configure(config)

        # ... implement other abstract methods
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime

from src.models.standard_types import StandardState, StandardResponse
from src.services.app_logger import log

if TYPE_CHECKING:
    from src.core.chatbot import Chatbot  # Avoid circular imports


class BaseInterface(ABC):
    """
    Abstract base class for all chatbot interfaces.

    Defines the contract that all interfaces must follow:
    - chat(): Send message and get response
    - configure(): Update assistant configuration at runtime
    - get_history(): Get conversation history
    - clear_history(): Clear conversation
    - run(): Run the interface (blocking)

    Architecture:
        Interface (CLI/Gradio/Web)
            │
            ├─ Input Conversion: Native format → StandardState
            │
            ├─ Call: chatbot.chat(state) → StandardResponse
            │
            └─ Output Conversion: StandardResponse → Native format

    This architecture ensures:
        ✓ All interfaces work the same way
        ✓ No interface-specific logic in Chatbot
        ✓ Easy to add new interfaces
        ✓ Chatbot can be tested without UI
    """

    def __init__(self, chatbot: "Chatbot"):
        """
        Initialize interface with chatbot instance.

        Args:
            chatbot: Fully configured Chatbot instance

        Raises:
            TypeError: If chatbot is None or invalid type
        """
        if chatbot is None:
            raise TypeError("Chatbot instance cannot be None")

        self.chatbot = chatbot
        self.logger = log.get(module=self.__class__.__name__)

        # Get session_id safely (may not exist in all chatbot implementations)
        session_id = getattr(chatbot, 'session_id', None)

        self.logger.debug(
            "Interface initialized",
            interface_type=self.__class__.__name__,
            session_id=session_id
        )

    def _get_session_id(self) -> Optional[str]:
        """
        Get session ID safely.

        Returns chatbot's session_id if available, otherwise None.
        Safe method that doesn't raise AttributeError.

        Returns:
            Session ID or None if not available
        """
        return getattr(self.chatbot, 'session_id', None)

    def _get_config(self) -> Dict[str, Any]:
        """
        Get configuration safely.

        Calls chatbot.get_config() if available, otherwise returns empty dict.
        Safe method that doesn't raise AttributeError.

        Returns:
            Configuration dictionary or empty dict if method unavailable
        """
        if hasattr(self.chatbot, 'get_config') and callable(getattr(self.chatbot, 'get_config')):
            try:
                return self.chatbot.get_config()
            except Exception as e:
                self.logger.warning(f"Error getting config: {str(e)}")
                return {}
        return {}

    def _get_session_info(self) -> Dict[str, Any]:
        """
        Get session info safely.

        Calls chatbot.get_session_info() if available, otherwise returns default dict.
        Safe method that doesn't raise AttributeError.

        Returns:
            Session info dictionary with defaults for missing keys
        """
        if hasattr(self.chatbot, 'get_session_info') and callable(getattr(self.chatbot, 'get_session_info')):
            try:
                return self.chatbot.get_session_info()
            except Exception as e:
                self.logger.warning(f"Error getting session info: {str(e)}")

        # Return default session info
        return {
            "session_id": self._get_session_id(),
            "created_at": datetime.now().isoformat(),
            "message_count": 0,
            "assistant_name": "Assistant",
            "metadata": {}
        }

    def _safe_chat(self, state: StandardState) -> StandardResponse:
        """
        Call chatbot.send() safely (the correct method for unified interface).

        Tries multiple approaches:
        1. Calls chatbot.send(state_dict) if available
        2. Falls back to chatbot.chat(state) if available
        3. Returns error response if both fail

        Args:
            state: StandardState with messages

        Returns:
            StandardResponse with text, type, confidence, etc.
        """
        from src.models.standard_types import ResponseType

        # Try send() method first (correct unified method)
        if hasattr(self.chatbot, 'send') and callable(getattr(self.chatbot, 'send')):
            try:
                # send() expects dict format: {"messages": [...]}
                state_dict = {"messages": state.messages}
                response_text = self.chatbot.send(state_dict)

                return StandardResponse(
                    text=response_text,
                    response_type=ResponseType.TEXT,
                    confidence=0.95,
                    session_id=self._get_session_id()
                )
            except Exception as e:
                self.logger.warning(f"Error calling chatbot.send(): {str(e)}")

        # Try chat() method as fallback
        if hasattr(self.chatbot, 'chat') and callable(getattr(self.chatbot, 'chat')):
            try:
                response = self.chatbot.chat(state)
                if isinstance(response, StandardResponse):
                    return response
                # If returns string, wrap in StandardResponse
                return StandardResponse(
                    text=str(response),
                    response_type=ResponseType.TEXT,
                    confidence=0.95,
                    session_id=self._get_session_id()
                )
            except Exception as e:
                self.logger.warning(f"Error calling chatbot.chat(): {str(e)}")

        # No valid method found - return error
        self.logger.error("Chatbot has no valid chat method (send() or chat())")
        return StandardResponse(
            text="Chatbot is not properly configured",
            response_type=ResponseType.ERROR,
            confidence=0.0,
            session_id=self._get_session_id()
        )

    # ========== ABSTRACT METHODS (must implement) ==========

    @abstractmethod
    def chat(self, state: StandardState) -> StandardResponse:
        """
        Send message and get response.

        This is the core method. Implementations:
        1. Receive input in their native format
        2. Convert to StandardState
        3. Call self.chatbot.chat(state)
        4. Return StandardResponse

        Args:
            state: StandardState with messages and optional metadata

        Returns:
            StandardResponse with text, type, confidence, action, metadata

        Raises:
            ValueError: If state is invalid
            Exception: If chat fails

        Example (CLI):
            def chat(self, user_input: str) -> StandardResponse:
                state = StandardState.from_message(user_input)
                return self.chatbot.chat(state)

        Example (Gradio):
            def chat(self, gradio_history, message) -> list:
                messages = self._convert_from_gradio(gradio_history, message)
                state = StandardState(messages=messages)
                response = self.chatbot.chat(state)
                return self._convert_to_gradio(response)
        """
        pass

    @abstractmethod
    def configure(self, config: Dict[str, Any]) -> None:
        """
        Reconfigure the assistant at runtime.

        Like LangGraph Studio, allows changing configuration without restart:
        - system_prompt
        - model
        - temperature
        - max_tokens
        - Any other assistant-specific settings

        Args:
            config: Dictionary with configuration updates

        Raises:
            ValueError: If configuration is invalid
            TypeError: If configuration type is invalid

        Example:
            interface.configure({
                "system_prompt": "New system prompt",
                "temperature": 0.8,
                "model": "gpt-4-turbo"
            })
        """
        pass

    @abstractmethod
    def get_history(self) -> List[Dict[str, Any]]:
        """
        Get conversation history.

        Returns full conversation from chatbot session.

        Returns:
            List of message dictionaries with:
                - role: "user" or "assistant"
                - content: message text
                - timestamp: when message was sent
                - metadata: optional additional info

        Example:
            history = interface.get_history()
            for msg in history:
                print(f"{msg['role']}: {msg['content']}")
        """
        pass

    @abstractmethod
    def clear_history(self) -> None:
        """
        Clear conversation history.

        Deletes all messages from the current session.
        Session ID remains the same.

        Example:
            interface.clear_history()
            # Conversation fresh starts
        """
        pass

    @abstractmethod
    def run(self) -> None:
        """
        Run the interface (blocking).

        Behavior depends on interface type:
        - CLI: Start input loop (blocking until exit)
        - Gradio: Launch web server (blocking)
        - FastAPI: Start server (blocking)
        - Flask: Start server (blocking)
        - LangGraph Studio: Connect to studio

        Called last, after interface is fully configured.

        Example (CLI):
            def run(self):
                while True:
                    user_input = input("> ")
                    response = self.chat(user_input)
                    print(response.text)

        Example (Gradio):
            def run(self):
                with gr.Blocks() as demo:
                    # Build Gradio UI
                    pass
                demo.launch()

        Example (FastAPI):
            def run(self):
                uvicorn.run(self.app, host="0.0.0.0", port=8000)
        """
        pass

    # ========== OPTIONAL METHODS (can override) ==========

    def get_session_info(self) -> Dict[str, Any]:
        """
        Get session metadata.

        Default implementation calls chatbot.get_session_info().
        Can be overridden for interface-specific info.

        Returns:
            Dictionary with session information
        """
        return self._get_session_info()

    def export_history(self, format: str = "json") -> str:
        """
        Export conversation history in specified format.

        Args:
            format: "json", "markdown", "csv", "pdf"

        Returns:
            Exported history as string

        Default implementation only supports JSON.
        Subclasses can override for other formats.
        """
        import json
        history = self.get_history()
        if format == "json":
            return json.dumps(history, indent=2, default=str)
        else:
            raise NotImplementedError(f"Export format '{format}' not supported")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get interface statistics.

        Returns:
            Dictionary with stats like message count, response times, etc.

        Default implementation provides basic stats.
        Subclasses can enhance with interface-specific stats.
        """
        history = self.get_history()
        session_info = self.get_session_info()

        return {
            "session_id": session_info["session_id"],
            "total_messages": len(history),
            "user_messages": len([m for m in history if m["role"] == "user"]),
            "assistant_messages": len([m for m in history if m["role"] == "assistant"]),
            "duration_seconds": session_info.get("duration", 0),
            "assistant_name": session_info.get("assistant_name", "Unknown")
        }

    # ========== PROTECTED HELPER METHODS ==========

    def _validate_state(self, state: StandardState) -> None:
        """
        Validate state before sending to chatbot.

        Checks:
        - state is StandardState instance
        - messages list is not empty
        - each message has role and content

        Args:
            state: StandardState to validate

        Raises:
            TypeError: If state is wrong type
            ValueError: If state is invalid

        Example:
            def chat(self, state):
                self._validate_state(state)  # Raises if invalid
                return self.chatbot.chat(state)
        """
        if not isinstance(state, StandardState):
            raise TypeError(
                f"Expected StandardState, got {type(state).__name__}. "
                f"Use StandardState or StandardState.from_message()"
            )

        if not state.messages:
            raise ValueError("State must have at least one message")

        for i, msg in enumerate(state.messages):
            if "role" not in msg:
                raise ValueError(f"Message {i} missing 'role' field")
            if "content" not in msg:
                raise ValueError(f"Message {i} missing 'content' field")

            valid_roles = {"user", "assistant", "system", "tool"}
            if msg["role"] not in valid_roles:
                raise ValueError(
                    f"Message {i} has invalid role '{msg['role']}'. "
                    f"Valid roles: {valid_roles}"
                )

    def _format_response(self, response: StandardResponse) -> str:
        """
        Format response for display in interface.

        Default: just return the text.
        Subclasses can override for custom formatting.

        Args:
            response: StandardResponse from chatbot

        Returns:
            Formatted string for display

        Example (CLI with colors):
            def _format_response(self, response):
                if response.response_type == ResponseType.ERROR:
                    return f"[RED]{response.text}[/RED]"
                return response.text
        """
        return response.text

    def _handle_error(self, error: Exception, context: str = "") -> StandardResponse:
        """
        Handle errors and return error response.

        Args:
            error: Exception that occurred
            context: Optional context string

        Returns:
            StandardResponse with error type and message
        """
        self.logger.error(
            f"Error in {context}",
            error=str(error),
            error_type=type(error).__name__,
            session_id=self._get_session_id(),
            exc_info=True
        )

        from src.models.standard_types import ResponseType

        return StandardResponse(
            text=f"An error occurred: {str(error)}",
            response_type=ResponseType.ERROR,
            confidence=0.0,
            session_id=self._get_session_id()
        )

    def _log_interaction(
        self,
        user_input: str,
        response: StandardResponse,
        duration_ms: Optional[float] = None
    ) -> None:
        """
        Log interaction for monitoring/debugging.

        Args:
            user_input: User's message
            response: Chatbot's response
            duration_ms: Optional response time in milliseconds
        """
        self.logger.debug(
            "Interaction logged",
            session_id=self._get_session_id(),
            user_input=user_input[:100],  # First 100 chars
            response_type=response.response_type.value,
            confidence=response.confidence,
            duration_ms=duration_ms
        )

    # ========== CLASS INFORMATION ==========

    def get_interface_info(self) -> Dict[str, Any]:
        """
        Get information about this interface.

        Returns:
            Dictionary with interface metadata
        """
        return {
            "name": self.__class__.__name__,
            "module": self.__class__.__module__,
            "description": self.__class__.__doc__ or "No description",
            "methods": [m for m in dir(self) if not m.startswith("_") and callable(getattr(self, m))],
            "session_id": self._get_session_id(),
            "chatbot_info": {
                "llm_model": str(self.chatbot.llm),
                "graph_type": self.chatbot.graph.__class__.__name__,
                "adapter_type": self.chatbot.adapter.__class__.__name__
            }
        }

    def __str__(self) -> str:
        """String representation"""
        return (
            f"{self.__class__.__name__}("
            f"session={self._get_session_id()}, "
            f"graph={self.chatbot.graph.__class__.__name__})"
        )

    def __repr__(self) -> str:
        """Detailed string representation"""
        return (
            f"<{self.__class__.__module__}.{self.__class__.__name__} "
            f"at {hex(id(self))} "
            f"session_id={self._get_session_id()}>"
        )


__all__ = ["BaseInterface"]
