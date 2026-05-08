# Supervisor Latency Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supervisor latency'yi ~2.45s'den <0.8s'ye düşür; dead code'u temizle ve prompt'u accuracy kaybetmeden kıs.

**Architecture:** (1) `gpt-4.1-mini` model override ekle — tam modelin 3-way routing için gereği yok. (2) Kullanılmayan `SUPERVISOR_SYSTEM_PROMPT` ve `tools.py`'yi sil. (3) `SUPERVISOR_PROMPT_TEMPLATE`'i daha kısa ve kararlı bir versiyon ile değiştir.

**Tech Stack:** Python, LangGraph, LangChain, OpenAI `gpt-4.1-mini`, pytest

---

## Etkilenen Dosyalar

| Dosya | İşlem | Değişiklik |
|-------|--------|------------|
| `config/config.yaml` | Modify | `agents.supervisor.model: gpt-4.1-mini` ekle |
| `src/graphs/supervisor/prompts.py` | Modify | `SUPERVISOR_SYSTEM_PROMPT` sil, `SUPERVISOR_PROMPT_TEMPLATE` yeniden yaz |
| `src/graphs/supervisor/graph.py` | Modify | Dead import'u kaldır, `all_tools` temizle, `_get_default_config` sadeleştir |
| `src/graphs/supervisor/tools.py` | **Delete** | Her iki tool da routing kararı için gereksiz |
| `tests/unit/test_supervisor_prompt.py` | Create | Yeni prompt ve model config testleri |

---

### Task 1: Supervisor model override — `gpt-4.1-mini`

**Files:**
- Modify: `config/config.yaml`
- Create: `tests/unit/test_supervisor_prompt.py`

**Bağlam:** Supervisor hiçbir agent config override'ı olmadığından global `gpt-4.1`'i kullanıyor. Routing ve chat zaten `gpt-4.1-mini` kullanıyor; 3-way classification için `mini` yeterli.

- [ ] **Step 1: Test yaz (failing)**

`tests/unit/test_supervisor_prompt.py` dosyasını oluştur:

```python
"""Supervisor config ve prompt testleri."""
import pytest


def test_supervisor_model_is_mini(tmp_path):
    """Supervisor agent config gpt-4.1-mini kullanmalı."""
    import yaml
    from pathlib import Path

    config_path = Path("config/config.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    supervisor_model = cfg.get("agents", {}).get("supervisor", {}).get("model", "")
    assert supervisor_model == "gpt-4.1-mini", (
        f"Supervisor modeli 'gpt-4.1-mini' olmalı, şu an: {supervisor_model!r}"
    )
```

- [ ] **Step 2: Test'in fail ettiğini doğrula**

```
pytest tests/unit/test_supervisor_prompt.py::test_supervisor_model_is_mini -v
```

Beklenen: `AssertionError: Supervisor modeli 'gpt-4.1-mini' olmalı`

- [ ] **Step 3: `config/config.yaml` güncelle**

`agents:` bloğuna `supervisor` satırını ekle:

```yaml
agents:
  routing:
    model: gpt-4.1-mini
  chat:
    model: gpt-4.1-mini
  report_agent:
    model: gpt-4.1
  supervisor:
    model: gpt-4.1-mini   # Routing kararı için full model gerekmez
```

- [ ] **Step 4: Test'in geçtiğini doğrula**

```
pytest tests/unit/test_supervisor_prompt.py::test_supervisor_model_is_mini -v
```

