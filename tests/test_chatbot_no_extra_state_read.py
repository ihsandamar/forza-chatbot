"""Test that chatbot does not call aget_state() after successful invoke."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.chatbot import Chatbot
from src.models.llm import LLM


@pytest.fixture
def chatbot_with_mock_graph():
    mock_llm = MagicMock(spec=LLM)
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"messages": [{"role": "assistant", "content": "ok"}]})
    mock_graph.aget_state = AsyncMock(return_value=MagicMock(tasks=[]))

    chatbot = Chatbot(llm=mock_llm, graph=mock_graph)
    return chatbot, mock_graph


@pytest.mark.asyncio
async def test_no_aget_state_after_successful_invoke(chatbot_with_mock_graph):
    """aget_state should NOT be called after a successful (non-interrupt) invoke."""
    chatbot, mock_graph = chatbot_with_mock_graph

    state = {"messages": [{"role": "user", "content": "hello"}]}
    await chatbot._invoke_graph_async(state, thread_id="test-session")

    # aget_state should NOT have been called
    mock_graph.aget_state.assert_not_called()
