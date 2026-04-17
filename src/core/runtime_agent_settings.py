"""
RuntimeAgentSettings — Lean sub-agent settings container.

Produces flat LangGraph configurable keys so nodes can read:
    config["configurable"]["routing_token"]
    config["configurable"]["routing_system_prompt"]

Usage:
    settings = RuntimeAgentSettings(subagents={
        "routing": SubAgentSettings(token="abc", system_prompt="..."),
        "chat":    SubAgentSettings(system_prompt="..."),
    })
    configurable = settings.to_graph_configurable()
    # → {"routing_token": "abc", "routing_system_prompt": "...", "chat_system_prompt": "..."}
"""
from __future__ import annotations
import dataclasses
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration


@dataclasses.dataclass
class SubAgentSettings:
    """Runtime settings for one sub-agent."""
    system_prompt: Optional[str] = None
    token: Optional[str] = None


@dataclasses.dataclass
class RuntimeAgentSettings:
    """Container for all sub-agent settings."""
    subagents: dict[str, SubAgentSettings] = dataclasses.field(default_factory=dict)

    def to_graph_configurable(self) -> dict:
        """Flat dict to merge into LangGraph configurable."""
        result: dict = {}
        for name, s in self.subagents.items():
            if s.system_prompt is not None:
                result[f"{name}_system_prompt"] = s.system_prompt
            if s.token is not None:
                result[f"{name}_token"] = s.token
        return result

    def get_subagent(self, name: str) -> Optional[SubAgentSettings]:
        return self.subagents.get(name)

    def update_subagent(self, name: str, **kwargs) -> RuntimeAgentSettings:
        """Immutable update — returns new instance."""
        new = dict(self.subagents)
        current = new.get(name) or SubAgentSettings()
        allowed = {k: v for k, v in kwargs.items() if k in ("system_prompt", "token")}
        new[name] = dataclasses.replace(current, **allowed)
        return RuntimeAgentSettings(subagents=new)

    @classmethod
    def from_supervisor_config(cls, cfg: "SupervisorAssistantConfiguration") -> RuntimeAgentSettings:
        """
        Initialise from SupervisorAssistantConfiguration defaults.
        Called once at startup to create the live settings object.
        """
        return cls(subagents={
            "routing": SubAgentSettings(
                system_prompt=cfg.routing_system_prompt or None,
                token=cfg.routing_token or None,
            ),
            "chat": SubAgentSettings(
                system_prompt=cfg.chat_system_prompt or None,
            ),
        })


__all__ = ["SubAgentSettings", "RuntimeAgentSettings"]
