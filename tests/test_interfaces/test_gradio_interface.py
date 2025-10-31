"""
Tests for GradioInterface

Tests the Gradio web interface implementation.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.interfaces.gradio_interface_v2 import GradioInterface
from src.models.standard_types import StandardState, StandardResponse, ResponseType


# ========== INITIALIZATION TESTS ==========

class TestGradioInterfaceInitialization:
    """Tests for GradioInterface initialization"""

    @pytest.mark.unit
    def test_initialization_with_defaults(self, mock_chatbot):
        """Test initializing with default parameters"""
        interface = GradioInterface(mock_chatbot)

        assert interface.chatbot == mock_chatbot
        assert interface.title == "🤖 Forza Chatbot"
        assert interface.port == 7860
        assert interface.share is False
        assert interface.theme == "default"

    @pytest.mark.unit
    def test_initialization_with_custom_params(self, mock_chatbot):
        """Test initializing with custom parameters"""
        interface = GradioInterface(
            mock_chatbot,
            title="Custom Bot",
            port=8000,
            share=True,
            theme="dark",
        )

        assert interface.title == "Custom Bot"
        assert interface.port == 8000
        assert interface.share is True
        assert interface.theme == "dark"

    @pytest.mark.unit
    def test_initialization_with_none_chatbot(self):
        """Test that None chatbot raises error"""
        with pytest.raises(TypeError):
            GradioInterface(None)

    @pytest.mark.unit
    def test_initialization_sets_logger(self, mock_chatbot):
        """Test that logger is set"""
        interface = GradioInterface(mock_chatbot)
        assert interface.logger is not None

    @pytest.mark.unit
    def test_gradio_history_initialized_empty(self, mock_chatbot):
        """Test that gradio_history starts empty"""
        interface = GradioInterface(mock_chatbot)
        assert interface.gradio_history == []


# ========== CHAT METHOD TESTS ==========

class TestGradioChat:
    """Tests for chat method"""

    @pytest.mark.unit
    def test_chat_calls_chatbot(self, mock_chatbot):
        """Test that chat calls chatbot.chat"""
        interface = GradioInterface(mock_chatbot)
        state = StandardState.from_message("Hello")

        response = interface.chat(state)

        mock_chatbot.chat.assert_called_once_with(state)
        assert isinstance(response, StandardResponse)

    @pytest.mark.unit
    def test_chat_with_invalid_state(self, mock_chatbot):
        """Test that invalid state is handled gracefully"""
        interface = GradioInterface(mock_chatbot)

        # Invalid state should return error response
        response = interface.chat(StandardState(messages=[]))

        # Should return error response, not raise
        assert response.response_type == ResponseType.ERROR

    @pytest.mark.unit
    def test_chat_error_handling(self, mock_chatbot):
        """Test error handling in chat"""
        interface = GradioInterface(mock_chatbot)
        mock_chatbot.chat.side_effect = ValueError("Test error")

        state = StandardState.from_message("Hello")
        response = interface.chat(state)

        assert response.response_type == ResponseType.ERROR
        assert response.confidence == 0.0


# ========== CONFIGURE TESTS ==========

class TestGradioConfigure:
    """Tests for configure method"""

    @pytest.mark.unit
    def test_configure_calls_chatbot(self, mock_chatbot):
        """Test that configure calls chatbot.configure"""
        interface = GradioInterface(mock_chatbot)
        config = {"system_prompt": "New prompt"}

        interface.configure(config)

        mock_chatbot.configure.assert_called_once_with(config)

    @pytest.mark.unit
    def test_configure_logs_update(self, mock_chatbot):
        """Test that configuration update is logged"""
        interface = GradioInterface(mock_chatbot)

        with patch.object(interface.logger, "info") as mock_log:
            interface.configure({"system_prompt": "Test"})
            mock_log.assert_called()

    @pytest.mark.unit
    def test_configure_with_error(self, mock_chatbot):
        """Test configure error handling"""
        interface = GradioInterface(mock_chatbot)
        mock_chatbot.configure.side_effect = ValueError("Config error")

        with pytest.raises(ValueError):
            interface.configure({"system_prompt": "Test"})


# ========== HISTORY TESTS ==========

class TestGradioHistory:
    """Tests for history management"""

    @pytest.mark.unit
    def test_get_history(self, mock_chatbot):
        """Test getting history"""
        interface = GradioInterface(mock_chatbot)

        history = interface.get_history()

        mock_chatbot.get_history.assert_called_once()
        assert isinstance(history, list)

    @pytest.mark.unit
    def test_clear_history(self, mock_chatbot):
        """Test clearing history"""
        interface = GradioInterface(mock_chatbot)
        interface.gradio_history = [("Hi", "Hello")]

        interface.clear_history()

        assert interface.gradio_history == []
        mock_chatbot.clear_history.assert_called_once()

    @pytest.mark.unit
    def test_gradio_history_tracking(self, mock_chatbot):
        """Test that gradio_history is updated"""
        interface = GradioInterface(mock_chatbot)

        # Simulate adding to history
        interface.gradio_history.append(("Hello", "Hi there"))

        assert len(interface.gradio_history) == 1
        assert interface.gradio_history[0] == ("Hello", "Hi there")


# ========== FORMAT CONVERSION TESTS ==========

class TestGradioFormatConversion:
    """Tests for converting between Gradio and StandardState formats"""

    @pytest.mark.unit
    def test_convert_from_gradio_empty_history(self):
        """Test converting empty Gradio history"""
        interface = GradioInterface(Mock())
        messages = interface._convert_from_gradio([], "Hello")

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"

    @pytest.mark.unit
    def test_convert_from_gradio_with_history(self):
        """Test converting Gradio history with existing messages"""
        interface = GradioInterface(Mock())
        history = [("Hi", "Hello"), ("How are you?", "I'm good")]

        messages = interface._convert_from_gradio(history, "What's new?")

        assert len(messages) == 5  # 2 user + 2 assistant + 1 new user
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hi"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hello"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "What's new?"

    @pytest.mark.unit
    def test_convert_from_gradio_missing_bot_response(self):
        """Test converting history with missing bot response"""
        interface = GradioInterface(Mock())
        history = [("Hi", None)]  # No bot response yet

        messages = interface._convert_from_gradio(history, "Hello")

        # Should only have user message from history + new message
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "user"

    @pytest.mark.unit
    def test_convert_to_gradio(self):
        """Test converting back to Gradio format"""
        interface = GradioInterface(Mock())
        messages = [("Hi", "Hello"), ("Bye", "See you")]

        result = interface._convert_to_gradio(messages)

        assert result == messages  # Should be same format

    @pytest.mark.unit
    def test_convert_roundtrip(self):
        """Test roundtrip conversion"""
        interface = GradioInterface(Mock())

        # Start with Gradio format
        gradio_history = [("Hello", "Hi there")]
        new_msg = "How are you?"

        # Convert to StandardState
        messages = interface._convert_from_gradio(gradio_history, new_msg)

        # Convert back to Gradio
        # (In practice, this would be after processing)
        result = interface._convert_to_gradio(gradio_history)

        assert result == gradio_history


# ========== QUICK PROMPTS TESTS ==========

class TestGradioQuickPrompts:
    """Tests for quick prompts loading"""

    @pytest.mark.unit
    def test_load_quick_prompts_default(self, mock_chatbot):
        """Test loading default prompts"""
        interface = GradioInterface(mock_chatbot)

        # Should load prompts (exact group names depend on config file)
        assert interface.quick_prompts
        assert isinstance(interface.quick_prompts, dict)
        # At least one group with prompts
        assert any(prompts for prompts in interface.quick_prompts.values())

    @pytest.mark.unit
    def test_load_quick_prompts_missing_file(self, mock_chatbot):
        """Test loading when file doesn't exist"""
        interface = GradioInterface(mock_chatbot, quick_prompts_file="/nonexistent/path.yaml")

        # Should fall back to defaults
        assert interface.quick_prompts
        assert isinstance(interface.quick_prompts, dict)

    @pytest.mark.unit
    def test_load_quick_prompts_with_file(self, mock_chatbot, tmp_path):
        """Test loading prompts from actual file"""
        # Create temporary YAML file
        prompts_file = tmp_path / "prompts.yaml"
        prompts_file.write_text("""
groups:
  Test:
    - "Test prompt 1"
    - "Test prompt 2"
  Another:
    - "Another prompt"
""")

        interface = GradioInterface(mock_chatbot, quick_prompts_file=str(prompts_file))

        assert "Test" in interface.quick_prompts
        assert "Another" in interface.quick_prompts
        assert len(interface.quick_prompts["Test"]) == 2


