"""Verify extract_response works after rename from _from_graph_state."""
import pytest
from unittest.mock import MagicMock
from src.core.chatbot import Chatbot


@pytest.fixture
def chatbot():
    llm = MagicMock()
    graph = MagicMock()
    return Chatbot(llm=llm, graph=graph)


def test_extract_response_from_message_objects(chatbot):
    msg = MagicMock()
    msg.content = "Hello from graph"
    output = {"messages": [msg]}
    assert chatbot.extract_response(output) == "Hello from graph"


def test_extract_response_from_dict_messages(chatbot):
    output = {"messages": [{"role": "assistant", "content": "Hi there"}]}
    assert chatbot.extract_response(output) == "Hi there"


def test_extract_response_empty_messages(chatbot):
    output = {"messages": []}
    result = chatbot.extract_response(output)
    assert isinstance(result, str)
    assert len(result) > 0  # Returns a fallback string


def test_extract_response_non_dict_input(chatbot):
    result = chatbot.extract_response("raw string")
    assert result == "raw string"


def test_private_name_gone(chatbot):
    """_from_graph_state must no longer exist as a method name."""
    assert not hasattr(chatbot, "_from_graph_state"), \
        "_from_graph_state should have been renamed to extract_response"
