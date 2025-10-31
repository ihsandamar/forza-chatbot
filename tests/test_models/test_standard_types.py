"""
Tests for Standard Types

Tests StandardState, StandardResponse, and related types.
"""

import pytest
import json
from datetime import datetime

from src.models.standard_types import (
    StandardState, StandardResponse, StandardAction,
    ResponseType, ValidationError, ValidationResult,
    AssistantConfigBase, SessionInfo
)


# ========== StandardState Tests ==========

class TestStandardState:
    """Tests for StandardState"""

    @pytest.mark.unit
    def test_standard_state_creation(self):
        """Test creating StandardState with messages"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]

        state = StandardState(messages=messages)

        assert state.messages == messages
        assert state.metadata == {}
        assert state.session_id is None

    @pytest.mark.unit
    def test_standard_state_from_message_helper(self):
        """Test creating StandardState from single message"""
        state = StandardState.from_message("Hello world")

        assert len(state.messages) == 1
        assert state.messages[0]["role"] == "user"
        assert state.messages[0]["content"] == "Hello world"

    @pytest.mark.unit
    def test_standard_state_from_message_with_session(self):
        """Test from_message with session_id"""
        state = StandardState.from_message("Test", session_id="abc123")

        assert state.session_id == "abc123"
        assert len(state.messages) == 1

    @pytest.mark.unit
    def test_standard_state_from_message_with_metadata(self):
        """Test from_message with metadata"""
        metadata = {"source": "cli", "user_id": "user123"}
        state = StandardState.from_message("Hello", metadata=metadata)

        assert state.metadata == metadata

    @pytest.mark.unit
    def test_get_user_message(self):
        """Test extracting last user message"""
        state = StandardState(messages=[
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Second message"}
        ])

        assert state.get_user_message() == "Second message"

    @pytest.mark.unit
    def test_get_user_message_empty(self):
        """Test get_user_message with no user messages"""
        state = StandardState(messages=[
            {"role": "assistant", "content": "Hello"}
        ])

        assert state.get_user_message() is None

    @pytest.mark.unit
    def test_get_last_message(self):
        """Test getting last message"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"}
        ]
        state = StandardState(messages=messages)

        assert state.get_last_message() == {"role": "assistant", "content": "Hi"}

    @pytest.mark.unit
    def test_get_last_message_empty(self):
        """Test get_last_message with empty messages"""
        state = StandardState(messages=[])

        assert state.get_last_message() is None

    @pytest.mark.unit
    def test_get_conversation_summary(self):
        """Test conversation summary"""
        state = StandardState(messages=[
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Hi there"}
        ])

        summary = state.get_conversation_summary()

        assert "USER:" in summary
        assert "ASSISTANT:" in summary
        assert "Hello" in summary

    @pytest.mark.unit
    def test_to_dict(self):
        """Test converting to dictionary"""
        state = StandardState(
            messages=[{"role": "user", "content": "Test"}],
            metadata={"source": "cli"},
            session_id="abc123"
        )

        result = state.to_dict()

        assert result["messages"] == state.messages
        assert result["metadata"] == {"source": "cli"}
        assert result["session_id"] == "abc123"

    @pytest.mark.unit
    def test_to_json(self):
        """Test converting to JSON"""
        state = StandardState(messages=[{"role": "user", "content": "Test"}])
        json_str = state.to_json()

        parsed = json.loads(json_str)
        assert parsed["messages"][0]["content"] == "Test"

    @pytest.mark.unit
    def test_len(self):
        """Test len() on state"""
        state = StandardState(messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"}
        ])

        assert len(state) == 2

    @pytest.mark.unit
    def test_bool_with_messages(self):
        """Test bool() with messages"""
        state = StandardState(messages=[{"role": "user", "content": "Test"}])
        assert bool(state) is True

    @pytest.mark.unit
    def test_bool_without_messages(self):
        """Test bool() without messages"""
        state = StandardState(messages=[])
        assert bool(state) is False


# ========== StandardAction Tests ==========

class TestStandardAction:
    """Tests for StandardAction"""

    @pytest.mark.unit
    def test_action_creation(self):
        """Test creating StandardAction"""
        action = StandardAction(
            type="routing",
            target="http://example.com",
            params={"id": "123"}
        )

        assert action.type == "routing"
        assert action.target == "http://example.com"
        assert action.params == {"id": "123"}

    @pytest.mark.unit
    def test_action_to_dict(self):
        """Test converting action to dict"""
        action = StandardAction(
            type="submit",
            target="form_id",
            params={"field": "value"}
        )

        result = action.to_dict()

        assert result["type"] == "submit"
        assert result["target"] == "form_id"
        assert result["params"]["field"] == "value"

    @pytest.mark.unit
    def test_action_bool_none(self):
        """Test bool() on 'none' action"""
        action = StandardAction(type="none")
        assert bool(action) is False

    @pytest.mark.unit
    def test_action_bool_true(self):
        """Test bool() on non-'none' action"""
        action = StandardAction(type="routing", target="http://example.com")
        assert bool(action) is True


