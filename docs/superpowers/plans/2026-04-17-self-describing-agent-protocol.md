# Self-Describing Agent Protocol — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Yeni bir agent eklemek, sadece kendi dizinini yazmayı gerektirsin — supervisor, registry, entrypoints'e dokunulmadan.

**Architecture:** `AgentDescriptor` dataclass + `@register_graph` güncellenmesi → `BaseGraph.create()` factory classmethod → `GraphRepository` auto-discovery → `SupervisorGraph.build_graph()` dinamik tool/prompt üretimi → `graph_entrypoints.py` tek satır factory'ler.

**Tech Stack:** Python, LangGraph, LangChain, dataclasses

**Çalıştırma sırası kritik:** Task'lar sırayla uygulanmalı (her biri bir sonrakine bağımlı).

**Spec:** `docs/superpowers/specs/2026-04-17-self-describing-agent-protocol-design.md`

---

### Task 1: AgentDescriptor + Yeni @register_graph

**Files:**
- Modify: `src/graphs/registry.py`

- [ ] **Step 1: Mevcut dosyayı oku**

```bash
cat src/graphs/registry.py
```

- [ ] **Step 2: registry.py'yi yeni implementasyonla değiştir**

`src/graphs/registry.py` içeriğini tamamen şununla değiştir:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Type

@dataclass
class AgentDescriptor:
    name: str
    description: str
    examples: list[str] = field(default_factory=list)
    state_type: str = "messages"
    returns_to_supervisor: bool = True
    cls: Optional[Type] = None

# name → AgentDescriptor
GRAPH_REGISTRY: dict[str, AgentDescriptor] = {}


def register_graph(
    name: str,
    description: str = "",
    examples: list[str] = None,
    state_type: str = "messages",
    returns_to_supervisor: bool = True,
):
    """
    Decorator: bir graph sınıfını GRAPH_REGISTRY'ye kaydeder.

    Kullanım:
        @register_graph(
            name="my_agent",
            description="Kullanıcı X istediğinde devreye girer.",
            examples=["örnek sorgu 1", "örnek sorgu 2"],
        )
        class MyAgentGraph(BaseGraph): ...
    """
    def decorator(cls):
        GRAPH_REGISTRY[name] = AgentDescriptor(
            name=name,
            description=description,
            examples=examples or [],
            state_type=state_type,
            returns_to_supervisor=returns_to_supervisor,
            cls=cls,
        )
        return cls
    return decorator
```

- [ ] **Step 3: Python syntax kontrolü**

```bash
python -c "from src.graphs.registry import GRAPH_REGISTRY, register_graph, AgentDescriptor; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/graphs/registry.py
git commit -m "refactor: add AgentDescriptor to registry, extend @register_graph with description/examples"
```

---

### Task 2: BaseGraph.create() Factory Classmethod

**Files:**
- Modify: `src/graphs/base/base_graph.py` — sadece `create()` classmethod eklenir, başka hiçbir şey değişmez

- [ ] **Step 1: create() metodunu BaseGraph sınıfına ekle**

`src/graphs/base/base_graph.py` dosyasında `build_graph` abstract method tanımından hemen önce şu metodu ekle (satır ~125'e, `_get_default_config` ve `_get_default_metadata` tanımlarından sonra):

```python
    @classmethod
    def create(cls, llm: "LLM", app_config=None) -> "BaseGraph":
        """
        Factory classmethod: graph instance'ı oluşturur.

        Varsayılan implementasyon sadece llm geçer.
        Karmaşık setup gerektiren graph'lar (DB, dosya yolları vb.) bu metodu override eder.

        Args:
            llm: Language model instance
            app_config: Uygulama konfigürasyonu (ConfigLoader'dan gelen nesne)

        Returns:
            BaseGraph instance
        """
        return cls(llm=llm)
