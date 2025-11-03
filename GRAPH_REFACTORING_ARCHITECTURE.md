# Graph Refactoring Architecture Yol Haritası

## 📋 Özet

Bu döküman, forza-chatbot projesindeki graph (agent) mekanizmasının yapısal iyileştirmesini hedeflemektedir. Amaç, graphları daha modüler, DI-uyumlu, type-safe ve bakım yapılabilir hale getirmektir.

---

## 🔍 Mevcut Durum

### Mevcut Yapı
```
src/graphs/
├── base_graph.py (ABC: BaseGraph)
├── graph_repository.py (Registry Pattern)
├── registry.py (GRAPH_REGISTRY dict)
├── chat_graph.py
├── text2sql_graph.py
├── core_text2sql_graph.py
├── generic_sql_graph.py
├── forza_rag_graph.py
├── forza_routing_graph.py
├── forza_toolkit_graph.py
├── gib_mevzuat_graph.py
├── intent_graph.py
├── query_extraction_graph.py
├── master_report_graph.py
├── sefim_rag_graph.py
├── supervisor_graph.py
└── enhanced_query_extraction/
    ├── models.py
    ├── agents.py
    ├── tools.py
    └── utils.py
```

### Mevcut Sınırlamalar
1. **Config Management Yok**: Graphlar hardcoded parametreleri kullanıyor
2. **Type Safety Eksik**: State ve output tiplerinin validation'ı yok
3. **DI Zayıf**: LLM dışında dependency injection pattern yok
4. **Documentation Eksik**: Graph'ın çalıştığı tiplerle ilgili metadata yok
5. **File Organization Karışık**: Benzer graphlar bir klasörde toplanmamış
6. **No Metadata**: Graph capabilities, requirements, version bilgisi yok

---

## 🎯 Hedefler

1. **Graph-Specific Configuration**: Her graph kendi `config.yaml` dosyası
2. **Type Safety**: State, Output, Config için strict typing
3. **DI Compatible**: Dependency Injection pattern uyumlu
4. **Metadata System**: Graph capabilities ve requirements tracking
5. **Organized Structure**: Logical grouping (routing, extraction, sql, rag, vb.)
6. **Easy to Develop**: Developer-friendly documentation ve examples
7. **Future-Ready**: Prompt invoke'lar için hazırlıklı (Phase 2)

---

## 🏗️ File Structure (Hedef)

```
src/graphs/
├── __init__.py
├── base/
│   ├── __init__.py
│   ├── base_graph.py (Enhanced BaseGraph with config support)
│   ├── graph_config.py (GraphConfig dataclass)
│   ├── graph_state.py (State typing & validation)
│   ├── graph_metadata.py (GraphMetadata - capabilities, requirements)
│   └── graph_types.py (Type definitions: InputType, OutputType)
├── core/
│   ├── __init__.py
│   ├── chat_graph.py (Chat interface graph)
│   └── intent_graph.py (Intent detection graph)
├── routing/
│   ├── __init__.py
│   ├── forza_routing_graph.py (Main routing/supervisor)
│   └── supervisor_graph.py (Supervisor/orchestrator)
├── extraction/
│   ├── __init__.py
│   ├── query_extraction_graph.py
│   ├── enhanced_query_extraction_graph.py
│   └── enhanced_query_extraction/
│       ├── __init__.py
│       ├── models.py
│       ├── agents.py
│       ├── tools.py
│       └── utils.py
├── sql/
│   ├── __init__.py
│   ├── text2sql_graph.py
│   ├── core_text2sql_graph.py
│   └── generic_sql_graph.py
├── rag/
│   ├── __init__.py
│   ├── forza_rag_graph.py
│   ├── sefim_rag_graph.py
│   ├── gib_mevzuat_graph.py
│   └── forza_toolkit_graph.py
├── report/
│   ├── __init__.py
│   └── master_report_graph.py
├── repository/
│   ├── __init__.py
│   ├── graph_repository.py (Enhanced)
│   └── graph_loader.py (Config-based graph loading)
├── registry/
│   ├── __init__.py
│   ├── registry.py (Enhanced registry)
│   └── graph_discovery.py (Auto-discovery)
└── configs/
    ├── __init__.py
    ├── chat_graph.yaml
    ├── intent_graph.yaml
    ├── forza_routing_graph.yaml
    ├── query_extraction_graph.yaml
    ├── text2sql_graph.yaml
    ├── core_text2sql_graph.yaml
    ├── generic_sql_graph.yaml
    ├── forza_rag_graph.yaml
    ├── sefim_rag_graph.yaml
    ├── gib_mevzuat_graph.yaml
    ├── forza_toolkit_graph.yaml
    ├── master_report_graph.yaml
    ├── supervisor_graph.yaml
    └── defaults.yaml (Default configuration)
```

