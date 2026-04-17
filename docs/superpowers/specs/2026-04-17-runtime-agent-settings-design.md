# RuntimeAgentSettings Refactor — Design Spec

## Goal

Replace the 445-line `RuntimeConfiguration` dead-end with a lean `RuntimeAgentSettings` dataclass
that actually works: startup initialises it, `_prepare_config()` merges it into the LangGraph
`configurable` dict as flat keys, and the API GET/POST expose only sub-agent settings (system_prompt,
token) — no LLM fields.

## Why the current system is broken

| Problem | Root cause |
|---|---|
| `GET /api/configuration` always 503 | `dependencies.py` never sets `runtime_config` |
| `routing_token` never reaches nodes | `_prepare_config` puts everything under nested `assistant_config` key |
| `LLMRuntimeConfig` allows hot-swap of provider/key | Dangerous + unused |
| 445-line `RuntimeConfiguration` with dead methods | `from_config_with_assistant`, `extract_subagents_from_assistant_config`, `to_builder_params`, `extra_config` — never called |
| `graph_config.py` (306 lines) | Not imported anywhere outside itself |

---

## Architecture

**LangGraph-native pattern** (same as LangGraph dev):
```python
# What nodes read:
config["configurable"]["routing_token"]
config["configurable"]["routing_system_prompt"]
config["configurable"]["thread_id"]

# What Chatbot does at invoke time:
graph.invoke(state, config={
    "configurable": {
        "thread_id": session_id,
        "routing_token": "...",
        "routing_system_prompt": "...",
        "chat_system_prompt": "...",
    }
})
```

`RuntimeAgentSettings.to_graph_configurable()` produces that flat dict.
`Chatbot._prepare_config()` merges it in.
`dependencies.py` initialises it from `SupervisorAssistantConfiguration` defaults at startup.

---

## File Map

### Create
- `src/core/runtime_agent_settings.py` — `SubAgentSettings` + `RuntimeAgentSettings`

### Modify
- `src/core/chatbot.py` — replace `runtime_config`/`assistant_config` with `runtime_agent_settings`, fix `_prepare_config()`
- `src/api/dependencies.py` — init `RuntimeAgentSettings` on startup
- `src/api/models/requests/configuration.py` — delete `LLMConfigUpdateRequest`, remove `llm` field
- `src/api/models/responses/configuration.py` — delete `LLMConfigView`, `ConfigFieldView`; remove `llm` from `ConfigurationView`
- `src/api/routes/configuration.py` — rewrite using `RuntimeAgentSettings`; no LLM section; no 503 on empty
- `src/interfaces/gradio_interface.py` — remove LLM settings inputs, use `runtime_agent_settings`

### Delete
- `src/core/runtime_config.py` (445 lines, dead)
- `src/graphs/base/graph_config.py` (306 lines, not imported by anything)

---

## Component Design

### 1. `src/core/runtime_agent_settings.py` (new)

```python
"""
RuntimeAgentSettings — Lean sub-agent settings container.

Produces flat LangGraph configurable keys so nodes can read:
    config["configurable"]["routing_token"]
    config["configurable"]["routing_system_prompt"]
"""
from __future__ import annotations
import dataclasses
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration


@dataclasses.dataclass
class SubAgentSettings:
    """Runtime settings for one sub-agent (system_prompt + token only)."""
    system_prompt: Optional[str] = None
    token: Optional[str] = None


@dataclasses.dataclass
class RuntimeAgentSettings:
    """
    Container for all sub-agent settings.

    Usage:
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="abc", system_prompt="..."),
            "chat":    SubAgentSettings(system_prompt="..."),
        })
        configurable = settings.to_graph_configurable()
        # → {"routing_token": "abc", "routing_system_prompt": "...", "chat_system_prompt": "..."}
    """
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
    def from_supervisor_config(cls, cfg: SupervisorAssistantConfiguration) -> RuntimeAgentSettings:
        """
        Initialise from SupervisorAssistantConfiguration defaults.
        Called once at startup — creates the live settings object.
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

---

### 2. `src/core/chatbot.py` changes

**Remove:**
- `from src.core.runtime_config import RuntimeConfiguration`
- `assistant_config` parameter from `__init__`
- `self.assistant_config` attribute
- `RuntimeConfiguration` type hints everywhere

**Add:**
- `from src.core.runtime_agent_settings import RuntimeAgentSettings`

**`__init__` signature** (new):
```python
def __init__(
    self,
    llm: LLM,
    graph: BaseGraph,
    config: dict = None,
    runtime_agent_settings: Optional[RuntimeAgentSettings] = None,
):
    self.llm = llm
    self.graph = graph
    self.config = config if config else {}
    self.runtime_agent_settings = runtime_agent_settings