```

- [ ] **Step 2: Syntax kontrolü**

```bash
python -c "from src.graphs.base.base_graph import BaseGraph; print(hasattr(BaseGraph, 'create'))"
```

Beklenen: `True`

- [ ] **Step 3: Commit**

```bash
git add src/graphs/base/base_graph.py
git commit -m "feat: add BaseGraph.create() factory classmethod for GraphRepository integration"
```

---

### Task 3: GraphRepository — Auto-Discovery + create() Kullanımı

**Files:**
- Modify: `src/graphs/graph_repository.py`

- [ ] **Step 1: graph_repository.py'yi yeni implementasyonla değiştir**

```python
import sys
import logging
from pathlib import Path

from src.graphs.registry import GRAPH_REGISTRY
from src.models.llm import LLM

logger = logging.getLogger(__name__)


class GraphRepository:
    def __init__(self, llm: LLM, app_config=None):
        self.llm = llm
        self.app_config = app_config
        self.register_all()

    def get(self, graph_type: str):
        """Graph instance'ını oluşturur ve build_graph() çağırır."""
        if isinstance(graph_type, dict):
            graph_type = graph_type.get("type") or graph_type.get("name", str(graph_type))
        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        descriptor = GRAPH_REGISTRY[graph_type]
        instance = descriptor.cls.create(llm=self.llm, app_config=self.app_config)
        return instance.build_graph()

    def get_raw(self, graph_type: str):
        """Build etmeden graph instance'ını döner."""
        if isinstance(graph_type, dict):
            graph_type = graph_type.get("type") or graph_type.get("name", str(graph_type))
        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        descriptor = GRAPH_REGISTRY[graph_type]
        return descriptor.cls.create(llm=self.llm, app_config=self.app_config)

    def list_graphs(self):
        return list(GRAPH_REGISTRY.keys())

    def register_all(self):
        if getattr(sys, "frozen", False):
            self._register_explicit()
        else:
            self._register_auto_discover()

    def _register_auto_discover(self):
        """
        src/graphs/*/graph.py pattern'ini glob ile tarar.
        @register_graph decorator tetiklenince GRAPH_REGISTRY dolar.
        """
        import importlib
        from glob import glob

        pattern = str(Path(__file__).parent / "*/graph.py")
        for path in glob(pattern):
            parts = Path(path).parts
            try:
                idx = next(i for i, p in enumerate(parts) if p == "src")
                module_name = ".".join(parts[idx:]).removesuffix(".py")
                importlib.import_module(module_name)
            except StopIteration:
                logger.warning(f"'src' bulunamadı path'te: {path}")
            except ImportError as e:
                logger.warning(f"Graph yüklenemedi: {path} — {e}")

    def _register_explicit(self):
        """
        PyInstaller build için explicit import listesi.
        Yeni agent eklendiğinde sadece buraya 1 satır import eklenir.
        """
        try:
            import src.graphs.chat.graph
            import src.graphs.supervisor.graph
            import src.graphs.routing.graph
            import src.graphs.report_agent.graph
            logger.info("Tüm graph'lar yüklendi (explicit mode)")
        except ImportError as e:
            logger.warning(f"Graph yüklenemedi: {e}")