Beklenen: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add config/config.yaml tests/unit/test_supervisor_prompt.py
git commit -m "perf(supervisor): switch to gpt-4.1-mini for routing decisions"
```

---

### Task 2: `tools.py` sil, `prompts.py` temizle ve yeniden yaz

**Files:**
- Delete: `src/graphs/supervisor/tools.py`
- Modify: `src/graphs/supervisor/prompts.py`
- Modify: `tests/unit/test_supervisor_prompt.py`

**Bağlam:**
- `tools.py` içindeki `get_current_time` ve `get_supervisor_status` supervisor'ın routing kararında hiç kullanılmıyor; sadece LLM'e gönderilen tool schema'sını şişiriyor.
- `prompts.py` satır 5-6'da bu tool'ları import ediyor ama hiç kullanmıyor (dead import).
- `SUPERVISOR_SYSTEM_PROMPT` (54 satır) runtime'da `create_agent`'a geçilmiyor; sadece `_get_default_config()`'a girip orada ölüyor.
- `SUPERVISOR_PROMPT_TEMPLATE` — "belirsiz sorgularda kullanıcıdan netlik iste" kuralı gereksiz round-trip üretir; "yönlendirme gerekçeni belirt" ise hiçbir zaman okunmaz.

- [ ] **Step 1: Test ekle (failing)**

`tests/unit/test_supervisor_prompt.py` dosyasına şu testleri ekle:

```python
def test_supervisor_system_prompt_is_removed():
    """SUPERVISOR_SYSTEM_PROMPT kaldırıldı — import edilememeli."""
    import importlib
    mod = importlib.import_module("src.graphs.supervisor.prompts")
    assert not hasattr(mod, "SUPERVISOR_SYSTEM_PROMPT"), (
        "SUPERVISOR_SYSTEM_PROMPT hâlâ mevcut; dead code temizlenmedi."
    )


def test_tools_module_deleted():
    """tools.py silindi — import edilememeli."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.graphs.supervisor.tools")


def test_supervisor_prompt_template_renders():
    """SUPERVISOR_PROMPT_TEMPLATE doğru render edilmeli."""
    from src.graphs.supervisor.prompts import SUPERVISOR_PROMPT_TEMPLATE

    rendered = SUPERVISOR_PROMPT_TEMPLATE.format(agent_descriptions="- test_agent: test açıklama")
    assert "{agent_descriptions}" not in rendered
    assert "test_agent" in rendered
    assert "transfer" in rendered.lower() or "yönlendir" in rendered.lower()


def test_supervisor_prompt_no_clarification_instruction():
    """Prompt 'netlik iste' / clarification döngüsü tetikleyen ifade içermemeli."""
    from src.graphs.supervisor.prompts import SUPERVISOR_PROMPT_TEMPLATE

    text = SUPERVISOR_PROMPT_TEMPLATE.lower()
    assert "netlik iste" not in text, "Clarification instruction kaldırılmadı"
    assert "belirsiz" not in text, "Clarification instruction kaldırılmadı"
```

- [ ] **Step 2: Testlerin fail ettiğini doğrula**

```
pytest tests/unit/test_supervisor_prompt.py -v
```

Beklenen: 3 yeni test FAIL (tools_module_deleted hariç muhtemelen geçer, diğerleri fail).

- [ ] **Step 3: `tools.py` dosyasını sil**

```bash
git rm src/graphs/supervisor/tools.py
```

- [ ] **Step 4: `prompts.py`'yi yeniden yaz**

`src/graphs/supervisor/prompts.py` dosyasını tamamen şununla değiştir:

```python
"""
Supervisor prompts — yalnızca SUPERVISOR_PROMPT_TEMPLATE kullanılır.
"""

SUPERVISOR_PROMPT_TEMPLATE = """\
Sen ForzaAI orkestratörüsün. Kullanıcı mesajını okuyup MUTLAKA bir transfer aracı çağır.

Mevcut agent'lar:
{agent_descriptions}

Yönlendirme kuralları (sırayla uygula):
1. Sayfa açma, navigasyon, link, ekran, modül isteği → routing
2. Veri, rapor, satış, ciro, stok, analiz, grafik, SQL, hesaplama → report_agent
3. Diğer her mesaj → chat

Kural: Asla doğrudan cevap verme. Her zaman bir agent'a transfer et.\
"""
```

- [ ] **Step 5: Testlerin geçtiğini doğrula**

```
pytest tests/unit/test_supervisor_prompt.py -v
```

Beklenen: tüm testler PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/graphs/supervisor/prompts.py tests/unit/test_supervisor_prompt.py
git commit -m "refactor(supervisor): remove SUPERVISOR_SYSTEM_PROMPT dead code, rewrite prompt for speed+clarity"
```

---

### Task 3: `graph.py` — dead import ve utility tool temizliği