# ========== StandardResponse Tests ==========

class TestStandardResponse:
    """Tests for StandardResponse"""

    @pytest.mark.unit
    def test_response_creation_minimal(self):
        """Test creating StandardResponse with minimal args"""
        response = StandardResponse(text="Hello")

        assert response.text == "Hello"
        assert response.response_type == ResponseType.TEXT
        assert response.confidence == 0.95
        assert response.action.type == "none"

    @pytest.mark.unit
    def test_response_creation_full(self):
        """Test creating StandardResponse with all args"""
        action = StandardAction(type="routing", target="http://example.com")
        response = StandardResponse(
            text="Navigate here",
            response_type=ResponseType.NAVIGATION,
            confidence=0.92,
            action=action,
            metadata={"page_id": "ABC123"},
            session_id="session123"
        )

        assert response.text == "Navigate here"
        assert response.response_type == ResponseType.NAVIGATION
        assert response.confidence == 0.92
        assert response.action.target == "http://example.com"
        assert response.metadata["page_id"] == "ABC123"
        assert response.session_id == "session123"

    @pytest.mark.unit
    def test_response_to_dict(self):
        """Test converting response to dict"""
        response = StandardResponse(
            text="Test",
            response_type=ResponseType.TEXT,
            confidence=0.9
        )

        result = response.to_dict()

        assert result["text"] == "Test"
        assert result["type"] == "text"
        assert result["confidence"] == 0.9
        assert "timestamp" in result

    @pytest.mark.unit
    def test_response_to_json(self):
        """Test converting response to JSON"""
        response = StandardResponse(text="JSON test")
        json_str = response.to_json()

        parsed = json.loads(json_str)
        assert parsed["text"] == "JSON test"
        assert "timestamp" in parsed

    @pytest.mark.unit
    def test_response_str(self):
        """Test string representation (text only)"""
        response = StandardResponse(text="Just the text")
        assert str(response) == "Just the text"

    @pytest.mark.unit
    def test_response_error_type(self):
        """Test error response"""
        response = StandardResponse(
            text="Something went wrong",
            response_type=ResponseType.ERROR,
            confidence=0.0
        )

        assert response.response_type == ResponseType.ERROR
        assert response.confidence == 0.0

    @pytest.mark.unit
    def test_response_types_enum(self):
        """Test all response types"""
        types = [
            ResponseType.TEXT,
            ResponseType.NAVIGATION,
            ResponseType.TABLE,
            ResponseType.FORM,
            ResponseType.ERROR,
            ResponseType.STRUCTURED
        ]

        for response_type in types:
            response = StandardResponse(
                text="Test",
                response_type=response_type
            )
            assert response.response_type == response_type


# ========== AssistantConfigBase Tests ==========

class TestAssistantConfigBase:
    """Tests for AssistantConfigBase"""

    @pytest.mark.unit
    def test_config_creation_minimal(self):
        """Test creating config with minimal args"""
        config = AssistantConfigBase()

        assert config.system_prompt == "Sen yardımcı bir asistansın."
        assert config.assistant_name == "Assistant"
        assert config.model is None
        assert config.temperature is None

    @pytest.mark.unit
    def test_config_creation_full(self):
        """Test creating config with all args"""
        config = AssistantConfigBase(
            system_prompt="Custom prompt",
            assistant_name="CustomBot",
            model="gpt-4",
            temperature=0.8,
            max_tokens=2048
        )

        assert config.system_prompt == "Custom prompt"
        assert config.assistant_name == "CustomBot"
        assert config.model == "gpt-4"
        assert config.temperature == 0.8
        assert config.max_tokens == 2048

    @pytest.mark.unit
    def test_to_dict_excludes_none(self):
        """Test to_dict excludes None values"""
        config = AssistantConfigBase(
            system_prompt="Test",
            model="gpt-4"
            # temperature and max_tokens are None
        )

        result = config.to_dict()

        assert "system_prompt" in result
        assert "model" in result
        assert "temperature" not in result  # Excluded
        assert "max_tokens" not in result    # Excluded

    @pytest.mark.unit
    def test_update_method(self):
        """Test updating config"""
        config = AssistantConfigBase(system_prompt="Original")
        updated = config.update(system_prompt="Updated", temperature=0.5)

        # Original unchanged
        assert config.system_prompt == "Original"
        assert config.temperature is None

        # New instance updated
        assert updated.system_prompt == "Updated"
        assert updated.temperature == 0.5

    @pytest.mark.unit
    def test_merge_method(self):
        """Test merging configs"""
        config1 = AssistantConfigBase(
            system_prompt="Prompt1",
            temperature=0.5
        )
        config2 = AssistantConfigBase(
            system_prompt="Prompt2",
            max_tokens=1024
        )

        merged = config1.merge(config2)

        # config2 values override config1
        assert merged.system_prompt == "Prompt2"
        assert merged.temperature == 0.5
        assert merged.max_tokens == 1024

    @pytest.mark.unit
    def test_temperature_validation(self):
        """Test temperature must be 0-2"""
        # Valid temperatures
        for temp in [0, 0.5, 1.0, 1.5, 2.0]:
            config = AssistantConfigBase(temperature=temp)
            assert config.temperature == temp

        # Invalid temperatures
        with pytest.raises(ValueError):
            AssistantConfigBase(temperature=-0.1)

        with pytest.raises(ValueError):
            AssistantConfigBase(temperature=2.1)

    @pytest.mark.unit
    def test_max_tokens_validation(self):
        """Test max_tokens must be > 0"""
        # Valid
        config = AssistantConfigBase(max_tokens=100)
        assert config.max_tokens == 100

        # Invalid
        with pytest.raises(ValueError):
            AssistantConfigBase(max_tokens=0)

        with pytest.raises(ValueError):
            AssistantConfigBase(max_tokens=-1)


