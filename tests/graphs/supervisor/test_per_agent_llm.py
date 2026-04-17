"""Tests for SupervisorGraph._resolve_agent_llm() priority logic."""
import pytest
from unittest.mock import MagicMock
from src.models.llm import LLM


def _make_supervisor(app_config):
    """Create a SupervisorGraph instance bypassing __init__."""
    from src.graphs.supervisor.graph import SupervisorGraph
    graph = SupervisorGraph.__new__(SupervisorGraph)
    graph.llm = LLM(provider="openai", model="gpt-4.1", temperature=0.0, api_key="sk-test")
    graph.app_config = app_config
    return graph


class TestResolveAgentLLM:
    """Test _resolve_agent_llm() priority: Studio field → YAML agents → global."""

    def test_falls_back_to_global_llm_when_no_override(self):
        """No Studio field, no YAML agents → returns self.llm unchanged."""
        app_config = MagicMock(spec=[])  # no attributes at all
        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is graph.llm

    def test_studio_override_takes_precedence(self):
        """Non-empty routing_model on app_config → creates new LLM."""
        app_config = MagicMock(spec=["routing_model"])
        app_config.routing_model = "anthropic:claude-haiku-4-5"
        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is not graph.llm
        assert result.provider == "anthropic"
        assert result.model == "claude-haiku-4-5"

    def test_empty_studio_field_falls_through_to_yaml(self):
        """Empty routing_model → skip Studio override, check YAML agents section."""
        mock_agent_cfg = MagicMock(spec=["model"])
        mock_agent_cfg.model = "gpt-4.1-mini"
        mock_agents = MagicMock(spec=["routing"])
        mock_agents.routing = mock_agent_cfg

        app_config = MagicMock(spec=["routing_model", "agents"])
        app_config.routing_model = ""
        app_config.agents = mock_agents

        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is not graph.llm
        assert result.provider == "openai"
        assert result.model == "gpt-4.1-mini"

    def test_yaml_agents_section_absent_falls_back_to_global(self):
        """Empty Studio field + no agents section → returns self.llm."""
        app_config = MagicMock(spec=["routing_model"])
        app_config.routing_model = ""
        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is graph.llm

    def test_yaml_agent_model_absent_falls_back_to_global(self):
        """agents section present but specific agent has no model attr → returns self.llm."""
        mock_agent_cfg = MagicMock(spec=[])  # no model attribute
        mock_agents = MagicMock(spec=["routing"])
        mock_agents.routing = mock_agent_cfg

        app_config = MagicMock(spec=["routing_model", "agents"])
        app_config.routing_model = ""
        app_config.agents = mock_agents

        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is graph.llm

    def test_app_config_none_falls_back_to_global(self):
        """app_config=None should immediately return self.llm."""
        graph = _make_supervisor(None)
        result = graph._resolve_agent_llm("routing")
        assert result is graph.llm

    def test_malformed_studio_model_string_falls_back_to_global(self):
        """Malformed 'provider:' string should log warning and fall back to global LLM."""
        app_config = MagicMock(spec=["routing_model"])
        app_config.routing_model = "openai:"  # malformed — empty model after colon
        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is graph.llm  # fallback, not crash