```

- [ ] **Step 2: Sözdizimi kontrolü**

```bash
python -c "from src.graphs.graph_repository import GraphRepository; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/graphs/graph_repository.py
git commit -m "refactor: GraphRepository auto-discovery + create() pattern + app_config support"
```

---

### Task 4: chat/graph.py — @register_graph Güncelle

**Files:**
- Modify: `src/graphs/chat/graph.py`

- [ ] **Step 1: @register_graph dekoratörünü güncelle**

`chat/graph.py`'de şu satırı:

```python
@register_graph("chat")
```

Şununla değiştir:

```python
@register_graph(
    name="chat",
    description="Genel sohbet, bilgi soruları, ERP dışı konular ve analitik olmayan kullanıcı etkileşimleri.",
    examples=["merhaba", "nasılsın", "bana yardım et", "ne yapabilirsin"],
    state_type="messages",
    returns_to_supervisor=True,
)
```

- [ ] **Step 2: ChatGraph'ın create() inherit ettiğini doğrula (override gerekmez)**

```bash
python -c "
from src.graphs.chat.graph import ChatGraph
from src.graphs.registry import GRAPH_REGISTRY
print('chat' in GRAPH_REGISTRY)
print(GRAPH_REGISTRY['chat'].description[:30])
"
```

Beklenen:
```
True
Genel sohbet, bilgi soruları
```

- [ ] **Step 3: Commit**

```bash
git add src/graphs/chat/graph.py
git commit -m "refactor: add description/examples to ChatGraph @register_graph"
```

---

### Task 5: routing/graph.py — @register_graph + create() + Module-Level I/O Kaldır

**Files:**
- Modify: `src/graphs/routing/graph.py`

- [ ] **Step 1: Module-level config satırını kaldır**

`routing/graph.py`'de şu satırı sil (satır 45 civarı):

```python
config = ConfigLoader.load_config("config/config.yaml")
```

- [ ] **Step 2: @register_graph dekoratörünü güncelle**

```python
@register_graph(
    name="routing",
    description="ERP uygulaması içinde sayfa navigasyonu — kullanıcı belirli bir sayfaya gitmek, bir ekranı açmak veya bir modüle geçmek istediğinde.",
    examples=["Müşteri kartına git", "Stok hareketlerini aç", "Satış siparişleri ekranı", "Cari hesap listesi"],
    state_type="messages",
    returns_to_supervisor=True,
)
```

- [ ] **Step 3: RoutingGraph.__init__ imzasına app_config ekle**

`__init__` metodunun başına `app_config=None` parametresi ekle ve config yüklemeyi buraya taşı:

```python
def __init__(self, llm: LLM, config: Optional[RoutingAssistantConfiguration] = None, app_config=None):
    # app_config yoksa lazy yükle (test uyumluluğu için)
    if app_config is None:
        app_config = ConfigLoader.load_config("config/config.yaml")
    self._app_config = app_config

    super().__init__(
        llm=llm,
        state_class=NavigationState,
        config=config,
        metadata=self._get_default_metadata()
    )
    self.vectorstore = self._setup_vectorstore()
    # ...
```

- [ ] **Step 4: `_setup_vectorstore` ve diğer metodlarda `config` → `self._app_config` değiştir**

`routing/graph.py` içinde `config.` ile başlayan tüm referansları `self._app_config.` ile değiştir:

```bash
grep -n "config\." src/graphs/routing/graph.py | grep -v "self\." | grep -v "#"
```

Bulunan her `config.X` ifadesini `self._app_config.X` ile değiştir.

- [ ] **Step 5: create() classmethod ekle**

`@register_graph` dekoratöründen hemen sonra, `__init__`'ten önce:

```python
@classmethod
def create(cls, llm: LLM, app_config=None) -> "RoutingGraph":
    return cls(llm=llm, app_config=app_config)
