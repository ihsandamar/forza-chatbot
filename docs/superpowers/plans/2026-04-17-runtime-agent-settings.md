# RuntimeAgentSettings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 445-line dead `RuntimeConfiguration` with `RuntimeAgentSettings` — a lean dataclass that actually reaches LangGraph nodes via flat configurable keys, fixes the always-503 `/api/configuration` endpoint, and deletes ~750 lines of dead code.

**Architecture:** New `src/core/runtime_agent_settings.py` holds `SubAgentSettings(system_prompt, token)` and `RuntimeAgentSettings` which produces a flat `{routing_token: ..., routing_system_prompt: ...}` dict. `Chatbot._prepare_config()` merges this into the LangGraph `configurable` dict (instead of nesting everything under `assistant_config`). `dependencies.py` initialises the settings object at startup so the API GET works immediately.

**Tech Stack:** Python 3.11 dataclasses, FastAPI, Pydantic v2, LangGraph, pytest

---

## File Map

| File | Action | What changes |
|---|---|---|
| `src/core/runtime_agent_settings.py` | **Create** | New `SubAgentSettings` + `RuntimeAgentSettings` |
| `src/core/chatbot.py` | **Modify** | Remove `assistant_config`/`runtime_config`, add `runtime_agent_settings`, fix `_prepare_config` |
| `src/api/dependencies.py` | **Modify** | Init `RuntimeAgentSettings` at startup |
| `src/api/models/responses/configuration.py` | **Modify** | Simplify `SubAgentConfigView`, remove `LLMConfigView`, `ConfigFieldView` |
| `src/api/routes/configuration.py` | **Modify** | Rewrite: no LLM section, use `get_runtime_settings()` |
| `src/api/models/requests/configuration.py` | **Modify** | Delete `LLMConfigUpdateRequest`, remove `llm` field |
| `src/interfaces/gradio_interface.py` | **Modify** | Remove LLM inputs, use `RuntimeAgentSettings` |
| `src/core/runtime_config.py` | **Delete** | 445-line dead file |
| `src/graphs/base/graph_config.py` | **Delete** | 306-line dead file |

---

### Task 1: Create `src/core/runtime_agent_settings.py`

**Files:**
- Create: `src/core/runtime_agent_settings.py`
- Test: `tests/unit/test_runtime_agent_settings.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_runtime_agent_settings.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_runtime_agent_settings.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.core.runtime_agent_settings'`

- [ ] **Step 3: Implement `src/core/runtime_agent_settings.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_runtime_agent_settings.py -v
```

Expected: 16 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add src/core/runtime_agent_settings.py tests/unit/test_runtime_agent_settings.py
git commit -m "feat(core): add RuntimeAgentSettings dataclass with SubAgentSettings"
```

---

### Task 2: Update `src/core/chatbot.py`

**Files:**
- Modify: `src/core/chatbot.py`
- Test: `tests/unit/test_chatbot_prepare_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_chatbot_prepare_config.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_chatbot_prepare_config.py -v
```

Expected: multiple failures — `runtime_config` still exists, `assistant_config` still in signature, wrong `_prepare_config` behavior.

- [ ] **Step 3: Edit `src/core/chatbot.py` — update imports**

Replace lines 26 (the RuntimeConfiguration import):

**Find:**
```python
from src.core.runtime_config import RuntimeConfiguration
```

**Replace with:**
```python
from src.core.runtime_agent_settings import RuntimeAgentSettings
```

- [ ] **Step 4: Edit `src/core/chatbot.py` — rewrite `__init__`**

**Find:**
```python
    def __init__(
        self,
        llm: LLM,
        graph: BaseGraph,
        config: dict = None,
        assistant_config: dict = None,
        runtime_config: Optional[RuntimeConfiguration] = None
    ):
        """
        Initialize chatbot.

        Args:
            llm: Language model instance
            graph: LangGraph instance
            config: Graph configuration
            assistant_config: Assistant-specific configuration
            runtime_config: Runtime configuration for dynamic updates
        """
        self.llm = llm
        self.graph = graph
        self.config = config if config else {}
        self.assistant_config = assistant_config if assistant_config else {}
        self.runtime_config = runtime_config