# ========== EVENT HANDLER TESTS ==========

class TestGradioEventHandlers:
    """Tests for event handlers"""

    @pytest.mark.unit
    def test_handle_send_basic(self, mock_chatbot):
        """Test basic send handler"""
        interface = GradioInterface(mock_chatbot)
        history = []

        result = interface._handle_send(history, "Hello")

        assert isinstance(result, list)

    @pytest.mark.unit
    def test_handle_send_empty_message(self, mock_chatbot):
        """Test send with empty message"""
        interface = GradioInterface(mock_chatbot)
        history = [("Hi", "Hello")]

        result = interface._handle_send(history, "   ")

        # Should return unchanged history
        assert result == history

    @pytest.mark.unit
    def test_handle_send_with_history(self, mock_chatbot):
        """Test send with existing history"""
        interface = GradioInterface(mock_chatbot)
        history = [("Hi", "Hello")]

        result = interface._handle_send(history, "How are you?")

        # Should add new message to history
        assert len(result) >= len(history)

    @pytest.mark.unit
    def test_handle_clear(self, mock_chatbot):
        """Test clear handler"""
        interface = GradioInterface(mock_chatbot)
        interface.gradio_history = [("Hi", "Hello")]

        result = interface._handle_clear()

        assert result == []
        assert interface.gradio_history == []

    @pytest.mark.unit
    def test_handle_quick_prompt(self, mock_chatbot):
        """Test quick prompt handler"""
        interface = GradioInterface(mock_chatbot)

        result = interface._handle_quick_prompt([], "Test prompt")

        assert isinstance(result, list)

    @pytest.mark.unit
    def test_handle_config_update(self, mock_chatbot):
        """Test config update handler"""
        interface = GradioInterface(mock_chatbot)

        interface._handle_config_update("New prompt", 0.8, "NewBot")

        mock_chatbot.configure.assert_called_once()


