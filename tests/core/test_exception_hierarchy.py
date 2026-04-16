"""Verify the 5 live exception classes survive the pruning."""
import pytest
from src.core.exceptions.chatbot_exception import (
    ChatbotBaseException,
    ConfigurationException,
    MessageProcessingException,
    GraphExecutionException,
    GraphInvocationException,
    InvalidGraphStateException,
)


def test_configuration_exception_is_raisable():
    with pytest.raises(ConfigurationException) as exc_info:
        raise ConfigurationException("bad config")
    assert exc_info.value.error_code == "CONFIG_ERROR"


def test_message_processing_exception_is_raisable():
    with pytest.raises(MessageProcessingException) as exc_info:
        raise MessageProcessingException("bad message")
    assert exc_info.value.error_code == "MESSAGE_ERROR"


def test_graph_execution_exception_is_raisable():
    with pytest.raises(GraphExecutionException):
        raise GraphExecutionException("graph failed")


def test_graph_invocation_exception_is_raisable():
    with pytest.raises(GraphInvocationException):
        raise GraphInvocationException("invocation failed", graph_name="test")


def test_invalid_graph_state_exception_is_raisable():
    with pytest.raises(InvalidGraphStateException):
        raise InvalidGraphStateException("bad state", state_type="dict")


def test_all_keepers_are_subclass_of_base():
    for cls in (ConfigurationException, MessageProcessingException,
                GraphExecutionException, GraphInvocationException,
                InvalidGraphStateException):
        assert issubclass(cls, ChatbotBaseException)