```

- [ ] **Step 6: Kullanılmayan standalone import'ları kaldır**

`routing/graph.py`'nin başındaki kullanılmayan import bloğunu sil (satır 32-42):

```python
from .nodes import (
    extract_user_input_node,
    extract_category_from_query,
    find_documents_node,
    select_most_relevant_document,
    detect_page_parameters_node,
    extract_page_parameters_node,
    update_url_with_parameters_node,
    format_navigation_output_node,
    validate_tool_results_node,
    find_alternative_pages_node,
)
```

- [ ] **Step 7: Import hatası olmadığını doğrula**

```bash
python -c "from src.graphs.routing.graph import RoutingGraph; print('OK')"
```

Beklenen: `OK` (config dosyası okunmadan)

- [ ] **Step 8: Commit**

```bash
git add src/graphs/routing/graph.py
git commit -m "refactor: RoutingGraph — remove module-level I/O, add create(), update @register_graph"
```

---

### Task 6: report_agent/graph.py — @register_graph + create()

**Files:**
- Modify: `src/graphs/report_agent/graph.py`

- [ ] **Step 1: Mevcut dosyada @register_graph var mı kontrol et**

```bash
grep -n "register_graph" src/graphs/report_agent/graph.py
```

Eğer yoksa, `build_report_agent_graph` fonksiyonunu barındıran class'a veya fonksiyona dekoratör + classmethod eklenecek.

- [ ] **Step 2: report_agent/graph.py başına import ekle**

```python
from src.graphs.registry import register_graph
```

- [ ] **Step 3: ReportAgentGraph sınıfı yoksa oluştur, varsa güncelle**

Eğer `build_report_agent_graph` bir fonksiyon olarak tanımlıysa, bir wrapper class ile sar:

```python
@register_graph(
    name="report_agent",
    description="ERP veri analizi, satış ve stok raporları, SQL sorguları, grafikler ve görselleştirmeler.",
    examples=[
        "geçen ayın satışları",
        "en çok satan ürünler",
        "şube bazlı ciro karşılaştırması",
        "kategori bazlı stok durumu",
        "günlük satış trendi grafiği",
    ],
    state_type="report",
    returns_to_supervisor=False,
)
class ReportAgentGraph:
    """Registry wrapper for report agent — build_report_agent_graph factory'sini kullanır."""

    @classmethod
    def create(cls, llm, app_config=None):
        from pathlib import Path
        from src.services.config_loader import ConfigLoader

        if app_config is None:
            app_config = ConfigLoader.load_config()

        project_root = Path(__file__).parent.parent.parent.parent
        business_rules_path = str(
            project_root / "src" / "graphs" / "report_agent" / "data" / "business_rules.json"
        )
        chroma_persist_dir = str(project_root / "data" / "vector_store")

        # build_report_agent_graph direkt olarak compiled graph döner,
        # bu yüzden build_graph() wrapper'a ihtiyaç var
        return cls(
            llm=llm,
            app_config=app_config,
            business_rules_path=business_rules_path,
            chroma_persist_dir=chroma_persist_dir,
        )

    def __init__(self, llm, app_config, business_rules_path, chroma_persist_dir):
        self._llm = llm
        self._app_config = app_config
        self._business_rules_path = business_rules_path
        self._chroma_persist_dir = chroma_persist_dir

    def build_graph(self):
        return build_report_agent_graph(
            llm=self._llm.get_chat(),
            table_name=getattr(self._app_config, "report_table_name", "MasterReportDocumentTable"),
            column_metadata={},
            connection_string=self._app_config.database.uri,
            business_rules_path=self._business_rules_path,
            chroma_persist_dir=self._chroma_persist_dir,
        )
```

**Not:** `build_report_agent_graph` fonksiyonu mevcut haliyle kalır — sadece `ReportAgentGraph` wrapper sınıfı eklenir.

- [ ] **Step 4: Registry'de göründüğünü doğrula**

```bash
python -c "
from src.graphs.report_agent.graph import ReportAgentGraph
from src.graphs.registry import GRAPH_REGISTRY
print('report_agent' in GRAPH_REGISTRY)
print(GRAPH_REGISTRY['report_agent'].returns_to_supervisor)
"
```

Beklenen:
```
True
False
```

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/graph.py
git commit -m "feat: add ReportAgentGraph registry wrapper with create() and @register_graph"
```

---

### Task 7: SupervisorGraph — @register_graph + create() + Dinamik build_graph()

**Files:**
- Modify: `src/graphs/supervisor/graph.py`
- Modify: `src/graphs/supervisor/prompts.py`

- [ ] **Step 1: supervisor/prompts.py — SUPERVISOR_PROMPT_TEMPLATE ekle**

`supervisor/prompts.py` dosyasında mevcut `SUPERVISOR_SYSTEM_PROMPT` sabitinin yanına şunu ekle:

```python
SUPERVISOR_PROMPT_TEMPLATE = """\
Sen bir ERP asistanı orkestratörüsün.
Kullanıcı mesajını analiz et ve uygun agent'a yönlendir.

Mevcut agent'lar:
{agent_descriptions}

Kurallar:
- Belirsiz sorgularda önce kullanıcıdan netlik iste
- Tek agent'a yönlendir
- Yönlendirme gerekçeni reason alanında belirt
"""
```

