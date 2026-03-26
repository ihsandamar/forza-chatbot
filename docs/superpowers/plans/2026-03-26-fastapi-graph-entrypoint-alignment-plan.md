# FastAPI Graph Entrypoint Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `src/api/dependencies.py`'deki `get_chatbot()` fonksiyonunu `graph_entrypoints.supervisor_graph()`'ı doğrudan kullanacak şekilde değiştir; böylece FastAPI ile LangGraph dev ortamı aynı graph build kod yolunu paylaşsın.

**Architecture:** Tek dosya değişikliği. `ChatbotBuilder → DependencyFactory → GraphRepository → GRAPH_REGISTRY` zinciri kaldırılır; yerine `graph_entrypoints.supervisor_graph()` direkt çağrılır. `Chatbot` wrapper, `ChatService`, tüm API route'ları dokunulmaz.

**Tech Stack:** Python, FastAPI, LangGraph, LLM (OpenAI)

**Spec:** `docs/superpowers/specs/2026-03-26-fastapi-graph-entrypoint-alignment-design.md`

---

## File Map

| Dosya | Değişiklik |
|---|---|
| `src/api/dependencies.py` | `get_chatbot()` yeniden yaz — tek değişiklik |

---

### Task 1: `dependencies.py` — import'ları güncelle

**Files:**
- Modify: `src/api/dependencies.py:1-11`

- [ ] **Step 1: Eski import'ları kaldır, yenilerini ekle**

Mevcut satırlar 1-11:
```python
from functools import lru_cache
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.models.llm import LLM
from src.services.config_loader import ConfigLoader
from src.services.container import ServiceContainer
from src.graphs.graph_repository import GraphRepository
from src.builders.chatbot_builder import ChatbotBuilder
from src.builders.dependency_factory import DependencyFactory
from src.builders.adapter_factory import AdapterFactory
from src.factories.llm_factory import LLMFactory
```

Yeni satırlar 1-6:
```python
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.models.llm import LLM
from src.graphs.graph_entrypoints import supervisor_graph, _get_config
```

**Not:** `lru_cache`, `ConfigLoader`, `ServiceContainer`, `GraphRepository`, `ChatbotBuilder`, `DependencyFactory`, `AdapterFactory`, `LLMFactory` artık kullanılmıyor — tamamı kaldırılır.

- [ ] **Step 2: Syntax kontrolü**

```bash
python -c "import ast; ast.parse(open('src/api/dependencies.py').read()); print('OK')"
```

Expected: `OK`

---

### Task 2: `dependencies.py` — `get_chatbot()` fonksiyonunu değiştir

**Files:**
- Modify: `src/api/dependencies.py:19-52`

- [ ] **Step 1: `get_chatbot()` gövdesini değiştir**

Mevcut satırlar 19-52:
```python
def get_chatbot() -> Chatbot:
    """
    Dependency to get Chatbot instance

    Returns:
        Chatbot: Singleton instance of chatbot
    """
    global _chatbot_instance
    if _chatbot_instance is None:
        # Load config
        config = ConfigLoader.load_config("config/config.yaml")

        # Create builders with config
        dependency_factory = DependencyFactory(config=config)
        adapter_factory = AdapterFactory()

        # Build chatbot
        _chatbot_instance = (
            ChatbotBuilder(dependency_factory, adapter_factory)
            .with_model(
                config.llm.model,
                config.llm.temperature,
                config.llm.api_key,
                config.llm.provider,
                config.llm.base_url
            )
            .with_graph(config.chatbot.graph_type)
            # Note: thread_id is passed at runtime via adapter_kwargs (session_id)
            # No need to set it here as default config
            .with_assistant_configuration(getattr(config, 'sql_agent_configuration', None))
            .build()
        )

    return _chatbot_instance
```

Yeni:
```python
def get_chatbot() -> Chatbot:
    """
    Dependency to get Chatbot instance.

    Uses graph_entrypoints.supervisor_graph() directly — same code path as LangGraph dev.

    Returns:
        Chatbot: Singleton instance of chatbot
    """
    global _chatbot_instance
    if _chatbot_instance is None:
        config = _get_config()

        # LLM: Chatbot wrapper metadata için (get_config_for_ui).
        # supervisor_graph() kendi LLM instance'ını dahili oluşturur.
        llm = LLM(
            provider=config.llm.provider,
            model=config.llm.model,
            temperature=config.llm.temperature,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )

        # LangGraph dev ile birebir aynı kod yolu.
        # Kasıtlı olarak supervisor_graph() hardcode edilmiştir —
        # config.yaml: graph_type=supervisor, bu FastAPI deployment'ı supervisor-only'dir.
        compiled = supervisor_graph()

        _chatbot_instance = Chatbot(
            llm=llm,
            graph=compiled,
            config={"configurable": {"thread_id": "1"}},  # ChatService runtime'da session_id ile override eder
        )

    return _chatbot_instance
```

- [ ] **Step 2: Syntax kontrolü**

```bash
python -c "import ast; ast.parse(open('src/api/dependencies.py').read()); print('OK')"
```

Expected: `OK`

---

### Task 3: Doğrulama

**Files:**
- Read: `src/api/dependencies.py` (final hali)

- [ ] **Step 1: Import'ların resolve edildiğini kontrol et**

```bash
python -c "from src.api.dependencies import get_chatbot, get_chat_service; print('imports OK')"
```

Expected: `imports OK`

**Not:** Bu komut `supervisor_graph()` ve config'i yüklemeye çalışır. Eğer DB bağlantısı yoksa hata alınabilir — o durumda import seviyesinde hata olmadığına bak (runtime hataları kabul edilebilir).

- [ ] **Step 2: Kullanılmayan import kalmadığını doğrula**

```bash
python -c "
import ast
import sys
tree = ast.parse(open('src/api/dependencies.py').read())
imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
for imp in imports:
    if isinstance(imp, ast.ImportFrom):
        print(f'from {imp.module} import {[a.name for a in imp.names]}')
    else:
        print(f'import {[a.name for a in imp.names]}')
"
```

Expected: Sadece 4 import görünmeli — `ChatService`, `Chatbot`, `LLM`, `supervisor_graph/_get_config`

- [ ] **Step 3: Mevcut testleri çalıştır**

```bash
pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

Expected: Mevcut test sonuçlarıyla aynı (bu değişiklik test davranışını etkilemez)

- [ ] **Step 4: Commit**

```bash
git add src/api/dependencies.py
git commit -m "feat: use graph_entrypoints.supervisor_graph() directly in FastAPI

- Remove ChatbotBuilder/DependencyFactory/AdapterFactory/GraphRepository chain
- Use supervisor_graph() from graph_entrypoints — same code path as LangGraph dev
- LLM instance in Chatbot wrapper preserved for metadata (get_config_for_ui)
- Chatbot, ChatService, API routes unchanged"
```