---

## 📐 Type Definitions (Phase 1)

### 1. GraphConfig (src/graphs/base/graph_config.py)

```python
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

@dataclass
class GraphConfig:
    """
    Graph-level configuration container.

    Each graph can load its own config.yaml file.
    Supports parameter override at runtime.
    """
    # Identity
    name: str  # Unique graph identifier (e.g., "text2sql_graph")
    version: str = "1.0.0"
    description: str = ""

    # Parameters (from config.yaml)
    parameters: Dict[str, Any] = field(default_factory=dict)

    # Optional: Model preferences
    model_overrides: Optional[Dict[str, str]] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None

    # Runtime configuration
    timeout: int = 30
    max_retries: int = 3
    enable_logging: bool = True

    # Metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'GraphConfig':
        """Load configuration from YAML file."""
        pass

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        pass
```

### 2. GraphMetadata (src/graphs/base/graph_metadata.py)

```python
from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum

class GraphCapability(Enum):
    """Graph capabilities."""
    TEXT_GENERATION = "text_generation"
    INTENT_DETECTION = "intent_detection"
    QUERY_EXTRACTION = "query_extraction"
    SQL_GENERATION = "sql_generation"
    ROUTING = "routing"
    RAG = "rag"
    TOOL_USE = "tool_use"
    REPORTING = "reporting"

@dataclass
class InputSpec:
    """Input specification for graph."""
    name: str
    type: str  # "list[dict]", "dict", "str", etc.
    required: bool = True
    description: str = ""

@dataclass
class OutputSpec:
    """Output specification for graph."""
    name: str
    type: str  # "str", "dict", "list[dict]", etc.
    description: str = ""

@dataclass
class GraphMetadata:
    """
    Metadata about graph capabilities, requirements, and specifications.

    This helps with:
    - Graph discovery and selection
    - Type checking and validation
    - Documentation generation
    - Capability checking before graph selection
    """

    # Identity
    name: str
    category: str  # "routing", "extraction", "sql", "rag", "core"

    # Capabilities
    capabilities: List[GraphCapability]

    # Input/Output specs
    input_spec: InputSpec
    output_spec: OutputSpec

    # Requirements
    required_tools: List[str] = None
    required_models: List[str] = None

    # Additional metadata
    version: str = "1.0.0"
    author: str = ""
    last_updated: str = ""
    tags: List[str] = None

    def has_capability(self, capability: GraphCapability) -> bool:
        """Check if graph has specific capability."""
        return capability in self.capabilities

    def get_capabilities(self) -> List[str]:
        """Get list of capability names."""
        return [cap.value for cap in self.capabilities]
```

### 3. GraphState & GraphOutput (src/graphs/base/graph_types.py)

```python
from typing import TypedDict, Any, List, Optional, Dict
from enum import Enum

class MessageRole(Enum):
    """Message role in conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"

class Message(TypedDict):
    """Standard message format across all graphs."""
    role: MessageRole
    content: str
    metadata: Optional[Dict[str, Any]]

class GraphState(TypedDict, total=False):
    """
    Base state type for all graphs.

    Each graph can extend this with additional fields.
    total=False allows optional fields.
    """
    # Core fields (all graphs)
    messages: List[Message]
    session_id: str
    user_id: Optional[str]

    # Metadata
    metadata: Dict[str, Any]

    # Graph-specific fields should be added in subclasses
    # Example:
    # class Text2SqlState(GraphState):
    #     extracted_query: str
    #     generated_sql: str

class OutputType(Enum):
    """Output type from graph."""
    TEXT = "text"
    STRUCTURED = "structured"
    TOOL_CALL = "tool_call"
    ROUTING = "routing"

class GraphOutput(TypedDict, total=False):
    """
    Standardized output from all graphs.
    """
    type: OutputType
    content: str  # Main response

    # For structured output
    data: Optional[Dict[str, Any]]

    # For routing
    next_graph: Optional[str]
    routing_reason: Optional[str]

    # For tool calls
    tool_name: Optional[str]
    tool_args: Optional[Dict[str, Any]]

    # Metadata
    metadata: Dict[str, Any]
    confidence: float
```

### 4. Enhanced BaseGraph (src/graphs/base/base_graph.py)

