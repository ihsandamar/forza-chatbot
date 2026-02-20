# Report Agent Rewrite — Network Architecture + Tam State Ayrımı

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Report agent'ı her sub-agent'ın kendi TypedDict state'ine sahip olduğu, LangGraph network mimarisi üzerine sıfırdan yeniden yaz. Mevcut business logic dosyaları değişmeden import edilir; sadece orchestration ve node katmanı yeniden yazılır.

**Architecture:** Thin `OrchestratorState` coordination bus + 4 bağımsız sub-agent. Her agent kendi `State` TypedDict'iyle izole çalışır. Orchestrator Bridge Node pattern ile `OrchestratorState ↔ AgentState` mapping'ini yönetir. Routing conditional edges ile yapılır.

**Parallelism Strategy:** LangGraph native fan-out/fan-in. Bağımsız node'lara `graph.add_edge(A, B)` + `graph.add_edge(A, C)` ile ayrı ayrı edge eklenir — LangGraph B ve C'yi otomatik olarak paralel çalıştırır, fan-in node'unda (D) her ikisini bekler. `asyncio.gather()` kullanılmaz; paralel node'lar her zaman farklı state key'lerine yazar.

**Tech Stack:** LangGraph `StateGraph`, `Command`, `interrupt()`, Python `TypedDict`.

---

## LangGraph Parallelism Rehberi

> Bu bölümü önce oku. Parallelism tüm agent graph'larının temel tasarım prensibidir.

### Temel Pattern

```python
# Fan-out: A'dan sonra B ve C paralel çalışır — sadece edge yeterli
graph.add_edge("A", "B")
graph.add_edge("A", "C")

# Fan-in: D, B ve C'nin her ikisi de tamamlanınca otomatik başlar
graph.add_edge("B", "D")
graph.add_edge("C", "D")
```

LangGraph, birden fazla incoming edge'i olan bir node'u tüm predecessorları tamamlanana kadar otomatik bekletir. Ekstra scheduler, lock veya asyncio kodu gerektirmez.

### Çakışma Önleme Kuralı (zorunlu)

Paralel çalışan node'lar **farklı state key'lerine** yazmalı. Aynı key'e yazan iki paralel node varsa LangGraph son gelen ile override eder (veri kaybolur).

### Bu Sistemde Paralel Noktalar

| Agent | Fan-out Node | Paralel Node'lar | Fan-in Node | Kazanım |
|---|---|---|---|---|
| **ClassifyAgent** | `classify_intent` | `detect_references` + `validate_entities` | `detect_ambiguity` | Entity ve referans tespiti aynı anda |
| **AnalysisAgent** | `check_results` | `extract_insights` + `decide_viz` | `build_analysis_result` | LLM insights + viz kararı aynı anda |

---

## Korunan Dosyalar — Değişmez, Import Edilir

```
# Business Logic (tamamen korunur)
src/graphs/report/intent.py                   → ClassifyAgent kullanır
src/graphs/report/conversation_manager.py     → ClassifyAgent kullanır
src/graphs/report/ambiguity_detectors.py      → ClassifyAgent kullanır
src/graphs/report/ambiguity_framework.py      → ClassifyAgent kullanır
src/graphs/report/ambiguity_router.py         → ClassifyAgent kullanır
src/graphs/report/hitl_question_builder.py    → ClassifyAgent kullanır
src/graphs/report/entity_validator.py         → ClassifyAgent kullanır
src/graphs/report/query_type_patterns.py      → ClassifyAgent kullanır
src/graphs/report/delta_parser.py             → SQLAgent kullanır
src/graphs/report/query_type_actions.py       → SQLAgent kullanır
src/graphs/report/query_type_viz_mapping.py   → AnalysisAgent kullanır
src/graphs/report/business_context_tracker.py → AnalysisAgent kullanır
src/graphs/report/report_interpreter.py       → AnalysisAgent kullanır
src/graphs/report/response_generator.py       → ResponseAgent kullanır
src/graphs/report/conversational_cache.py     → Tüm agentlar (opsiyonel)
src/graphs/report/semantic_cache.py           → Tüm agentlar (opsiyonel)
src/graphs/report/tools.py                    → HITL yardımcıları
src/graphs/generic_text2sql/                  → SQLAgent kullanır (değişmez)
src/graphs/data_visualization/               → viz_bridge kullanır (değişmez)
```

---

## Mevcut nodes.py → Yeni Agent Mapping

```
nodes.py FONKSIYONU                          → YENİ KONUM
─────────────────────────────────────────────────────────────────
# ClassifyAgent
create_intent_classifier_node()              → classify_agent.py: classify_intent_node()
create_conversation_aware_intent_node()      → classify_agent.py: classify_intent_node() (LLM path)
_detect_references_llm()                     → classify_agent.py: detect_references_node() ← AYRI NODE (paralel)
_analyze_query_with_context()                → classify_agent.py: (internal, detect_references_node içinde)
create_validate_entities_node()              → classify_agent.py: validate_entities_node() ← AYRI NODE (paralel)
ask_user_for_clarification_node()            → classify_agent.py: hitl_clarification_node()
process_user_clarification_node()            → classify_agent.py: process_clarification_node()
_process_enhanced_clarification()            → classify_agent.py: (internal)
_process_*_clarification() (6 adet)          → classify_agent.py: (internal)
_load_hitl_config()                          → classify_agent.py: modül başına taşı
get_hitl_metrics()                           → classify_agent.py: export et (monitoring)
route_after_intent()                         → classify_agent.py: (internal routing)
route_after_intent_smart()                   → classify_agent.py: (internal routing)
route_after_intent_classification()          → classify_agent.py: (internal routing)

# SQLAgent
extract_query_node()                         → sql_agent.py: extract_and_prepare_node()
delta_sql_modifier_node()                    → sql_agent.py: delta_sql_modifier_node()
_parse_delta_changes()                       → sql_agent.py: (internal, delta_parser'dan)
_apply_sql_delta()                           → sql_agent.py: (internal)
_determine_execution_mode()                  → sql_agent.py: detect_execution_mode_node()
update_conversation_history_node()           → sql_agent.py: update_history_node()
_enrich_query_with_context()                 → sql_agent.py: (internal)
_build_conversation_context()                → sql_agent.py: (internal)
_build_modification_context_hint()           → sql_agent.py: (internal)
create_text2sql_node()                       → sql_agent.py: (separate mode için, opsiyonel)

# AnalysisAgent
check_results_node()                         → analysis_agent.py: check_results_node()
decide_visualization_node()                  → analysis_agent.py: decide_viz_node() ← AYRI NODE (paralel)
create_business_insights_node()              → analysis_agent.py: extract_insights_node() ← AYRI NODE (paralel)
create_llm_viz_decision_node()               → analysis_agent.py: decide_viz_node() (LLM path)
create_parallel_insights_viz_node()          → KALDIRILIR — LangGraph native fan-out kullanılır
route_after_results()                        → analysis_agent.py: (internal routing)

# ResponseAgent
build_response_node()                        → response_agent.py: build_response_node()
create_natural_response_node()               → response_agent.py: build_response_node() (LLM path)

# Orchestrator
rollback_node()                              → graph.py: rollback_bridge_node()
create_visualization_node()                  → graph.py: viz_bridge_node() (data_visualization subgraph wrap)

# KALDIRILIR (kullanılmıyor)
immediate_acknowledgment_node()              → sil
create_parallel_insights_viz_node()          → sil (LangGraph native edge'ler karşılar)
```