```

**Replace with:**
```python
    def __init__(
        self,
        llm: LLM,
        graph: BaseGraph,
        config: dict = None,
        runtime_agent_settings: Optional[RuntimeAgentSettings] = None,
    ):
        """
        Initialize chatbot.

        Args:
            llm: Language model instance
            graph: LangGraph instance
            config: Graph configuration
            runtime_agent_settings: Sub-agent runtime settings (system_prompt, token)
        """
        self.llm = llm
        self.graph = graph
        self.config = config if config else {}
        self.runtime_agent_settings = runtime_agent_settings
```

- [ ] **Step 5: Edit `src/core/chatbot.py` — rewrite `_prepare_config`**

**Find:**
```python
    def _prepare_config(self, thread_id: str = None) -> dict:
        """
        Prepare full configuration with assistant_config and thread_id.

        DRY: Extracted common config preparation logic.

        Args:
            thread_id: Optional thread ID for graph execution (session_id)

        Raises:
            ConfigurationException: If config preparation fails

        Returns:
            Full config dict with configurable section
        """
        try:
            assistant_config_dict = (
                self.assistant_config.to_dict()
                if hasattr(self.assistant_config, 'to_dict')
                else self.assistant_config
            )

            if not isinstance(self.config, dict):
                raise ConfigurationException(
                    "Config must be a dictionary",
                    context={"config_type": type(self.config).__name__}
                )

            # Build config without deepcopy — LangGraph doesn't mutate this
            configurable = {
                **self.config.get("configurable", {}),
                "assistant_config": assistant_config_dict,
            }
            if thread_id:
                configurable["thread_id"] = thread_id

            return {**self.config, "configurable": configurable}
        except ConfigurationException:
            raise
        except Exception as e:
            raise ConfigurationException(
                f"Failed to prepare configuration: {str(e)}",
                context={"original_error": str(e)}
            ) from e
```

**Replace with:**
```python
    def _prepare_config(self, thread_id: str = None) -> dict:
        """
        Prepare full configuration for graph invocation.

        Merges runtime_agent_settings as flat keys into configurable so nodes can read:
            config["configurable"]["routing_token"]
            config["configurable"]["routing_system_prompt"]

        Args:
            thread_id: Session ID — overrides base config thread_id when provided

        Raises:
            ConfigurationException: If config preparation fails

        Returns:
            Full config dict with configurable section
        """
        try:
            if not isinstance(self.config, dict):
                raise ConfigurationException(
                    "Config must be a dictionary",
                    context={"config_type": type(self.config).__name__}
                )
            configurable = dict(self.config.get("configurable", {}))
            if self.runtime_agent_settings:
                configurable.update(self.runtime_agent_settings.to_graph_configurable())
            if thread_id:
                configurable["thread_id"] = thread_id
            return {**self.config, "configurable": configurable}
        except ConfigurationException:
            raise
        except Exception as e:
            raise ConfigurationException(
                f"Failed to prepare configuration: {str(e)}",
                context={"original_error": str(e)}
            ) from e
