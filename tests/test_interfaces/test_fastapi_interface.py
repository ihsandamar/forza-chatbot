"""
Tests for FastAPIInterface

Tests the FastAPI REST API interface implementation.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime

from src.interfaces.fastapi_interface import (
    FastAPIInterface, ChatRequest, ChatResponse, ConfigureRequest,
    HealthResponse, SessionResponse, HistoryResponse
)
from src.models.standard_types import StandardState, StandardResponse, ResponseType


# ========== INITIALIZATION TESTS ==========

class TestFastAPIInterfaceInitialization:
    """Tests for FastAPIInterface initialization"""

    @pytest.mark.unit
    def test_initialization_with_defaults(self, mock_chatbot):
        """Test initializing with default parameters"""
        interface = FastAPIInterface(mock_chatbot)

        assert interface.chatbot == mock_chatbot
        assert interface.title == "Forza Chatbot API"
        assert interface.version == "2.0"
        assert interface.app is not None

    @pytest.mark.unit
    def test_initialization_with_custom_params(self, mock_chatbot):
        """Test initializing with custom parameters"""
        interface = FastAPIInterface(
            mock_chatbot,
            title="Custom API",
            version="1.0",
            description="Custom description",
            cors_origins=["http://localhost:3000"],
        )

        assert interface.title == "Custom API"
        assert interface.version == "1.0"
        assert interface.description == "Custom description"

    @pytest.mark.unit
    def test_initialization_with_none_chatbot(self):
        """Test that None chatbot raises error"""
        with pytest.raises(TypeError):
            FastAPIInterface(None)

    @pytest.mark.unit
    def test_initialization_sets_logger(self, mock_chatbot):
        """Test that logger is set"""
        interface = FastAPIInterface(mock_chatbot)
        assert interface.logger is not None

    @pytest.mark.unit
    def test_fastapi_app_created(self, mock_chatbot):
        """Test that FastAPI app is created"""
        interface = FastAPIInterface(mock_chatbot)
        assert interface.app is not None
        assert hasattr(interface.app, 'routes')


# ========== HEALTH CHECK TESTS ==========

class TestHealthCheck:
    """Tests for health check endpoint"""

    @pytest.mark.unit
    def test_health_check_endpoint(self, mock_chatbot):
        """Test health check endpoint"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    @pytest.mark.unit
    def test_health_check_response_format(self, mock_chatbot):
        """Test health check response format"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/health")
        data = response.json()

        assert "service" in data
        assert "version" in data
        assert data["service"] == "Forza Chatbot API"


# ========== CHAT ENDPOINT TESTS ==========

class TestChatEndpoint:
    """Tests for chat endpoint"""

    @pytest.mark.unit
    def test_chat_basic_request(self, mock_chatbot):
        """Test basic chat request"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/chat", json={"message": "Hello"})

        assert response.status_code == 200
        data = response.json()
        assert "text" in data
        assert "response_type" in data
        assert "confidence" in data

    @pytest.mark.unit
    def test_chat_with_session_id(self, mock_chatbot):
        """Test chat with session ID"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/chat", json={
            "message": "Hello",
            "session_id": "user-123"
        })

        assert response.status_code == 200
        data = response.json()
        # Session ID in response comes from the chatbot, not the request
        assert data["session_id"] == mock_chatbot.session_id

    @pytest.mark.unit
    def test_chat_with_metadata(self, mock_chatbot):
        """Test chat with metadata"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/chat", json={
            "message": "Hello",
            "metadata": {"source": "mobile"}
        })

        assert response.status_code == 200
        data = response.json()
        assert "metadata" in data

    @pytest.mark.unit
    def test_chat_empty_message(self, mock_chatbot):
        """Test chat with empty message"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/chat", json={"message": ""})

        # Should fail validation
        assert response.status_code == 422  # Validation error

    @pytest.mark.unit
    def test_chat_missing_message(self, mock_chatbot):
        """Test chat without message field"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/chat", json={})

        # Should fail validation
        assert response.status_code == 422

    @pytest.mark.unit
    def test_chat_response_format(self, mock_chatbot):
        """Test chat response format"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/chat", json={"message": "Test"})

        data = response.json()
        assert "text" in data
        assert "response_type" in data
        assert "confidence" in data
        assert "session_id" in data
        assert "timestamp" in data


# ========== CONFIGURATION ENDPOINT TESTS ==========

class TestConfigurationEndpoint:
    """Tests for configuration endpoints"""

    @pytest.mark.unit
    def test_configure_system_prompt(self, mock_chatbot):
        """Test updating system prompt"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/configure", json={
            "system_prompt": "New system prompt"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        mock_chatbot.configure.assert_called()

    @pytest.mark.unit
    def test_configure_temperature(self, mock_chatbot):
        """Test updating temperature"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/configure", json={
            "temperature": 0.8
        })

        assert response.status_code == 200

    @pytest.mark.unit
    def test_configure_multiple_params(self, mock_chatbot):
        """Test updating multiple parameters"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/configure", json={
            "system_prompt": "New prompt",
            "temperature": 0.7,
            "assistant_name": "NewBot"
        })

        assert response.status_code == 200
        mock_chatbot.configure.assert_called()

    @pytest.mark.unit
    def test_configure_temperature_bounds(self, mock_chatbot):
        """Test temperature validation (0-2 range)"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        # Invalid: temperature > 2
        response = client.post("/configure", json={
            "temperature": 2.5
        })

        assert response.status_code == 422

    @pytest.mark.unit
    def test_configure_empty_request(self, mock_chatbot):
        """Test configuration with no parameters"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.post("/configure", json={})

        # Should fail - at least one parameter required
        assert response.status_code == 400

    @pytest.mark.unit
    def test_get_config(self, mock_chatbot):
        """Test getting current configuration"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/config")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "config" in data


# ========== HISTORY ENDPOINT TESTS ==========

class TestHistoryEndpoints:
    """Tests for history management endpoints"""

    @pytest.mark.unit
    def test_get_history(self, mock_chatbot):
        """Test getting history"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/history")

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "messages" in data
        assert "message_count" in data

    @pytest.mark.unit
    def test_clear_history(self, mock_chatbot):
        """Test clearing history"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.delete("/history")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        mock_chatbot.clear_history.assert_called()


# ========== SESSION ENDPOINT TESTS ==========

class TestSessionEndpoint:
    """Tests for session endpoints"""

    @pytest.mark.unit
    def test_get_session_info(self, mock_chatbot):
        """Test getting session info"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/session")

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "created_at" in data
        assert "message_count" in data
        assert "assistant_name" in data