---

## Yeni Dosya Yapısı

```
src/graphs/report_v2/
├── __init__.py
├── state.py                    # OrchestratorState + ClassifyResult/SQLResult/AnalysisResult
├── graph.py                    # Network orchestrator, bridge nodes, routing
├── configuration.py            # ReportV2Configuration (ReportAgentConfiguration'ı extend)
└── agents/
    ├── __init__.py
    ├── classify_agent.py       # ClassifyState + tüm classify node'ları + build_classify_agent()
    ├── sql_agent.py            # SQLState + tüm sql node'ları + build_sql_agent()
    ├── analysis_agent.py       # AnalysisState + tüm analysis node'ları + build_analysis_agent()
    └── response_agent.py       # ResponseState + response node'ları + build_response_agent()
```

---

## State Tasarımı

### OrchestratorState (Thin Bus)

```python
class OrchestratorState(TypedDict):
    # Core
    messages: Annotated[List[BaseMessage], add_messages]
    user_input: str
    session_id: Optional[str]

    # Paylaşılan bağlam (agent'lar arası)
    conversation_history: List[Dict[str, Any]]
    active_context: Optional[ActiveQueryContext]   # Delta SQL için
    query_history: Annotated[List[QueryCheckpoint], checkpoint_reducer]
    clarification_count: int                       # HITL döngü koruması (max 3)
    user_clarification: Optional[str]

    # Agent çıktı slotları
    classify_result: Optional[ClassifyResult]
    sql_result:      Optional[SQLResult]
    analysis_result: Optional[AnalysisResult]
    viz_artifact:    Optional[Dict[str, Any]]      # data_visualization subgraph çıktısı

    # Final
    error: Optional[str]
    final_response: Optional[str]
```

### Agent Result Types

```python
class ClassifyResult(TypedDict):
    intent_type: str           # "new_query"|"filter"|"sort"|"rollback"|"visualize"
    query_type: str            # "ranking"|"comparison"|"time_series"|"single_value"|...
    confidence: float
    needs_clarification: bool
    pending_question: Optional[PendingQuestion]
    user_query: str            # Temizlenmiş sorgu metni
    entities: Optional[Dict]
    reference_context: Optional[Dict]   # is_followup, previous_entities, vb.

class SQLResult(TypedDict):
    results: List[Dict[str, Any]]
    sql_query: str
    no_records_message: Optional[str]
    updated_active_context: Optional[ActiveQueryContext]
    conversation_entry: Optional[Dict]   # history'e eklenecek
    error: Optional[str]

class AnalysisResult(TypedDict):
    should_visualize: bool
    viz_decision: Dict[str, Any]         # {chart_type, x_axis, y_axis, ...}
    business_insights: Optional[BusinessContext]
    viz_reasoning: Optional[str]
```

### ClassifyState (İzole)

Fan-out sonrası paralel node'lar (`detect_references_node` ve `validate_entities_node`) farklı key'lere yazar — çakışma yok.

```python
class ClassifyState(TypedDict):
    # INPUT (OrchestratorState'den gelir)
    user_input: str
    messages: List[BaseMessage]
    conversation_history: List[Dict]
    active_context: Optional[ActiveQueryContext]
    user_clarification: Optional[str]
    clarification_count: int

    # INTERNAL (sadece bu agent içinde)
    _intent_type: Optional[str]
    _confidence: Optional[float]
    _query_type: Optional[str]
    _query_type_confidence: Optional[float]
    _needs_clarification: Optional[bool]
    _pending_question: Optional[PendingQuestion]
    _user_query: Optional[str]
    _ambiguity_context: Optional[Any]

    # Paralel node'ların yazdığı key'ler (çakışma yok)
    _reference_context: Optional[Dict]      # detect_references_node yazar
    _extracted_entities: Optional[Dict]     # validate_entities_node yazar
    _entity_validation_done: Optional[bool] # validate_entities_node yazar

    _modification_action: Optional[str]

    # OUTPUT
    classify_result: Optional[ClassifyResult]
```

### SQLState (İzole)

```python
class SQLState(TypedDict):
    # INPUT
    user_query: str
    query_type: str
    active_context: Optional[ActiveQueryContext]
    conversation_history: List[Dict]
    reference_context: Optional[Dict]

    # INTERNAL (generic_text2sql pipeline field'ları)
    parsed_intent: Optional[Dict]
    enriched_metadata: Optional[Dict]
    resolved_steps: Optional[List[Dict]]
    sql_queries: Optional[List[str]]
    schema_metadata: Optional[Dict]
    business_rules: Optional[Dict]
    business_rules_context: Optional[str]
    merged_sql_components: Optional[Dict]
    applied_business_rules: Optional[List[Dict]]
    detected_tables: Optional[List[str]]
    resolution_metadata: Optional[Dict]
    retry_count: Optional[int]
    sql_error_history: Optional[List[Dict]]
    no_records_message: Optional[str]
    _execution_mode: Optional[str]      # "full"|"delta"
    _delta_fallback: Optional[bool]
    _delta_changes: Optional[Dict]
    _sql_context_hint: Optional[str]    # follow-up context injection

    # OUTPUT
    results: Optional[List[Dict]]
    sql_result: Optional[SQLResult]
```

### AnalysisState (İzole)

Fan-out sonrası paralel node'lar (`extract_insights_node` ve `decide_viz_node`) farklı key'lere yazar — çakışma yok.

```python
class AnalysisState(TypedDict):
    # INPUT
    results: List[Dict]
    query_type: str
    user_query: str
    active_context: Optional[ActiveQueryContext]
    no_records_message: Optional[str]
    error: Optional[str]

    # Paralel node'ların yazdığı key'ler (çakışma yok)
    _business_insights: Optional[BusinessContext]   # extract_insights_node yazar
    _viz_decision: Optional[Dict[str, Any]]         # decide_viz_node yazar
    _should_visualize: Optional[bool]               # decide_viz_node yazar
    _viz_reasoning: Optional[str]                   # decide_viz_node yazar

    # OUTPUT
    analysis_result: Optional[AnalysisResult]
```

### ResponseState (İzole)

```python
class ResponseState(TypedDict):
    # INPUT
    classify_result: ClassifyResult
    sql_result: SQLResult
    analysis_result: AnalysisResult
    viz_artifact: Optional[Dict[str, Any]]
    messages: List[BaseMessage]

    # OUTPUT
    final_response: str
```

---

## Task 1: Modül İskeleti

**Files:**
- Create: `src/graphs/report_v2/__init__.py`
- Create: `src/graphs/report_v2/agents/__init__.py`

```bash
mkdir -p src/graphs/report_v2/agents
```

`src/graphs/report_v2/__init__.py`:
```python
"""Report Agent V2 — Network Architecture with Complete State Separation."""
```

`src/graphs/report_v2/agents/__init__.py`:
```python
"""Report V2 Sub-agents."""
```

```bash
git add src/graphs/report_v2/
git commit -m "feat: scaffold report_v2 module structure"
```

---

## Task 2: state.py — OrchestratorState + Agent Result Types

**File:** `src/graphs/report_v2/state.py`