```

- [ ] **Step 6: Edit `src/core/chatbot.py` — replace runtime config methods**

Replace the entire "Runtime Configuration Management" section (lines ~498-581) with:

**Find:**
```python
    # ========================================
    # Runtime Configuration Management
    # ========================================

    def get_runtime_config(self) -> Optional[RuntimeConfiguration]:
        """
        Get current runtime configuration.

        Returns:
            RuntimeConfiguration instance or None
        """
        return self.runtime_config

    def update_runtime_config(self, new_config: RuntimeConfiguration):
        """
        Update runtime configuration.

        Note: This updates the configuration but does NOT rebuild the chatbot.
        For LLM or graph type changes, you need to rebuild the chatbot.
        For sub-agent config changes (prompts, tokens), they will be applied
        on the next graph execution.

        Args:
            new_config: New RuntimeConfiguration instance

        Example:
            # Update sub-agent token
            new_config = chatbot.runtime_config.update_subagent(
                "routing",
                token="new-token"
            )
            chatbot.update_runtime_config(new_config)
        """
        self.runtime_config = new_config

        # Update graph config with new configurable params
        if "configurable" not in self.config:
            self.config["configurable"] = {}
        self.config["configurable"].update(new_config.to_graph_configurable())

    def get_config_for_ui(self) -> Dict[str, Any]:
        """
        Get configuration in UI-friendly format.

        Returns:
            Dict with configuration data suitable for display in UI

        Example:
            config_data = chatbot.get_config_for_ui()
            # Returns:
            # {
            #     "llm": {"model": "gpt-4o-mini", "temperature": 0.0, ...},
            #     "graph_type": "supervisor",
            #     "subagents": {
            #         "routing": {"system_prompt": "...", "token": "***", ...}
            #     }
            # }
        """
        if self.runtime_config:
            config_dict = self.runtime_config.to_dict()

            # Mask sensitive data for UI
            if "llm" in config_dict and config_dict["llm"].get("api_key"):
                api_key = config_dict["llm"]["api_key"]
                if len(api_key) > 8:
                    config_dict["llm"]["api_key"] = f"{api_key[:4]}...{api_key[-4:]}"

            # Mask tokens in subagents
            for name, subagent in config_dict.get("subagents", {}).items():
                if subagent.get("token"):
                    token = subagent["token"]
                    if len(token) > 8:
                        subagent["token"] = f"{token[:4]}...{token[-4:]}"

            return config_dict

        # Fallback for chatbots without runtime config
        return {
            "llm": {
                "model": getattr(self.llm, "model_name", "unknown"),
                "temperature": getattr(self.llm, "temperature", 0.0)
            },
            "graph_type": getattr(self.graph, "name", "unknown"),
            "subagents": {}
        }
```

**Replace with:**
```python
    # ========================================
    # Runtime Settings Management
    # ========================================

    def get_runtime_settings(self) -> Optional[RuntimeAgentSettings]:
        """Get current runtime agent settings."""
        return self.runtime_agent_settings

    def update_runtime_settings(self, new_settings: RuntimeAgentSettings) -> None:
        """Update runtime agent settings (effective on next graph invocation)."""
        self.runtime_agent_settings = new_settings

    def get_config_for_ui(self) -> Dict[str, Any]:
        """Get configuration in UI-friendly format."""
        if self.runtime_agent_settings:
            return {
                "subagents": {
                    name: {
                        "system_prompt": s.system_prompt,
                        "has_token": bool(s.token),
                    }
                    for name, s in self.runtime_agent_settings.subagents.items()
                }
            }
        return {"subagents": {}}
```

- [ ] **Step 7: Run tests to verify they pass**

```
pytest tests/unit/test_chatbot_prepare_config.py tests/core/test_chatbot_extract_response.py tests/test_chatbot_no_extra_state_read.py -v
```

Expected: all PASSED

- [ ] **Step 8: Commit**

```bash
git add src/core/chatbot.py tests/unit/test_chatbot_prepare_config.py
git commit -m "refactor(core): replace runtime_config/assistant_config with RuntimeAgentSettings in Chatbot"
```

---

### Task 3: Wire startup in `src/api/dependencies.py`

**Files:**
- Modify: `src/api/dependencies.py`

- [ ] **Step 1: Replace the full file contents**

```python
# src/api/dependencies.py
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.core.runtime_agent_settings import RuntimeAgentSettings
from src.models.llm import LLM
from src.graphs.graph_entrypoints import supervisor_graph, _get_config
from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration


# Singleton instances
_chat_service_instance = None
_chatbot_instance = None


def get_chatbot() -> Chatbot:
    """
    Dependency to get Chatbot instance.

    Uses graph_entrypoints.supervisor_graph() directly — same code path as LangGraph dev.
    RuntimeAgentSettings is initialised from SupervisorAssistantConfiguration defaults,
    so GET /api/configuration works from the first request.

    Returns:
        Chatbot: Singleton instance
    """
    global _chatbot_instance
    if _chatbot_instance is None:
        config = _get_config()

        llm = LLM(
            provider=config.llm.provider,
            model=config.llm.model,
            temperature=config.llm.temperature,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )

        compiled = supervisor_graph()

        _chatbot_instance = Chatbot(
            llm=llm,
            graph=compiled,
            config={"configurable": {"thread_id": "1"}},
            runtime_agent_settings=RuntimeAgentSettings.from_supervisor_config(
                SupervisorAssistantConfiguration()
            ),
        )

    return _chatbot_instance


