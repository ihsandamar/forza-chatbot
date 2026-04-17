# AI Coding Agent Instructions - Forza Chatbot

## Project Overview

**Forza Chatbot** is an LLM-powered multi-interface chatbot orchestrating multiple specialized agents via LangGraph. It routes user queries through specialized workflows: navigation routing, conversational chat, and dynamic SQL-to-report generation.

**Tech Stack:** LangGraph 1.0 + LangChain + Chroma RAG + FastAPI/Gradio + OpenAI/Anthropic

---

## Architecture & Critical Patterns

### Multi-Agent Orchestration (Supervisor Pattern)

The codebase uses **LangGraph StateGraph** with a **supervisor orchestrator**:

```python
# src/graphs/supervisor/graph.py
START → supervisor (ReAct agent with handoff tools)
  ├→ routing (document navigation)
  ├→ chat (conversation)
  └→ report (SQL generation + visualization)
    ↓
  supervisor processes responses
    ↓
  END
```

**Key insight:** Supervisor uses `assign_to_*_agent()` tools for routing. Each sub-agent is a compiled StateGraph passed as a node.

### Graph Registration & Runtime Configuration

**1. Graph Discovery (Dynamic Loading)**
```python
# src/graphs/registry.py
@register_graph("supervisor")  # Decorator registers graph
class SupervisorGraph(BaseGraph[SupervisorAssistantConfiguration]):
    def __init__(self, llm: LLM, config: Optional[SupervisorAssistantConfiguration] = None)
    def build_graph(self) -> StateGraph
```

All graphs auto-discovered via `GraphRepository.register_all()` - no hard-coded imports.

**2. Configuration Composition Pattern (Critical!)**
```python
# Supervisor config holds sub-agent configs as FLAT fields
class SupervisorAssistantConfiguration:
    routing_token: str  # Flat field
    routing_system_prompt: str
    routing_model: str
    chat_system_prompt: str
    
    def get_routing_config(self) -> RoutingAssistantConfiguration:
        """Extract sub-agent config from flat fields"""
        return RoutingAssistantConfiguration(
            token=self.routing_token,
            system_prompt=self.routing_system_prompt,
            # ...
        )
```

**Why?** Enables LangGraph Studio UI to modify all configs (including sub-agents) in one interface. Sub-agents receive config via state injection Node + `config` parameter.

**3. Runtime Config Injection Pattern**
```python
# State-based config for subgraphs
def prepare_routing_config_node(default_supervisor_config):
    async def prepare_config(state: MessagesState, config: dict = None):
        supervisor_config = config['configurable'] if config else default_supervisor_config
        routing_config = supervisor_config.get_routing_config()
        
        # Inject into state for subgraph to access
        state["token"] = routing_config.token
        state["routing_system_prompt"] = routing_config.system_prompt
        return state
    return RunnableLambda(prepare_config)
```

In subgraph nodes, get config from state: `state.get("routing_system_prompt", default_prompt)`

### State Management

All graphs use **TypedDict-based state** (LangGraph 1.0 pattern):

```python
# src/graphs/base/graph_types.py
class MyGraphState(TypedDict):
    messages: Annotated[list, add_messages]  # Merges messages
    custom_field: str
    nested_dict: dict  # Direct dict (no nested TypedDict)
```

**Critical:** State fields are directly accessible: `state["field"]` not `state.field`. Use `add_messages` for automatic merging.

### Report Graph (HITL + Parallel Execution)

**Report-specific architecture:**

```
START → extract_intent
    ↓
query_analyzer (classify: new_query | refine | context_continuation)
    ↓
[CONDITIONAL] Intent-based routing
    ├→ new_query → ALL nodes (full execution)
    ├→ refine → SKIP table_creation (delta execution)
    └→ context_continuation → Lightweight skipping
    ↓
[PARALLEL] insights_extractor + viz_decision_maker (same time)
    ↓
HITL detection (ambiguity framework)
    │ ├→ Column ambiguity
    │ ├→ Value ambiguity
    │ ├→ Intent ambiguity
    │ └→ Context ambiguity
    ├→ If ambiguous: Build question → wait for user
    └→ If confident: Continue
    ↓
text2sql_executor
    ↓
visualization_builder
    ↓
response_formatter → END
```