**Sorumluluk:** Sistemin tek paylaşılan "contract"ı burası. Agent'lar sadece kendi input/output'larını bilir; orchestrator hepsini bir arada tutar.

```python
"""
OrchestratorState — Report V2 Network Architecture

Thin coordination bus.
Agent'lar kendi TypedDict state'lerini kullanır;
bu modül sadece agent çıktılarının typed contract'larını ve
orchestrator'ın coordination alanlarını tanımlar.
"""

from typing import TypedDict, List, Optional, Dict, Any, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# Korunan state tipleri — DEĞİŞMEZ
from src.graphs.report.state import (
    ActiveQueryContext,
    QueryCheckpoint,
    PendingQuestion,
    BusinessContext,
    checkpoint_reducer,
    create_empty_context,
    create_checkpoint,
)


class ClassifyResult(TypedDict):
    intent_type: str
    query_type: str
    confidence: float
    needs_clarification: bool
    pending_question: Optional[PendingQuestion]
    user_query: str
    entities: Optional[Dict[str, Any]]
    reference_context: Optional[Dict[str, Any]]


class SQLResult(TypedDict):
    results: List[Dict[str, Any]]
    sql_query: str
    no_records_message: Optional[str]
    updated_active_context: Optional[ActiveQueryContext]
    conversation_entry: Optional[Dict[str, Any]]
    error: Optional[str]


class AnalysisResult(TypedDict):
    should_visualize: bool
    viz_decision: Dict[str, Any]
    business_insights: Optional[BusinessContext]
    viz_reasoning: Optional[str]


class OrchestratorState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_input: str
    session_id: Optional[str]
    conversation_history: List[Dict[str, Any]]
    active_context: Optional[ActiveQueryContext]
    query_history: Annotated[List[QueryCheckpoint], checkpoint_reducer]
    clarification_count: int
    user_clarification: Optional[str]
    classify_result: Optional[ClassifyResult]
    sql_result: Optional[SQLResult]
    analysis_result: Optional[AnalysisResult]
    viz_artifact: Optional[Dict[str, Any]]
    error: Optional[str]
    final_response: Optional[str]


def create_initial_state(user_input: str, session_id: Optional[str] = None) -> OrchestratorState:
    return OrchestratorState(
        messages=[],
        user_input=user_input,
        session_id=session_id,
        conversation_history=[],
        active_context=None,
        query_history=[],
        clarification_count=0,
        user_clarification=None,
        classify_result=None,
        sql_result=None,
        analysis_result=None,
        viz_artifact=None,
        error=None,
        final_response=None,
    )
```

```bash
git add src/graphs/report_v2/state.py
git commit -m "feat: add OrchestratorState with typed agent result contracts"
```

---

## Task 3: classify_agent.py

**File:** `src/graphs/report_v2/agents/classify_agent.py`

**Sorumluluk:** Kullanıcı niyetini anla, ambiguity'yi tespit et, HITL tetikle, `ClassifyResult` üret.

**nodes.py'den taşınanlar:**
- `create_intent_classifier_node()` + `create_conversation_aware_intent_node()` → `classify_intent_node()`
- `_detect_references_llm()` + `_analyze_query_with_context()` → `detect_references_node()` **(yeni ayrı node)**
- `create_validate_entities_node()` → `validate_entities_node()` **(yeni ayrı node)**
- `ask_user_for_clarification_node()` → `hitl_clarification_node()`
- `process_user_clarification_node()` → `process_clarification_node()`
- `_process_enhanced_clarification()` ve 6 adet `_process_*_clarification()` → internal
- `_load_hitl_config()`, `get_hitl_metrics()` → modül başına
- Tüm `route_after_intent*()` → internal routing

**İç graph akışı — LangGraph native parallelism:**

```
START
  ↓
classify_intent          (intent_type, query_type, user_query, confidence)
  ↓ (fan-out — LangGraph parallel edges)
├── detect_references   ─┐  yazar: _reference_context
└── validate_entities   ─┘  yazar: _extracted_entities, _entity_validation_done
         ↓ (fan-in — LangGraph her ikisini bekler)
    detect_ambiguity
         ↓ (conditional)
    ├── hitl_clarification → process_clarification → classify_intent (döngü)
    └── build_result → END
```

**Neden paralel?**
- `detect_references` → `ConversationManager._detect_references_llm()` → LLM çağrısı
- `validate_entities` → `EntityValidator.validate()` → DB + rule-based
- İkisi de sadece `user_input + conversation_history + active_context` okur, birbirinin çıktısına bağımlı değil
- Farklı state key'lerine yazar → çakışma yok

**Temel yapı:**