def get_chat_service() -> ChatService:
    """
    Dependency to get ChatService instance.

    Returns:
        ChatService: Singleton instance
    """
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService(get_chatbot())
    return _chat_service_instance
```

- [ ] **Step 2: Run the existing test suite to verify no regressions**

```
pytest tests/api/ tests/core/ tests/unit/ -v
```

Expected: all PASSED

- [ ] **Step 3: Commit**

```bash
git add src/api/dependencies.py
git commit -m "fix(api): init RuntimeAgentSettings at startup — GET /api/configuration no longer 503"
```

---

### Task 4: Simplify response models and rewrite configuration route

> These two files change together because the route builds `SubAgentConfigView(name=..., system_prompt=..., has_token=...)` — if we update the route before the model, the constructor call breaks. Do both in one commit.

**Files:**
- Modify: `src/api/models/responses/configuration.py`
- Modify: `src/api/routes/configuration.py`
- Test: `tests/api/routes/test_configuration_endpoints.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/api/routes/test_configuration_endpoints.py
"""Tests for GET/POST /api/configuration using RuntimeAgentSettings."""
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.configuration import router
from src.api.dependencies import get_chat_service
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.core.runtime_agent_settings import RuntimeAgentSettings, SubAgentSettings


def _make_client(runtime_agent_settings=None) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/configuration")

    mock_chatbot = MagicMock(spec=Chatbot)
    mock_chatbot.get_runtime_settings.return_value = runtime_agent_settings

    mock_service = MagicMock(spec=ChatService)
    mock_service.chatbot = mock_chatbot

    app.dependency_overrides[get_chat_service] = lambda: mock_service
    return TestClient(app)


class TestGetConfiguration:
    def test_returns_200_with_settings(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(system_prompt="route", token="secret-tok"),
            "chat": SubAgentSettings(system_prompt="chat"),
        })
        client = _make_client(settings)
        resp = client.get("/api/configuration")
        assert resp.status_code == 200
        data = resp.json()
        assert "subagents" in data
        assert "routing" in data["subagents"]
        assert data["subagents"]["routing"]["system_prompt"] == "route"
        assert data["subagents"]["routing"]["has_token"] is True
        assert data["subagents"]["routing"]["token_preview"] == "secret-tok"
        assert data["subagents"]["chat"]["has_token"] is False
        assert "available_subagent_types" in data
        assert "routing" in data["available_subagent_types"]

    def test_returns_200_with_empty_settings(self):
        client = _make_client(RuntimeAgentSettings())
        resp = client.get("/api/configuration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["subagents"] == {}
        assert data["available_subagent_types"] == []

    def test_no_llm_field_in_response(self):
        client = _make_client(RuntimeAgentSettings())
        resp = client.get("/api/configuration")
        assert "llm" not in resp.json()

    def test_503_when_no_chatbot(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/configuration")
        mock_service = MagicMock(spec=ChatService)
        mock_service.chatbot = None
        app.dependency_overrides[get_chat_service] = lambda: mock_service
        client = TestClient(app)
        resp = client.get("/api/configuration")
        assert resp.status_code == 503

    def test_token_preview_long_token(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="this-is-a-long-token-value")
        })
        client = _make_client(settings)
        data = client.get("/api/configuration").json()
        assert data["subagents"]["routing"]["token_preview"] == "this-is-a-..."
        assert data["subagents"]["routing"]["has_token"] is True

    def test_token_preview_short_token(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="short")
        })
        client = _make_client(settings)
        data = client.get("/api/configuration").json()
        assert data["subagents"]["routing"]["token_preview"] == "short"