**Key files:**
- `src/graphs/report/hitl_question_builder.py` - Question generation
- `src/graphs/report/ambiguity_framework.py` - Ambiguity types
- `src/graphs/report/nodes.py` - Execution nodes (includes parallel node)

**Parallel Execution Pattern (Phase 1 optimization):**
```python
async def parallel_node(state):
    # Both run concurrently, results merged into state
    insights_task = insights_extractor(state)
    viz_task = viz_decision_maker(state)
    
    results = await asyncio.gather(insights_task, viz_task)
    state["business_context"] = results[0]
    state["_viz_decision"] = results[1]
    return state
```

---

## Project-Specific Conventions

### 1. Configuration & Startup

**Config loading flow:**
```python
# main.py - Entry point
config = ConfigLoader.load_config("config/config.yaml")  # YAML with ${ENV_VAR} support
runtime_agent_settings = RuntimeAgentSettings.from_supervisor_config(SupervisorAssistantConfiguration())
chatbot = Chatbot(llm=..., graph=..., runtime_agent_settings=runtime_agent_settings)

# src/services/config_loader.py - YAML parser
# config/config.yaml - Config schema (chat.graph_type, report.hitl, embedding.provider, etc.)
```

**Interface selection:** `python main.py --interface [cli|gradio|api|fastapi] --config config/config.yaml`

### 2. Async-First Node Pattern

All graph nodes MUST be async:
```python
async def my_node(state: MyState, config: dict = None) -> MyState:
    """Node must be async. Access config via config['configurable']."""
    llm = config.get("configurable", {}).llm if config else default_llm
    result = await llm.ainvoke(...)
    state["field"] = result
    return state

# Register: builder.add_node("my_node", my_node)
```

### 3. Conditional Edge Pattern

```python
def my_conditional(state) -> str:
    """Return destination string (node name)."""
    if state.get("is_complex"):
        return "complex_handler"
    return "simple_handler"

builder.add_conditional_edges("my_node", my_conditional, 
    {"complex_handler": "complex_handler", "simple_handler": "simple_handler"})
```

### 4. Logging Convention

```python
import logging
logger = logging.getLogger(__name__)

logger.info("[SUPERVISOR] Message format with component prefix")
logger.debug(f"[ROUTING] Detailed debug info")
logger.error(f"[REPORT] Error occurred", exc_info=True)
```

### 5. Type Safety: Pydantic Configuration

All configurations inherit from `BaseAssistantConfiguration`:
```python
from src.models.base_assistant_configuration import BaseAssistantConfiguration

class MyGraphConfig(BaseAssistantConfiguration):
    custom_field: str
    
    # Mark sub-agent configs for dynamic discovery
    Field(json_schema_extra={"is_subagent_config": True})
```

LangGraph Studio will auto-detect and allow editing sub-configs.

---

## Testing & Development Workflows

### Running Tests

```bash
# Report graph tests (HITL, LLM integration, ambiguity detection)
pytest tests/graphs/report/test_enhanced_hitl.py -v
pytest tests/graphs/report/test_llm_integration.py -v

# Phase optimization tests
python test_phase1_optimization.py
python test_phase2_viz.py

# Full test suite
pytest tests/ -v
```

### Running Interfaces

```bash
# CLI (blocking input loop)
python main.py --interface cli

# Gradio web UI (localhost:7860)
python main.py --interface gradio --config config/config.yaml

# FastAPI (localhost:8000)
python main.py --interface api

# LangGraph Studio (requires langgraph-cli)
langgraph up --config config/config.yaml
```

### Building Executable

```bash
# Smart incremental build (checks package changes)
.\build_api.bat

# Output: dist/chatbot-api/chatbot-api.exe
# Config copied to dist/chatbot-api/config/
```

### Initialize Vector Stores

```bash
# Business rules for generic_text2sql
python src/graphs/generic_text2sql/setup_business_rules_vectorstore.py

# Catalog vectorstore (for routing)
python scripts/create_vector_store_for_catalog.py
```

---

## Common Dev Tasks

### Adding a New Graph

1. Create `src/graphs/my_feature/graph.py`
2. Define state via TypedDict
3. Inherit from `BaseGraph[MyConfig]`
4. Implement `build_graph()`, `_get_default_config()`, `_get_default_metadata()`
5. Use `@register_graph("my_feature")` decorator
6. Auto-discovered via `GraphRepository.register_all()`

### Adding a HITL Ambiguity Type

