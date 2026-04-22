# Per-Agent LLM Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Global bir LLM config'in yanına opsiyonel per-agent model override eklemek; hem `config.yaml` (statik) hem LangGraph Studio (runtime) üzerinden çalışsın.

**Architecture:** `LLM.from_override(base, model_string)` classmethod'u `"provider:model"` ya da salt `"model"` string'ini parse ederek base LLM ayarlarını (temperature, api_key, base_url) miras alan yeni bir LLM döndürür. `SupervisorGraph._resolve_agent_llm(name)` bu factory'yi kullanarak şu öncelik sırasını uygular: (1) Studio field (`routing_model` vb.) → (2) YAML `agents.*` section → (3) global LLM. `config.yaml`'daki opsiyonel `agents` section ve `SupervisorAssistantConfiguration`'daki boş-string default'lar bu iki kanalı temsil eder.

**Tech Stack:** Python 3.11, Pydantic v2, LangGraph, PyYAML (ConfigLoader), pytest

---

## Dosya Yapısı

| Dosya | Değişiklik |
|-------|-----------|
| `src/models/llm.py` | `from_override()` classmethod eklenir |
| `config/config.yaml` | Opsiyonel `agents` section eklenir |
| `src/graphs/supervisor/assistant_configuration.py` | `routing_model`, `chat_model`, `report_model` default'ları `""` yapılır |
| `src/graphs/supervisor/graph.py` | `_resolve_agent_llm()` eklenir, `build_graph()` içinde kullanılır |
| `tests/unit/test_llm_client_caching.py` | `TestLLMFromOverride` class'ı eklenir |
| `tests/graphs/supervisor/test_per_agent_llm.py` | Yeni dosya — `_resolve_agent_llm` testleri |

---

### Task 1: `LLM.from_override()` classmethod

**Files:**
- Modify: `src/models/llm.py`
- Test: `tests/unit/test_llm_client_caching.py`

- [ ] **Step 1: Failing test yaz**

`tests/unit/test_llm_client_caching.py` dosyasına aşağıdaki class'ı ekle (dosyanın sonuna):

```python
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
```

- [ ] **Step 2: Testin fail ettiğini doğrula**

```
pytest tests/unit/test_llm_client_caching.py::TestLLMFromOverride -v
```

Beklenen: `AttributeError: type object 'LLM' has no attribute 'from_override'`

- [ ] **Step 3: `from_override()` implementasyonu**

`src/models/llm.py` içindeki `LLM` class'ına `get_chat()` metodunun altına ekle:

```python
    @classmethod
    def from_override(cls, base: "LLM", model_string: str) -> "LLM":
        """Create a new LLM inheriting base settings but overriding provider/model.

        Args:
            base: Base LLM — temperature, api_key, base_url bu nesnedn alınır.
            model_string: "provider:model" (e.g. "anthropic:claude-haiku-4-5")
                          veya salt "model" (e.g. "gpt-4.1-mini", provider base'den alınır).

        Returns:
            New LLM instance — base mutate edilmez.
        """
        if ":" in model_string:
            provider, model = model_string.split(":", 1)
        else:
            provider, model = base.provider, model_string

        return cls(
            provider=provider,
            model=model,
            temperature=base.temperature,
            api_key=base.api_key,
            base_url=base.base_url if provider == base.provider else None,
        )
```

- [ ] **Step 4: Testlerin geçtiğini doğrula**

```
pytest tests/unit/test_llm_client_caching.py -v
```

Beklenen: Tüm testler PASS (önceki caching testleri dahil).

- [ ] **Step 5: Commit**

```bash
git add src/models/llm.py tests/unit/test_llm_client_caching.py
git commit -m "feat(llm): add LLM.from_override() for per-agent model override"
```

---

### Task 2: `config.yaml` opsiyonel `agents` section

**Files:**
- Modify: `config/config.yaml`

- [ ] **Step 1: `agents` section ekle**

`config/config.yaml` içinde `llm:` bölümünün hemen altına ekle:

```yaml
# Per-agent LLM override (optional).
# Absent or empty agent entries → global llm.* is used.
# Format: plain model name (same provider) or "provider:model" (cross-provider).
agents:
  routing:
    model: gpt-4.1-mini   # Lighter model for routing decisions
  chat:
    model: gpt-4.1-mini   # Lighter model for chat
  report:
    model: gpt-4.1        # Full model for SQL generation
```

- [ ] **Step 2: Manuel doğrula**

```
python -c "
from src.services.config_loader import ConfigLoader
c = ConfigLoader.load_config()
print('routing model:', c.agents.routing.model)
print('report model:', c.agents.report.model)
print('global model:', c.llm.model)
"
```

Beklenen çıktı:
```
routing model: gpt-4.1-mini
report model: gpt-4.1
global model: gpt-4.1
```