class TestPostConfiguration:
    def test_returns_200_on_valid_update(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="old", system_prompt="old-prompt"),
        })
        client = _make_client(settings)
        resp = client.post("/api/configuration", json={
            "subagents": {"routing": {"token": "new-token"}}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "routing token" in data["message"]

    def test_no_changes_message(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="tok"),
        })
        client = _make_client(settings)
        resp = client.post("/api/configuration", json={"subagents": {}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "No changes"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/api/routes/test_configuration_endpoints.py -v
```

Expected: failures because current route imports `LLMConfigView`, old `SubAgentConfigView` fields, always 503.

- [ ] **Step 3: Rewrite `src/api/models/responses/configuration.py`**

```python
"""
Configuration Response Models.

Simplified: subagents only, no LLM section.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class SubAgentConfigView(BaseModel):
    """View model for one sub-agent's runtime settings."""

    name: str = Field(description="Sub-agent name", example="routing")

    system_prompt: Optional[str] = Field(
        default=None,
        description="Current system prompt for this agent"
    )

    has_token: bool = Field(
        default=False,
        description="Whether a non-empty token is set"
    )

    token_preview: Optional[str] = Field(
        default=None,
        description="First 10 chars of token + '...' (or full token if ≤ 10 chars)"
    )


class ConfigurationView(BaseModel):
    """Main view model for runtime configuration (subagents only)."""

    subagents: Dict[str, SubAgentConfigView] = Field(
        description="Sub-agent configurations, keyed by agent name"
    )

    available_subagent_types: List[str] = Field(
        description="List of available sub-agent names"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "subagents": {
                    "routing": {
                        "name": "routing",
                        "system_prompt": "Sen Forza navigasyon asistanısın...",
                        "has_token": True,
                        "token_preview": "your-api-t..."
                    }
                },
                "available_subagent_types": ["routing", "chat"]
            }
        }


class ConfigurationUpdateResponse(BaseModel):
    """Response model for configuration update operations."""

    success: bool = Field(description="Whether the update was successful")

    message: str = Field(description="Human-readable message about the update")

    updated_config: ConfigurationView = Field(description="The updated configuration")


__all__ = [
    "SubAgentConfigView",
    "ConfigurationView",
    "ConfigurationUpdateResponse",
]
```

- [ ] **Step 4: Rewrite `src/api/routes/configuration.py`**

```python
"""
Configuration Routes — sub-agent runtime settings only.

GET  /api/configuration  → current subagent settings
POST /api/configuration  → update system_prompt / token per agent
"""
import logging
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.services.chat_service import ChatService
from src.api.dependencies import get_chat_service
from src.api.models.requests.configuration import (
    ConfigurationUpdateRequest,
    SubAgentConfigUpdateRequest,
)
from src.api.models.responses.configuration import (
    ConfigurationView,
    ConfigurationUpdateResponse,
    SubAgentConfigView,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_view(settings) -> ConfigurationView:
    """Build ConfigurationView from RuntimeAgentSettings."""
    subagent_views: Dict[str, SubAgentConfigView] = {}
    if settings:
        for name, s in settings.subagents.items():
            token_preview = None
            if s.token:
                token_preview = s.token[:10] + "..." if len(s.token) > 10 else s.token
            subagent_views[name] = SubAgentConfigView(
                name=name,
                system_prompt=s.system_prompt,
                has_token=bool(s.token),
                token_preview=token_preview,
            )
    return ConfigurationView(
        subagents=subagent_views,
        available_subagent_types=list(subagent_views.keys()),
    )


@router.get(
    "",
    response_model=ConfigurationView,
    summary="Get current sub-agent settings",
)
async def get_configuration(
    chat_service: ChatService = Depends(get_chat_service),
) -> ConfigurationView:
    if not chat_service.chatbot:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chatbot not initialized",
        )
    return _build_view(chat_service.chatbot.get_runtime_settings())


@router.post(
    "",
    response_model=ConfigurationUpdateResponse,
    summary="Update sub-agent settings",
)
async def update_configuration(
    update_request: ConfigurationUpdateRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> ConfigurationUpdateResponse:
    if not chat_service.chatbot:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chatbot not initialized",
        )
    settings = chat_service.chatbot.get_runtime_settings()
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime settings not available",
        )

    updated_items = []
    if update_request.subagents:
        for agent_name, agent_update in update_request.subagents.items():
            agent_updates: dict = {}
            if agent_update.system_prompt is not None:
                agent_updates["system_prompt"] = agent_update.system_prompt
                updated_items.append(f"{agent_name} system_prompt")
            if agent_update.token is not None:
                agent_updates["token"] = agent_update.token
                updated_items.append(f"{agent_name} token")
            if agent_updates:
                settings = settings.update_subagent(agent_name, **agent_updates)

    chat_service.chatbot.update_runtime_settings(settings)
    message = f"Updated: {', '.join(updated_items)}" if updated_items else "No changes"
    return ConfigurationUpdateResponse(
        success=True,
        message=message,
        updated_config=_build_view(settings),
    )