```

**`_prepare_config`** (rewritten):
```python
def _prepare_config(self, thread_id: str = None) -> dict:
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

**Runtime settings methods** (replace old `get_runtime_config` / `update_runtime_config` / `get_config_for_ui`):
```python
def get_runtime_settings(self) -> Optional[RuntimeAgentSettings]:
    return self.runtime_agent_settings

def update_runtime_settings(self, new_settings: RuntimeAgentSettings) -> None:
    self.runtime_agent_settings = new_settings

def get_config_for_ui(self) -> dict:
    if self.runtime_agent_settings:
        return {
            "subagents": {
                name: {"system_prompt": s.system_prompt, "has_token": bool(s.token)}
                for name, s in self.runtime_agent_settings.subagents.items()
            }
        }
    return {"subagents": {}}
```

**`_process_message`** — token injection path unchanged (already puts token directly on graph_state, not via configurable). No change needed here.

---

### 3. `src/api/dependencies.py` changes

```python
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.core.runtime_agent_settings import RuntimeAgentSettings
from src.models.llm import LLM
from src.graphs.graph_entrypoints import supervisor_graph, _get_config
from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration

_chat_service_instance = None
_chatbot_instance = None


def get_chatbot() -> Chatbot:
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
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService(get_chatbot())
    return _chat_service_instance
```

---

### 4. `src/api/models/requests/configuration.py` changes

**Delete:** `LLMConfigUpdateRequest` class entirely.

**Remove** `llm` field from `ConfigurationUpdateRequest`.

