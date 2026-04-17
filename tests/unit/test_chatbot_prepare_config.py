"""Tests for Chatbot._prepare_config() after RuntimeAgentSettings integration."""
from unittest.mock import MagicMock
import pytest
from src.core.chatbot import Chatbot
from src.core.runtime_agent_settings import RuntimeAgentSettings, SubAgentSettings


def _make_chatbot(runtime_agent_settings=None, base_config=None):
    if base_config is None:
        base_config = {"configurable": {"thread_id": "base"}}
    return Chatbot(
        llm=MagicMock(),
        graph=MagicMock(),
        config=base_config,
        runtime_agent_settings=runtime_agent_settings,
    )


class TestPrepareConfig:
    def test_thread_id_override(self):
        bot = _make_chatbot()
        result = bot._prepare_config(thread_id="sess-1")
        assert result["configurable"]["thread_id"] == "sess-1"

    def test_thread_id_falls_back_to_base(self):
        bot = _make_chatbot(base_config={"configurable": {"thread_id": "default-thread"}})
        result = bot._prepare_config()
        assert result["configurable"]["thread_id"] == "default-thread"

    def test_no_assistant_config_key(self):
        """Old nested assistant_config must be gone."""
        bot = _make_chatbot()
        result = bot._prepare_config(thread_id="x")
        assert "assistant_config" not in result["configurable"]

    def test_settings_flat_keys_merged(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="tok123", system_prompt="route!")
        })
        bot = _make_chatbot(runtime_agent_settings=settings)
        result = bot._prepare_config(thread_id="x")
        assert result["configurable"]["routing_token"] == "tok123"
        assert result["configurable"]["routing_system_prompt"] == "route!"
        assert result["configurable"]["thread_id"] == "x"

    def test_none_settings_no_extra_keys(self):
        bot = _make_chatbot(runtime_agent_settings=None)
        result = bot._prepare_config(thread_id="x")
        assert set(result["configurable"].keys()) == {"thread_id"}

    def test_none_token_not_in_configurable(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token=None, system_prompt="hi")
        })
        bot = _make_chatbot(runtime_agent_settings=settings)
        result = bot._prepare_config(thread_id="x")
        assert "routing_token" not in result["configurable"]
        assert result["configurable"]["routing_system_prompt"] == "hi"

    def test_multiple_agents_all_merged(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="tok"),
            "chat": SubAgentSettings(system_prompt="chat!"),
        })
        bot = _make_chatbot(runtime_agent_settings=settings)
        result = bot._prepare_config(thread_id="x")
        assert result["configurable"]["routing_token"] == "tok"
        assert result["configurable"]["chat_system_prompt"] == "chat!"


class TestRuntimeSettingsMethods:
    def test_get_runtime_settings_returns_none_by_default(self):
        bot = _make_chatbot()
        assert bot.get_runtime_settings() is None

    def test_get_runtime_settings_returns_settings(self):
        settings = RuntimeAgentSettings()
        bot = _make_chatbot(runtime_agent_settings=settings)
        assert bot.get_runtime_settings() is settings

    def test_update_runtime_settings(self):
        bot = _make_chatbot()
        new_settings = RuntimeAgentSettings(subagents={"routing": SubAgentSettings(token="new")})
        bot.update_runtime_settings(new_settings)
        assert bot.get_runtime_settings() is new_settings

    def test_init_no_assistant_config_param(self):
        """Verify old assistant_config param is gone."""
        import inspect
        sig = inspect.signature(Chatbot.__init__)
        assert "assistant_config" not in sig.parameters
        assert "runtime_config" not in sig.parameters
        assert "runtime_agent_settings" in sig.parameters