__all__ = ["router"]
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/api/routes/test_configuration_endpoints.py -v
```

Expected: all PASSED

- [ ] **Step 6: Run broader test suite to verify no regressions**

```
pytest tests/api/ tests/unit/ tests/core/ -v
```

Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add src/api/models/responses/configuration.py src/api/routes/configuration.py tests/api/routes/test_configuration_endpoints.py
git commit -m "refactor(api): simplify configuration endpoint — subagents only, fix 503 on GET"
```

---

### Task 5: Simplify request models

**Files:**
- Modify: `src/api/models/requests/configuration.py`

The route no longer imports `LLMConfigUpdateRequest`. Remove it and clean up the request models.

- [ ] **Step 1: Replace the full file contents**

```python
"""
Configuration Request Models.
"""
from typing import Optional, Dict
from pydantic import BaseModel, Field


class SubAgentConfigUpdateRequest(BaseModel):
    """Request model for updating one sub-agent's runtime settings."""

    system_prompt: Optional[str] = Field(
        default=None,
        description="New system prompt for the sub-agent",
        example="Sen Forza navigasyon asistanısın.",
    )

    token: Optional[str] = Field(
        default=None,
        description="Authentication token for the sub-agent",
        example="secret-token-123",
    )


class ConfigurationUpdateRequest(BaseModel):
    """Request model for updating sub-agent runtime settings."""

    subagents: Optional[Dict[str, SubAgentConfigUpdateRequest]] = Field(
        default=None,
        description="Sub-agent updates, keyed by agent name",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "subagents": {
                    "routing": {"token": "your-api-token"},
                    "chat": {"system_prompt": "Sen yardımcı bir asistansın."},
                }
            }
        }


__all__ = ["SubAgentConfigUpdateRequest", "ConfigurationUpdateRequest"]
```

- [ ] **Step 2: Run tests to verify nothing broke**

```
pytest tests/api/ tests/unit/ tests/core/ -v
```

Expected: all PASSED

- [ ] **Step 3: Commit**

```bash
git add src/api/models/requests/configuration.py
git commit -m "refactor(api): remove LLMConfigUpdateRequest — configuration requests are subagent-only"
```

---

### Task 6: Update `src/interfaces/gradio_interface.py`

**Files:**
- Modify: `src/interfaces/gradio_interface.py`

The Gradio interface currently references `RuntimeConfiguration` but it's never passed at runtime (launcher calls `GradioInterface(chat_service)` without it). We replace the import and clean up the settings tab UI to use `RuntimeAgentSettings`.

- [ ] **Step 1: Replace the import**

**Find:**
```python
from src.core.runtime_config import RuntimeConfiguration
```

**Replace with:**
```python
from src.core.runtime_agent_settings import RuntimeAgentSettings
```

- [ ] **Step 2: Replace the `__init__` parameter**

**Find:**
```python
    def __init__(
        self,
        chat_service: ChatService,
        runtime_config: Optional[RuntimeConfiguration] = None,
        title: str = "Forza Chatbot"
    ):
        """
        Initialize Gradio interface.

        Args:
            chat_service: Configured ChatService instance
            runtime_config: RuntimeConfiguration for dynamic settings UI
            title: Title for the Gradio app
        """
        self.chat_service = chat_service
        self.runtime_config = runtime_config
        self.title = title
```

**Replace with:**
```python
    def __init__(
        self,
        chat_service: ChatService,
        runtime_agent_settings: Optional[RuntimeAgentSettings] = None,
        title: str = "Forza Chatbot"
    ):
        """
        Initialize Gradio interface.

        Args:
            chat_service: Configured ChatService instance
            runtime_agent_settings: Sub-agent runtime settings for the settings tab UI
            title: Title for the Gradio app
        """
        self.chat_service = chat_service
        self.runtime_agent_settings = runtime_agent_settings
        self.title = title
```

- [ ] **Step 3: Replace the settings tab content**