```python
"""
ClassifyAgent — Intent ve Query Type sınıflandırma.

LangGraph Parallelism:
    classify_intent → [detect_references || validate_entities] → detect_ambiguity
    Fan-out: iki bağımsız node aynı anda çalışır.

Bağımlılıklar (değişmeden import):
    src/graphs/report/intent.py
    src/graphs/report/conversation_manager.py
    src/graphs/report/ambiguity_detectors.py
    src/graphs/report/ambiguity_framework.py
    src/graphs/report/ambiguity_router.py
    src/graphs/report/hitl_question_builder.py
    src/graphs/report/entity_validator.py
    src/graphs/report/query_type_patterns.py
    src/graphs/report/tools.py
"""
import logging
from typing import TypedDict, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage
from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from src.graphs.report.state import ActiveQueryContext, PendingQuestion, BusinessContext
from src.graphs.report_v2.state import ClassifyResult, OrchestratorState

logger = logging.getLogger(__name__)

HITL_CONFIG = _load_hitl_config()  # nodes.py'deki _load_hitl_config() buraya taşınır


# ─── ClassifyState ────────────────────────────────────────────────────────────
class ClassifyState(TypedDict):
    # INPUT
    user_input: str
    messages: List[BaseMessage]
    conversation_history: List[Dict[str, Any]]
    active_context: Optional[ActiveQueryContext]
    user_clarification: Optional[str]
    clarification_count: int
    # INTERNAL
    _intent_type: Optional[str]
    _confidence: Optional[float]
    _query_type: Optional[str]
    _query_type_confidence: Optional[float]
    _needs_clarification: Optional[bool]
    _pending_question: Optional[PendingQuestion]
    _user_query: Optional[str]
    _ambiguity_context: Optional[Any]
    _modification_action: Optional[str]
    # Paralel node çıktıları (farklı key'ler — çakışma yok)
    _reference_context: Optional[Dict[str, Any]]    # detect_references_node
    _extracted_entities: Optional[Dict[str, Any]]   # validate_entities_node
    _entity_validation_done: Optional[bool]         # validate_entities_node
    # OUTPUT
    classify_result: Optional[ClassifyResult]


# ─── Input helper ─────────────────────────────────────────────────────────────
def create_classify_input(orch_state: OrchestratorState) -> ClassifyState:
    """OrchestratorState'den ClassifyAgent girdi state'ini oluştur."""
    return ClassifyState(
        user_input=orch_state["user_input"],
        messages=orch_state.get("messages", []),
        conversation_history=orch_state.get("conversation_history", []),
        active_context=orch_state.get("active_context"),
        user_clarification=orch_state.get("user_clarification"),
        clarification_count=orch_state.get("clarification_count", 0),
        _intent_type=None, _confidence=None, _query_type=None,
        _query_type_confidence=None, _needs_clarification=None,
        _pending_question=None, _user_query=None,
        _ambiguity_context=None, _modification_action=None,
        _reference_context=None,
        _extracted_entities=None, _entity_validation_done=False,
        classify_result=None,
    )


# ─── Node'lar ─────────────────────────────────────────────────────────────────
async def classify_intent_node(state: ClassifyState) -> dict:
    """
    nodes.py:969 — Intent type + query type sınıflandırma.
    Sonraki fan-out için _intent_type, _query_type, _user_query set eder.
    """
    ...

async def detect_references_node(state: ClassifyState) -> dict:
    """
    nodes.py: _detect_references_llm() + _analyze_query_with_context() — AYRI NODE.
    Paralel: sadece _reference_context key'ine yazar.
    """
    ...

async def validate_entities_node(state: ClassifyState) -> dict:
    """
    nodes.py:1340 — Entity validation.
    Paralel: sadece _extracted_entities, _entity_validation_done key'lerine yazar.
    """
    ...

async def detect_ambiguity_node(state: ClassifyState) -> dict:
    """
    Fan-in: detect_references + validate_entities'in her ikisi bittikten sonra çalışır.
    _reference_context ve _extracted_entities'i okuyarak ambiguity check yapar.
    """
    ...

async def hitl_clarification_node(state: ClassifyState) -> dict:
    """nodes.py:1492 — interrupt() ile kullanıcıya soru sor."""
    ...

async def process_clarification_node(state: ClassifyState) -> dict:
    """nodes.py:1671 — Kullanıcı cevabını işle, state'i güncelle."""
    ...

async def build_classify_result_node(state: ClassifyState) -> dict:
    """Tüm internal field'lardan ClassifyResult üret."""
    ...


# ─── Routing ──────────────────────────────────────────────────────────────────
def route_after_ambiguity(state: ClassifyState) -> str:
    if state.get("clarification_count", 0) >= HITL_CONFIG.get("max_clarifications", 3):
        return "build_result"   # Max HITL'e ulaştı, devam et
    if state.get("_needs_clarification"):
        return "hitl_clarification"
    return "build_result"


# ─── Graph builder ────────────────────────────────────────────────────────────
def build_classify_agent(llm: Optional[BaseChatModel] = None):
    """
    ClassifyAgent subgraph'ını compile et.

    Graph akışı:
        classify_intent
            ↓ fan-out (paralel)
        detect_references || validate_entities
            ↓ fan-in
        detect_ambiguity → [hitl loop | build_result]

    llm=None → rule-based fallback (IntentClassifier)
    llm=chat → ConversationManager (LLM-powered)
    """
    graph = StateGraph(ClassifyState)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("detect_references", detect_references_node)
    graph.add_node("validate_entities", validate_entities_node)
    graph.add_node("detect_ambiguity", detect_ambiguity_node)
    graph.add_node("hitl_clarification", hitl_clarification_node)
    graph.add_node("process_clarification", process_clarification_node)
    graph.add_node("build_result", build_classify_result_node)

    graph.add_edge(START, "classify_intent")

    # Fan-out: classify_intent'ten detect_references VE validate_entities paralel başlar
    graph.add_edge("classify_intent", "detect_references")
    graph.add_edge("classify_intent", "validate_entities")

    # Fan-in: detect_ambiguity her ikisi de bitince otomatik başlar
    graph.add_edge("detect_references", "detect_ambiguity")
    graph.add_edge("validate_entities", "detect_ambiguity")

    graph.add_conditional_edges("detect_ambiguity", route_after_ambiguity, {
        "hitl_clarification": "hitl_clarification",
        "build_result": "build_result",
    })
    graph.add_edge("hitl_clarification", "process_clarification")
    graph.add_edge("process_clarification", "classify_intent")  # yeniden classify
    graph.add_edge("build_result", END)
    return graph.compile()
```

**Önemli:** Node fonksiyonlarının içi nodes.py'den kopyalanır. `state: ReportState` → `state: ClassifyState` parametresi ve ilgili field erişimleri güncellenir; iş mantığı değişmez.

```bash
git add src/graphs/report_v2/agents/classify_agent.py
git commit -m "feat: add ClassifyAgent — parallel detect_references + validate_entities fan-out"
```

---

## Task 4: sql_agent.py

**File:** `src/graphs/report_v2/agents/sql_agent.py`

**Sorumluluk:** Kullanıcı sorgusunu SQL'e dönüştür, çalıştır, `SQLResult` üret.

**nodes.py'den taşınanlar:**
- `extract_query_node()` → `extract_and_prepare_node()` (context injection dahil)
- `delta_sql_modifier_node()` + tüm `_parse_delta_*`, `_apply_sql_delta()` → aynı isim
- `_determine_execution_mode()` → `detect_execution_mode_node()`
- `update_conversation_history_node()` → `update_history_node()`
- `_enrich_query_with_context()`, `_build_conversation_context()`, `_build_modification_context_hint()` → internal
- `create_build_query_type_context_node()` (query_type_actions.py) → `build_query_type_context_node()`
- `create_all_text2sql_nodes()` (node_factories.py) → merged pipeline nodes

**İç graph akışı:**
```
START
  ↓
extract_and_prepare     (query çıkar + context injection)
  ↓
build_query_type_context (query_type'a göre SQL ipuçları)
  ↓
detect_execution_mode   (delta / full?)
  ↓ (conditional)
├── [delta_sql_modifier] ──→ sql_executor   (6 node atlanır — hız)
│         ↓ (fallback to full pipeline)
└── [create_table] → sql_architect → retrieve_business_rules
                   → metadata_enrichment → value_resolver
                   → sql_query_builder → sql_executor
                         ↓
                    cleanup_table → update_history → build_sql_result → END
```

**Not:** generic_text2sql pipeline node'ları değişmeden import edilir. SQL pipeline içinde LangGraph parallelism uygulanmaz — pipeline sırası kritik (her node bir öncekinin çıktısını kullanır).

**Temel yapı:**

