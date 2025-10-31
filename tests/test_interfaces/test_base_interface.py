"""
Tests for BaseInterface

Tests the abstract interface that all UIs inherit from.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.interfaces.base_interface import BaseInterface
from src.models.standard_types import (
    StandardState, StandardResponse, ResponseType, StandardAction
)


# ========== Test Implementation ==========

class ConcreteInterface(BaseInterface):
    """Concrete implementation for testing"""

    def chat(self, state: StandardState) -> StandardResponse:
        """Simple implementation"""
        return self.chatbot.chat(state)

    def configure(self, config: dict) -> None:
        """Simple implementation"""
        self.chatbot.configure(config)

    def get_history(self):
        """Simple implementation"""
        return self.chatbot.get_history()

    def clear_history(self) -> None:
        """Simple implementation"""
        self.chatbot.clear_history()

    def run(self) -> None:
        """Simple implementation"""
        pass


# ========== Initialization Tests ==========

class TestBaseInterfaceInitialization:
    """Tests for BaseInterface initialization"""

    @pytest.mark.unit
    def test_initialization_with_valid_chatbot(self, mock_chatbot):
        """Test initializing with valid chatbot"""
        interface = ConcreteInterface(mock_chatbot)

        assert interface.chatbot == mock_chatbot
        assert interface.logger is not None

    @pytest.mark.unit
    def test_initialization_with_none_chatbot(self):
        """Test that None chatbot raises error"""
        with pytest.raises(TypeError, match="Chatbot instance cannot be None"):
            ConcreteInterface(None)

    @pytest.mark.unit
    def test_initialization_logging(self, mock_chatbot):
        """Test that initialization logs correctly"""
        interface = ConcreteInterface(mock_chatbot)

        # Verify logger is set (it's an instance attribute)
        assert interface.logger is not None
        assert hasattr(interface, 'logger')


# ========== Abstract Method Tests ==========

class TestAbstractMethods:
    """Tests for abstract methods"""

    @pytest.mark.unit
    def test_cannot_instantiate_abstract_class(self):
        """Test that BaseInterface cannot be instantiated directly"""
        # BaseInterface has 5 abstract methods, so it can't be instantiated
        with pytest.raises(TypeError):
            BaseInterface(Mock())

    @pytest.mark.unit
    def test_concrete_implementation_required(self):
        """Test that all abstract methods must be implemented"""

        class IncompleteInterface(BaseInterface):
            # Only implement some methods
            def chat(self, state):
                pass

            def configure(self, config):
                pass

        # Still can't instantiate - missing abstract methods
        with pytest.raises(TypeError):
            IncompleteInterface(Mock())

    @pytest.mark.unit
    def test_concrete_implementation_works(self, mock_chatbot):
        """Test that complete implementation works"""
        interface = ConcreteInterface(mock_chatbot)
        assert interface is not None


# ========== Chat Method Tests ==========

class TestChatMethod:
    """Tests for chat method"""

    @pytest.mark.unit
    def test_chat_calls_chatbot(self, mock_chatbot):
        """Test that chat calls chatbot.chat"""
        interface = ConcreteInterface(mock_chatbot)
        state = StandardState.from_message("Hello")

        response = interface.chat(state)

        mock_chatbot.chat.assert_called_once_with(state)
        assert isinstance(response, StandardResponse)

    @pytest.mark.unit
    def test_chat_returns_standard_response(self, mock_chatbot):
        """Test that chat returns StandardResponse"""
        interface = ConcreteInterface(mock_chatbot)
        state = StandardState.from_message("Test")

        response = interface.chat(state)

        assert isinstance(response, StandardResponse)
        assert response.text == "Test response"


# ========== Configure Method Tests ==========

class TestConfigureMethod:
    """Tests for configure method"""

    @pytest.mark.unit
    def test_configure_calls_chatbot(self, mock_chatbot):
        """Test that configure calls chatbot.configure"""
        interface = ConcreteInterface(mock_chatbot)
        config = {"system_prompt": "New prompt"}

        interface.configure(config)

        mock_chatbot.configure.assert_called_once_with(config)

    @pytest.mark.unit
    def test_configure_with_multiple_settings(self, mock_chatbot):
        """Test configuring multiple settings"""
        interface = ConcreteInterface(mock_chatbot)
        config = {
            "system_prompt": "New prompt",
            "temperature": 0.8,
            "model": "gpt-4"
        }

        interface.configure(config)

        mock_chatbot.configure.assert_called_once_with(config)


# ========== History Methods Tests ==========

class TestHistoryMethods:
    """Tests for history management methods"""

    @pytest.mark.unit
    def test_get_history(self, mock_chatbot):
        """Test getting history"""
        interface = ConcreteInterface(mock_chatbot)

        history = interface.get_history()

        mock_chatbot.get_history.assert_called_once()
        assert isinstance(history, list)

    @pytest.mark.unit
    def test_clear_history(self, mock_chatbot):
        """Test clearing history"""
        interface = ConcreteInterface(mock_chatbot)

        interface.clear_history()

        mock_chatbot.clear_history.assert_called_once()


# ========== Validation Tests ==========

class TestValidateState:
    """Tests for state validation"""

    @pytest.mark.unit
    def test_validate_valid_state(self, mock_chatbot):
        """Test validating valid state"""
        interface = ConcreteInterface(mock_chatbot)
        state = StandardState.from_message("Hello")

        # Should not raise
        interface._validate_state(state)

    @pytest.mark.unit
    def test_validate_non_standard_state(self, mock_chatbot):
        """Test that non-StandardState raises TypeError"""
        interface = ConcreteInterface(mock_chatbot)

        with pytest.raises(TypeError, match="Expected StandardState"):
            interface._validate_state({"messages": []})

    @pytest.mark.unit
    def test_validate_empty_messages(self, mock_chatbot):
        """Test that empty messages raises ValueError"""
        interface = ConcreteInterface(mock_chatbot)
        state = StandardState(messages=[])

        with pytest.raises(ValueError, match="must have at least one message"):
            interface._validate_state(state)

    @pytest.mark.unit
    def test_validate_missing_role(self, mock_chatbot):
        """Test that message without role raises ValueError"""
        interface = ConcreteInterface(mock_chatbot)
        state = StandardState(messages=[
            {"content": "Hello"}  # Missing role
        ])

        with pytest.raises(ValueError, match="missing 'role'"):
            interface._validate_state(state)

    @pytest.mark.unit
    def test_validate_missing_content(self, mock_chatbot):
        """Test that message without content raises ValueError"""
        interface = ConcreteInterface(mock_chatbot)
        state = StandardState(messages=[
            {"role": "user"}  # Missing content
        ])

        with pytest.raises(ValueError, match="missing 'content'"):
            interface._validate_state(state)

    @pytest.mark.unit
    def test_validate_invalid_role(self, mock_chatbot):
        """Test that invalid role raises ValueError"""
        interface = ConcreteInterface(mock_chatbot)
        state = StandardState(messages=[
            {"role": "invalid", "content": "Hello"}
        ])

        with pytest.raises(ValueError, match="invalid role"):
            interface._validate_state(state)

    @pytest.mark.unit
    def test_validate_valid_roles(self, mock_chatbot):
        """Test all valid roles"""
        interface = ConcreteInterface(mock_chatbot)

        for role in ["user", "assistant", "system", "tool"]:
            state = StandardState(messages=[
                {"role": role, "content": "Test"}
            ])
            interface._validate_state(state)  # Should not raise


# ========== Format Response Tests ==========

class TestFormatResponse:
    """Tests for response formatting"""

    @pytest.mark.unit
    def test_format_response_default(self, mock_chatbot):
        """Test default formatting returns text"""
        interface = ConcreteInterface(mock_chatbot)
        response = StandardResponse(text="Hello world")

        formatted = interface._format_response(response)

        assert formatted == "Hello world"

    @pytest.mark.unit
    def test_format_response_preserves_text(self, mock_chatbot):
        """Test formatting preserves response text"""
        interface = ConcreteInterface(mock_chatbot)
        response = StandardResponse(
            text="Test response",
            response_type=ResponseType.NAVIGATION
        )

        formatted = interface._format_response(response)

        assert formatted == "Test response"


# ========== Error Handling Tests ==========

class TestHandleError:
    """Tests for error handling"""

    @pytest.mark.unit
    def test_handle_error_returns_error_response(self, mock_chatbot):
        """Test that error handling returns error response"""
        interface = ConcreteInterface(mock_chatbot)
        error = ValueError("Test error")

        response = interface._handle_error(error, context="test")

        assert isinstance(response, StandardResponse)
        assert response.response_type == ResponseType.ERROR
        assert response.confidence == 0.0
        assert "Test error" in response.text

    @pytest.mark.unit
    def test_handle_error_logs(self, mock_chatbot):
        """Test that error is logged"""
        interface = ConcreteInterface(mock_chatbot)

        with patch.object(interface.logger, 'error') as mock_log:
            error = ValueError("Test error")
            interface._handle_error(error)

            mock_log.assert_called_once()

    @pytest.mark.unit
    def test_handle_error_includes_session(self, mock_chatbot):
        """Test that error response includes session_id"""
        interface = ConcreteInterface(mock_chatbot)
        error = ValueError("Test")

        response = interface._handle_error(error)

        assert response.session_id == mock_chatbot.session_id


# ========== Logging Tests ==========

class TestLogInteraction:
    """Tests for interaction logging"""

    @pytest.mark.unit
    def test_log_interaction(self, mock_chatbot):
        """Test logging interaction"""
        interface = ConcreteInterface(mock_chatbot)
        response = StandardResponse(text="Response")

        with patch.object(interface.logger, 'debug') as mock_log:
            interface._log_interaction("Input", response, duration_ms=100)

            mock_log.assert_called_once()

    @pytest.mark.unit
    def test_log_interaction_with_duration(self, mock_chatbot):
        """Test logging includes duration"""
        interface = ConcreteInterface(mock_chatbot)
        response = StandardResponse(text="Response")

        with patch.object(interface.logger, 'debug') as mock_log:
            interface._log_interaction("Input", response, duration_ms=50)

            # Verify duration was logged
            call_kwargs = mock_log.call_args[1]
            assert call_kwargs.get('duration_ms') == 50


# ========== Session Info Tests ==========

class TestSessionInfo:
    """Tests for session information"""

    @pytest.mark.unit
    def test_get_session_info(self, mock_chatbot):
        """Test getting session info"""
        interface = ConcreteInterface(mock_chatbot)

        info = interface.get_session_info()

        mock_chatbot.get_session_info.assert_called_once()
        assert isinstance(info, dict)

    @pytest.mark.unit
    def test_get_interface_info(self, mock_chatbot):
        """Test getting interface info"""
        interface = ConcreteInterface(mock_chatbot)

        info = interface.get_interface_info()

        assert info["name"] == "ConcreteInterface"
        assert "module" in info
        assert "methods" in info
        assert "session_id" in info
        assert "chatbot_info" in info


# ========== Export History Tests ==========

class TestExportHistory:
    """Tests for history export"""

    @pytest.mark.unit
    def test_export_history_json(self, mock_chatbot):
        """Test exporting history as JSON"""
        interface = ConcreteInterface(mock_chatbot)

        json_str = interface.export_history(format="json")

        assert isinstance(json_str, str)
        assert len(json_str) > 0

    @pytest.mark.unit
    def test_export_history_unsupported_format(self, mock_chatbot):
        """Test that unsupported format raises error"""
        interface = ConcreteInterface(mock_chatbot)

        with pytest.raises(NotImplementedError):
            interface.export_history(format="pdf")


# ========== Statistics Tests ==========

class TestGetStats:
    """Tests for getting statistics"""

    @pytest.mark.unit
    def test_get_stats(self, mock_chatbot):
        """Test getting stats"""
        interface = ConcreteInterface(mock_chatbot)

        stats = interface.get_stats()

        assert isinstance(stats, dict)
        assert "session_id" in stats
        assert "total_messages" in stats
        assert "user_messages" in stats
        assert "assistant_messages" in stats

    @pytest.mark.unit
    def test_stats_message_counts(self, mock_chatbot):
        """Test that stats correctly count messages"""
        interface = ConcreteInterface(mock_chatbot)

        stats = interface.get_stats()

        # Mock returns 2 messages (1 user, 1 assistant)
        assert stats["total_messages"] == 2
        assert stats["user_messages"] == 1
        assert stats["assistant_messages"] == 1


# ========== String Representation Tests ==========

class TestStringRepresentation:
    """Tests for string representation"""

    @pytest.mark.unit
    def test_str(self, mock_chatbot):
        """Test __str__ representation"""
        interface = ConcreteInterface(mock_chatbot)

        str_repr = str(interface)

        assert "ConcreteInterface" in str_repr
        assert "test-session-123" in str_repr

    @pytest.mark.unit
    def test_repr(self, mock_chatbot):
        """Test __repr__ representation"""
        interface = ConcreteInterface(mock_chatbot)

        repr_str = repr(interface)

        assert "ConcreteInterface" in repr_str
        assert "test-session-123" in repr_str
        assert "0x" in repr_str  # Memory address


# ========== Integration Tests ==========

class TestIntegration:
    """Integration tests for BaseInterface"""

    @pytest.mark.integration
    def test_full_chat_cycle(self, mock_chatbot):
        """Test full chat cycle"""
        interface = ConcreteInterface(mock_chatbot)

        # Chat
        state = StandardState.from_message("Hello")
        response = interface.chat(state)

        assert response.text == "Test response"

        # Get history
        history = interface.get_history()
        assert len(history) > 0

        # Configure
        interface.configure({"system_prompt": "New"})
        mock_chatbot.configure.assert_called()

        # Clear
        interface.clear_history()
        mock_chatbot.clear_history.assert_called()

    @pytest.mark.integration
    def test_error_recovery(self, mock_chatbot):
        """Test error handling and recovery"""
        interface = ConcreteInterface(mock_chatbot)

        # Cause validation error
        with pytest.raises(ValueError):
            interface._validate_state(StandardState(messages=[]))

        # Interface should still be usable
        state = StandardState.from_message("Test")
        response = interface.chat(state)
        assert response is not None