**Find:**
```python
                        with gr.Tab("⚙️ Ayarlar"):
                            # Runtime Configuration Section
                            if self.runtime_config:
                                gr.Markdown("### 🤖 LLM Yapılandırması")

                                llm_model_input = gr.Textbox(
                                    label="Model",
                                    value=self.runtime_config.llm.model,
                                    placeholder="gpt-4o-mini",
                                    info="Kullanılacak LLM modeli"
                                )
                                llm_temp_slider = gr.Slider(
                                    minimum=0,
                                    maximum=1,
                                    value=self.runtime_config.llm.temperature,
                                    label="Sıcaklık",
                                    step=0.1,
                                    info="Model yaratıcılık derecesi"
                                )

                                # Sub-Agent Configurations
                                gr.Markdown("### 🔧 Alt-Agent Yapılandırması")

                                # Routing Agent Config
                                routing_config = self.runtime_config.get_subagent("routing")
                                gr.Markdown("**Routing Agent**")
                                routing_token_input = gr.Textbox(
                                    label="Token",
                                    value=getattr(routing_config, 'token', '') if routing_config else '',
                                    placeholder="Forza API token...",
                                    type="password",
                                    info="Routing agent için API token",
                                    interactive=True
                                )

                                routing_prompt_input = gr.Textbox(
                                    label="System Prompt",
                                    value=routing_config.system_prompt if routing_config else '',
                                    lines=3,
                                    info="Routing agent için sistem mesajı",
                                    interactive=True
                                )

                                # Chat Agent Config
                                chat_config = self.runtime_config.get_subagent("chat")
                                gr.Markdown("**Chat Agent**")
                                chat_prompt_input = gr.Textbox(
                                    label="System Prompt",
                                    value=chat_config.system_prompt if chat_config else '',
                                    lines=3,
                                    info="Chat agent için sistem mesajı",
                                    interactive=True
                                )

                                # Save Configuration Button
                                config_save_btn = gr.Button("💾 Yapılandırmayı Kaydet", variant="primary")
                                config_status = gr.Textbox(
                                    label="Durum",
                                    interactive=False,
                                    lines=2,
                                    value="",
                                    show_label=False
                                )

                                gr.Markdown("---")
```

**Replace with:**
```python
                        with gr.Tab("⚙️ Ayarlar"):
                            # Runtime Agent Settings Section
                            if self.runtime_agent_settings:
                                gr.Markdown("### 🔧 Alt-Agent Yapılandırması")

                                routing_settings = self.runtime_agent_settings.get_subagent("routing")
                                chat_settings = self.runtime_agent_settings.get_subagent("chat")

                                gr.Markdown("**Routing Agent**")
                                routing_token_input = gr.Textbox(
                                    label="Token",
                                    value=routing_settings.token or "" if routing_settings else "",
                                    placeholder="Forza API token...",
                                    type="password",
                                    info="Routing agent için API token",
                                    interactive=True
                                )

                                routing_prompt_input = gr.Textbox(
                                    label="System Prompt",
                                    value=routing_settings.system_prompt or "" if routing_settings else "",
                                    lines=3,
                                    info="Routing agent için sistem mesajı",
                                    interactive=True
                                )

                                gr.Markdown("**Chat Agent**")
                                chat_prompt_input = gr.Textbox(
                                    label="System Prompt",
                                    value=chat_settings.system_prompt or "" if chat_settings else "",
                                    lines=3,
                                    info="Chat agent için sistem mesajı",
                                    interactive=True
                                )

                                config_save_btn = gr.Button("💾 Yapılandırmayı Kaydet", variant="primary")
                                config_status = gr.Textbox(
                                    label="Durum",
                                    interactive=False,
                                    lines=2,
                                    value="",
                                    show_label=False
                                )

                                gr.Markdown("---")
```

- [ ] **Step 4: Replace the settings save handler**