```python
from abc import ABC, abstractmethod
from typing import Type, Optional, Dict, Any
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.models.models import LLM
from src.graphs.base.graph_config import GraphConfig
from src.graphs.base.graph_metadata import GraphMetadata
from src.graphs.base.graph_types import GraphState, GraphOutput

class BaseGraph(ABC):
    """
    Enhanced BaseGraph with:
    - Configuration support
    - Metadata tracking
    - Type safety
    - DI compatibility
    """

    def __init__(
        self,
        llm: LLM,
        state_class: Type[GraphState],
        config: Optional[GraphConfig] = None,
        metadata: Optional[GraphMetadata] = None,
        memory: Optional[MemorySaver] = None
    ):
        self.llm = llm
        self.state_class = state_class
        self.config = config or GraphConfig(name=self.__class__.__name__)
        self.metadata = metadata or self._get_default_metadata()
        self.memory = memory or MemorySaver()

    @abstractmethod
    def _get_default_metadata(self) -> GraphMetadata:
        """
        Return default metadata for this graph.
        Subclasses must implement.
        """
        pass

    @abstractmethod
    def build_graph(self) -> StateGraph:
        """
        Build and return the StateGraph.
        Subclasses must implement.
        """
        pass

    def get_graph_builder(self) -> StateGraph:
        """Get StateGraph builder."""
        return StateGraph(self.state_class)

    def get_memory(self) -> MemorySaver:
        """Get memory object."""
        return self.memory

    def get_config(self) -> GraphConfig:
        """Get graph configuration."""
        return self.config

    def get_metadata(self) -> GraphMetadata:
        """Get graph metadata."""
        return self.metadata

    def validate_input(self, state: Dict[str, Any]) -> bool:
        """
        Validate input against input spec.
        Subclasses can override for custom validation.
        """
        # Basic validation: check if required fields exist
        required_field = self.metadata.input_spec.name
        return required_field in state
```

---

## 🔄 Implementation Plan (Phase 1)

### Step 1: Create Base Infrastructure
- [ ] Create `src/graphs/base/` directory
- [ ] Implement `graph_config.py` - GraphConfig dataclass
- [ ] Implement `graph_metadata.py` - GraphMetadata & GraphCapability
- [ ] Implement `graph_types.py` - Type definitions
- [ ] Enhance `base_graph.py` - Add config & metadata support
- [ ] Update imports in `__init__.py`

### Step 2: Organize Existing Graphs
- [ ] Create subdirectories: `core/`, `routing/`, `extraction/`, `sql/`, `rag/`, `report/`
- [ ] Move existing graph files to appropriate directories
- [ ] Update all relative imports

### Step 3: Create Configuration Files
- [ ] Create `src/graphs/configs/` directory
- [ ] Create `defaults.yaml` with default configuration
- [ ] Create individual `*.yaml` files for each graph
- [ ] Implement `graph_config.from_yaml()` method

### Step 4: Update GraphRepository
- [ ] Enhance GraphRepository to support config loading
- [ ] Create `graph_loader.py` for config-based graph creation
- [ ] Update registry to include metadata
- [ ] Implement graph discovery

### Step 5: Update Existing Graphs
- [ ] Add metadata to each graph class
- [ ] Add config loading to constructors
- [ ] Add input/output validation
- [ ] Update imports after reorganization

### Step 6: Documentation & Testing
- [ ] Create graph development guide
- [ ] Add examples for creating new graphs
- [ ] Write unit tests for type validation
- [ ] Document metadata system

---

## 💾 Configuration Example

### `src/graphs/configs/text2sql_graph.yaml`

```yaml
name: "text2sql_graph"
version: "1.0.0"
description: "Convert natural language queries to SQL"
category: "sql"

parameters:
  max_iterations: 3
  temperature: 0.0
  sql_dialect: "postgresql"
  schema_context_window: 2000

tags:
  - "sql-generation"
  - "database"
  - "llm-powered"

metadata:
  capabilities:
    - "query_extraction"
    - "sql_generation"
    - "validation"

  input_requirements:
    - "natural_language_query"
    - "database_schema"

  output_type: "structured"
  output_fields:
    - "sql_query"
    - "explanation"
    - "confidence_score"

# Phase 2: Prompt Configuration
# prompts:
#   extract_query: "prompts/text2sql/extract_query.txt"
#   generate_sql: "prompts/text2sql/generate_sql.txt"
#   validate_sql: "prompts/text2sql/validate_sql.txt"
```

### Usage in Code

```python
from src.graphs.sql.text2sql_graph import Text2SqlGraph
from src.graphs.base.graph_config import GraphConfig

# Load configuration
config = GraphConfig.from_yaml("src/graphs/configs/text2sql_graph.yaml")

# Create graph with config
graph = Text2SqlGraph(llm=llm, config=config)

# Access config parameters
max_iterations = graph.get_config().parameters.get("max_iterations", 3)
```

