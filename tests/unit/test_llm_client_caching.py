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


class TestLLMFromOverride:
    """Tests for LLM.from_override() factory method."""

    def test_parses_provider_colon_model_format(self):
        """'provider:model' string should set both provider and model."""
        base = LLM(provider="openai", model="gpt-4.1", temperature=0.0, api_key="sk-test", base_url="https://api.openai.com/v1")
        result = LLM.from_override(base, "anthropic:claude-haiku-4-5")
        assert result.provider == "anthropic"
        assert result.model == "claude-haiku-4-5"

    def test_plain_model_inherits_provider(self):
        """Plain model name without ':' should inherit provider from base."""
        base = LLM(provider="openai", model="gpt-4.1", temperature=0.0, api_key="sk-test")
        result = LLM.from_override(base, "gpt-4.1-mini")
        assert result.provider == "openai"
        assert result.model == "gpt-4.1-mini"

    def test_inherits_temperature_and_api_key(self):
        """Temperature and api_key should always be inherited from base."""
        base = LLM(provider="openai", model="gpt-4.1", temperature=0.7, api_key="sk-test")
        result = LLM.from_override(base, "gpt-4.1-mini")
        assert result.temperature == 0.7
        assert result.api_key == "sk-test"

    def test_same_provider_inherits_base_url(self):
        """When provider stays the same, base_url should be inherited."""
        base = LLM(provider="openai", model="gpt-4.1", temperature=0.0, api_key="sk-test", base_url="https://custom.openai.com/v1")
        result = LLM.from_override(base, "gpt-4.1-mini")
        assert result.base_url == "https://custom.openai.com/v1"

    def test_different_provider_clears_base_url(self):
        """When provider changes, base_url should be None (provider-specific)."""
        base = LLM(provider="openai", model="gpt-4.1", temperature=0.0, api_key="sk-test", base_url="https://api.openai.com/v1")
        result = LLM.from_override(base, "anthropic:claude-haiku-4-5")
        assert result.base_url is None

    def test_returns_new_instance(self):
        """from_override() must return a new LLM, not mutate base."""
        base = LLM(provider="openai", model="gpt-4.1", temperature=0.0, api_key="sk-test")
        result = LLM.from_override(base, "gpt-4.1-mini")
        assert result is not base
        assert base.model == "gpt-4.1"  # base unchanged