**Find:**
```python
            # Runtime Configuration Handlers
            if self.runtime_config:
                def save_runtime_config(llm_model, llm_temp, routing_token, routing_prompt, chat_prompt):
                    """Save updated runtime configuration"""
                    try:
                        # Update LLM config
                        new_config = self.runtime_config.update_llm(
                            model=llm_model,
                            temperature=llm_temp
                        )

                        # Update routing agent if exists
                        if new_config.get_subagent("routing"):
                            new_config = new_config.update_subagent(
                                "routing",
                                token=routing_token,
                                system_prompt=routing_prompt
                            )

                        # Update chat agent if exists
                        if new_config.get_subagent("chat"):
                            new_config = new_config.update_subagent(
                                "chat",
                                system_prompt=chat_prompt
                            )

                        # Apply new configuration to chatbot
                        self.runtime_config = new_config
                        if self.chat_service.chatbot:
                            self.chat_service.chatbot.update_runtime_config(new_config)

                        return "✓ Yapılandırma başarıyla kaydedildi!\n\nNot: Model değişiklikleri yeni oturumlarda geçerli olacaktır."

                    except Exception as e:
                        return f"✗ Hata: {str(e)}"

                # Build input list - inputs are always available now
                config_inputs = [
                    llm_model_input,
                    llm_temp_slider,
                    routing_token_input,
                    routing_prompt_input,
                    chat_prompt_input
                ]

                config_save_btn.click(
                    fn=save_runtime_config,
                    inputs=config_inputs,
                    outputs=[config_status]
                )
```

**Replace with:**
```python
            # Runtime Agent Settings Handlers
            if self.runtime_agent_settings:
                def save_settings(routing_token, routing_prompt, chat_prompt):
                    """Save updated sub-agent settings."""
                    try:
                        settings = self.runtime_agent_settings or RuntimeAgentSettings()
                        settings = settings.update_subagent(
                            "routing",
                            token=routing_token,
                            system_prompt=routing_prompt,
                        )
                        settings = settings.update_subagent(
                            "chat",
                            system_prompt=chat_prompt,
                        )
                        self.runtime_agent_settings = settings
                        if self.chat_service.chatbot:
                            self.chat_service.chatbot.update_runtime_settings(settings)
                        return "✓ Ayarlar kaydedildi."
                    except Exception as e:
                        return f"✗ Hata: {str(e)}"

                config_save_btn.click(
                    fn=save_settings,
                    inputs=[routing_token_input, routing_prompt_input, chat_prompt_input],
                    outputs=[config_status],
                )
```

- [ ] **Step 5: Run the full test suite**

```
pytest tests/ -v --ignore=tests/integration
```

Expected: all PASSED (Gradio has no unit tests, so this just checks nothing else broke)

- [ ] **Step 6: Commit**

```bash
git add src/interfaces/gradio_interface.py
git commit -m "refactor(gradio): replace RuntimeConfiguration with RuntimeAgentSettings, remove LLM settings tab"
```

---

### Task 7: Delete dead files

**Files:**
- Delete: `src/core/runtime_config.py`
- Delete: `src/graphs/base/graph_config.py`

- [ ] **Step 1: Verify no remaining imports of `runtime_config`**

```
grep -r "runtime_config\|RuntimeConfiguration\|LLMRuntimeConfig" src/ --include="*.py"
```

Expected output: zero matches (all references removed in Tasks 2, 4, 6).

If any remain, fix them before proceeding.

- [ ] **Step 2: Verify no remaining imports of `graph_config`**

```
grep -r "from src.graphs.base.graph_config\|import GraphConfig" src/ --include="*.py"
```

Expected output: zero matches.

- [ ] **Step 3: Delete the files**

```bash
git rm src/core/runtime_config.py src/graphs/base/graph_config.py
```

- [ ] **Step 4: Run the full test suite**

```
pytest tests/ -v --ignore=tests/integration
```

Expected: all PASSED. If any test fails with `ModuleNotFoundError: runtime_config`, that test still imports the deleted module — fix the import in that test file.

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor: delete dead runtime_config.py (445 lines) and graph_config.py (306 lines)"
```

---

## Verification

After all 7 tasks:

```bash
# Unit tests
pytest tests/unit/test_runtime_agent_settings.py tests/unit/test_chatbot_prepare_config.py -v

# Route tests
pytest tests/api/routes/test_configuration_endpoints.py -v

# Full suite (no integration)
pytest tests/ -v --ignore=tests/integration

# Manual smoke test — should return 200 with subagents payload:
# curl http://localhost:8000/api/configuration
```