---

## 📝 Example: Refactored Graph

### Old Implementation (Current)

```python
# src/graphs/text2sql_graph.py
from langgraph.graph import StateGraph

class Text2SqlGraph:
    def __init__(self, llm):
        self.llm = llm

    def build_graph(self):
        builder = StateGraph(dict)
        # ... build graph with hardcoded parameters
        return builder.compile()
```

### New Implementation (Phase 1)

```python
# src/graphs/sql/text2sql_graph.py
from typing import Type, Dict, Any, Optional
from langgraph.graph import StateGraph

from src.models.models import LLM
from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_config import GraphConfig
from src.graphs.base.graph_metadata import GraphMetadata, GraphCapability, InputSpec, OutputSpec
from src.graphs.base.graph_types import GraphState

class Text2SqlState(GraphState):
    """Text2SQL specific state."""
    natural_language_query: str
    database_schema: str
    extracted_query: Optional[str]
    generated_sql: Optional[str]
    validation_result: Optional[bool]

class Text2SqlGraph(BaseGraph):
    """
    Convert natural language queries to SQL.

    Capabilities:
    - Query extraction and understanding
    - SQL generation
    - Query validation
    """

    def __init__(
        self,
        llm: LLM,
        config: Optional[GraphConfig] = None
    ):
        if config is None:
            config = GraphConfig.from_yaml(
                "src/graphs/configs/text2sql_graph.yaml"
            )

        super().__init__(
            llm=llm,
            state_class=Text2SqlState,
            config=config,
            metadata=self._get_default_metadata()
        )

    def _get_default_metadata(self) -> GraphMetadata:
        """Define graph metadata."""
        return GraphMetadata(
            name="text2sql_graph",
            category="sql",
            capabilities=[
                GraphCapability.QUERY_EXTRACTION,
                GraphCapability.SQL_GENERATION,
            ],
            input_spec=InputSpec(
                name="messages",
                type="list[dict]",
                description="User query in natural language"
            ),
            output_spec=OutputSpec(
                name="result",
                type="dict",
                description="Generated SQL and metadata"
            ),
            required_tools=["database_schema_loader"],
            version="1.0.0",
            author="Forza Team",
            tags=["sql", "database", "llm-powered"]
        )

    def build_graph(self) -> StateGraph:
        """Build the StateGraph."""
        builder = self.get_graph_builder()

        # Use config parameters
        max_iterations = self.config.parameters.get("max_iterations", 3)
        temperature = self.config.parameters.get("temperature", 0.0)

        # Add nodes and edges using LangGraph API
        builder.add_node("extract_query", self.extract_query_node)
        builder.add_node("generate_sql", self.generate_sql_node)
        builder.add_node("validate_sql", self.validate_sql_node)

        builder.add_edge("__start__", "extract_query")
        builder.add_conditional_edges(
            "generate_sql",
            self.should_validate,
            {True: "validate_sql", False: "__end__"}
        )

        return builder.compile(checkpointer=self.memory)

    async def extract_query_node(self, state: Text2SqlState) -> Text2SqlState:
        """Extract query intent from natural language."""
        # Implementation using LLM
        pass

    async def generate_sql_node(self, state: Text2SqlState) -> Text2SqlState:
        """Generate SQL from extracted query."""
        # Implementation using LLM
        pass

    async def validate_sql_node(self, state: Text2SqlState) -> Text2SqlState:
        """Validate generated SQL."""
        # Implementation
        pass

    def should_validate(self, state: Text2SqlState) -> bool:
        """Decide if validation is needed."""
        return True
```

---

## 🔌 DI Integration

### With Existing Builder

```python
from src.builders.chatbot_builder import ChatbotBuilder
from src.builders.dependency_factory import DependencyFactory
from src.builders.adapter_factory import AdapterFactory

# Create dependencies
dep_factory = DependencyFactory()
adapter_factory = AdapterFactory()

# Build chatbot with DI
builder = ChatbotBuilder(
    factory=dep_factory,
    adapter_factory=adapter_factory
)

chatbot = (
    builder
    .set_llm_model("gpt-4")
    .set_graph("text2sql_graph")  # Will load config automatically
    .set_adapter("default")
    .build()
)
```

### Direct Instantiation with Config

