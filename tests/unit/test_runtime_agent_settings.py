"""Unit tests for RuntimeAgentSettings."""
import dataclasses
import pytest
from src.core.runtime_agent_settings import SubAgentSettings, RuntimeAgentSettings


class TestSubAgentSettings:
    def test_defaults(self):
        s = SubAgentSettings()
        assert s.system_prompt is None
        assert s.token is None

    def test_with_values(self):
        s = SubAgentSettings(system_prompt="hello", token="tok")
        assert s.system_prompt == "hello"
        assert s.token == "tok"


class TestToGraphConfigurable:
    def test_empty(self):
        settings = RuntimeAgentSettings()
        assert settings.to_graph_configurable() == {}

    def test_full_routing(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(system_prompt="route me", token="abc")
        })
        result = settings.to_graph_configurable()
        assert result == {
            "routing_system_prompt": "route me",
            "routing_token": "abc",
        }

    def test_skips_none_system_prompt(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(system_prompt=None, token="abc")
        })
        result = settings.to_graph_configurable()
        assert "routing_system_prompt" not in result
        assert result["routing_token"] == "abc"

    def test_skips_none_token(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(system_prompt="route", token=None)
        })
        result = settings.to_graph_configurable()
        assert "routing_token" not in result
        assert result["routing_system_prompt"] == "route"

    def test_multiple_agents(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="tok"),
            "chat": SubAgentSettings(system_prompt="chat!"),
        })
        result = settings.to_graph_configurable()
        assert result["routing_token"] == "tok"
        assert result["chat_system_prompt"] == "chat!"
        assert "routing_system_prompt" not in result
        assert "chat_token" not in result


class TestUpdateSubagent:
    def test_immutable(self):
        original = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="old")
        })
        updated = original.update_subagent("routing", token="new")
        assert original.subagents["routing"].token == "old"  # unchanged
        assert updated.subagents["routing"].token == "new"

    def test_new_agent(self):
        settings = RuntimeAgentSettings()
        updated = settings.update_subagent("chat", system_prompt="hi")
        assert updated.subagents["chat"].system_prompt == "hi"

    def test_partial_update_preserves_other_fields(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(system_prompt="route", token="tok")
        })
        updated = settings.update_subagent("routing", token="new-tok")
        assert updated.subagents["routing"].system_prompt == "route"  # preserved
        assert updated.subagents["routing"].token == "new-tok"

    def test_ignores_unknown_kwargs(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="tok")
        })
        # unknown kwargs (e.g., temperature) are silently ignored
        updated = settings.update_subagent("routing", temperature=0.7)
        assert updated.subagents["routing"].token == "tok"


class TestGetSubagent:
    def test_existing(self):
        s = SubAgentSettings(token="x")
        settings = RuntimeAgentSettings(subagents={"routing": s})
        assert settings.get_subagent("routing") is s

    def test_missing_returns_none(self):
        settings = RuntimeAgentSettings()
        assert settings.get_subagent("routing") is None


class TestFromSupervisorConfig:
    def test_maps_fields(self):
        from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration
        cfg = SupervisorAssistantConfiguration(
            routing_token="my-token",
            routing_system_prompt="route!",
            chat_system_prompt="chat!",
        )
        settings = RuntimeAgentSettings.from_supervisor_config(cfg)
        assert settings.subagents["routing"].token == "my-token"
        assert settings.subagents["routing"].system_prompt == "route!"
        assert settings.subagents["chat"].system_prompt == "chat!"
        assert settings.subagents["chat"].token is None

    def test_empty_string_token_becomes_none(self):
        from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration
        cfg = SupervisorAssistantConfiguration(routing_token="")  # default
        settings = RuntimeAgentSettings.from_supervisor_config(cfg)
        assert settings.subagents["routing"].token is None