```python
"""
SQLAgent — Text-to-SQL pipeline.

Bağımlılıklar (değişmeden import):
    src/graphs/report/delta_parser.py
    src/graphs/report/query_type_actions.py
    src/graphs/generic_text2sql/node_factories.py  (tüm pipeline nodes)
"""
...

class SQLState(TypedDict):
    # INPUT
    user_query: str
    query_type: str
    active_context: Optional[ActiveQueryContext]
    conversation_history: List[Dict[str, Any]]
    reference_context: Optional[Dict[str, Any]]
    # INTERNAL — generic_text2sql pipeline field'ları
    parsed_intent: Optional[Dict]
    enriched_metadata: Optional[Dict]
    resolved_steps: Optional[List[Dict]]
    sql_queries: Optional[List[str]]
    schema_metadata: Optional[Dict]
    business_rules: Optional[Dict]
    business_rules_context: Optional[str]
    merged_sql_components: Optional[Dict]
    applied_business_rules: Optional[List[Dict]]
    detected_tables: Optional[List[str]]
    resolution_metadata: Optional[Dict]
    retry_count: Optional[int]
    sql_error_history: Optional[List[Dict]]
    no_records_message: Optional[str]
    _execution_mode: Optional[str]
    _delta_fallback: Optional[bool]
    _delta_changes: Optional[Dict]
    _sql_context_hint: Optional[str]
    # OUTPUT
    results: Optional[List[Dict]]
    sql_result: Optional[SQLResult]


def create_sql_input(orch_state: OrchestratorState, classify_result: ClassifyResult) -> SQLState:
    return SQLState(
        user_query=classify_result["user_query"],
        query_type=classify_result["query_type"],
        active_context=orch_state.get("active_context"),
        conversation_history=orch_state.get("conversation_history", []),
        reference_context=classify_result.get("reference_context"),
        parsed_intent=None, enriched_metadata=None, resolved_steps=None,
        sql_queries=None, schema_metadata=None, business_rules=None,
        business_rules_context=None, merged_sql_components=None,
        applied_business_rules=None, detected_tables=None,
        resolution_metadata=None, retry_count=0, sql_error_history=None,
        no_records_message=None, _execution_mode=None,
        _delta_fallback=False, _delta_changes=None, _sql_context_hint=None,
        results=None, sql_result=None,
    )


async def extract_and_prepare_node(state: SQLState) -> dict: ...       # nodes.py:1848
async def build_query_type_context_node(state: SQLState) -> dict: ...  # query_type_actions.py
async def detect_execution_mode_node(state: SQLState) -> dict: ...     # nodes.py:3778
async def delta_sql_modifier_node(state: SQLState) -> dict: ...        # nodes.py:2120
async def update_history_node(state: SQLState) -> dict: ...            # nodes.py:1223
async def build_sql_result_node(state: SQLState) -> dict: ...


def route_after_execution_mode(state: SQLState) -> str:
    if state.get("_execution_mode") == "delta" and not state.get("_delta_fallback"):
        return "delta_sql_modifier"
    return "create_table"


def build_sql_agent(node_kit=None, llm=None):
    """node_kit: GenericText2SQLNodeKit (merged pipeline için gerekli)"""
    from src.graphs.generic_text2sql.node_factories import create_all_text2sql_nodes
    text2sql_nodes = create_all_text2sql_nodes(node_kit)

    graph = StateGraph(SQLState)
    graph.add_node("extract_and_prepare", extract_and_prepare_node)
    graph.add_node("build_query_type_context", build_query_type_context_node)
    graph.add_node("detect_execution_mode", detect_execution_mode_node)
    graph.add_node("delta_sql_modifier", delta_sql_modifier_node)
    graph.add_node("create_table", text2sql_nodes["create_table"])
    graph.add_node("sql_architect", text2sql_nodes["sql_architect"])
    graph.add_node("retrieve_business_rules", text2sql_nodes["retrieve_business_rules"])
    graph.add_node("metadata_enrichment", text2sql_nodes["metadata_enrichment"])
    graph.add_node("value_resolver", text2sql_nodes["value_resolver"])
    graph.add_node("sql_query_builder", text2sql_nodes["sql_query_builder"])
    graph.add_node("sql_executor", text2sql_nodes["sql_executor"])
    graph.add_node("cleanup_table", text2sql_nodes["cleanup_table"])
    graph.add_node("update_history", update_history_node)
    graph.add_node("build_sql_result", build_sql_result_node)

    graph.add_edge(START, "extract_and_prepare")
    graph.add_edge("extract_and_prepare", "build_query_type_context")
    graph.add_edge("build_query_type_context", "detect_execution_mode")
    graph.add_conditional_edges("detect_execution_mode", route_after_execution_mode, {
        "delta_sql_modifier": "delta_sql_modifier",
        "create_table": "create_table",
    })
    graph.add_conditional_edges("delta_sql_modifier",
        lambda s: "create_table" if s.get("_delta_fallback") else "sql_executor",
        {"sql_executor": "sql_executor", "create_table": "create_table"})
    graph.add_edge("create_table", "sql_architect")
    graph.add_edge("sql_architect", "retrieve_business_rules")
    graph.add_edge("retrieve_business_rules", "metadata_enrichment")
    graph.add_edge("metadata_enrichment", "value_resolver")
    graph.add_edge("value_resolver", "sql_query_builder")
    graph.add_edge("sql_query_builder", "sql_executor")
    graph.add_edge("sql_executor", "cleanup_table")
    graph.add_edge("cleanup_table", "update_history")
    graph.add_edge("update_history", "build_sql_result")
    graph.add_edge("build_sql_result", END)
    return graph.compile()
```

```bash
git add src/graphs/report_v2/agents/sql_agent.py
git commit -m "feat: add SQLAgent — migrated delta/full pipeline from nodes.py"
```

---

## Task 5: analysis_agent.py

**File:** `src/graphs/report_v2/agents/analysis_agent.py`

**Sorumluluk:** SQL sonuçlarını analiz et — boş mu? Görsel gerekli mi? Business insights var mı?

**nodes.py'den taşınanlar:**
- `check_results_node()` → `check_results_node()`
- `decide_visualization_node()` + `create_llm_viz_decision_node()` → `decide_viz_node()` **(ayrı paralel node)**
- `create_business_insights_node()` → `extract_insights_node()` **(ayrı paralel node)**
- `create_parallel_insights_viz_node()` → **KALDIRILIR** — LangGraph native fan-out karşılar
- `route_after_results()` → internal routing

**İç graph akışı — LangGraph native parallelism:**

```
START
  ↓
check_results            (boş/hata kontrolü)
  ↓ (conditional)
├── build_result → END   (no_records veya error — erken çıkış)
└── (fan-out — LangGraph parallel edges)
    ├── extract_insights ─┐  yazar: _business_insights
    └── decide_viz       ─┘  yazar: _viz_decision, _should_visualize, _viz_reasoning
             ↓ (fan-in — LangGraph her ikisini bekler)
       build_analysis_result → END
```

**Neden paralel?**
- `extract_insights` → `BusinessContextTracker` + `ReportInterpreter` → LLM çağrısı
- `decide_viz` → `query_type_viz_mapping.py` (rule-based) veya LLM → bağımsız
- İkisi de sadece `results + query_type + user_query` okur, birbirinin çıktısına bağımlı değil
- Farklı state key'lerine yazar → çakışma yok
- `create_parallel_insights_viz_node()`'daki asyncio.gather mantığını LangGraph graph'ı kendisi yürütür

**Temel yapı:**