- [ ] **Step 2: supervisor/graph.py — @register_graph dekoratörünü güncelle**

```python
@register_graph(
    name="supervisor",
    description="Orkestratör — kullanıcı mesajlarını doğru agent'a yönlendirir.",
    state_type="messages",
    returns_to_supervisor=False,
)
```

- [ ] **Step 3: SupervisorGraph.__init__ — app_config parametresi ekle**

```python
def __init__(self, llm: LLM, config: Optional[SupervisorAssistantConfiguration] = None, app_config=None):
    super().__init__(
        llm=llm,
        state_class=MessagesState,
        config=config,
        metadata=self._get_default_metadata(),
    )
    self.app_config = app_config
```

- [ ] **Step 4: create() classmethod ekle**

```python
@classmethod
def create(cls, llm: LLM, app_config=None) -> "SupervisorGraph":
    return cls(llm=llm, app_config=app_config)
```

- [ ] **Step 5: build_graph() — dinamik hale getir**

Mevcut `build_graph()` metodunu şununla değiştir:

```python
def build_graph(self) -> StateGraph:
    logger.info("[SUPERVISOR] Registry'den agent'lar okunuyor...")

    # Supervisor dışındaki tüm kayıtlı agent'ları al
    agents = {
        name: desc for name, desc in GRAPH_REGISTRY.items()
        if name != "supervisor"
    }

    # Her agent için dinamik tool üret
    handoff_tools = []
    for name, desc in agents.items():
        if desc.returns_to_supervisor:
            tool_fn = create_handoff_tool(
                agent_name=name,
                description=f"{desc.description}" + (
                    f"\n\nÖrnekler:\n" + "\n".join(f"- {ex}" for ex in desc.examples)
                    if desc.examples else ""
                ),
            )
        else:
            tool_fn = create_forward_tool(
                agent_name=name,
                description=f"{desc.description}" + (
                    f"\n\nÖrnekler:\n" + "\n".join(f"- {ex}" for ex in desc.examples)
                    if desc.examples else ""
                ),
            )
        handoff_tools.append(tool_fn)

    all_tools = [get_current_time, get_supervisor_status] + handoff_tools

    # Dinamik sistem promptu
    agent_descriptions = "\n".join(
        f"- {name}: {desc.description}" for name, desc in agents.items()
    )
    system_prompt = SUPERVISOR_PROMPT_TEMPLATE.format(
        agent_descriptions=agent_descriptions
    )

    supervisor_agent = create_agent(
        model=self.llm.get_chat(),
        tools=all_tools,
        system_prompt=system_prompt,
        name="supervisor"
    )

    builder = self.get_graph_builder()
    destinations = list(agents.keys())
    builder.add_node("supervisor", supervisor_agent, destinations=destinations)

    for name, desc in agents.items():
        try:
            subgraph = desc.cls.create(llm=self.llm, app_config=self.app_config).build_graph()
            builder.add_node(name, subgraph)
            if desc.returns_to_supervisor:
                builder.add_edge(name, "supervisor")
            else:
                builder.add_edge(name, END)
            logger.info(f"[SUPERVISOR] ✓ {name} subgraph eklendi")
        except Exception as e:
            logger.error(f"[SUPERVISOR] {name} subgraph inşa hatası: {e}")

    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", END)

    compiled = builder.compile(
        checkpointer=self.get_memory(),
        name="supervisor_graph"
    )
    logger.info("[SUPERVISOR] Supervisor graph derlendi ✓")
    return compiled
```

- [ ] **Step 6: Import ekle (eğer yoksa)**

`supervisor/graph.py` başına şu import'ları ekle/güncelle:

```python
from src.graphs.registry import GRAPH_REGISTRY
from src.graphs.supervisor.prompts import SUPERVISOR_PROMPT_TEMPLATE
from src.graphs.supervisor.tools import get_current_time, get_supervisor_status
from src.graphs.supervisor.utilities import create_handoff_tool, create_forward_tool
```

`assign_to_*` import'larını kaldır — artık kullanılmıyor.

- [ ] **Step 7: _build_report_agent() metodunu sil**

Supervisor artık report_agent'ı doğrudan registry'den alıyor. `_build_report_agent()` metodu gereksiz — sil.

- [ ] **Step 8: Syntax kontrolü**

```bash
python -c "from src.graphs.supervisor.graph import SupervisorGraph; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 9: Commit**

```bash
git add src/graphs/supervisor/graph.py src/graphs/supervisor/prompts.py
git commit -m "feat: SupervisorGraph — dynamic build_graph from registry, add create(), remove _build_report_agent()"
```

---

### Task 8: supervisor/tools.py — Hardcoded Handoff Tool'ları Kaldır

**Files:**
- Modify: `src/graphs/supervisor/tools.py`

Supervisor artık araçları dinamik üretiyor. Hardcoded `assign_to_*` sabitleri kaldırılır.

- [ ] **Step 1: Dosyayı sadece utility tool'lara indir**

`src/graphs/supervisor/tools.py` içeriğini şununla değiştir:

```python
"""
Supervisor Utility Tools — agent yönlendirme araçları değil,
yardımcı araçlar. Yönlendirme araçları SupervisorGraph.build_graph()
içinde dinamik olarak üretilir.
"""
from langchain_core.tools import tool
from datetime import datetime


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def get_supervisor_status() -> str:
    """Get the current status of the supervisor system."""
    return "Supervisor is operational and ready to assist."
```

- [ ] **Step 2: Syntax kontrolü**

```bash
python -c "from src.graphs.supervisor.tools import get_current_time, get_supervisor_status; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/graphs/supervisor/tools.py
git commit -m "refactor: supervisor/tools.py — remove hardcoded assign_to_* tools (now generated dynamically)"
```

---

### Task 9: graph_entrypoints.py — Basitleştir

**Files:**
- Modify: `src/graphs/graph_entrypoints.py`

- [ ] **Step 1: graph_entrypoints.py'yi yeni implementasyonla değiştir**

```python
from pathlib import Path
from src.models.llm import LLM
from src.graphs.graph_repository import GraphRepository
from src.services.config_loader import ConfigLoader

# Global config cache — startup event veya lazy load ile dolar
_config_cache = None


def _get_config():
    global _config_cache
    if _config_cache is None:
        _config_cache = ConfigLoader.load_config()
    return _config_cache


def _get_config_no_block():
    global _config_cache
    return _config_cache


def _make_graph(name: str):
    """Generic factory: registry'den graph oluşturur."""
    config = _get_config()
    llm = LLM(
        provider=config.llm.provider,
        model=config.llm.model,
        temperature=config.llm.temperature,
        api_key=config.llm.api_key,
    )
    repo = GraphRepository(llm=llm, app_config=config)
    return repo.get(name)


# langgraph.json entry point'leri — her biri tek satır
def supervisor_graph():
    return _make_graph("supervisor")


def routing_graph():
    return _make_graph("routing")


def report_agent_graph():
    return _make_graph("report_agent")

