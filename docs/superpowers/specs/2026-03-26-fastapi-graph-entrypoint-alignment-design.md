# Design: FastAPI Graph Entrypoint Alignment

**Date:** 2026-03-26
**Status:** Approved
**Scope:** `src/api/dependencies.py`

---

## Problem

FastAPI ve LangGraph dev ortamları aynı supervisor graph'ı farklı kod yollarından build ediyor:

- **LangGraph dev:** `langgraph.json` → `graph_entrypoints.supervisor_graph()` → `SupervisorGraph(llm).build_graph()`
- **FastAPI:** `dependencies.py` → `ChatbotBuilder` → `DependencyFactory` → `GraphRepository` → `GRAPH_REGISTRY["supervisor"](llm).build_graph()`

Bu farklılık nedeniyle:
1. Davranış tutarsızlıkları gizlenebilir (farklı kod yolu = farklı build parametresi riski)
2. `graph_entrypoints.py`'deki değişiklikler LangGraph dev'e yansıyor ama FastAPI'ye yansımıyor
3. Ekstra abstraction katmanları (`ChatbotBuilder`, `GraphRepository`, `GRAPH_REGISTRY`) gereksiz overhead ve karmaşıklık ekliyor

---

## Hedef

`dependencies.py`'deki `get_chatbot()` fonksiyonunu `graph_entrypoints.supervisor_graph()`'ı doğrudan kullanacak şekilde değiştir. Her iki ortam aynı tek kod yolunu kullansın.

---

## Tasarım

### Değişen Dosya

**`src/api/dependencies.py`** — tek değişiklik

#### Kaldırılan import'lar

```python
from src.builders.chatbot_builder import ChatbotBuilder
from src.builders.dependency_factory import DependencyFactory
from src.builders.adapter_factory import AdapterFactory
from src.services.config_loader import ConfigLoader
```

#### Eklenen import'lar

```python
from src.graphs.graph_entrypoints import supervisor_graph, _get_config
from src.models.llm import LLM
```

> **Not:** `_get_config()` graph_entrypoints'in internal cache helper'ı. `ConfigLoader.load_config()` varsayılan olarak `"config/config.yaml"` kullanır — her iki yol da aynı config'i döner. Bu import, modülün kendi fonksiyonlarının (supervisor_graph, routing_graph, vb.) kullandığı pattern ile tutarlı.

#### `get_chatbot()` değişikliği

Mevcut:
```python
config = ConfigLoader.load_config("config/config.yaml")
dependency_factory = DependencyFactory(config=config)
adapter_factory = AdapterFactory()
_chatbot_instance = (
    ChatbotBuilder(dependency_factory, adapter_factory)
    .with_model(config.llm.model, config.llm.temperature, config.llm.api_key,
                config.llm.provider, config.llm.base_url)
    .with_graph(config.chatbot.graph_type)
    .with_assistant_configuration(getattr(config, 'sql_agent_configuration', None))
    .build()
)
```

Yeni:
```python
config = _get_config()

# LLM: sadece Chatbot wrapper metadata içindir (get_config_for_ui).
# supervisor_graph() kendi LLM instance'ını dahili olarak oluşturur
# (LangGraph dev ortamındaki davranışla aynı).
llm = LLM(
    provider=config.llm.provider,
    model=config.llm.model,
    temperature=config.llm.temperature,
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
)

# Compiled graph: LangGraph dev ile birebir aynı kod yolu
compiled = supervisor_graph()

_chatbot_instance = Chatbot(
    llm=llm,
    graph=compiled,
    config={"configurable": {"thread_id": "1"}},  # default; ChatService runtime'da session_id ile override eder
)
```

### Korunacaklar

Aşağıdaki bileşenler **değişmez**:

| Bileşen | Neden korunuyor |
|---|---|
| `Chatbot` wrapper | thread_id yönetimi, HITL Command resume, ainvoke |
| `ChatService` | HTTP request/response işleme, session yönetimi |
| API route'ları | Tüm endpoint'ler aynı kalır |
| `ChatbotBuilder` / `GraphRepository` / `GRAPH_REGISTRY` | Silinmiyor; sadece `dependencies.py`'de kullanılmıyor |
| `supervisor_graph()` | Değişmez — LangGraph dev ile paylaşılır |
| `main.py` startup | Config pre-load, embedding preload korunur |

---

## Akış Karşılaştırması

| | Eski | Yeni |
|---|---|---|
| Graph build yolu | `GRAPH_REGISTRY["supervisor"](llm).build_graph()` | `supervisor_graph()` |
| Config yükleme | `ConfigLoader.load_config("config/config.yaml")` | `_get_config()` (graph_entrypoints cache) |
| LangGraph dev ile aynı kod yolu | ❌ | ✅ |
| Abstraction katmanı sayısı | 4 (Builder→Factory→Repository→Registry) | 0 |
| `Chatbot` wrapper | ✅ korunuyor | ✅ korunuyor |

---

## Notlar

- **İki LLM instance:** `dependencies.py`'deki LLM yalnızca `Chatbot.get_config_for_ui()` için metadata tutar. `supervisor_graph()` kendi LLM'ini dahili olarak oluşturur (LangGraph dev ile aynı). Bu kasıtlı ve zararsızdır.
- **`_get_config()`:** graph_entrypoints'in internal cache helper'ı. `ConfigLoader.load_config("config/config.yaml")` ile eşdeğer çıktı üretir — risk yok.
- **Kapsam dışı:** `supervisor_graph()` fonksiyonunun LLM init'inde `base_url` eksikliği önceden var olan bir sorun; bu değişikliğin kapsamı dışında.

## Riskler

- **Düşük:** `_get_config()` internal fonksiyon. Config yüklemesi eşdeğer — aynı `.env` ve `config.yaml`.
- **Sıfır:** `Chatbot`, `ChatService`, route'lar dokunulmaz. HITL, session, thread_id yönetimi değişmez.

---

## Etkilenen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `src/api/dependencies.py` | `get_chatbot()` yeniden yaz |