```python
"""
AnalysisAgent — Sonuç analizi, viz karar, business insights.

LangGraph Parallelism:
    check_results → [extract_insights || decide_viz] → build_analysis_result
    Fan-out: iki bağımsız LLM çağrısı aynı anda çalışır.
    create_parallel_insights_viz_node() artık gerekli değil.

Bağımlılıklar (değişmeden import):
    src/graphs/report/query_type_viz_mapping.py
    src/graphs/report/business_context_tracker.py
    src/graphs/report/report_interpreter.py
"""
...

class AnalysisState(TypedDict):
    # INPUT
    results: List[Dict[str, Any]]
    query_type: str
    user_query: str
    active_context: Optional[ActiveQueryContext]
    no_records_message: Optional[str]
    error: Optional[str]
    # Paralel node çıktıları (farklı key'ler — çakışma yok)
    _business_insights: Optional[BusinessContext]   # extract_insights_node yazar
    _viz_decision: Optional[Dict[str, Any]]         # decide_viz_node yazar
    _should_visualize: Optional[bool]               # decide_viz_node yazar
    _viz_reasoning: Optional[str]                   # decide_viz_node yazar
    # OUTPUT
    analysis_result: Optional[AnalysisResult]


def create_analysis_input(
    orch_state: OrchestratorState,
    classify_result: ClassifyResult,
    sql_result: SQLResult,
) -> AnalysisState:
    return AnalysisState(
        results=sql_result.get("results", []),
        query_type=classify_result.get("query_type", "unknown"),
        user_query=classify_result.get("user_query", ""),
        active_context=orch_state.get("active_context"),
        no_records_message=sql_result.get("no_records_message"),
        error=sql_result.get("error"),
        _business_insights=None,
        _viz_decision=None, _should_visualize=None, _viz_reasoning=None,
        analysis_result=None,
    )


async def check_results_node(state: AnalysisState) -> dict: ...         # nodes.py:2714
async def extract_insights_node(state: AnalysisState) -> dict: ...      # nodes.py:3991
async def decide_viz_node(state: AnalysisState) -> dict: ...            # nodes.py:191 + LLM path
async def build_analysis_result_node(state: AnalysisState) -> dict: ...


def route_after_check(state: AnalysisState) -> str:
    if state.get("no_records_message") or state.get("error"):
        return "build_result"    # Fan-out'u atla, direkt sonuç üret
    return "fan_out"             # Paralel branch'e gir


def build_analysis_agent(
    business_tracker=None,
    report_interpreter=None,
):
    """
    AnalysisAgent subgraph'ını compile et.

    Graph akışı:
        check_results (conditional)
            ↓ fan-out (paralel)
        extract_insights || decide_viz
            ↓ fan-in
        build_analysis_result

    business_tracker=None → rule-based viz, insights atlanır
    business_tracker=instance → LLM insights aktif
    """
    graph = StateGraph(AnalysisState)
    graph.add_node("check_results", check_results_node)
    graph.add_node("extract_insights", extract_insights_node)
    graph.add_node("decide_viz", decide_viz_node)
    graph.add_node("build_analysis_result", build_analysis_result_node)

    graph.add_edge(START, "check_results")
    graph.add_conditional_edges("check_results", route_after_check, {
        "build_result": "build_analysis_result",  # erken çıkış
        "fan_out": "extract_insights",             # fan-out başlangıcı (aşağıdaki edge ile birlikte)
    })
    # Fan-out: check_results'tan decide_viz de paralel başlar
    # conditional_edges sadece "extract_insights" tarafını bağlar,
    # decide_viz için ayrıca edge ekleriz:
    graph.add_edge("check_results", "decide_viz")   # paralel branch

    # Fan-in: build_analysis_result her ikisi de bitince başlar
    graph.add_edge("extract_insights", "build_analysis_result")
    graph.add_edge("decide_viz", "build_analysis_result")
    graph.add_edge("build_analysis_result", END)
    return graph.compile()
```

**Not:** `route_after_check`'in "fan_out" → "extract_insights" conditional edge'i ve ek `graph.add_edge("check_results", "decide_viz")` birlikte, LangGraph'ın `check_results`'ı iki ayrı node'a yönlendirmesini sağlar. Eğer conditional + düz edge çakışması yaratıyorsa alternatif olarak sadece düz `add_edge` kullanılır ve `check_results` her iki branch'i de her zaman tetikler, `build_analysis_result` içinde boş sonuç durumu handle edilir.

```bash
git add src/graphs/report_v2/agents/analysis_agent.py
git commit -m "feat: add AnalysisAgent — native parallel extract_insights + decide_viz fan-out"
```

---

## Task 6: response_agent.py

**File:** `src/graphs/report_v2/agents/response_agent.py`

**Sorumluluk:** Tüm agent çıktılarını kullanıcıya yönelik yanıta dönüştür.

**nodes.py'den taşınanlar:**
- `build_response_node()` + `create_natural_response_node()` → `build_response_node()` (LLM inject ile path belirlenir)

**İç graph akışı:** `START → build_response → END` (tek node, sade — bağımlılık var, paralel fırsat yok)

**Temel yapı:**

```python
"""
ResponseAgent — Final yanıt üretimi.

Bağımlılıklar (değişmeden import):
    src/graphs/report/response_generator.py
"""
...

class ResponseState(TypedDict):
    # INPUT
    classify_result: ClassifyResult
    sql_result: SQLResult
    analysis_result: AnalysisResult
    viz_artifact: Optional[Dict[str, Any]]
    messages: List[BaseMessage]
    # OUTPUT
    final_response: str


def create_response_input(
    orch_state: OrchestratorState,
    classify_result: ClassifyResult,
    sql_result: SQLResult,
    analysis_result: AnalysisResult,
) -> ResponseState:
    return ResponseState(
        classify_result=classify_result,
        sql_result=sql_result,
        analysis_result=analysis_result,
        viz_artifact=orch_state.get("viz_artifact"),
        messages=orch_state.get("messages", []),
        final_response="",
    )


async def build_response_node(state: ResponseState) -> dict: ...   # nodes.py:3395 + 4212


def build_response_agent(response_generator=None):
    """response_generator=None → template-based, instance → LLM-powered"""
    graph = StateGraph(ResponseState)
    graph.add_node("build_response", build_response_node)
    graph.add_edge(START, "build_response")
    graph.add_edge("build_response", END)
    return graph.compile()
```

```bash
git add src/graphs/report_v2/agents/response_agent.py
git commit -m "feat: add ResponseAgent — migrated build_response and natural_response"
```

---

## Task 7: graph.py — Orchestrator Network

**File:** `src/graphs/report_v2/graph.py`

**Sorumluluk:** Agent'ları compile et, bridge node'larla `OrchestratorState ↔ AgentState` mapping'ini yap, network routing'i kur.

**Bridge Node Pattern:**
Her agent için bir bridge node: OrchestratorState'den agent'a input hazırla → agent'ı `ainvoke` et → çıktıyı OrchestratorState'e yaz.

**Network akışı:**
```
START → classify_agent
  ↓ (conditional: intent_type)
  ├── sql_agent         → analysis_agent ──┐
  ├── analysis_agent    (visualize_direct) ┤
  │                                        ↓ (conditional: should_visualize)
  │                               ┌── viz_bridge → response_agent → END
  │                               └── response_agent → END
  ├── rollback          → response_agent → END
  └── response_agent    (error path) → END
```