# Yeni agent eklendiğinde sadece bu iki satır eklenir:
# def finance_agent_graph():
#     return _make_graph("finance_agent")
```

- [ ] **Step 2: Import kontrolü**

```bash
python -c "from src.graphs.graph_entrypoints import supervisor_graph, routing_graph, report_agent_graph; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/graphs/graph_entrypoints.py
git commit -m "refactor: graph_entrypoints.py — single _make_graph() factory, remove per-agent boilerplate"
```

---

### Task 10: _chat_service.py — app_config Geçir

**Files:**
- Modify: `src/launch/_chat_service.py`

- [ ] **Step 1: build_chat_service fonksiyonunda GraphRepository çağrısını güncelle**

Şu satırı:

```python
graph = GraphRepository(llm).get(config.chatbot.graph_type)
```

Şununla değiştir:

```python
graph = GraphRepository(llm, app_config=config).get(config.chatbot.graph_type)
```

- [ ] **Step 2: Kontrol**

```bash
python -c "from src.launch._chat_service import build_chat_service; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/launch/_chat_service.py
git commit -m "fix: pass app_config to GraphRepository in build_chat_service"
```

---

### Task 11: routing/nodes.py — Standalone Fonksiyonları Sil

**Files:**
- Modify: `src/graphs/routing/nodes.py`

`routing/graph.py` `RoutingNodeKit` instance metodlarını kullanıyor. Standalone fonksiyonlar ölü kod.

- [ ] **Step 1: Standalone fonksiyonların kullanılmadığını doğrula**

```bash
grep -n "^def " src/graphs/routing/nodes.py
```

Bu komut module-level fonksiyon tanımlarını listeler. `RoutingNodeKit` dışındaki tüm fonksiyonlar (satır 840+) silinecek.

- [ ] **Step 2: Satır 840'tan sonrasını sil**

`routing/nodes.py`'de `RoutingNodeKit` sınıfı bittikten sonra gelen tüm standalone fonksiyon tanımlarını sil. Silinecek fonksiyonlar:
- `extract_user_input_node` (standalone)
- `extract_category_from_query` (standalone)
- `find_documents_node` (standalone)
- `select_most_relevant_document` (standalone)
- `detect_page_parameters_node` (standalone)
- `extract_page_parameters_node` (standalone)
- `update_url_with_parameters_node` (standalone)
- `format_navigation_output_node` (standalone)
- `validate_tool_results_node` (standalone)
- `find_alternative_pages_node` (standalone)
- `_execute_tools_for_parameters` (standalone helper)

**Silinmeyecekler:** `_is_base_url_parameter`, `_find_parametresiz_alternative`, `_build_metadata_filter`, `_parse_url_parameters`, `_guess_endpoint_from_param_name`, `_check_tool_results_validity`, `_create_empty_output`, `_document_to_navigation_output`, `_process_parameters` — bunlar `RoutingNodeKit` metotları tarafından kullanılan private helper'lar.

- [ ] **Step 3: Satır sayısı kontrolü**

```bash
wc -l src/graphs/routing/nodes.py
```

Beklenen: ~840 satır (önceki ~2060)

- [ ] **Step 4: Graph'ın hâlâ import edildiğini doğrula**

```bash
python -c "from src.graphs.routing.graph import RoutingGraph; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/graphs/routing/nodes.py
git commit -m "refactor: routing/nodes.py — delete ~1000 lines of duplicate standalone functions"
```

---

### Task 12: Integration Doğrulama

- [ ] **Step 1: Tüm graph'ların registry'ye kayıtlı olduğunu doğrula**

```bash
python -c "
from src.graphs.graph_repository import GraphRepository
from src.models.llm import LLM

class MockLLM:
    pass

repo = GraphRepository.__new__(GraphRepository)
repo.llm = MockLLM()
repo.app_config = None
repo._register_auto_discover()

from src.graphs.registry import GRAPH_REGISTRY
print('Kayıtlı graph\\'lar:', list(GRAPH_REGISTRY.keys()))
for name, desc in GRAPH_REGISTRY.items():
    print(f'  {name}: description={bool(desc.description)}, examples={len(desc.examples)}')
"
```

Beklenen:
```
Kayıtlı graph'lar: ['chat', 'routing', 'report_agent', 'supervisor']
  chat: description=True, examples=4
  routing: description=True, examples=4
  report_agent: description=True, examples=5
  supervisor: description=True, examples=0
```

- [ ] **Step 2: pytest collection hatasız**

```bash
python -m pytest --collect-only -q 2>&1 | tail -5
```

Beklenen: hata yok, ~368 test collected.

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "docs: update any stale comments after agent protocol refactor"
```