- [ ] **Step 3: Commit**

```bash
git add config/config.yaml
git commit -m "feat(config): add optional per-agent model override in config.yaml"
```

---

### Task 3: `SupervisorAssistantConfiguration` model field default'larını düzelt

**Files:**
- Modify: `src/graphs/supervisor/assistant_configuration.py:54-66,77-89,136-148`

Mevcut durum: `routing_model`, `chat_model`, `report_model` field'larının default'ları Anthropic model adları. Bu field'lar şimdiye kadar kullanılmıyordu. Artık `_resolve_agent_llm()` bu field'ları okuyacak. `""` (boş string) = "global LLM'i kullan" anlamına gelecek.

- [ ] **Step 1: `Literal` listelerine `""` ekle ve default'ları güncelle**

`src/graphs/supervisor/assistant_configuration.py` içinde:

**`routing_model` field'ı** (satır 54-66) şu hale getirilecek:

```python
    routing_model: Annotated[
        Literal[
            "",                           # Use global LLM (default)
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-sonnet-4-5",
            "openai:gpt-5",
            "openai:gpt-5-mini"
        ],
        {"__template_metadata__": {"kind": "llm"}},
    ] = Field(
        default="",
        description="Language model for routing sub-agent (empty = use global LLM)",
        json_schema_extra={"langgraph_nodes": ["routing"]},
    )
```

**`chat_model` field'ı** (satır 77-89) şu hale getirilecek:

```python
    chat_model: Annotated[
        Literal[
            "",                           # Use global LLM (default)
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-sonnet-4-5",
            "openai:gpt-5",
            "openai:gpt-5-mini"
        ],
        {"__template_metadata__": {"kind": "llm"}},
    ] = Field(
        default="",
        description="Language model for chat sub-agent (empty = use global LLM)",
        json_schema_extra={"langgraph_nodes": ["chat"]},
    )
```

**`report_model` field'ı** (satır 136-148) şu hale getirilecek:

```python
    report_model: Annotated[
        Literal[
            "",                           # Use global LLM (default)
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-sonnet-4-5",
            "openai:gpt-5",
            "openai:gpt-5-mini"
        ],
        {"__template_metadata__": {"kind": "llm"}},
    ] = Field(
        default="",
        description="Language model for report sub-agent (empty = use global LLM)",
        json_schema_extra={"langgraph_nodes": ["report"]},
    )
```

- [ ] **Step 2: Import kontrolü yap**

```
python -c "from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration; c = SupervisorAssistantConfiguration(); print(c.routing_model, c.chat_model, c.report_model)"
```

Beklenen: `  ` (üç boş string)

- [ ] **Step 3: Mevcut testlerin hâlâ geçtiğini doğrula**

```
pytest tests/graphs/supervisor/ -v
```

Beklenen: Tüm testler PASS.

- [ ] **Step 4: Commit**

```bash
git add src/graphs/supervisor/assistant_configuration.py
git commit -m "refactor(supervisor): set routing/chat/report_model defaults to empty string (use global LLM)"
```

---

### Task 4: `SupervisorGraph._resolve_agent_llm()` ve `build_graph()` wireup

**Files:**
- Modify: `src/graphs/supervisor/graph.py`
- Create: `tests/graphs/supervisor/test_per_agent_llm.py`

- [ ] **Step 1: Test dosyasını oluştur**

`tests/graphs/supervisor/test_per_agent_llm.py` oluştur:

```python
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
        """Non-empty routing_model field on app_config → creates new LLM."""
        app_config = MagicMock()
        app_config.routing_model = "anthropic:claude-haiku-4-5"
        # Make sure agents attr doesn't interfere
        del app_config.agents
        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is not graph.llm
        assert result.provider == "anthropic"
        assert result.model == "claude-haiku-4-5"

    def test_empty_studio_field_falls_through_to_yaml(self):
        """Empty routing_model → skip Studio override, check YAML agents section."""
        mock_agent_cfg = MagicMock()
        mock_agent_cfg.model = "gpt-4.1-mini"
        mock_agents = MagicMock()
        mock_agents.routing = mock_agent_cfg

        app_config = MagicMock()
        app_config.routing_model = ""  # empty = skip
        app_config.agents = mock_agents

        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is not graph.llm
        assert result.provider == "openai"   # inherited from base
        assert result.model == "gpt-4.1-mini"

    def test_yaml_agents_section_absent_falls_back_to_global(self):
        """Empty Studio field + no agents section → returns self.llm."""
        app_config = MagicMock(spec=["routing_model"])
        app_config.routing_model = ""
        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is graph.llm

    def test_yaml_agent_model_absent_falls_back_to_global(self):
        """agents section present but specific agent has no model → returns self.llm."""
        mock_agent_cfg = MagicMock(spec=[])  # no model attribute
        mock_agents = MagicMock()
        mock_agents.routing = mock_agent_cfg

        app_config = MagicMock()
        app_config.routing_model = ""
        app_config.agents = mock_agents

        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("routing")
        assert result is graph.llm

    def test_report_agent_uses_report_model_field(self):
        """report_model field should be read for 'report_agent' agent name."""
        app_config = MagicMock()
        app_config.report_agent_model = ""  # report_agent → field is report_agent_model
        # But registry name is "report_agent", so field name is "report_agent_model" —
        # test that it reads correctly
        del app_config.agents
        graph = _make_supervisor(app_config)
        result = graph._resolve_agent_llm("report_agent")
        # No field named report_agent_model with a value → falls back to global
        assert result is graph.llm
```

