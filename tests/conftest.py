"""
Pytest Configuration

Shared fixtures and configuration for all tests.
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime

# Fixtures for StandardState and StandardResponse
from src.models.standard_types import (
    StandardState, StandardResponse, ResponseType,
    StandardAction, AssistantConfigBase
)


@pytest.fixture
def sample_state():
    """Create a sample StandardState for testing"""
    return StandardState(
        messages=[
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi! How can I help?"}
        ],
        session_id="test-session-123"
    )


@pytest.fixture
def sample_response():
    """Create a sample StandardResponse for testing"""
    return StandardResponse(
        text="This is a test response",
        response_type=ResponseType.TEXT,
        confidence=0.95,
        action=StandardAction(type="none"),
        session_id="test-session-123"
    )


@pytest.fixture
def sample_config():
    """Create a sample AssistantConfig for testing"""
    return AssistantConfigBase(
        system_prompt="You are a helpful assistant",
        assistant_name="TestBot",
        temperature=0.7
    )


# Mock fixtures for Chatbot and dependencies

@pytest.fixture
def mock_llm():
    """Create a mock LLM"""
    llm = Mock()
    llm.invoke = Mock(return_value=Mock(content="Mock response"))
    return llm


@pytest.fixture
def mock_graph():
    """Create a mock LangGraph"""
    graph = Mock()
    graph.invoke = Mock(return_value={"messages": [Mock(content="Graph output")]})
    graph.__class__.__name__ = "MockGraph"
    return graph


@pytest.fixture
def mock_adapter():
    """Create a mock StateAdapter"""
    adapter = Mock()
    adapter.to_graph_state = Mock(return_value={"test": "state"})
    adapter.from_graph_state = Mock(return_value="Formatted response")
    adapter.to_api_response = Mock(return_value={"text": "API response"})
    adapter.get_required_params = Mock(return_value=[])
    adapter.__class__.__name__ = "MockAdapter"
    return adapter


@pytest.fixture
def mock_chatbot(mock_llm, mock_graph, mock_adapter, sample_config):
    """
    Create a mock Chatbot instance.

    This is useful for testing interfaces without creating
    a full Chatbot instance.
    """
    chatbot = Mock()

    # Basic attributes
    chatbot.llm = mock_llm
    chatbot.graph = mock_graph
    chatbot.adapter = mock_adapter
    chatbot.session_id = "test-session-123"

    # Methods
    chatbot.chat = Mock(return_value=StandardResponse(
        text="Test response",
        session_id="test-session-123"
    ))

    chatbot.configure = Mock()

    chatbot.get_config = Mock(return_value={
        "system_prompt": "You are a helpful assistant",
        "assistant_name": "TestBot",
        "temperature": 0.7
    })

    chatbot.get_history = Mock(return_value=[
        {
            "role": "user",
            "content": "Hello",
            "timestamp": datetime.now().isoformat()
        },
        {
            "role": "assistant",
            "content": "Hi there",
            "timestamp": datetime.now().isoformat()
        }
    ])

    chatbot.clear_history = Mock()

    chatbot.get_session_info = Mock(return_value={
        "session_id": "test-session-123",
        "created_at": datetime.now().isoformat(),
        "last_interaction": datetime.now().isoformat(),
        "message_count": 2,
        "assistant_name": "TestBot",
        "configuration": {
            "system_prompt": "You are a helpful assistant",
            "temperature": 0.7
        }
    })

    return chatbot


# Markers for test categorization

def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "interface: mark test as an interface test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