# ========== STATS ENDPOINT TESTS ==========

class TestStatsEndpoint:
    """Tests for statistics endpoint"""

    @pytest.mark.unit
    def test_get_stats(self, mock_chatbot):
        """Test getting statistics"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "stats" in data


# ========== EXPORT ENDPOINT TESTS ==========

class TestExportEndpoint:
    """Tests for history export"""

    @pytest.mark.unit
    def test_export_json(self, mock_chatbot):
        """Test exporting history as JSON"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/export?format=json")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["format"] == "json"
        assert "data" in data

    @pytest.mark.unit
    def test_export_unsupported_format(self, mock_chatbot):
        """Test exporting with unsupported format"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/export?format=csv")

        assert response.status_code == 400


# ========== CHAT METHOD TESTS ==========

class TestChatMethod:
    """Tests for chat method"""

    @pytest.mark.unit
    def test_chat_calls_chatbot(self, mock_chatbot):
        """Test that chat calls chatbot.chat"""
        interface = FastAPIInterface(mock_chatbot)
        state = StandardState.from_message("Hello")

        response = interface.chat(state)

        mock_chatbot.chat.assert_called_once_with(state)
        assert isinstance(response, StandardResponse)

    @pytest.mark.unit
    def test_chat_with_invalid_state(self, mock_chatbot):
        """Test that invalid state is handled gracefully"""
        interface = FastAPIInterface(mock_chatbot)

        # Invalid state should return error response
        response = interface.chat(StandardState(messages=[]))

        assert response.response_type == ResponseType.ERROR

    @pytest.mark.unit
    def test_chat_error_handling(self, mock_chatbot):
        """Test error handling in chat"""
        interface = FastAPIInterface(mock_chatbot)
        mock_chatbot.chat.side_effect = ValueError("Test error")

        state = StandardState.from_message("Hello")
        response = interface.chat(state)

        assert response.response_type == ResponseType.ERROR
        assert response.confidence == 0.0


# ========== CONFIGURE METHOD TESTS ==========

class TestConfigureMethod:
    """Tests for configure method"""

    @pytest.mark.unit
    def test_configure_calls_chatbot(self, mock_chatbot):
        """Test that configure calls chatbot.configure"""
        interface = FastAPIInterface(mock_chatbot)
        config = {"system_prompt": "New prompt"}

        interface.configure(config)

        mock_chatbot.configure.assert_called_once_with(config)

    @pytest.mark.unit
    def test_configure_with_error(self, mock_chatbot):
        """Test configure error handling"""
        interface = FastAPIInterface(mock_chatbot)
        mock_chatbot.configure.side_effect = ValueError("Config error")

        with pytest.raises(ValueError):
            interface.configure({"system_prompt": "Test"})


# ========== CORS CONFIGURATION TESTS ==========

class TestCORSConfiguration:
    """Tests for CORS configuration"""

    @pytest.mark.unit
    def test_default_cors_allows_all(self, mock_chatbot):
        """Test that default CORS allows all origins"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/health")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_custom_cors_origins(self, mock_chatbot):
        """Test custom CORS origins"""
        interface = FastAPIInterface(
            mock_chatbot,
            cors_origins=["http://localhost:3000", "https://example.com"]
        )
        client = TestClient(interface.app)

        response = client.get("/health")
        assert response.status_code == 200