```python
from src.graphs.sql.text2sql_graph import Text2SqlGraph
from src.graphs.base.graph_config import GraphConfig

llm = LLM.from_env()

# Load config from file
config = GraphConfig.from_yaml("src/graphs/configs/text2sql_graph.yaml")

# Create graph with DI-ready constructor
graph = Text2SqlGraph(llm=llm, config=config)

# Use in chatbot
chatbot = Chatbot(
    llm=llm,
    graph=graph.build_graph(),
    config={"configurable": {"max_iterations": 3}}
)
```

---

## 📊 Benefits

### For Developers
- ✅ Clear input/output types (type hints)
- ✅ Self-documenting graphs (metadata)
- ✅ Easy to create new graphs (template)
- ✅ Configuration per graph (no hardcoding)
- ✅ Better error messages (validation)

### For Operations
- ✅ Easy to discover graph capabilities
- ✅ Configuration management (YAML)
- ✅ Type safety prevents runtime errors
- ✅ Organized file structure
- ✅ Easier debugging and monitoring

### For Future
- ✅ Ready for Phase 2 (prompt invoke)
- ✅ Ready for caching layer
- ✅ Ready for graph versioning
- ✅ Ready for A/B testing
- ✅ Ready for observability

---

## 🚀 Phase 2 (Future)

### Prompt Management
```yaml
# src/graphs/configs/text2sql_graph.yaml
prompts:
  extract_query:
    path: "prompts/text2sql/extract_query.txt"
    temperature: 0.0
    max_tokens: 500

  generate_sql:
    path: "prompts/text2sql/generate_sql.txt"
    temperature: 0.0
    max_tokens: 1000

  validate_sql:
    path: "prompts/text2sql/validate_sql.txt"
    temperature: 0.0
```

### Implementation
```python
# src/graphs/sql/text2sql_graph.py
async def extract_query_node(self, state: Text2SqlState) -> Text2SqlState:
    """Extract query using configured prompt."""
    prompt_config = self.config.prompts["extract_query"]
    prompt_text = load_prompt(prompt_config.path)

    response = await self.llm.invoke(
        prompt_text,
        temperature=prompt_config.temperature,
        max_tokens=prompt_config.max_tokens
    )

    state["extracted_query"] = response
    return state
```

---

## 📅 Timeline

| Phase | Task | Duration | Dependencies |
|-------|------|----------|--------------|
| 1.1 | Create base infrastructure | 3 days | None |
| 1.2 | Organize existing graphs | 2 days | 1.1 |
| 1.3 | Create config files | 2 days | 1.1, 1.2 |
| 1.4 | Update GraphRepository | 2 days | 1.1, 1.2 |
| 1.5 | Update existing graphs | 5 days | 1.3, 1.4 |
| 1.6 | Testing & documentation | 3 days | 1.5 |
| **Total Phase 1** | | **17 days** | |
| 2.1 | Prompt management | 3 days | Phase 1 |
| 2.2 | Prompt loading system | 3 days | 2.1 |
| 2.3 | Integrate with graphs | 2 days | 2.1, 2.2 |

---

## ✅ Checklist for New Graph Development

Use this when creating a new graph:

```python
# ✅ 1. Create state class
class MyGraphState(GraphState):
    # Add graph-specific fields
    pass

# ✅ 2. Implement metadata
def _get_default_metadata(self) -> GraphMetadata:
    return GraphMetadata(
        name="my_graph",
        category="category_name",
        capabilities=[...],
        input_spec=...,
        output_spec=...,
    )

# ✅ 3. Create config file
# src/graphs/configs/my_graph.yaml

# ✅ 4. Implement build_graph()
def build_graph(self) -> StateGraph:
    builder = self.get_graph_builder()
    # Add nodes and edges
    return builder.compile(checkpointer=self.memory)

# ✅ 5. Add to appropriate directory
# src/graphs/category/my_graph.py

# ✅ 6. Update __init__.py
# from src.graphs.category.my_graph import MyGraph

# ✅ 7. Test
# - Unit tests for nodes
# - Integration tests
# - Config loading test
```

---

## 🔗 Related Documentation

- [Chatbot Refactoring Architecture](./CHATBOT_REFACTORING_ARCHITECTURE.md) - Core chatbot refactoring
- [Exception Hierarchy](./src/core/exceptions/) - Error handling patterns
- [Adapter Pattern](./src/adapters/) - State adaptation
- [Builder Pattern](./src/builders/) - Dependency injection

---

## 📞 Support

For questions about graph refactoring, refer to:
- Graph development guide: `GRAPH_DEVELOPMENT_GUIDE.md` (Phase 1.6)
- Example graphs: `src/graphs/core/`, `src/graphs/sql/`
- Tests: `tests/graphs/` (Phase 1.6)