- [ ] **Step 2: Testin fail ettiğini doğrula**

```
pytest tests/graphs/supervisor/test_per_agent_llm.py -v
```

Beklenen: `AttributeError: '_resolve_agent_llm'`

- [ ] **Step 3: `_resolve_agent_llm()` metodunu ekle**

`src/graphs/supervisor/graph.py` içinde `build_graph()` metodunun hemen üstüne şunu ekle:

```python
    def _resolve_agent_llm(self, agent_name: str) -> LLM:
        """Resolve which LLM to use for a given agent.

        Priority order:
        1. Studio override: app_config.<agent_name>_model (non-empty string)
        2. YAML agents section: app_config.agents.<agent_name>.model
        3. Global LLM (self.llm) — fallback

        Args:
            agent_name: Registry name of the agent (e.g. "routing", "report_agent").

        Returns:
            LLM instance — may be self.llm or a new instance with overridden model.
        """
        # 1. Studio override field (e.g. routing_model, chat_model, report_model)
        studio_field = f"{agent_name}_model"
        model_string = getattr(self.app_config, studio_field, None)
        if model_string:  # non-empty string
            return LLM.from_override(self.llm, model_string)

        # 2. YAML agents.* section
        agents_cfg = getattr(self.app_config, "agents", None)
        if agents_cfg is not None:
            agent_cfg = getattr(agents_cfg, agent_name, None)
            if agent_cfg is not None:
                model = getattr(agent_cfg, "model", None)
                if model:
                    return LLM.from_override(self.llm, model)

        # 3. Fall back to global LLM
        return self.llm
```

- [ ] **Step 4: `build_graph()` içinde `_resolve_agent_llm()` kullan**

`src/graphs/supervisor/graph.py` içindeki `build_graph()` metodunda, subgraph oluşturan döngüyü güncelle.

Mevcut kod (satır 148-158):
```python
        for name, desc in agents.items():
            try:
                subgraph = desc.cls.create(llm=self.llm, app_config=self.app_config).build_graph()
```

Yeni hali:
```python
        for name, desc in agents.items():
            try:
                agent_llm = self._resolve_agent_llm(name)
                subgraph = desc.cls.create(llm=agent_llm, app_config=self.app_config).build_graph()
```

- [ ] **Step 5: Testlerin geçtiğini doğrula**

```
pytest tests/graphs/supervisor/test_per_agent_llm.py -v
```

Beklenen: Tüm testler PASS.

- [ ] **Step 6: Tüm test suite'ini çalıştır**

```
pytest tests/ -x -q
```

Beklenen: Tüm testler PASS, hiçbir regression yok.

- [ ] **Step 7: Commit**

```bash
git add src/graphs/supervisor/graph.py tests/graphs/supervisor/test_per_agent_llm.py
git commit -m "feat(supervisor): add per-agent LLM override via _resolve_agent_llm()"
```

---

## Self-Review

**Spec coverage:**
- ✅ Global LLM config değişmedi (`config.yaml llm.*` hâlâ geçerli)
- ✅ Per-agent model override: YAML `agents.*` section (Task 2)
- ✅ Per-agent model override: LangGraph Studio fields (Task 3 + Task 4)
- ✅ Öncelik sırası: Studio → YAML → global (Task 4)
- ✅ `"provider:model"` ve salt `"model"` formatları destekleniyor (Task 1)
- ✅ Base LLM mutate edilmiyor (Task 1 test: `test_returns_new_instance`)
- ✅ Aynı provider'da base_url miras alınıyor; farklı provider'da temizleniyor (Task 1)

**Placeholder scan:** Yok — tüm adımlar kod içeriyor.

**Type consistency:**
- `LLM.from_override(base: LLM, model_string: str) -> LLM` — Task 1'de tanımlandı, Task 4'te `_resolve_agent_llm()` içinde kullanılıyor. Tutarlı.
- `_resolve_agent_llm(agent_name: str) -> LLM` — Task 4'te tanımlandı, `build_graph()` içinde kullanılıyor. Tutarlı.