# ========== STRING REPRESENTATION TESTS ==========

class TestStringRepresentation:
    """Tests for string representation"""

    @pytest.mark.unit
    def test_str(self, mock_chatbot):
        """Test __str__ representation"""
        interface = FastAPIInterface(mock_chatbot)

        str_repr = str(interface)

        assert "FastAPIInterface" in str_repr
        assert "2.0" in str_repr  # version

    @pytest.mark.unit
    def test_repr(self, mock_chatbot):
        """Test __repr__ representation"""
        interface = FastAPIInterface(mock_chatbot)

        repr_str = repr(interface)

        assert "FastAPIInterface" in repr_str
        assert "0x" in repr_str  # Memory address


# ========== INTEGRATION TESTS ==========

class TestFastAPIIntegration:
    """Integration tests for FastAPI interface"""

    @pytest.mark.integration
    def test_full_chat_cycle(self, mock_chatbot):
        """Test full chat cycle via API"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        # Chat
        response = client.post("/chat", json={"message": "Hello"})
        assert response.status_code == 200

        # Get history
        response = client.get("/history")
        assert response.status_code == 200

        # Get stats
        response = client.get("/stats")
        assert response.status_code == 200

        # Clear history
        response = client.delete("/history")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_configuration_workflow(self, mock_chatbot):
        """Test configuration workflow"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        # Get current config
        response = client.get("/config")
        assert response.status_code == 200

        # Update config
        response = client.post("/configure", json={
            "system_prompt": "New prompt",
            "temperature": 0.8
        })
        assert response.status_code == 200

        # Get config again
        response = client.get("/config")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_multi_turn_conversation(self, mock_chatbot):
        """Test multi-turn conversation via API"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        # First message
        response1 = client.post("/chat", json={"message": "Hi"})
        assert response1.status_code == 200

        # Second message
        response2 = client.post("/chat", json={"message": "How are you?"})
        assert response2.status_code == 200

        # Third message
        response3 = client.post("/chat", json={"message": "Goodbye"})
        assert response3.status_code == 200

    @pytest.mark.integration
    def test_error_recovery(self, mock_chatbot):
        """Test recovery from errors"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        # Cause error
        mock_chatbot.chat.side_effect = ValueError("Test error")

        # Try to send message (should return error)
        response = client.post("/chat", json={"message": "Hello"})
        assert response.status_code == 200  # Request succeeds, response contains error

        # Reset mock and try again
        mock_chatbot.chat.side_effect = None

        # Should work after reset
        response = client.post("/chat", json={"message": "Second try"})
        assert response.status_code == 200


# ========== OPENAPI DOCUMENTATION TESTS ==========

class TestOpenAPIDocumentation:
    """Tests for OpenAPI documentation"""

    @pytest.mark.unit
    def test_openapi_schema_available(self, mock_chatbot):
        """Test that OpenAPI schema is available"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/openapi.json")

        assert response.status_code == 200
        schema = response.json()
        assert "paths" in schema
        assert "info" in schema

    @pytest.mark.unit
    def test_swagger_ui_available(self, mock_chatbot):
        """Test that Swagger UI is available"""
        interface = FastAPIInterface(mock_chatbot)
        client = TestClient(interface.app)

        response = client.get("/docs")

        assert response.status_code == 200