```python
"""
Report V2 Orchestrator — Network Architecture

Bridge Node Pattern:
  Her agent node bir bridge fonksiyonu.
  OrchestratorState → create_*_input() → agent.ainvoke() → OrchestratorState güncelle.

Network Routing:
  Classify sonucu intent_type'a göre routing yapar.
  Agent'lar birbirini doğrudan çağırmaz — orchestrator routing'i yönetir.
"""

import logging
from typing import Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.models.llm import LLM
from src.graphs.report_v2.state import OrchestratorState, SQLResult, AnalysisResult
from src.graphs.report_v2.agents.classify_agent import build_classify_agent, create_classify_input
from src.graphs.report_v2.agents.sql_agent import build_sql_agent, create_sql_input
from src.graphs.report_v2.agents.analysis_agent import build_analysis_agent, create_analysis_input
from src.graphs.report_v2.agents.response_agent import build_response_agent, create_response_input

logger = logging.getLogger(__name__)


# ─── Bridge Factories ─────────────────────────────────────────────────────────

def make_classify_bridge(classify_agent):
    async def node(state: OrchestratorState) -> dict:
        result = await classify_agent.ainvoke(create_classify_input(state))
        return {"classify_result": result.get("classify_result")}
    return node


def make_sql_bridge(sql_agent):
    async def node(state: OrchestratorState) -> dict:
        classify_result = state["classify_result"]
        result = await sql_agent.ainvoke(create_sql_input(state, classify_result))
        sql_result = result.get("sql_result")
        updates = {"sql_result": sql_result}
        if sql_result and sql_result.get("updated_active_context"):
            updates["active_context"] = sql_result["updated_active_context"]
        if sql_result and sql_result.get("conversation_entry"):
            history = list(state.get("conversation_history", []))
            history.append(sql_result["conversation_entry"])
            updates["conversation_history"] = history[-20:]  # son 20 tur
        return updates
    return node


def make_analysis_bridge(analysis_agent):
    async def node(state: OrchestratorState) -> dict:
        classify_result = state["classify_result"]
        sql_result = state.get("sql_result") or SQLResult(
            results=[], sql_query="", no_records_message=None,
            updated_active_context=None, conversation_entry=None, error=None,
        )
        result = await analysis_agent.ainvoke(
            create_analysis_input(state, classify_result, sql_result)
        )
        return {"analysis_result": result.get("analysis_result")}
    return node


def make_viz_bridge(visualization_graph):
    """
    data_visualization subgraph'ını OrchestratorState üzerinden çağırır.
    Subgraph input: results + viz_decision + user_query
    Subgraph output: viz_artifact (render edilmiş grafik verisi)
    """
    async def node(state: OrchestratorState) -> dict:
        sql_result = state.get("sql_result") or {}
        analysis_result = state.get("analysis_result") or {}
        classify_result = state.get("classify_result") or {}
        viz_input = {
            "results": sql_result.get("results", []),
            "viz_decision": analysis_result.get("viz_decision", {}),
            "user_query": classify_result.get("user_query", ""),
        }
        viz_output = await visualization_graph.ainvoke(viz_input)
        return {"viz_artifact": viz_output}
    return node


def make_response_bridge(response_agent):
    async def node(state: OrchestratorState) -> dict:
        classify_result = state["classify_result"]
        sql_result = state.get("sql_result") or SQLResult(
            results=[], sql_query="", no_records_message=None,
            updated_active_context=None, conversation_entry=None, error=None,
        )
        analysis_result = state.get("analysis_result") or AnalysisResult(
            should_visualize=False,
            viz_decision={"needs_graph": False},
            business_insights=None, viz_reasoning=None,
        )
        result = await response_agent.ainvoke(
            create_response_input(state, classify_result, sql_result, analysis_result)
        )
        final_response = result.get("final_response", "")
        from langchain_core.messages import AIMessage
        return {
            "final_response": final_response,
            "messages": [AIMessage(content=final_response)],
        }
    return node


async def rollback_bridge_node(state: OrchestratorState) -> dict:
    """nodes.py:3369 rollback_node mantığı — önceki checkpoint'e dön."""
    query_history = state.get("query_history", [])
    if not query_history:
        return {"error": "Geri alınacak sorgu bulunamadı."}
    last = query_history[-1]
    return {
        "active_context": last.get("active_context"),
        "sql_result": None,
        "analysis_result": None,
    }


# ─── Routing ──────────────────────────────────────────────────────────────────

def route_after_classify(state: OrchestratorState) -> str:
    classify_result = state.get("classify_result")
    if not classify_result:
        return "response_agent"
    intent = classify_result.get("intent_type", "new_query")
    if intent == "rollback":
        return "rollback"
    if intent == "visualize" and state.get("active_context"):
        return "analysis_agent"   # SQL atla, direkt viz
    return "sql_agent"


def route_after_sql(state: OrchestratorState) -> str:
    sql_result = state.get("sql_result") or {}
    if sql_result.get("error") or sql_result.get("no_records_message"):
        return "response_agent"
    return "analysis_agent"


def route_after_analysis(state: OrchestratorState) -> str:
    analysis_result = state.get("analysis_result") or {}
    if analysis_result.get("should_visualize"):
        return "viz_bridge"
    return "response_agent"


# ─── Graph Builder ────────────────────────────────────────────────────────────

def build_report_v2_graph(
    node_kit=None,
    llm: Optional[LLM] = None,
    visualization_graph=None,   # Compiled data_visualization subgraph
    checkpointer=None,
):
    """
    Report V2 network graph'ını compile et.

    Args:
        node_kit: GenericText2SQLNodeKit (SQL pipeline)
        llm: LLM instance — None ise tüm agentlar rule-based fallback kullanır
        visualization_graph: Compiled data_visualization subgraph (ainvoke: results, viz_decision, user_query)
        checkpointer: LangGraph checkpointer (default: MemorySaver)
    """
    logger.info("[REPORT_V2] Building network graph...")

    llm_chat = llm.get_chat() if llm else None

    business_tracker = None
    report_interpreter = None
    response_generator = None

    if llm_chat:
        from src.graphs.report.business_context_tracker import BusinessContextTracker
        from src.graphs.report.report_interpreter import create_report_interpreter
        from src.graphs.report.response_generator import create_response_generator
        business_tracker = BusinessContextTracker(llm=llm_chat)
        report_interpreter = create_report_interpreter(llm=llm_chat)
        response_generator = create_response_generator(llm=llm_chat)

    classify_agent = build_classify_agent(llm=llm_chat)
    sql_agent = build_sql_agent(node_kit=node_kit, llm=llm_chat)
    analysis_agent = build_analysis_agent(
        business_tracker=business_tracker,
        report_interpreter=report_interpreter,
    )
    response_agent = build_response_agent(response_generator=response_generator)

    logger.info("[REPORT_V2] Sub-agents compiled ✓")

    graph = StateGraph(OrchestratorState)

    graph.add_node("classify_agent", make_classify_bridge(classify_agent))
    graph.add_node("sql_agent", make_sql_bridge(sql_agent))
    graph.add_node("analysis_agent", make_analysis_bridge(analysis_agent))
    graph.add_node("response_agent", make_response_bridge(response_agent))
    graph.add_node("rollback", rollback_bridge_node)

    if visualization_graph:
        graph.add_node("viz_bridge", make_viz_bridge(visualization_graph))
        graph.add_edge("viz_bridge", "response_agent")

    graph.add_edge(START, "classify_agent")
    graph.add_conditional_edges("classify_agent", route_after_classify, {
        "sql_agent": "sql_agent",
        "analysis_agent": "analysis_agent",
        "rollback": "rollback",
        "response_agent": "response_agent",
    })
    graph.add_conditional_edges("sql_agent", route_after_sql, {
        "analysis_agent": "analysis_agent",
        "response_agent": "response_agent",
    })
    if visualization_graph:
        graph.add_conditional_edges("analysis_agent", route_after_analysis, {
            "viz_bridge": "viz_bridge",
            "response_agent": "response_agent",
        })
    else:
        graph.add_edge("analysis_agent", "response_agent")
    graph.add_edge("rollback", "response_agent")
    graph.add_edge("response_agent", END)

    compiled = graph.compile(checkpointer=checkpointer or MemorySaver())
    logger.info("[REPORT_V2] Graph compiled successfully ✓")
    return compiled
```