**Files:**
- Modify: `src/graphs/supervisor/graph.py`
- Modify: `tests/unit/test_supervisor_prompt.py`

**Bağlam:**
- `graph.py:22` → `SUPERVISOR_SYSTEM_PROMPT` import'u dead (dosya silinmeden önce zaten kullanılmıyordu; artık sembol de yok).
- `graph.py:23` → `from src.graphs.supervisor.tools import ...` import'u `tools.py` silindiğinden `ModuleNotFoundError` verecek — düzeltilmeli.
- `graph.py:190` → `all_tools = [get_current_time, get_supervisor_status] + handoff_tools` — utility tool'lar kaldırılacak.
- `graph.py:66-70` → `_get_default_config()` `SUPERVISOR_SYSTEM_PROMPT`'u `SupervisorAssistantConfiguration`'a geçiriyor; bu satır sadeleştirilecek (config schema için yine de `SupervisorAssistantConfiguration` dönmeli).

- [ ] **Step 1: Test ekle**

`tests/unit/test_supervisor_prompt.py` dosyasına ekle:

```python
def test_supervisor_graph_imports_cleanly():
    """graph.py temiz import edilebilmeli (ModuleNotFoundError olmamalı)."""
    import importlib
    # Bu import chain'i tetikler: graph.py → prompts.py, registry, utilities
    importlib.import_module("src.graphs.supervisor.graph")


def test_supervisor_all_tools_no_utility_tools():
    """Supervisor agent yalnızca handoff/forward tool'larını kullanmalı."""
    # Doğrudan inspect ediyoruz: get_current_time ve get_supervisor_status
    # artık supervisor toolchain'inde bulunmamalı.
    from src.graphs.supervisor import graph as gmod
    import ast, inspect, textwrap

    src = inspect.getsource(gmod.SupervisorGraph.build_graph)
    assert "get_current_time" not in src, "get_current_time hâlâ all_tools'da"
    assert "get_supervisor_status" not in src, "get_supervisor_status hâlâ all_tools'da"
```

- [ ] **Step 2: Testlerin fail ettiğini doğrula**

```
pytest tests/unit/test_supervisor_prompt.py::test_supervisor_graph_imports_cleanly tests/unit/test_supervisor_prompt.py::test_supervisor_all_tools_no_utility_tools -v
```

Beklenen: `test_supervisor_graph_imports_cleanly` → `ModuleNotFoundError` (tools.py silindi); `test_supervisor_all_tools_no_utility_tools` → `AssertionError`.

- [ ] **Step 3: `graph.py` import bölümünü güncelle**

`graph.py` dosyasının ilk 25 satırını şununla değiştir:

```python
"""
Supervisor Graph - Multi-agent supervisor with routing and chat agents.
Routes requests between agents using handoff pattern.
"""
import logging
from typing import Optional

from langgraph.graph import StateGraph, START, END
from langgraph.graph import MessagesState
from langchain.agents import create_agent

from src.models.llm import LLM
from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_metadata import (
    GraphMetadata,
    GraphCapability,
    InputSpec,
    OutputSpec,
)
from src.graphs.registry import register_graph, GRAPH_REGISTRY
from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration
from src.graphs.supervisor.prompts import SUPERVISOR_PROMPT_TEMPLATE
from src.graphs.supervisor.utilities import create_handoff_tool, create_forward_tool
```

- [ ] **Step 4: `_get_default_config()` sadeleştir**

`graph.py` içinde `_get_default_config()` metodunu bul ve şununla değiştir:

```python
    def _get_default_config(self) -> SupervisorAssistantConfiguration:
        return SupervisorAssistantConfiguration(assistant_name="SupervisorAssistant")
```

- [ ] **Step 5: `build_graph()` içindeki `all_tools` satırını güncelle**

`graph.py` içinde şu satırı:

```python
        all_tools = [get_current_time, get_supervisor_status] + handoff_tools
```

Şununla değiştir:

```python
        all_tools = handoff_tools
```

- [ ] **Step 6: Testlerin geçtiğini doğrula**

```
pytest tests/unit/test_supervisor_prompt.py -v
```

Beklenen: tüm testler PASSED.

- [ ] **Step 7: Commit**

