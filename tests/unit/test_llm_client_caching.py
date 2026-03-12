"""Tests for LLM client caching."""
import pytest
from unittest.mock import patch, MagicMock
from src.models.llm import LLM


class TestLLMClientCaching:
    """Test that get_chat() returns the same instance on repeated calls."""

    @patch("src.models.llm.ChatOpenAI")
    def test_get_chat_returns_same_instance_openai(self, mock_cls):
        """OpenAI client should be created once and reused."""
        mock_cls.return_value = MagicMock(name="openai_client")
        llm = LLM(provider="openai", model="gpt-4o-mini", api_key="test")

        client1 = llm.get_chat()
        client2 = llm.get_chat()

        assert client1 is client2, "get_chat() should return the same instance"
        assert mock_cls.call_count == 1, "ChatOpenAI should be instantiated only once"

    @patch("src.models.llm.ChatAnthropic")
    def test_get_chat_returns_same_instance_anthropic(self, mock_cls):
        """Anthropic client should be created once and reused."""
        mock_cls.return_value = MagicMock(name="anthropic_client")
        llm = LLM(provider="anthropic", model="claude-sonnet-4-20250514", api_key="test")

        client1 = llm.get_chat()
        client2 = llm.get_chat()

        assert client1 is client2
        assert mock_cls.call_count == 1

    @patch("src.models.llm.ChatOpenAI")
    def test_different_llm_instances_have_separate_caches(self, mock_cls):
        """Two LLM instances should maintain independent caches."""
        mock_cls.side_effect = [MagicMock(name="client_a"), MagicMock(name="client_b")]

        llm1 = LLM(provider="openai", model="gpt-4o-mini", api_key="test")
        llm2 = LLM(provider="openai", model="gpt-4o", api_key="test")

        c1 = llm1.get_chat()
        c2 = llm2.get_chat()

        assert c1 is not c2, "Different LLM instances should have different clients"
