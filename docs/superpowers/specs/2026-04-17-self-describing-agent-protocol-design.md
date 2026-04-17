# Self-Describing Agent Protocol — Design Spec

**Tarih:** 2026-04-17
**Kapsam:** Agent ekleme sürecini 7 dosyadan 2-3 satıra indiren mimari refactor
**Durum:** Onaylandı — Implementation bekliyor

---

## 1. Problem

Şu an sisteme yeni bir agent eklemek şu 7 noktaya dokunmayı gerektiriyor:

1. `src/graphs/new_agent/` — agent dizini (beklenen)
2. `graph_repository.py` → `register_all()` içine hardcoded import
3. `graph_entrypoints.py` → yeni factory fonksiyon
4. `langgraph.json` → yeni entry
5. `supervisor/tools.py` → `assign_to_X_agent` tool
6. `supervisor/graph.py` → destination + node + edge
7. `supervisor/prompts.py` → agent açıklaması

Bu süreç belgesiz, hata-prone ve sürdürülemez. Geliştirici hangi dosyaların dokunulması gerektiğini bilmiyor.

---

## 2. Hedef

Yeni agent eklemek = sadece kendi dizinini yaz. Supervisor, registry, entrypoints — hiçbirine dokunulmaz.

---

## 3. Tasarım

### 3.1 AgentDescriptor ve Registry

**Dosya:** `src/graphs/registry.py`

```python
from dataclasses import dataclass, field
from typing import Optional, Type

@dataclass
class AgentDescriptor:
    name: str
    description: str
    examples: list[str] = field(default_factory=list)
    state_type: str = "messages"        # "messages" | "report" | custom
    returns_to_supervisor: bool = True  # False = report_agent gibi kendi akışını tamamlar
    cls: Optional[Type] = None          # Graph sınıfı — decorator tarafından set edilir

# name → AgentDescriptor
GRAPH_REGISTRY: dict[str, AgentDescriptor] = {}

def register_graph(
    name: str,
    description: str,
    examples: list[str] = None,
    state_type: str = "messages",
    returns_to_supervisor: bool = True,
):
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

### 3.2 create() Classmethod — BaseGraph Protokolü

**Dosya:** `src/graphs/base/base_graph.py`

Her `BaseGraph` subclass'ı bir `create()` classmethod sağlar. Bu method, graph'ın tüm setup bağımlılıklarını (DB bağlantısı, dosya yolları, vectorstore) kendi içinde çözer.

```python
class BaseGraph(ABC, Generic[ConfigT]):
    @classmethod
    def create(cls, llm: LLM, app_config) -> "BaseGraph":
        """
        Varsayılan factory: sadece llm yeterli olan basit graph'lar için.
        Karmaşık setup gerektiren graph'lar bu metodu override eder.
        """
        return cls(llm=llm)
```

**Karmaşık graph örneği:**

```python
# src/graphs/report_agent/graph.py
@register_graph(
    name="report_agent",
    description="ERP veri analizi, satış/stok raporları ve SQL sorguları.",
    examples=["geçen ayın satışları", "en çok satan ürünler", "şube bazlı ciro"],
    state_type="report",
    returns_to_supervisor=False,
)
class ReportAgentGraph(BaseGraph):
    @classmethod
    def create(cls, llm: LLM, app_config) -> "ReportAgentGraph":
        project_root = Path(__file__).parent.parent.parent.parent
        return build_report_agent_graph(
            llm=llm.get_chat(),
            table_name=app_config.report.table_name,
            connection_string=app_config.database.uri,
            business_rules_path=str(project_root / "src/graphs/report_agent/data/business_rules.json"),
            chroma_persist_dir=str(project_root / "data/vector_store"),
        )
```

**Kural:** `create()` dışında import zamanında hiçbir I/O, DB bağlantısı veya dosya okuma yapılmaz.

### 3.3 Auto-Discovery — GraphRepository

**Dosya:** `src/graphs/graph_repository.py`

```python
class GraphRepository:
    def __init__(self, llm: LLM, app_config=None):
        self.llm = llm
        self.app_config = app_config
        self.register_all()

    def get(self, graph_type: str):
        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        descriptor = GRAPH_REGISTRY[graph_type]
        return descriptor.cls.create(llm=self.llm, app_config=self.app_config)

    def register_all(self):
        if getattr(sys, "frozen", False):
            self._register_explicit()   # PyInstaller
        else:
            self._register_auto_discover()  # Dev / Docker

    def _register_auto_discover(self):
        """
        src/graphs/*/graph.py pattern'ini glob ile tarar.
        @register_graph decorator'ı tetiklenince GRAPH_REGISTRY dolar.
        """
        import importlib
        from glob import glob
        from pathlib import Path

        pattern = str(Path(__file__).parent / "*/graph.py")
        for path in glob(pattern):
            parts = Path(path).parts
            # src/graphs/chat/graph.py → src.graphs.chat.graph
            idx = next(i for i, p in enumerate(parts) if p == "src")
            module_name = ".".join(parts[idx:]).removesuffix(".py")
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                logger.warning(f"Graph yüklenemedi: {module_name} — {e}")

    def _register_explicit(self):
        """
        PyInstaller build için: sadece bu liste güncellenir.
        Yeni agent = bu listeye 1 satır.
        """
        import src.graphs.chat.graph
        import src.graphs.supervisor.graph
        import src.graphs.routing.graph
        import src.graphs.report_agent.graph
        # YENİ AGENT: buraya 1 satır eklenir