**Keep** `SubAgentConfigUpdateRequest` as-is (but remove `extra_params` field — it's dead).

Result:
```python
from typing import Optional, Dict
from pydantic import BaseModel, Field


class SubAgentConfigUpdateRequest(BaseModel):
    system_prompt: Optional[str] = Field(default=None)
    token: Optional[str] = Field(default=None)


class ConfigurationUpdateRequest(BaseModel):
    subagents: Optional[Dict[str, SubAgentConfigUpdateRequest]] = Field(default=None)

    class Config:
        json_schema_extra = {
            "example": {
                "subagents": {
                    "routing": {"token": "your-api-token"},
                    "chat": {"system_prompt": "Sen yardımcı bir asistansın."}
                }
            }
        }


__all__ = ["SubAgentConfigUpdateRequest", "ConfigurationUpdateRequest"]
```

---

### 5. `src/api/models/responses/configuration.py` changes

**Delete:** `ConfigFieldView`, `LLMConfigView` classes entirely.

**Remove** `llm` field from `ConfigurationView`. Keep `SubAgentConfigView`.

Result for `ConfigurationView`:
```python
class ConfigurationView(BaseModel):
    subagents: Dict[str, SubAgentConfigView] = Field(
        description="Sub-agent configurations, keyed by agent name"
    )
    available_subagent_types: List[str] = Field(
        description="List of available sub-agent names"
    )
```

`SubAgentConfigView` — simplify (remove `agent_type` + JSON Schema, keep values only):
```python
class SubAgentConfigView(BaseModel):
    name: str
    system_prompt: Optional[str] = None
    has_token: bool = False
    token_preview: Optional[str] = None
```

`ConfigurationUpdateResponse` — keep as-is.

---

### 6. `src/api/routes/configuration.py` rewrite

**Remove:** `LLMConfigView`, `LLMConfigUpdateRequest`, `_build_configuration_view` (inline the simpler logic).

**GET** — reads `chatbot.runtime_agent_settings` (never 503 on None — returns empty dict):
```python
@router.get("", response_model=ConfigurationView)
async def get_configuration(chat_service: ChatService = Depends(get_chat_service)):
    if not chat_service.chatbot:
        raise HTTPException(status_code=503, detail="Chatbot not initialized")
    settings = chat_service.chatbot.get_runtime_settings()
    subagent_views = {}
    if settings:
        for name, s in settings.subagents.items():
            token_preview = None
            if s.token and len(s.token) > 10:
                token_preview = s.token[:10] + "..."
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
```

**POST** — updates subagents only:
```python
@router.post("", response_model=ConfigurationUpdateResponse)
async def update_configuration(
    update_request: ConfigurationUpdateRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    if not chat_service.chatbot:
        raise HTTPException(status_code=503, detail="Chatbot not initialized")
    settings = chat_service.chatbot.get_runtime_settings()
    if settings is None:
        raise HTTPException(status_code=503, detail="Runtime settings not available")

    updated_items = []
    if update_request.subagents:
        for agent_name, agent_update in update_request.subagents.items():
            agent_updates = {}
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
        updated_config=await get_configuration(chat_service),
    )
```

---

### 7. `src/interfaces/gradio_interface.py` changes

**`__init__` signature** — replace `runtime_config: Optional[RuntimeConfiguration]` with
`runtime_agent_settings: Optional[RuntimeAgentSettings]`.

**Settings tab** — remove LLM section (`llm_model_input`, `llm_temp_slider`, "### 🤖 LLM Yapılandırması" heading).
Keep sub-agent section unchanged (routing_token, routing_prompt, chat_prompt) — but read initial values from `runtime_agent_settings`.

Initial values (instead of `self.runtime_config.get_subagent("routing").token`):
```python
routing_settings = self.runtime_agent_settings.get_subagent("routing") if self.runtime_agent_settings else None
chat_settings    = self.runtime_agent_settings.get_subagent("chat")    if self.runtime_agent_settings else None

routing_token_input = gr.Textbox(value=routing_settings.token or "" if routing_settings else "")
routing_prompt_input = gr.Textbox(value=routing_settings.system_prompt or "" if routing_settings else "")
chat_prompt_input    = gr.Textbox(value=chat_settings.system_prompt or ""    if chat_settings    else "")
```

**`save_runtime_config` handler** — rename to `save_settings`, remove LLM update logic:
```python
def save_settings(routing_token, routing_prompt, chat_prompt):
    try:
        settings = self.runtime_agent_settings or RuntimeAgentSettings()
        settings = settings.update_subagent("routing", token=routing_token, system_prompt=routing_prompt)
        settings = settings.update_subagent("chat", system_prompt=chat_prompt)
        self.runtime_agent_settings = settings
        if self.chat_service.chatbot:
            self.chat_service.chatbot.update_runtime_settings(settings)
        return "✓ Ayarlar kaydedildi."
    except Exception as e:
        return f"✗ Hata: {str(e)}"
```

**Guard** — replace `if self.runtime_config:` with `if self.runtime_agent_settings:`.

---

### 8. Delete files

- `src/core/runtime_config.py` — delete entirely
- `src/graphs/base/graph_config.py` — delete entirely
- Remove `RuntimeConfiguration` from `__all__` / imports wherever it appeared

---

## API Contract Changes

### Before (GET /api/configuration)
Returns 503 always (runtime_config never set).

### After (GET /api/configuration)
```json
{
  "subagents": {
    "routing": {
      "name": "routing",
      "system_prompt": "Sen Forza navigasyon asistanısın...",
      "has_token": false,
      "token_preview": null
    },
    "chat": {
      "name": "chat",
      "system_prompt": "Sen yardımcı bir sohbet asistanısın...",
      "has_token": false,
      "token_preview": null
    }
  },
  "available_subagent_types": ["routing", "chat"]
}
```

### Before (POST /api/configuration)
Returns 503 (runtime_config never set).

### After (POST /api/configuration)
```json
// Request:
{
  "subagents": {
    "routing": { "token": "my-forza-token" }
  }
}
// Response:
{
  "success": true,
  "message": "Updated: routing token",
  "updated_config": { ... }
}
```

---

## What this does NOT change

- `SupervisorAssistantConfiguration` — flat fields for Studio still work exactly as before.
  `RuntimeAgentSettings.from_supervisor_config()` reads the same fields.
- `_resolve_agent_llm()` in `supervisor/graph.py` — per-agent LLM override system untouched.
- YAML `agents.*` section — untouched.
- Token injection via `graph_state['token']` path (legacy) — untouched.
- Session / thread_id management — untouched.

---

## Testing scope

- Unit: `RuntimeAgentSettings.to_graph_configurable()` — flat key generation
- Unit: `RuntimeAgentSettings.update_subagent()` — immutability
- Unit: `Chatbot._prepare_config()` — configurable dict merging with and without settings
- Integration: `GET /api/configuration` returns 200 after startup
- Integration: `POST /api/configuration` subagent update reflected on next `_prepare_config()`
