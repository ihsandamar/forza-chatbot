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


def test_app_base_exception_does_not_shadow_python_builtin():
    """AppBaseException must not shadow Python's built-in BaseException."""
    from src.core.exceptions import AppBaseException
    # Python's built-in must still be accessible directly
    try:
        raise ValueError("sentinel")
    except BaseException as e:
        # This 'BaseException' must be Python's built-in, NOT ours
        assert type(e) is ValueError, "Python's built-in BaseException must catch ValueError"

    # Our AppBaseException must NOT be the same as Python's BaseException
    assert AppBaseException is not BaseException, \
        "AppBaseException must not be Python's built-in BaseException"


def test_app_base_exception_is_importable_and_functional():
    from src.core.exceptions import AppBaseException
    exc = AppBaseException(message="test error", error_code="TEST_ERR")
    assert exc.message == "test error"
    assert exc.error_code == "TEST_ERR"
    assert "[TEST_ERR] test error" == str(exc)
    d = exc.to_dict()
    assert d["error_code"] == "TEST_ERR"
    assert d["message"] == "test error"


def test_chatbot_base_exception_inherits_from_app_base():
    from src.core.exceptions import AppBaseException
    from src.core.exceptions import ChatbotBaseException
    assert issubclass(ChatbotBaseException, AppBaseException)