1. Add type to `AmbiguityType` enum in `src/graphs/report/ambiguity_framework.py`
2. Create detector function returning `AmbiguityContext`
3. Register in `AmbiguityDetectionEngine` (priority-ordered)
4. Implement corresponding case in `HitlQuestionBuilder.build_question()`
5. Test via `tests/graphs/report/test_enhanced_hitl.py`

### Debugging Graph Execution

```python
# Use LangGraph Studio for visual debugging
langgraph up --config config/config.yaml

# Or Log State at critical points
logger.debug(f"State keys: {list(state.keys())}")
logger.debug(f"Message count: {len(state.get('messages', []))}")

# Inspect node input/output
async def debug_node(state, config=None):
    logger.info(f"INPUT: {state}")
    result = await process(state)
    logger.info(f"OUTPUT: {result}")
    return result
```

---

## Integration Points & External Dependencies

### LLM Integration

```python
# src/models/llm.py
from src.models.llm import LLM
llm = LLM()

# Get chat model (respects provider from config)
chat_model = llm.get_chat()  # Uses openai or anthropic client

# Invoke
result = await chat_model.ainvoke({"messages": [HumanMessage(...)]})
```

**Providers in config:** `llm.provider` (openai, anthropic), uses `llm.api_key` environment variable.

### Vector Store Integration

```python
# src/graphs/routing/_setup_vectorstore.py
vectorstore = self._setup_vectorstore()  # Chroma instance
results = vectorstore.similarity_search(query, k=5)  # Returns docs with metadata
```

**Persistence:** `data/vector_store/` (chroma DB files)

### Report Agent Tools

```python
# Text2SQL execution
from src.graphs.generic_text2sql.graph import Text2SQLGraph
text2sql_result = await text2sql_graph.ainvoke(state)
# Returns: {"sql_queries": [...], "results": [...], "error": None}

# Visualization
from src.graphs.data_visualization.graph import VisualizationGraph
viz_result = await visualization_graph.ainvoke(state)
# Returns: {"chart_type": "pie", "image_base64": "..."}
```

### Database Connection

Uses config `database.uri` (PostgreSQL connection string), accessed via connection pools in nodes.

---

## Known Gotchas & Best Practices

1. **State Immutability**: Always return modified state copy, not mutation
   ```python
   state["field"] = new_value  # ✓ Correct
   return state
   ```

2. **Config Injection Timing**: Config injected at runtime via `config['configurable']` in node - don't cache in closure

3. **Subgraph State Conversion**: Report graph converts between Message-based state and internal states - check state schema boundaries

4. **HITL Priority**: Ambiguities checked in order (context > intent > scope > column > value). First match triggers question

5. **Parallel Node Handling**: Ensure both parallel tasks properly handle missing state fields with `.get()` + defaults

6. **Vector Store Rebuilds**: After updating business rules, rebuild index: `python setup_business_rules_vectorstore.py`

7. **PyInstaller Build**: Explicit imports required (in `src/graphs/graph_repository.py`) - dynamic imports won't work in exe

---

## Quick Reference: Key Files

| Path | Purpose |
|------|---------|
| `src/graphs/base/base_graph.py` | Abstract base for all graphs |
| `src/graphs/supervisor/graph.py` | Multi-agent orchestrator |
| `src/graphs/routing/graph.py` | Document/page navigation |
| `src/graphs/report/hitl_question_builder.py` | HITL question generation |
| `src/graphs/report/ambiguity_framework.py` | Ambiguity detection engine |
| `src/core/runtime_agent_settings.py` | Sub-agent runtime settings (system_prompt, token) |
| `main.py` | Entry point (CLI/interface selection) |
| `config/config.yaml` | Configuration schema |
| `requirements.txt` | Python dependencies |

---

## Documentation References

- **Two-Tier Supervisor:** `docs/two-tier-supervisor-architecture.md`
- **Generic Text2SQL:** `docs/generic_text2sql_architecture.md`
- **Supervisor Strategy:** `docs/supervisor-message-strategy.md`
- **Navigation Response:** `docs/navigation-response-format.md`
- **Phase Implementations:** `PHASE1_*`, `PHASE2_*`, `PHASE3_*` (optimization phases)
- **HITL System:** `ENHANCED_HITL_IMPLEMENTATION.md`
- **Report Optimization:** `CONVERSATIONAL_REPORT_OPTIMIZATION_PLAN.md`