# ========== ValidationError Tests ==========

class TestValidationError:
    """Tests for ValidationError"""

    @pytest.mark.unit
    def test_error_creation(self):
        """Test creating ValidationError"""
        error = ValidationError(
            field="message",
            message="Content cannot be empty",
            value="",
            suggestion="Provide a non-empty message"
        )

        assert error.field == "message"
        assert error.message == "Content cannot be empty"
        assert error.suggestion == "Provide a non-empty message"

    @pytest.mark.unit
    def test_error_to_dict(self):
        """Test converting error to dict"""
        error = ValidationError(
            field="test_field",
            message="Test error",
            value=None
        )

        result = error.to_dict()

        assert result["field"] == "test_field"
        assert result["message"] == "Test error"


# ========== ValidationResult Tests ==========

class TestValidationResult:
    """Tests for ValidationResult"""

    @pytest.mark.unit
    def test_result_valid(self):
        """Test valid result"""
        result = ValidationResult(is_valid=True)

        assert result.is_valid is True
        assert len(result.errors) == 0

    @pytest.mark.unit
    def test_result_invalid(self):
        """Test invalid result"""
        result = ValidationResult(is_valid=False)

        assert result.is_valid is False

    @pytest.mark.unit
    def test_add_error(self):
        """Test adding error"""
        result = ValidationResult(is_valid=True)
        result.add_error(
            field="test",
            message="Test error",
            suggestion="Fix it"
        )

        assert len(result.errors) == 1
        assert result.is_valid is False
        assert result.errors[0].field == "test"

    @pytest.mark.unit
    def test_add_warning(self):
        """Test adding warning"""
        result = ValidationResult(is_valid=True)
        result.add_warning("This is a warning")

        assert len(result.warnings) == 1
        assert result.is_valid is True  # Warnings don't fail validation

    @pytest.mark.unit
    def test_bool_conversion(self):
        """Test bool() on result"""
        valid_result = ValidationResult(is_valid=True)
        assert bool(valid_result) is True

        invalid_result = ValidationResult(is_valid=False)
        assert bool(invalid_result) is False


# ========== SessionInfo Tests ==========

class TestSessionInfo:
    """Tests for SessionInfo"""

    @pytest.mark.unit
    def test_session_info_creation(self):
        """Test creating SessionInfo"""
        now = datetime.now()
        info = SessionInfo(
            session_id="test-123",
            created_at=now,
            last_interaction=now,
            message_count=5,
            assistant_name="TestBot",
            configuration={"model": "gpt-4"}
        )

        assert info.session_id == "test-123"
        assert info.message_count == 5

    @pytest.mark.unit
    def test_session_info_to_dict(self):
        """Test converting to dict"""
        now = datetime.now()
        info = SessionInfo(
            session_id="test",
            created_at=now,
            last_interaction=now,
            message_count=0,
            assistant_name="Bot",
            configuration={}
        )

        result = info.to_dict()

        assert result["session_id"] == "test"
        assert "created_at" in result
        assert isinstance(result["created_at"], str)  # ISO format

    @pytest.mark.unit
    def test_session_duration(self):
        """Test duration calculation"""
        from datetime import timedelta

        start = datetime.now()
        end = start + timedelta(seconds=10)

        info = SessionInfo(
            session_id="test",
            created_at=start,
            last_interaction=end,
            message_count=0,
            assistant_name="Bot",
            configuration={}
        )

        duration = info.duration_seconds()

        # Allow small timing variations
        assert 9 < duration < 11