```bash
git add src/graphs/report_v2/graph.py
git commit -m "feat: add orchestrator network graph with bridge nodes, viz bridge, and conditional routing"
```

---

## Task 8: configuration.py

**File:** `src/graphs/report_v2/configuration.py`

Mevcut `ReportAgentConfiguration`'ı extend et — feature flag'ler korunur, gereksiz flag'ler kaldırılır.

```python
"""Report V2 Configuration."""
from src.graphs.report.configuration import ReportAgentConfiguration


class ReportV2Configuration(ReportAgentConfiguration):
    """
    Report V2 için runtime configuration.
    ReportAgentConfiguration'ı extend eder — tüm Text2SQL config field'ları miras alınır.
    enable_merged_text2sql kaldırılır (V2'de her zaman merged).
    """

    @property
    def enable_merged_text2sql(self) -> bool:
        return True  # V2'de her zaman merged — override edilemez
```

```bash
git add src/graphs/report_v2/configuration.py
git commit -m "feat: add ReportV2Configuration extending existing config"
```

---

## Task 9: graph_repository.py — V2 Kaydı

**File:** `src/graphs/graph_repository.py`

Mevcut `"report"` kaydını koruyarak `"report_v2"` key'iyle yeni graph'ı ekle.

```bash
grep -n "report" src/graphs/graph_repository.py
```

Bulduğun yere `"report_v2"` kaydını ekle:
```python
# Mevcut kayıt korunur — eski graph çalışmaya devam eder
"report": lambda: build_report_graph(...),

# Yeni V2 graph
"report_v2": lambda: build_report_v2_graph(
    node_kit=text2sql_node_kit,
    llm=llm,
    visualization_graph=visualization_graph,
),
```

```bash
git add src/graphs/graph_repository.py
git commit -m "feat: register report_v2 graph alongside existing report graph"
```

---

## Task 10: Visualization Bridge — data_visualization Entegrasyonu

**File:** `src/graphs/report_v2/graph.py` (Task 7'deki `make_viz_bridge` implementasyonunu doğrula)

**Sorumluluk:** `data_visualization` subgraph'ının beklediği gerçek input field'larını doğrula, bridge'i düzelt.

**Adım 1: data_visualization subgraph input schema'sını doğrula**

```bash
grep -n "def.*node\|StateGraph\|TypedDict\|class.*State" src/graphs/data_visualization/*.py | head -50
```

**Adım 2: Gerçek field isimlerini bul ve `make_viz_bridge`'i güncelle**

```python
# Doğrulanan schema'ya göre güncelle
viz_input = {
    "<actual_results_field>": sql_result.get("results", []),
    "<actual_decision_field>": analysis_result.get("viz_decision", {}),
    "<actual_query_field>": classify_result.get("user_query", ""),
}
```

**Adım 3: ResponseAgent'ın `build_response_node`'unda `viz_artifact` kullanımını doğrula**

`viz_artifact` varsa response'a embed et — `response_generator.py`'nin desteklediği format neyse ona göre.

```bash
git add src/graphs/report_v2/
git commit -m "fix: align viz_bridge input with data_visualization subgraph schema"
```

---

## Task 11: Smoke Test — Manuel Doğrulama

Graph'ın compile olduğunu ve temel akışın çalıştığını doğrula:

```python
# python -c "..." ile hızlı doğrulama
from src.graphs.report_v2.graph import build_report_v2_graph
from src.graphs.report_v2.state import create_initial_state
from unittest.mock import MagicMock

node_kit = MagicMock()
graph = build_report_v2_graph(node_kit=node_kit, llm=None)
print("Graph nodes:", list(graph.nodes.keys()))

# ClassifyAgent paralel node'larını doğrula
from src.graphs.report_v2.agents.classify_agent import build_classify_agent
classify = build_classify_agent(llm=None)
print("ClassifyAgent nodes:", list(classify.nodes.keys()))
# Beklenen: detect_references ve validate_entities her ikisi de var

# AnalysisAgent paralel node'larını doğrula
from src.graphs.report_v2.agents.analysis_agent import build_analysis_agent
analysis = build_analysis_agent()
print("AnalysisAgent nodes:", list(analysis.nodes.keys()))
# Beklenen: extract_insights ve decide_viz her ikisi de var

print("✓ All graphs compiled successfully")
```

Expected output:
```
Graph nodes: ['classify_agent', 'sql_agent', 'analysis_agent', 'response_agent', 'rollback']
ClassifyAgent nodes: ['classify_intent', 'detect_references', 'validate_entities', 'detect_ambiguity', 'hitl_clarification', 'process_clarification', 'build_result']
AnalysisAgent nodes: ['check_results', 'extract_insights', 'decide_viz', 'build_analysis_result']
✓ All graphs compiled successfully
```

```bash
git add .
git commit -m "feat: complete report_v2 network architecture rewrite"
```

---

## Her Agent'ın Net Sorumluluğu

| Agent | Sahip Olduğu State | LangGraph Parallelism | Ne Yapar |
|---|---|---|---|
| **ClassifyAgent** | `ClassifyState` | `detect_references` \|\| `validate_entities` | Intent, query_type, ambiguity, HITL |
| **SQLAgent** | `SQLState` | — (pipeline sırası kritik) | Delta/full SQL, pipeline, history |
| **AnalysisAgent** | `AnalysisState` | `extract_insights` \|\| `decide_viz` | Sonuç kontrolü, viz karar, insights |
| **ResponseAgent** | `ResponseState` | — (tüm inputları birleştirir) | Final yanıt formatla |
| **Orchestrator** | `OrchestratorState` | — | Agent sırası, routing, context taşı |

---

## Paralel Node'ların State Çakışma Matrisi

| Node A | Node B | A yazar | B yazar | Çakışma? |
|---|---|---|---|---|
| `detect_references` | `validate_entities` | `_reference_context` | `_extracted_entities`, `_entity_validation_done` | **Yok** ✓ |
| `extract_insights` | `decide_viz` | `_business_insights` | `_viz_decision`, `_should_visualize`, `_viz_reasoning` | **Yok** ✓ |

---

## Genişletme Kılavuzu

**Yeni paralel node eklemek:** Fan-out node'undan iki `add_edge` ekle, yeni node farklı bir key'e yazsın, fan-in node'una bağla. State TypedDict'e yeni key ekle.

**Yeni agent eklemek:** `agents/yeni_agent.py` oluştur + `graph.py`'de bridge node + conditional edge ekle.

**LLM inject etmek:** `build_*_agent(llm=llm_chat)` factory'sine geç — agent içinde `if llm: ... else: rule_based()` pattern'i.

**HITL eklemek:** Herhangi bir agent node'unda `interrupt()` çağır — orchestrator seviyesinde ek değişiklik gerekmez.

---

## Sonraki Adımlar (Bu Plan Kapsamı Dışı)

1. **Eski report/ graph deprecate:** `graph.py` ve `nodes.py` kaldır; `state.py` sadece shared type'lar için bırak
2. **E2E test:** Gerçek LLM + DB ile tam konuşma testi — hedef: %95 sorgu 10 sn altında