```bash
git add src/graphs/supervisor/graph.py tests/unit/test_supervisor_prompt.py
git commit -m "refactor(supervisor): remove dead imports and utility tools from agent toolchain"
```

---

### Task 4: Smoke test — sunucu ayağa kalkıyor mu?

**Files:**
- Modify: `tests/unit/test_supervisor_prompt.py`

**Bağlam:** Tüm değişiklikler birlikte çalışıyor mu? `supervisor_graph()` hatasız compile edilebilmeli. Config loader'ı mock'layarak gerçek DB / API bağlantısı olmadan test ediyoruz.

- [ ] **Step 1: Smoke test ekle**

`tests/unit/test_supervisor_prompt.py` dosyasına ekle:

```python
def test_supervisor_graph_builds_without_error(monkeypatch):
    """
    supervisor_graph() import zinciri ve graph.compile() hatasız çalışmalı.
    DB bağlantısı ve embedding model gerektirmeyen hafif bir mock kullanır.
    """
    import unittest.mock as mock

    # ConfigLoader'ı basit bir config nesnesiyle mock'la
    fake_cfg = mock.MagicMock()
    fake_cfg.database.uri = "mssql+pyodbc://fake"
    fake_cfg.agents = mock.MagicMock()
    fake_cfg.agents.supervisor = mock.MagicMock()
    fake_cfg.agents.supervisor.model = "gpt-4.1-mini"
    fake_cfg.embedding.model = "text-embedding-3-large"
    fake_cfg.embedding.api_key = "fake-key"
    fake_cfg.embedding.base_url = "https://api.openai.com/v1"
    fake_cfg.vector_store.persist_directory = "./data/vector_store"

    with mock.patch(
        "src.services.config_loader.ConfigLoader.load_config", return_value=fake_cfg
    ), mock.patch(
        "src.graphs.graph_repository.GraphRepository.get"
    ) as mock_repo:
        # Graph repository'nin build_graph'ını mock'la
        mock_repo.return_value = mock.MagicMock()

        from src.graphs.graph_entrypoints import supervisor_graph
        result = supervisor_graph()
        assert result is not None
```

- [ ] **Step 2: Test çalıştır**

```
pytest tests/unit/test_supervisor_prompt.py::test_supervisor_graph_builds_without_error -v
```

Eğer mock'lar yeterliyse PASSED. Import hatası varsa, eksik mock'u tespit edip ekle.

- [ ] **Step 3: Tüm test dosyasını çalıştır**

```
pytest tests/unit/test_supervisor_prompt.py -v
```

Beklenen: tüm testler PASSED.

- [ ] **Step 4: Final commit**

```bash
git add tests/unit/test_supervisor_prompt.py
git commit -m "test(supervisor): add smoke test for graph compilation after cleanup"
```

---

## Beklenen Sonuçlar

| Metrik | Önce | Sonra (beklenti) |
|--------|------|-----------------|
| Supervisor LLM çağrısı süresi | ~2.0-2.4s (gpt-4.1) | ~0.4-0.8s (gpt-4.1-mini) |
| Supervisor system prompt token | ~120 token | ~80 token |
| LLM'e gönderilen tool sayısı | 5 (routing + 2 utility) | 3 (yalnızca routing) |
| Dead code satırı | ~60 satır | 0 |
| Prompt clarification loop riski | Var | Kaldırıldı |

---

## Dikkat Noktaları

- **`SupervisorAssistantConfiguration`** hâlâ `BaseAssistantConfiguration.system_prompt` alanını miras alıyor. Bu alan LangGraph Studio'da görünür ama `create_agent`'a gitmiyor. Bu davranış değişmiyor — sadece `_get_default_config()` gereksiz `SUPERVISOR_SYSTEM_PROMPT` geçirmeyi bırakıyor.
- **tools.py silinince** git history'de kalır; ilerde gerekirse `git show` ile geri alınabilir.
- **`gpt-4.1-mini` accuracy riski:** Routing bir 3-way classification görevi. `gpt-4.1-mini` bu görev için fazlasıyla yeterli; accuracy kaybı beklenmez. İlk haftada routing kararlarını loglardan izle.