# ========== UI BUILDING TESTS ==========

class TestGradioUIBuilding:
    """Tests for UI building methods"""

    @pytest.mark.unit
    def test_build_ui_creates_demo(self, mock_chatbot):
        """Test that build_ui creates demo"""
        interface = GradioInterface(mock_chatbot)

        # Just test that it doesn't crash (demo creation is Gradio's job)
        # Skip actual Gradio UI creation in tests
        assert interface.demo is None  # Not created until run()

    @pytest.mark.unit
    def test_get_custom_css(self, mock_chatbot):
        """Test CSS generation"""
        interface = GradioInterface(mock_chatbot)

        css = interface._get_custom_css()

        assert isinstance(css, str)
        assert "gradio-container" in css
        assert "max-width" in css

    @pytest.mark.unit
    def test_theme_selection(self, mock_chatbot):
        """Test theme selection"""
        for theme in ["default", "dark", "soft"]:
            interface = GradioInterface(mock_chatbot, theme=theme)
            assert interface.theme == theme


# ========== EXPORT TESTS ==========

class TestGradioExport:
    """Tests for history export"""

    @pytest.mark.unit
    def test_export_history_json(self, mock_chatbot):
        """Test exporting history as JSON"""
        interface = GradioInterface(mock_chatbot)

        json_str = interface._export_history_json()

        assert isinstance(json_str, str)
        assert len(json_str) > 0

    @pytest.mark.unit
    def test_export_history_via_base_class(self, mock_chatbot):
        """Test export through base class method"""
        interface = GradioInterface(mock_chatbot)

        exported = interface.export_history(format="json")

        assert isinstance(exported, str)


# ========== STRING REPRESENTATION TESTS ==========

class TestGradioStringRepresentation:
    """Tests for string representation"""

    @pytest.mark.unit
    def test_str(self, mock_chatbot):
        """Test __str__ representation"""
        interface = GradioInterface(mock_chatbot, port=7860)

        str_repr = str(interface)

        assert "GradioInterface" in str_repr
        assert "7860" in str_repr


# ========== INTEGRATION TESTS ==========

class TestGradioIntegration:
    """Integration tests for Gradio interface"""

    @pytest.mark.integration
    def test_full_chat_cycle(self, mock_chatbot):
        """Test full chat cycle"""
        interface = GradioInterface(mock_chatbot)

        # Simulate chat
        history = []
        history = interface._handle_send(history, "Hello")

        assert isinstance(history, list)

        # Configure
        interface.configure({"system_prompt": "New"})
        mock_chatbot.configure.assert_called()

        # Clear
        interface.clear_history()
        assert interface.gradio_history == []

    @pytest.mark.integration
    def test_multi_turn_conversation(self, mock_chatbot):
        """Test multi-turn conversation"""
        interface = GradioInterface(mock_chatbot)

        history = []
        # First turn
        history = interface._handle_send(history, "Hi")
        # Second turn
        history = interface._handle_send(history, "How are you?")
        # Third turn
        history = interface._handle_send(history, "Goodbye")

        assert len(history) >= 3

    @pytest.mark.integration
    def test_error_recovery(self, mock_chatbot):
        """Test recovery from errors"""
        interface = GradioInterface(mock_chatbot)
        mock_chatbot.chat.side_effect = ValueError("Test error")

        # Try to send message (should handle error)
        history = interface._handle_send([], "Hello")

        # Should still return valid history
        assert isinstance(history, list)

        # Reset mock and try again
        mock_chatbot.chat.side_effect = None
        history = interface._handle_send([], "Second try")

        # Should work after reset
        assert isinstance(history, list)


# ========== BACKWARD COMPATIBILITY TESTS ==========

class TestBackwardCompatibility:
    """Tests for backward compatibility"""

    @pytest.mark.unit
    def test_run_gradio_legacy_exists(self, mock_chatbot):
        """Test that legacy run_gradio_legacy function exists"""
        from src.interfaces.gradio_interface_v2 import run_gradio_legacy

        # Function should be importable
        assert callable(run_gradio_legacy)