```

### 3.4 Dynamic Supervisor

**Dosya:** `src/graphs/supervisor/graph.py`

`build_graph()` artık registry'i okuyarak araçları ve sistem promptunu otomatik üretir.

```python
def build_graph(self) -> StateGraph:
    # Registry'den supervisor dışı tüm agent'ları al
    agents = {
        name: desc for name, desc in GRAPH_REGISTRY.items()
        if name != "supervisor"
    }

    # Dinamik tool üretimi
    handoff_tools = [_make_handoff_tool(name, desc) for name, desc in agents.items()]
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
        subgraph = desc.cls.create(self.llm, self.app_config).build_graph()
        builder.add_node(name, subgraph)
        if desc.returns_to_supervisor:
            builder.add_edge(name, "supervisor")
        else:
            builder.add_edge(name, END)

    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", END)
    return builder.compile(checkpointer=self.get_memory())
```

**Handoff tool factory:**

```python
def _make_handoff_tool(name: str, desc: AgentDescriptor):
    examples_text = "\n".join(f"  - {ex}" for ex in desc.examples)
    doc = f"{desc.description}\n\nÖrnekler:\n{examples_text}"

    @tool(name=f"assign_to_{name}", description=doc)
    def handoff(reason: str) -> str:
        """reason: Neden bu agent'a yönlendiriyorsun."""
        return f"Transferring to {name}: {reason}"

    return handoff
```

**Supervisor prompt template:**

```python
# src/graphs/supervisor/prompts.py
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

### 3.5 graph_entrypoints.py Basitleştirme

```python
def _make_graph(name: str):
    config = _get_config()
    llm = LLM(provider=config.llm.provider, model=config.llm.model,
               temperature=config.llm.temperature, api_key=config.llm.api_key)
    repo = GraphRepository(llm=llm, app_config=config)
    return repo.get(name)

# langgraph.json için gerekli named entry'ler — birer satır
def supervisor_graph():    return _make_graph("supervisor")
def routing_graph():       return _make_graph("routing")
def report_agent_graph():  return _make_graph("report_agent")
# YENİ AGENT: def finance_agent_graph(): return _make_graph("finance_agent")
```

### 3.6 routing/nodes.py Temizliği

`routing/graph.py` zaten `RoutingNodeKit` instance metodlarını kullanıyor (`self.node_kit.*`).
Standalone fonksiyonlar (satır 840-2060) ve `graph.py`'deki kullanılmayan import bloğu (satır 32-42) silinir.

**Ayrıca:** `routing/graph.py` satır 45'teki module-level `ConfigLoader.load_config()` çağrısı
`RoutingGraph.create()` classmethod'una taşınır — import zamanı I/O ortadan kalkar.

---

## 4. Mevcut Graph'lar için Yapılacaklar

| Graph | Değişiklik |
|---|---|
| `supervisor/graph.py` | `@register_graph(...)` ekle, `build_graph()` dinamik hale getir, `app_config` al |
| `routing/graph.py` | `@register_graph(...)` güncelle (description/examples ekle), `create()` ekle, module-level config kaldır |
| `chat/graph.py` | `@register_graph(...)` güncelle (description/examples ekle) |
| `report_agent/graph.py` | `@register_graph(...)` ekle, `create()` ekle |
| `routing/nodes.py` | Satır 840-2060 sil (standalone fonksiyonlar) |
| `routing/graph.py` | Satır 32-42 sil (kullanılmayan imports) |

---

## 5. Yeni Agent Ekleme Protokolü (Sonuç)

```
1. src/graphs/new_agent/ dizini oluştur
   - graph.py: @register_graph(name, description, examples) + create() override (gerekirse)
   - state.py, nodes.py, prompts.py, vb.

2. PyInstaller build kullanıyorsan:
   - graph_repository.py → _register_explicit() içine 1 satır import ekle

3. LangGraph Server'da expose etmek istersen:
   - graph_entrypoints.py → 1 satır fonksiyon
   - langgraph.json → 1 satır entry
```

Supervisor, tools, prompts: **dokunulmaz.**

---

## 6. Kapsam Dışı

- `report_agent` iç mantığı (text2sql, visualization) — bu spec sadece omurgayı etkiler
- `ReportState` değişikliği — ayrı spec
- Test altyapısı — ayrı kapsam

---

## 7. Başarı Kriterleri

- [ ] Yeni bir test agent'ı (`dummy_agent`) sadece kendi dizininde yazılarak supervisor'dan çağrılabilir
- [ ] `routing/nodes.py` 2060 → ~840 satır
- [ ] `graph_entrypoints.py` per-agent hardcoding kaldırıldı
- [ ] Import zamanında sıfır I/O (ConfigLoader, DB, dosya okuma)
- [ ] Mevcut 3 graph davranışı değişmedi
