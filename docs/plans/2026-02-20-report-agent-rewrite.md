# Report Agent Rewrite — Network Architecture + Tam State Ayrımı

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Report agent'ı her sub-agent'ın kendi TypedDict state'ine sahip olduğu, LangGraph network mimarisi üzerine sıfırdan yeniden yaz.

**Architecture:** Thin `OrchestratorState` coordination bus + 4 bağımsız sub-agent (Classify, SQL, Analysis, Response). Her agent kendi `Input`/`Output`/`InternalState` TypedDict'leriyle tanımlanır; orchestrator LangGraph `input`/`output` schema mapping ile aralarındaki translation'ı yönetir. Routing conditional edges + Command pattern kombinasyonuyla yapılır.

**Tech Stack:** LangGraph `StateGraph`, `Command`, `interrupt()`, Python TypedDict, mevcut business logic dosyaları değişmeden import edilir.

---

## Korunan Dosyalar (Değişmez, Import Edilir)

Aşağıdaki dosyalar olduğu gibi kalır. Yeni agent'lar bunları import eder:

```
src/graphs/report/intent.py                  # IntentClassifier, IntentType
src/graphs/report/delta_parser.py            # AdvancedDeltaParser, SQLModifier
src/graphs/report/entity_validator.py        # EntityValidator
src/graphs/report/ambiguity_detectors.py     # create_intent_detector, create_metadata_detector
src/graphs/report/ambiguity_framework.py     # AmbiguityContext, AmbiguityFramework
src/graphs/report/ambiguity_router.py        # AmbiguityRouter, should_trigger_hitl
src/graphs/report/hitl_question_builder.py   # HITLQuestionBuilder
src/graphs/report/query_type_patterns.py     # QueryTypePattern, detect_query_type
src/graphs/report/query_type_actions.py      # QueryTypeContextBuilder
src/graphs/report/query_type_viz_mapping.py  # QUERY_TYPE_VIZ_MAPPING
src/graphs/report/conversational_cache.py    # ConversationalSemanticCache
src/graphs/report/conversation_manager.py    # ConversationManager
src/graphs/report/business_context_tracker.py # BusinessContextTracker
src/graphs/report/report_interpreter.py      # ReportInterpreter
src/graphs/report/response_generator.py      # ResponseGenerator
src/graphs/report/semantic_cache.py          # SemanticCache
src/graphs/report/tools.py                   # HITLQuestions, format_interrupt_message
src/graphs/generic_text2sql/                 # Tüm text2sql modülü (değişmez)
src/graphs/data_visualization/               # Tüm viz modülü (değişmez)
```

## Yeni Dosya Yapısı

```
src/graphs/report_v2/
├── __init__.py
├── state.py                    # OrchestratorState + paylaşılan sub-type'lar
├── graph.py                    # Network orchestrator (ince wiring)
├── configuration.py            # ReportV2Configuration (Pydantic)
└── agents/
    ├── __init__.py
    ├── classify_agent.py       # ClassifyState + node'lar + build_classify_agent()
    ├── sql_agent.py            # SQLState + node'lar + build_sql_agent()
    ├── analysis_agent.py       # AnalysisState + node'lar + build_analysis_agent()
    └── response_agent.py       # ResponseState + node'lar + build_response_agent()
```

## State Mimarisi Özeti

```
OrchestratorState (ince, coordination bus)
├── messages              # Annotated[list, add_messages]
├── user_input            # str
├── session_id            # Optional[str]
├── conversation_history  # List[Dict] — turn bazlı özet
├── active_context        # Optional[ActiveQueryContext] — delta SQL için
├── query_history         # Annotated[list, checkpoint_reducer]
├── clarification_count   # int — HITL döngü koruması
├── classify_result       # Optional[ClassifyResult]  ← classify agent çıktısı
├── sql_result            # Optional[SQLResult]        ← sql agent çıktısı
├── analysis_result       # Optional[AnalysisResult]   ← analysis agent çıktısı
├── error                 # Optional[str]
└── final_response        # Optional[str]

ClassifyState (kendi içinde izole)
├── INPUT: user_input, messages, conversation_history, active_context,
│         user_clarification, clarification_count
├── INTERNAL: _ambiguity_context, _entity_validation_done, _extracted_entities
└── OUTPUT: classify_result → ClassifyResult
     ├── intent_type: str
     ├── query_type: str
     ├── confidence: float
     ├── needs_clarification: bool
     ├── pending_question: Optional[PendingQuestion]
     ├── user_query: str
     └── entities: Optional[Dict]

SQLState (kendi içinde izole, GenericText2SQLState'e benzer)
├── INPUT: user_query, query_type, active_context, conversation_history,
│         table_config (from runtime config)
├── INTERNAL: parsed_intent, enriched_metadata, resolved_steps,
│            sql_queries, schema_metadata, business_rules, retry_count,
│            sql_error_history, _execution_mode, _delta_changes
└── OUTPUT: sql_result → SQLResult
     ├── results: List[Dict]
     ├── sql_query: str
     ├── no_records_message: Optional[str]
     ├── updated_active_context: Optional[ActiveQueryContext]
     └── error: Optional[str]

AnalysisState (kendi içinde izole)
├── INPUT: results, query_type, user_query
├── INTERNAL: (yok — tek geçişli)
└── OUTPUT: analysis_result → AnalysisResult
     ├── viz_decision: Dict  # {needs_graph, chart_type, ...}
     ├── business_insights: Optional[BusinessContext]
     └── viz_reasoning: Optional[str]

ResponseState (kendi içinde izole)
├── INPUT: classify_result, sql_result, analysis_result, messages
└── OUTPUT: final_response → str, messages update
```

---

## Task 1: Modül iskeleti oluştur

**Files:**
- Create: `src/graphs/report_v2/__init__.py`
- Create: `src/graphs/report_v2/agents/__init__.py`

**Step 1: Dizinleri oluştur**

```bash
mkdir -p src/graphs/report_v2/agents
```

**Step 2: `__init__.py` dosyalarını oluştur**

`src/graphs/report_v2/__init__.py`:
```python
"""Report Agent V2 — Network Architecture with Complete State Separation."""
```

`src/graphs/report_v2/agents/__init__.py`:
```python
"""Report V2 Sub-agents."""
```

**Step 3: Commit**
```bash
git add src/graphs/report_v2/
git commit -m "feat: scaffold report_v2 module structure"
```

---

## Task 2: OrchestratorState yaz

**Files:**
- Create: `src/graphs/report_v2/state.py`
- Test: `tests/graphs/report_v2/test_orchestrator_state.py`

**Step 1: Test yaz (önce başarısız olacak)**

`tests/graphs/report_v2/test_orchestrator_state.py`:
```python
import pytest
from src.graphs.report_v2.state import (
    OrchestratorState,
    ClassifyResult,
    SQLResult,
    AnalysisResult,
    create_initial_orchestrator_state,
)


def test_orchestrator_state_required_fields():
    state = create_initial_orchestrator_state(user_input="test", session_id="s1")
    assert state["user_input"] == "test"
    assert state["session_id"] == "s1"
    assert state["messages"] == []
    assert state["conversation_history"] == []
    assert state["clarification_count"] == 0
    assert state["classify_result"] is None
    assert state["sql_result"] is None
    assert state["analysis_result"] is None
    assert state["error"] is None
    assert state["final_response"] is None


def test_classify_result_typed():
    result = ClassifyResult(
        intent_type="new_query",
        query_type="ranking",
        confidence=0.95,
        needs_clarification=False,
        pending_question=None,
        user_query="en çok satan ürünler",
        entities=None,
    )
    assert result["intent_type"] == "new_query"
    assert result["confidence"] == 0.95


def test_sql_result_typed():
    result = SQLResult(
        results=[{"col": "val"}],
        sql_query="SELECT * FROM t",
        no_records_message=None,
        updated_active_context=None,
        error=None,
    )
    assert result["results"] == [{"col": "val"}]


def test_analysis_result_typed():
    result = AnalysisResult(
        viz_decision={"needs_graph": True, "chart_type": "bar"},
        business_insights=None,
        viz_reasoning=None,
    )
    assert result["viz_decision"]["needs_graph"] is True
```

**Step 2: Testi çalıştır — başarısız olmalı**
```bash
pytest tests/graphs/report_v2/test_orchestrator_state.py -v
```
Expected: `ModuleNotFoundError`

**Step 3: `state.py` yaz**

`src/graphs/report_v2/state.py`:
```python
"""
OrchestratorState — Report V2 Network Architecture

Thin coordination bus. Her agent kendi state'ini yönetir.
Orchestrator sadece agent çıktılarını ve routing bilgisini tutar.
"""

from typing import TypedDict, List, Optional, Dict, Any, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# Korunan dosyalardan import — DEĞİŞMEZ
from src.graphs.report.state import (
    ActiveQueryContext,
    QueryCheckpoint,
    PendingQuestion,
    BusinessContext,
    checkpoint_reducer,
    create_empty_context,
    create_checkpoint,
)


# =============================================================================
# AGENT RESULT TYPES — Her agent'ın typed çıktısı
# =============================================================================

class ClassifyResult(TypedDict):
    """ClassifyAgent çıktısı."""
    intent_type: str           # "new_query" | "filter" | "sort" | "rollback" | "visualize"
    query_type: str            # "ranking" | "comparison" | "time_series" | "single_value" | ...
    confidence: float          # 0.0–1.0
    needs_clarification: bool
    pending_question: Optional[PendingQuestion]
    user_query: str            # Temizlenmiş/çıkarılmış sorgu metni
    entities: Optional[Dict[str, Any]]


class SQLResult(TypedDict):
    """SQLAgent çıktısı."""
    results: List[Dict[str, Any]]
    sql_query: str
    no_records_message: Optional[str]
    updated_active_context: Optional[ActiveQueryContext]
    error: Optional[str]


class AnalysisResult(TypedDict):
    """AnalysisAgent çıktısı."""
    viz_decision: Dict[str, Any]       # {needs_graph, chart_type, x_axis, y_axis, ...}
    business_insights: Optional[BusinessContext]
    viz_reasoning: Optional[str]


# =============================================================================
# ORCHESTRATOR STATE — Thin coordination bus
# =============================================================================

class OrchestratorState(TypedDict):
    """
    Report V2 Orchestrator State.

    Agent'lar arası koordinasyon için ince bus.
    Her agent kendi TypedDict state'ini kullanır;
    bu state sadece agent çıktılarını ve routing bilgisini tutar.
    """

    # Core iletişim
    messages: Annotated[List[BaseMessage], add_messages]
    user_input: str
    session_id: Optional[str]

    # Konuşma bağlamı (agent'lar arası paylaşılan)
    conversation_history: List[Dict[str, Any]]
    active_context: Optional[ActiveQueryContext]   # Delta SQL için
    query_history: Annotated[List[QueryCheckpoint], checkpoint_reducer]

    # HITL koordinasyon
    clarification_count: int           # Max 3 — sonsuz döngü koruması
    user_clarification: Optional[str]  # HITL sonrası kullanıcı cevabı

    # Agent çıktı slotları (typed)
    classify_result: Optional[ClassifyResult]
    sql_result: Optional[SQLResult]
    analysis_result: Optional[AnalysisResult]

    # Final
    error: Optional[str]
    final_response: Optional[str]


# =============================================================================
# FACTORY
# =============================================================================

def create_initial_orchestrator_state(
    user_input: str,
    session_id: Optional[str] = None,
) -> OrchestratorState:
    """Yeni konuşma için boş OrchestratorState oluşturur."""
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
        error=None,
        final_response=None,
    )
```

**Step 4: Testi çalıştır — geçmeli**
```bash
pytest tests/graphs/report_v2/test_orchestrator_state.py -v
```
Expected: 4 PASSED

**Step 5: Commit**
```bash
git add src/graphs/report_v2/state.py tests/graphs/report_v2/
git commit -m "feat: add OrchestratorState with typed agent result slots"
```

---

## Task 3: ClassifyAgent — State + Nodes

**Files:**
- Create: `src/graphs/report_v2/agents/classify_agent.py`
- Test: `tests/graphs/report_v2/agents/test_classify_agent.py`

**Step 1: Test yaz**

`tests/graphs/report_v2/agents/test_classify_agent.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.graphs.report_v2.agents.classify_agent import (
    ClassifyState,
    build_classify_agent,
    create_classify_input,
)
from src.graphs.report_v2.state import OrchestratorState, create_initial_orchestrator_state


def test_classify_input_extraction():
    """OrchestratorState'den ClassifyState input alanları doğru çıkarılıyor mu."""
    orch_state = create_initial_orchestrator_state(
        user_input="en çok satan ürünler", session_id="s1"
    )
    classify_input = create_classify_input(orch_state)

    assert classify_input["user_input"] == "en çok satan ürünler"
    assert classify_input["conversation_history"] == []
    assert classify_input["clarification_count"] == 0
    assert classify_input["user_clarification"] is None


@pytest.mark.asyncio
async def test_build_classify_agent_returns_compiled_graph():
    """build_classify_agent compiled graph döndürüyor mu."""
    mock_llm = MagicMock()
    agent = build_classify_agent(llm=mock_llm)
    assert agent is not None
    # Compiled LangGraph graph'ın invoke metodu var
    assert hasattr(agent, "ainvoke")
```

**Step 2: Testi çalıştır — başarısız olmalı**
```bash
pytest tests/graphs/report_v2/agents/test_classify_agent.py -v
```

**Step 3: `classify_agent.py` yaz**

`src/graphs/report_v2/agents/classify_agent.py`:
```python
"""
ClassifyAgent — Intent ve Query Type sınıflandırma sub-agent'ı.

Sorumluluklar:
- User intent classify (new_query, filter, sort, rollback, visualize)
- Query type detect (ranking, comparison, time_series, ...)
- Ambiguity detect + HITL soru üret
- Entity validation (comparison/time_series_comparison için)

Kullandığı business logic (değişmeden import):
- src/graphs/report/intent.py
- src/graphs/report/conversation_manager.py
- src/graphs/report/ambiguity_detectors.py
- src/graphs/report/ambiguity_router.py
- src/graphs/report/hitl_question_builder.py
- src/graphs/report/entity_validator.py
- src/graphs/report/query_type_patterns.py
"""

import logging
from typing import TypedDict, List, Optional, Dict, Any, Literal

from langchain_core.messages import BaseMessage
from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

# Korunan business logic — DEĞİŞMEZ
from src.graphs.report.state import ActiveQueryContext, PendingQuestion
from src.graphs.report_v2.state import ClassifyResult, OrchestratorState

logger = logging.getLogger(__name__)


# =============================================================================
# CLASSIFY STATE — Bu agent'a özel, izole
# =============================================================================

class ClassifyState(TypedDict):
    """ClassifyAgent internal state."""

    # --- INPUT (OrchestratorState'den gelir) ---
    user_input: str
    messages: List[BaseMessage]
    conversation_history: List[Dict[str, Any]]
    active_context: Optional[ActiveQueryContext]
    user_clarification: Optional[str]
    clarification_count: int

    # --- INTERNAL (sadece bu agent içinde kullanılır) ---
    _ambiguity_context: Optional[Any]
    _entity_validation_done: Optional[bool]
    _extracted_entities: Optional[Dict[str, Any]]
    _intent_type: Optional[str]
    _confidence: Optional[float]
    _query_type: Optional[str]
    _needs_clarification: Optional[bool]
    _pending_question: Optional[PendingQuestion]
    _user_query: Optional[str]

    # --- OUTPUT (OrchestratorState'e yazılır) ---
    classify_result: Optional[ClassifyResult]


# =============================================================================
# INPUT HELPERS
# =============================================================================

def create_classify_input(orch_state: OrchestratorState) -> ClassifyState:
    """OrchestratorState'den ClassifyAgent input'u oluştur."""
    return ClassifyState(
        user_input=orch_state["user_input"],
        messages=orch_state.get("messages", []),
        conversation_history=orch_state.get("conversation_history", []),
        active_context=orch_state.get("active_context"),
        user_clarification=orch_state.get("user_clarification"),
        clarification_count=orch_state.get("clarification_count", 0),
        # Internal başlangıç değerleri
        _ambiguity_context=None,
        _entity_validation_done=False,
        _extracted_entities=None,
        _intent_type=None,
        _confidence=None,
        _query_type=None,
        _needs_clarification=None,
        _pending_question=None,
        _user_query=None,
        classify_result=None,
    )


# =============================================================================
# NODE FUNCTIONS
# =============================================================================

async def classify_intent_node(state: ClassifyState) -> dict:
    """
    Intent + query type classification.

    Mevcut conversation_manager veya basit IntentClassifier kullanır.
    Sonucu _intent_type, _confidence, _query_type olarak yazar.
    """
    from src.graphs.report.intent import IntentClassifier, IntentType

    user_input = state["user_input"]
    conversation_history = state.get("conversation_history", [])
    active_context = state.get("active_context")

    logger.info(f"[CLASSIFY] Classifying: '{user_input[:80]}'")

    try:
        # Query type detection — korunan dosyadan
        from src.graphs.report.query_type_patterns import detect_query_type
        query_type, qt_confidence = detect_query_type(user_input)

        # Intent type detection
        # Not: LLM varsa ConversationManager kullan (build_classify_agent'a inject edilir)
        # Şimdilik basit rule-based fallback
        intent_type = _infer_intent_from_context(user_input, active_context)
        confidence = qt_confidence

        logger.info(f"[CLASSIFY] intent={intent_type}, query_type={query_type}, conf={confidence:.2f}")

        return {
            "_intent_type": intent_type,
            "_confidence": confidence,
            "_query_type": query_type,
            "_user_query": user_input,
        }

    except Exception as e:
        logger.error(f"[CLASSIFY] Error: {e}")
        return {
            "_intent_type": "new_query",
            "_confidence": 0.5,
            "_query_type": "unknown",
            "_user_query": user_input,
        }


def _infer_intent_from_context(user_input: str, active_context: Optional[ActiveQueryContext]) -> str:
    """Basit rule-based intent inference (LLM fallback)."""
    lower = user_input.lower()

    # Rollback signals
    if any(kw in lower for kw in ["geri al", "önceki", "undo"]):
        return "rollback"

    # Visualization signals
    if any(kw in lower for kw in ["grafik", "chart", "görsel", "plot"]):
        if active_context and active_context.get("current_sql"):
            return "visualize"

    # Filter/sort signals on existing context
    if active_context and active_context.get("current_sql"):
        if any(kw in lower for kw in ["filtrele", "sadece", "sırala", "büyükten", "küçükten"]):
            return "filter"

    return "new_query"


async def detect_ambiguity_node(state: ClassifyState) -> dict:
    """
    Ambiguity detection — HITL gerekip gerekmediğine karar ver.

    Korunan ambiguity_detectors + ambiguity_router kullanır.
    """
    from src.graphs.report.ambiguity_router import should_trigger_hitl, apply_auto_resolution
    from src.graphs.report.hitl_question_builder import HITLQuestionBuilder

    intent_type = state.get("_intent_type", "new_query")
    query_type = state.get("_query_type", "unknown")
    confidence = state.get("_confidence", 0.5)
    clarification_count = state.get("clarification_count", 0)

    # Max clarification check
    if clarification_count >= 3:
        logger.warning("[CLASSIFY] Max clarification reached, forcing proceed")
        return {"_needs_clarification": False}

    # Confidence threshold
    if confidence < 0.6 or query_type == "unknown":
        builder = HITLQuestionBuilder()
        question = builder.build_query_type_question(
            user_input=state["user_input"],
            detected_type=query_type,
        )
        logger.info(f"[CLASSIFY] Low confidence ({confidence:.2f}), triggering HITL")
        return {
            "_needs_clarification": True,
            "_pending_question": question,
        }

    return {"_needs_clarification": False}


async def entity_validation_node(state: ClassifyState) -> dict:
    """
    Entity validation — comparison/time_series_comparison için entity'leri doğrula.

    EntityValidator korunan dosyadan import edilir.
    """
    query_type = state.get("_query_type", "unknown")

    # Sadece bu query type'lar için çalış
    if query_type not in ("comparison", "time_series_comparison"):
        return {"_entity_validation_done": True}

    if state.get("_entity_validation_done"):
        return {}

    logger.info(f"[CLASSIFY] Entity validation for query_type={query_type}")

    try:
        from src.graphs.report.entity_validator import EntityValidator
        # EntityValidator LLM gerektiriyor — inject edilmemiş olabilir
        # Bu durumda validation skip edilir
        return {"_entity_validation_done": True}
    except Exception as e:
        logger.warning(f"[CLASSIFY] Entity validation skipped: {e}")
        return {"_entity_validation_done": True}


async def hitl_ask_user_node(state: ClassifyState) -> dict:
    """
    HITL node — interrupt() ile kullanıcı input'u bekle.

    Kullanıcı Command(resume=...) ile cevap verir.
    """
    pending_question = state.get("_pending_question")
    if not pending_question:
        return {}

    question_text = pending_question.get("question", "Lütfen açıklayın.")
    logger.info(f"[CLASSIFY] HITL interrupt: {question_text[:100]}")

    # interrupt() graph'ı durdurur, kullanıcı cevabı bekler
    user_response = interrupt(question_text)
    logger.info(f"[CLASSIFY] User response: {user_response}")

    return {
        "user_clarification": user_response,
        "clarification_count": state.get("clarification_count", 0) + 1,
        "_needs_clarification": False,
    }


async def build_classify_result_node(state: ClassifyState) -> dict:
    """
    ClassifyResult oluştur — orchestrator'a yazılacak typed output.
    """
    result = ClassifyResult(
        intent_type=state.get("_intent_type", "new_query"),
        query_type=state.get("_query_type", "unknown"),
        confidence=state.get("_confidence", 0.5),
        needs_clarification=state.get("_needs_clarification", False),
        pending_question=state.get("_pending_question"),
        user_query=state.get("_user_query", state["user_input"]),
        entities=state.get("_extracted_entities"),
    )

    logger.info(f"[CLASSIFY] Result: intent={result['intent_type']}, "
               f"type={result['query_type']}, conf={result['confidence']:.2f}")

    return {"classify_result": result}


# =============================================================================
# ROUTING
# =============================================================================

def route_after_ambiguity(state: ClassifyState) -> str:
    """Ambiguity sonrası routing."""
    if state.get("_needs_clarification"):
        return "hitl_ask_user"

    query_type = state.get("_query_type", "unknown")
    if query_type in ("comparison", "time_series_comparison"):
        if not state.get("_entity_validation_done"):
            return "entity_validation"

    return "build_result"


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_classify_agent(llm: Optional[BaseChatModel] = None):
    """
    ClassifyAgent subgraph'ını compile et.

    Args:
        llm: LLM instance (opsiyonel — LLM yoksa rule-based fallback)

    Returns:
        Compiled LangGraph subgraph (ClassifyState ile)
    """
    graph = StateGraph(ClassifyState)

    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("detect_ambiguity", detect_ambiguity_node)
    graph.add_node("entity_validation", entity_validation_node)
    graph.add_node("hitl_ask_user", hitl_ask_user_node)
    graph.add_node("build_result", build_classify_result_node)

    graph.add_edge(START, "classify_intent")
    graph.add_edge("classify_intent", "detect_ambiguity")

    graph.add_conditional_edges(
        "detect_ambiguity",
        route_after_ambiguity,
        {
            "hitl_ask_user": "hitl_ask_user",
            "entity_validation": "entity_validation",
            "build_result": "build_result",
        },
    )

    # HITL sonrası yeniden classify
    graph.add_edge("hitl_ask_user", "classify_intent")
    graph.add_edge("entity_validation", "build_result")
    graph.add_edge("build_result", END)

    return graph.compile()
```

**Step 4: Testi çalıştır**
```bash
pytest tests/graphs/report_v2/agents/test_classify_agent.py -v
```
Expected: PASSED

**Step 5: Commit**
```bash
git add src/graphs/report_v2/agents/classify_agent.py tests/graphs/report_v2/agents/
git commit -m "feat: add ClassifyAgent with isolated ClassifyState and HITL support"
```

---

## Task 4: SQLAgent — State + Nodes

**Files:**
- Create: `src/graphs/report_v2/agents/sql_agent.py`
- Test: `tests/graphs/report_v2/agents/test_sql_agent.py`

**Step 1: Test yaz**

```python
# tests/graphs/report_v2/agents/test_sql_agent.py
import pytest
from unittest.mock import MagicMock
from src.graphs.report_v2.agents.sql_agent import (
    SQLState,
    create_sql_input,
    build_sql_agent,
)
from src.graphs.report_v2.state import (
    ClassifyResult,
    create_initial_orchestrator_state,
)


def test_sql_input_extraction_from_classify_result():
    """ClassifyResult + OrchestratorState'den SQLState input doğru çıkarılıyor."""
    orch_state = create_initial_orchestrator_state(user_input="test", session_id="s1")
    classify_result = ClassifyResult(
        intent_type="new_query",
        query_type="ranking",
        confidence=0.9,
        needs_clarification=False,
        pending_question=None,
        user_query="en çok satan ürünler",
        entities=None,
    )

    sql_input = create_sql_input(orch_state, classify_result)
    assert sql_input["user_query"] == "en çok satan ürünler"
    assert sql_input["query_type"] == "ranking"
    assert sql_input["active_context"] is None


def test_build_sql_agent_returns_compiled_graph():
    mock_node_kit = MagicMock()
    agent = build_sql_agent(node_kit=mock_node_kit)
    assert hasattr(agent, "ainvoke")
```

**Step 2: Testi çalıştır — başarısız olmalı**
```bash
pytest tests/graphs/report_v2/agents/test_sql_agent.py -v
```

**Step 3: `sql_agent.py` yaz**

`src/graphs/report_v2/agents/sql_agent.py`:
```python
"""
SQLAgent — Text-to-SQL pipeline sub-agent'ı.

Sorumluluklar:
- Delta vs Full execution mode karar
- SQL oluşturma (generic_text2sql node'larını çalıştırır)
- SQL execute + retry (self-healing)
- ActiveQueryContext güncelleme

Kullandığı business logic (değişmeden import):
- src/graphs/generic_text2sql/node_factories.py
- src/graphs/report/delta_parser.py
- src/graphs/report/query_type_actions.py
"""

import logging
from typing import TypedDict, List, Optional, Dict, Any

from langgraph.graph import StateGraph, START, END

from src.graphs.report.state import ActiveQueryContext
from src.graphs.report_v2.state import ClassifyResult, SQLResult, OrchestratorState

logger = logging.getLogger(__name__)


# =============================================================================
# SQL STATE — Bu agent'a özel, izole
# =============================================================================

class SQLState(TypedDict):
    """SQLAgent internal state."""

    # --- INPUT ---
    user_query: str
    query_type: str
    active_context: Optional[ActiveQueryContext]
    conversation_history: List[Dict[str, Any]]

    # --- INTERNAL (generic_text2sql pipeline field'ları) ---
    parsed_intent: Optional[Dict[str, Any]]
    enriched_metadata: Optional[Dict[str, Any]]
    resolved_steps: Optional[List[Dict[str, Any]]]
    sql_queries: Optional[List[str]]
    schema_metadata: Optional[Dict[str, Any]]
    business_rules: Optional[Dict[str, Any]]
    business_rules_context: Optional[str]
    merged_sql_components: Optional[Dict[str, Any]]
    applied_business_rules: Optional[List[Dict[str, Any]]]
    detected_tables: Optional[List[str]]
    resolution_metadata: Optional[Dict[str, Any]]
    retry_count: Optional[int]
    sql_error_history: Optional[List[Dict[str, Any]]]
    no_records_message: Optional[str]

    # Execution mode (delta vs full)
    _execution_mode: Optional[str]    # "full" | "delta"
    _delta_fallback: Optional[bool]
    _delta_changes: Optional[Dict[str, Any]]

    # --- OUTPUT ---
    results: Optional[List[Dict[str, Any]]]
    sql_result: Optional[SQLResult]


# =============================================================================
# INPUT HELPERS
# =============================================================================

def create_sql_input(
    orch_state: OrchestratorState,
    classify_result: ClassifyResult,
) -> SQLState:
    """OrchestratorState + ClassifyResult'dan SQLAgent input'u oluştur."""
    return SQLState(
        user_query=classify_result["user_query"],
        query_type=classify_result["query_type"],
        active_context=orch_state.get("active_context"),
        conversation_history=orch_state.get("conversation_history", []),
        parsed_intent=None,
        enriched_metadata=None,
        resolved_steps=None,
        sql_queries=None,
        schema_metadata=None,
        business_rules=None,
        business_rules_context=None,
        merged_sql_components=None,
        applied_business_rules=None,
        detected_tables=None,
        resolution_metadata=None,
        retry_count=0,
        sql_error_history=[],
        no_records_message=None,
        results=None,
        _execution_mode=None,
        _delta_fallback=False,
        _delta_changes=None,
        sql_result=None,
    )


# =============================================================================
# NODE FUNCTIONS
# =============================================================================

async def detect_execution_mode_node(state: SQLState) -> dict:
    """
    Delta vs Full execution mode belirle.

    Delta: Mevcut SQL üzerine küçük değişiklik (filter ekle, sort değiştir)
    Full: Yeni SQL oluştur (baştan)
    """
    from src.graphs.report.delta_parser import AdvancedDeltaParser

    active_context = state.get("active_context")
    user_query = state["user_query"]

    if not active_context or not active_context.get("current_sql"):
        logger.info("[SQL] No active context → full execution")
        return {"_execution_mode": "full"}

    try:
        parser = AdvancedDeltaParser()
        delta = parser.parse(user_query, active_context)
        if delta and delta.get("has_changes"):
            logger.info(f"[SQL] Delta detected → delta execution: {delta}")
            return {
                "_execution_mode": "delta",
                "_delta_changes": delta,
            }
    except Exception as e:
        logger.warning(f"[SQL] Delta parse error: {e} → full fallback")

    return {"_execution_mode": "full"}


async def build_sql_result_node(state: SQLState) -> dict:
    """
    SQLResult oluştur — orchestrator'a yazılacak typed output.

    generic_text2sql pipeline'ın bitiminde çalışır.
    """
    results = state.get("results") or []
    sql_queries = state.get("sql_queries") or []
    sql_query = sql_queries[-1] if sql_queries else ""
    no_records = state.get("no_records_message")

    # ActiveQueryContext'i güncelle
    updated_context = None
    if results and sql_query:
        from src.graphs.report.state import create_checkpoint
        from datetime import datetime
        active = state.get("active_context") or {}
        updated_context = ActiveQueryContext(
            current_table=active.get("current_table", ""),
            current_sql=sql_query,
            applied_filters=active.get("applied_filters", []),
            grouping_columns=active.get("grouping_columns", []),
            order_by_columns=active.get("order_by_columns", []),
            result_sample=results[:5],
            result_row_count=len(results),
            last_execution_time=datetime.now().isoformat(),
            confidence_score=0.9,
        )

    result = SQLResult(
        results=results,
        sql_query=sql_query,
        no_records_message=no_records,
        updated_active_context=updated_context,
        error=None,
    )

    logger.info(f"[SQL] Result: {len(results)} rows, sql_len={len(sql_query)}")
    return {"sql_result": result}


# =============================================================================
# ROUTING
# =============================================================================

def route_after_execution_mode(state: SQLState) -> str:
    """Delta vs Full path routing."""
    if state.get("_execution_mode") == "delta" and not state.get("_delta_fallback"):
        return "delta_sql_modifier"
    return "create_table"


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_sql_agent(node_kit=None):
    """
    SQLAgent subgraph'ını compile et.

    Args:
        node_kit: GenericText2SQLNodeKit instance (merged text2sql için)

    Returns:
        Compiled LangGraph subgraph (SQLState ile)
    """
    from src.graphs.generic_text2sql.node_factories import create_all_text2sql_nodes

    if node_kit is None:
        raise ValueError("node_kit required for SQLAgent")

    text2sql_nodes = create_all_text2sql_nodes(node_kit)

    graph = StateGraph(SQLState)

    # Execution mode detection
    graph.add_node("detect_execution_mode", detect_execution_mode_node)

    # Text2SQL pipeline nodes (generic, korunan)
    graph.add_node("create_table", text2sql_nodes["create_table"])
    graph.add_node("sql_architect", text2sql_nodes["sql_architect"])
    graph.add_node("retrieve_business_rules", text2sql_nodes["retrieve_business_rules"])
    graph.add_node("metadata_enrichment", text2sql_nodes["metadata_enrichment"])
    graph.add_node("value_resolver", text2sql_nodes["value_resolver"])
    graph.add_node("sql_query_builder", text2sql_nodes["sql_query_builder"])
    graph.add_node("sql_executor", text2sql_nodes["sql_executor"])
    graph.add_node("cleanup_table", text2sql_nodes["cleanup_table"])

    # Delta path node (korunan delta_parser'ı kullanır)
    from src.graphs.report.nodes import delta_sql_modifier_node  # geçici — Task 5'te kaldırılır
    graph.add_node("delta_sql_modifier", delta_sql_modifier_node)

    # Result builder
    graph.add_node("build_sql_result", build_sql_result_node)

    # Edges
    graph.add_edge(START, "detect_execution_mode")

    graph.add_conditional_edges(
        "detect_execution_mode",
        route_after_execution_mode,
        {
            "delta_sql_modifier": "delta_sql_modifier",
            "create_table": "create_table",
        },
    )

    # Delta path
    graph.add_conditional_edges(
        "delta_sql_modifier",
        lambda s: "create_table" if s.get("_delta_fallback") else "sql_executor",
        {"sql_executor": "sql_executor", "create_table": "create_table"},
    )

    # Full path
    graph.add_edge("create_table", "sql_architect")
    graph.add_edge("sql_architect", "retrieve_business_rules")
    graph.add_edge("retrieve_business_rules", "metadata_enrichment")
    graph.add_edge("metadata_enrichment", "value_resolver")
    graph.add_edge("value_resolver", "sql_query_builder")
    graph.add_edge("sql_query_builder", "sql_executor")

    # Converge
    graph.add_edge("sql_executor", "cleanup_table")
    graph.add_edge("cleanup_table", "build_sql_result")
    graph.add_edge("build_sql_result", END)

    return graph.compile()
```

**Step 4: Testi çalıştır**
```bash
pytest tests/graphs/report_v2/agents/test_sql_agent.py -v
```
Expected: PASSED

**Step 5: Commit**
```bash
git add src/graphs/report_v2/agents/sql_agent.py tests/graphs/report_v2/agents/test_sql_agent.py
git commit -m "feat: add SQLAgent with isolated SQLState, delta/full routing"
```

---

## Task 5: AnalysisAgent — State + Nodes

**Files:**
- Create: `src/graphs/report_v2/agents/analysis_agent.py`
- Test: `tests/graphs/report_v2/agents/test_analysis_agent.py`

**Step 1: Test yaz**

```python
# tests/graphs/report_v2/agents/test_analysis_agent.py
import pytest
from src.graphs.report_v2.agents.analysis_agent import (
    AnalysisState,
    create_analysis_input,
    build_analysis_agent,
)
from src.graphs.report_v2.state import (
    ClassifyResult,
    SQLResult,
    create_initial_orchestrator_state,
)


def test_analysis_input_extraction():
    orch_state = create_initial_orchestrator_state(user_input="test")
    classify_result = ClassifyResult(
        intent_type="new_query", query_type="ranking",
        confidence=0.9, needs_clarification=False,
        pending_question=None, user_query="test query", entities=None,
    )
    sql_result = SQLResult(
        results=[{"urun": "A", "satis": 100}],
        sql_query="SELECT * FROM t",
        no_records_message=None,
        updated_active_context=None,
        error=None,
    )

    analysis_input = create_analysis_input(orch_state, classify_result, sql_result)
    assert analysis_input["results"] == [{"urun": "A", "satis": 100}]
    assert analysis_input["query_type"] == "ranking"


def test_build_analysis_agent_returns_compiled_graph():
    agent = build_analysis_agent()
    assert hasattr(agent, "ainvoke")
```

**Step 2: Testi çalıştır — başarısız olmalı**

**Step 3: `analysis_agent.py` yaz**

`src/graphs/report_v2/agents/analysis_agent.py`:
```python
"""
AnalysisAgent — Visualization + Business Insights sub-agent'ı.

Sorumluluklar:
- Visualization gerekip gerekmediğine karar ver (LLM veya rule-based)
- Business insights çıkar (opsiyonel)
- Viz chart type, axis belirle

Kullandığı business logic (değişmeden import):
- src/graphs/report/report_interpreter.py
- src/graphs/report/business_context_tracker.py
- src/graphs/report/query_type_viz_mapping.py
"""

import logging
from typing import TypedDict, List, Optional, Dict, Any

from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph, START, END

from src.graphs.report_v2.state import (
    ClassifyResult, SQLResult, AnalysisResult, OrchestratorState
)

logger = logging.getLogger(__name__)


# =============================================================================
# ANALYSIS STATE — Bu agent'a özel, izole
# =============================================================================

class AnalysisState(TypedDict):
    """AnalysisAgent internal state."""

    # --- INPUT ---
    results: List[Dict[str, Any]]
    query_type: str
    user_query: str

    # --- OUTPUT ---
    analysis_result: Optional[AnalysisResult]


# =============================================================================
# INPUT HELPERS
# =============================================================================

def create_analysis_input(
    orch_state: OrchestratorState,
    classify_result: ClassifyResult,
    sql_result: SQLResult,
) -> AnalysisState:
    return AnalysisState(
        results=sql_result.get("results", []),
        query_type=classify_result.get("query_type", "unknown"),
        user_query=classify_result.get("user_query", ""),
        analysis_result=None,
    )


# =============================================================================
# NODE FUNCTIONS
# =============================================================================

async def decide_viz_node(state: AnalysisState) -> dict:
    """
    Visualization karar node.

    Önce query_type mapping'e bakar (hızlı, deterministik).
    Fallback: data shape analizi.
    """
    from src.graphs.report.query_type_viz_mapping import QUERY_TYPE_VIZ_MAPPING

    query_type = state.get("query_type", "unknown")
    results = state.get("results", [])

    # Query type → viz mapping (korunan dosyadan)
    viz_config = QUERY_TYPE_VIZ_MAPPING.get(query_type)

    if viz_config:
        viz_decision = {
            "needs_graph": True,
            "chart_type": viz_config.get("default_chart", "bar"),
            "source": "query_type_mapping",
        }
    elif not results or len(results) == 1:
        viz_decision = {"needs_graph": False, "source": "data_shape"}
    else:
        viz_decision = {
            "needs_graph": len(results) > 1,
            "chart_type": "bar",
            "source": "fallback",
        }

    logger.info(f"[ANALYSIS] Viz decision: {viz_decision}")

    result = AnalysisResult(
        viz_decision=viz_decision,
        business_insights=None,
        viz_reasoning=None,
    )

    return {"analysis_result": result}


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_analysis_agent(llm: Optional[BaseChatModel] = None):
    """
    AnalysisAgent subgraph'ını compile et.

    Args:
        llm: LLM (opsiyonel — LLM yoksa rule-based fallback)
    """
    graph = StateGraph(AnalysisState)
    graph.add_node("decide_viz", decide_viz_node)
    graph.add_edge(START, "decide_viz")
    graph.add_edge("decide_viz", END)
    return graph.compile()
```

**Step 4: Test + commit**
```bash
pytest tests/graphs/report_v2/agents/test_analysis_agent.py -v
git add src/graphs/report_v2/agents/analysis_agent.py tests/graphs/report_v2/agents/test_analysis_agent.py
git commit -m "feat: add AnalysisAgent with isolated AnalysisState"
```

---

## Task 6: ResponseAgent — State + Nodes

**Files:**
- Create: `src/graphs/report_v2/agents/response_agent.py`
- Test: `tests/graphs/report_v2/agents/test_response_agent.py`

**Step 1: Test yaz**

```python
# tests/graphs/report_v2/agents/test_response_agent.py
import pytest
from src.graphs.report_v2.agents.response_agent import (
    ResponseState,
    create_response_input,
    build_response_agent,
)
from src.graphs.report_v2.state import (
    ClassifyResult, SQLResult, AnalysisResult,
    create_initial_orchestrator_state,
)


def test_response_input_extraction():
    orch_state = create_initial_orchestrator_state(user_input="test")
    classify_result = ClassifyResult(
        intent_type="new_query", query_type="ranking",
        confidence=0.9, needs_clarification=False,
        pending_question=None, user_query="test", entities=None,
    )
    sql_result = SQLResult(
        results=[{"urun": "A"}], sql_query="SELECT *",
        no_records_message=None, updated_active_context=None, error=None,
    )
    analysis_result = AnalysisResult(
        viz_decision={"needs_graph": False},
        business_insights=None, viz_reasoning=None,
    )

    resp_input = create_response_input(orch_state, classify_result, sql_result, analysis_result)
    assert resp_input["query_type"] == "ranking"
    assert resp_input["results"] == [{"urun": "A"}]


def test_build_response_agent():
    agent = build_response_agent()
    assert hasattr(agent, "ainvoke")
```

**Step 2: Testi çalıştır — başarısız olmalı**

**Step 3: `response_agent.py` yaz**

`src/graphs/report_v2/agents/response_agent.py`:
```python
"""
ResponseAgent — Final yanıt üretim sub-agent'ı.

Sorumluluklar:
- SQL sonuçlarından natural language yanıt oluştur
- Visualization output'u yanıta ekle
- Hata durumlarını kullanıcı dostu mesaja çevir

Kullandığı business logic (değişmeden import):
- src/graphs/report/response_generator.py
"""

import logging
from typing import TypedDict, List, Optional, Dict, Any

from langchain_core.messages import BaseMessage
from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph, START, END

from src.graphs.report_v2.state import (
    ClassifyResult, SQLResult, AnalysisResult, OrchestratorState
)

logger = logging.getLogger(__name__)


# =============================================================================
# RESPONSE STATE — Bu agent'a özel, izole
# =============================================================================

class ResponseState(TypedDict):
    """ResponseAgent internal state."""

    # --- INPUT ---
    query_type: str
    user_query: str
    results: List[Dict[str, Any]]
    sql_query: str
    viz_decision: Dict[str, Any]
    no_records_message: Optional[str]
    error: Optional[str]
    messages: List[BaseMessage]

    # --- OUTPUT ---
    final_response: Optional[str]


# =============================================================================
# INPUT HELPERS
# =============================================================================

def create_response_input(
    orch_state: OrchestratorState,
    classify_result: ClassifyResult,
    sql_result: SQLResult,
    analysis_result: AnalysisResult,
) -> ResponseState:
    return ResponseState(
        query_type=classify_result.get("query_type", "unknown"),
        user_query=classify_result.get("user_query", ""),
        results=sql_result.get("results", []),
        sql_query=sql_result.get("sql_query", ""),
        viz_decision=analysis_result.get("viz_decision", {}),
        no_records_message=sql_result.get("no_records_message"),
        error=sql_result.get("error"),
        messages=orch_state.get("messages", []),
        final_response=None,
    )


# =============================================================================
# NODE FUNCTIONS
# =============================================================================

async def generate_response_node(state: ResponseState) -> dict:
    """
    Final yanıt oluştur.

    Önce hata/no-records durumlarını kontrol et.
    Sonra sonuçlara göre natural language yanıt üret.
    """
    error = state.get("error")
    no_records = state.get("no_records_message")
    results = state.get("results", [])

    if error:
        response = f"Sorgu çalıştırılırken bir hata oluştu: {error}"
        logger.warning(f"[RESPONSE] Error response: {error[:100]}")
    elif no_records:
        response = no_records
        logger.info("[RESPONSE] No records response")
    elif not results:
        response = "Sorgunuza uygun kayıt bulunamadı."
    else:
        # Basit template response (LLM inject edilmişse ResponseGenerator kullanılır)
        count = len(results)
        query_type = state.get("query_type", "unknown")
        response = f"{count} kayıt bulundu. (query_type: {query_type})"
        logger.info(f"[RESPONSE] Template response: {count} rows")

    return {"final_response": response}


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_response_agent(llm: Optional[BaseChatModel] = None):
    """
    ResponseAgent subgraph'ını compile et.

    Args:
        llm: LLM (opsiyonel — ResponseGenerator için)
    """
    graph = StateGraph(ResponseState)
    graph.add_node("generate_response", generate_response_node)
    graph.add_edge(START, "generate_response")
    graph.add_edge("generate_response", END)
    return graph.compile()
```

**Step 4: Test + commit**
```bash
pytest tests/graphs/report_v2/agents/test_response_agent.py -v
git add src/graphs/report_v2/agents/response_agent.py tests/graphs/report_v2/agents/test_response_agent.py
git commit -m "feat: add ResponseAgent with isolated ResponseState"
```

---

## Task 7: Orchestrator Graph — Network Wiring

**Files:**
- Create: `src/graphs/report_v2/graph.py`
- Test: `tests/graphs/report_v2/test_orchestrator_graph.py`

**Step 1: Test yaz**

```python
# tests/graphs/report_v2/test_orchestrator_graph.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.graphs.report_v2.graph import build_report_v2_graph
from src.graphs.report_v2.state import create_initial_orchestrator_state


def test_build_report_v2_graph_returns_compiled():
    mock_node_kit = MagicMock()
    graph = build_report_v2_graph(node_kit=mock_node_kit)
    assert graph is not None
    assert hasattr(graph, "ainvoke")


def test_build_report_v2_graph_without_llm():
    """LLM olmadan da build edilebilmeli (rule-based fallback)."""
    mock_node_kit = MagicMock()
    graph = build_report_v2_graph(node_kit=mock_node_kit, llm=None)
    assert graph is not None
```

**Step 2: Testi çalıştır — başarısız olmalı**

**Step 3: `graph.py` yaz**

`src/graphs/report_v2/graph.py`:
```python
"""
Report V2 Orchestrator Graph — Network Architecture

Network mimarisi:
  START
    ↓
  classify_agent  ←──────────────────┐
    ↓ (conditional)                  │ (re-classify after HITL)
  ├── [sql_agent]                    │
  │     ↓                           │
  │   [analysis_agent]              │
  │     ↓                           │
  │   [response_agent] → END        │
  │                                  │
  └── [rollback] → response_agent   │
  └── [visualize_direct] → analysis_agent
"""

import logging
from typing import Optional, Literal

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.models.llm import LLM
from src.graphs.report_v2.state import OrchestratorState, create_initial_orchestrator_state
from src.graphs.report_v2.agents.classify_agent import (
    build_classify_agent,
    create_classify_input,
)
from src.graphs.report_v2.agents.sql_agent import (
    build_sql_agent,
    create_sql_input,
)
from src.graphs.report_v2.agents.analysis_agent import (
    build_analysis_agent,
    create_analysis_input,
)
from src.graphs.report_v2.agents.response_agent import (
    build_response_agent,
    create_response_input,
)

logger = logging.getLogger(__name__)


# =============================================================================
# BRIDGE NODES — Orchestrator ↔ Agent state mapping
# =============================================================================

def make_classify_bridge(classify_agent):
    """ClassifyAgent'ı OrchestratorState üzerinde çalıştıran bridge node."""
    async def classify_bridge_node(state: OrchestratorState) -> dict:
        logger.info("[ORCHESTRATOR] Running classify_agent...")
        classify_input = create_classify_input(state)
        result = await classify_agent.ainvoke(classify_input)
        classify_result = result.get("classify_result")
        logger.info(f"[ORCHESTRATOR] classify_result: {classify_result}")
        return {"classify_result": classify_result}
    return classify_bridge_node


def make_sql_bridge(sql_agent):
    """SQLAgent'ı OrchestratorState üzerinde çalıştıran bridge node."""
    async def sql_bridge_node(state: OrchestratorState) -> dict:
        logger.info("[ORCHESTRATOR] Running sql_agent...")
        classify_result = state.get("classify_result")
        if not classify_result:
            return {"error": "classify_result missing before sql_agent"}

        sql_input = create_sql_input(state, classify_result)
        result = await sql_agent.ainvoke(sql_input)

        sql_result = result.get("sql_result")
        # ActiveQueryContext'i orchestrator'da güncelle
        updated_context = sql_result.get("updated_active_context") if sql_result else None

        updates = {"sql_result": sql_result}
        if updated_context:
            updates["active_context"] = updated_context

        logger.info(f"[ORCHESTRATOR] sql_result: {len(sql_result.get('results', []))} rows")
        return updates
    return sql_bridge_node


def make_analysis_bridge(analysis_agent):
    """AnalysisAgent'ı OrchestratorState üzerinde çalıştıran bridge node."""
    async def analysis_bridge_node(state: OrchestratorState) -> dict:
        logger.info("[ORCHESTRATOR] Running analysis_agent...")
        classify_result = state.get("classify_result")
        sql_result = state.get("sql_result")

        if not classify_result or not sql_result:
            return {"error": "Missing classify_result or sql_result"}

        analysis_input = create_analysis_input(state, classify_result, sql_result)
        result = await analysis_agent.ainvoke(analysis_input)

        analysis_result = result.get("analysis_result")
        logger.info(f"[ORCHESTRATOR] analysis_result: {analysis_result}")
        return {"analysis_result": analysis_result}
    return analysis_bridge_node


def make_response_bridge(response_agent):
    """ResponseAgent'ı OrchestratorState üzerinde çalıştıran bridge node."""
    async def response_bridge_node(state: OrchestratorState) -> dict:
        logger.info("[ORCHESTRATOR] Running response_agent...")
        classify_result = state.get("classify_result")
        sql_result = state.get("sql_result")
        analysis_result = state.get("analysis_result")

        # sql_result yoksa (rollback/visualize_direct path)
        if not sql_result:
            from src.graphs.report_v2.state import SQLResult
            sql_result = SQLResult(
                results=[], sql_query="", no_records_message=None,
                updated_active_context=None, error=None,
            )
        if not analysis_result:
            from src.graphs.report_v2.state import AnalysisResult
            analysis_result = AnalysisResult(
                viz_decision={"needs_graph": False}, business_insights=None, viz_reasoning=None,
            )

        response_input = create_response_input(state, classify_result, sql_result, analysis_result)
        result = await response_agent.ainvoke(response_input)

        final_response = result.get("final_response", "")
        from langchain_core.messages import AIMessage
        return {
            "final_response": final_response,
            "messages": [AIMessage(content=final_response)],
        }
    return response_bridge_node


async def rollback_bridge_node(state: OrchestratorState) -> dict:
    """Rollback — önceki query context'e dön."""
    query_history = state.get("query_history", [])
    if not query_history:
        return {"error": "Geri alınacak sorgu bulunamadı."}

    last_checkpoint = query_history[-1]
    prev_context = last_checkpoint.get("active_context")
    logger.info(f"[ORCHESTRATOR] Rollback to checkpoint v{last_checkpoint.get('version')}")
    return {
        "active_context": prev_context,
        "sql_result": None,
        "analysis_result": None,
    }


# =============================================================================
# ROUTING
# =============================================================================

def route_after_classify(state: OrchestratorState) -> str:
    """
    ClassifyAgent sonrası routing.

    Routing önceliği:
    1. Hata → response (error message)
    2. Rollback intent → rollback
    3. Visualize intent (existing context) → analysis (skip SQL)
    4. Clarification needed → ERROR (classify_agent içinde interrupt() halleder)
    5. Default → sql_agent
    """
    classify_result = state.get("classify_result")
    if not classify_result:
        return "response_agent"  # error path

    intent_type = classify_result.get("intent_type", "new_query")
    active_context = state.get("active_context")

    if intent_type == "rollback":
        return "rollback"

    if intent_type == "visualize" and active_context:
        return "analysis_agent"  # SQL skip, direkt viz

    return "sql_agent"


def route_after_sql(state: OrchestratorState) -> str:
    """SQL sonrası routing."""
    sql_result = state.get("sql_result", {})
    error = sql_result.get("error") if sql_result else None
    no_records = sql_result.get("no_records_message") if sql_result else None

    if error:
        return "response_agent"  # hata mesajı üret

    if no_records:
        return "response_agent"  # "kayıt yok" mesajı üret

    return "analysis_agent"


def route_after_analysis(state: OrchestratorState) -> str:
    """Analysis sonrası routing — şimdilik hep response."""
    return "response_agent"


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_report_v2_graph(
    node_kit=None,
    llm: Optional[LLM] = None,
    visualization_graph=None,
    checkpointer=None,
):
    """
    Report V2 network graph'ını compile et.

    Args:
        node_kit: GenericText2SQLNodeKit (SQL pipeline için)
        llm: LLM instance (opsiyonel)
        visualization_graph: Compiled viz graph (opsiyonel)
        checkpointer: LangGraph checkpointer (default: MemorySaver)

    Returns:
        Compiled StateGraph (OrchestratorState ile)
    """
    logger.info("[REPORT_V2] Building network graph...")

    llm_chat = llm.get_chat() if llm else None

    # Sub-agent'ları compile et
    classify_agent = build_classify_agent(llm=llm_chat)
    sql_agent = build_sql_agent(node_kit=node_kit)
    analysis_agent = build_analysis_agent(llm=llm_chat)
    response_agent = build_response_agent(llm=llm_chat)

    logger.info("[REPORT_V2] Sub-agents compiled: classify, sql, analysis, response")

    # Orchestrator graph
    graph = StateGraph(OrchestratorState)

    # Bridge nodes (orchestrator ↔ agent state mapping)
    graph.add_node("classify_agent", make_classify_bridge(classify_agent))
    graph.add_node("sql_agent", make_sql_bridge(sql_agent))
    graph.add_node("analysis_agent", make_analysis_bridge(analysis_agent))
    graph.add_node("response_agent", make_response_bridge(response_agent))
    graph.add_node("rollback", rollback_bridge_node)

    # Network edges
    graph.add_edge(START, "classify_agent")

    graph.add_conditional_edges(
        "classify_agent",
        route_after_classify,
        {
            "sql_agent": "sql_agent",
            "analysis_agent": "analysis_agent",  # visualize_direct
            "rollback": "rollback",
            "response_agent": "response_agent",
        },
    )

    graph.add_conditional_edges(
        "sql_agent",
        route_after_sql,
        {
            "analysis_agent": "analysis_agent",
            "response_agent": "response_agent",
        },
    )

    graph.add_conditional_edges(
        "analysis_agent",
        route_after_analysis,
        {"response_agent": "response_agent"},
    )

    graph.add_edge("rollback", "response_agent")
    graph.add_edge("response_agent", END)

    # Compile
    if checkpointer is None:
        checkpointer = MemorySaver()

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("[REPORT_V2] Graph compiled successfully ✓")
    return compiled
```

**Step 4: Test + commit**
```bash
pytest tests/graphs/report_v2/test_orchestrator_graph.py -v
git add src/graphs/report_v2/graph.py tests/graphs/report_v2/test_orchestrator_graph.py
git commit -m "feat: add orchestrator network graph with bridge nodes"
```

---

## Task 8: Configuration

**Files:**
- Create: `src/graphs/report_v2/configuration.py`

**Step 1: `configuration.py` yaz**

`src/graphs/report_v2/configuration.py`:
```python
"""Report V2 Configuration — runtime-switchable config schema."""

from typing import Optional, List, Dict, Any
from pydantic import Field
from src.graphs.generic_text2sql.assistant_configuration import GenericSQLAssistantConfiguration


class ReportV2Configuration(GenericSQLAssistantConfiguration):
    """Report V2 unified configuration. GenericSQLAssistantConfiguration'ı extend eder."""

    enable_hitl: bool = Field(default=True)
    enable_llm_conversation: bool = Field(default=True)
    enable_business_insights: bool = Field(default=True)
    enable_llm_interpretation: bool = Field(default=True)
    enable_natural_response: bool = Field(default=True)
    enable_semantic_cache: bool = Field(default=True)
```

**Step 2: Commit**
```bash
git add src/graphs/report_v2/configuration.py
git commit -m "feat: add ReportV2Configuration"
```

---

## Task 9: Entrypoint Güncelle

**Files:**
- Modify: `src/graphs/graph_entrypoints.py`
- Modify: `src/graphs/graph_repository.py` (varsa report graph kaydı)

**Step 1: `graph_repository.py`'de report graph kaydını bul**

```bash
grep -n "report" src/graphs/graph_repository.py
```

**Step 2: V2 graph'ı register et**

`graph_entrypoints.py`'ye import ekle:
```python
from src.graphs.report_v2.graph import build_report_v2_graph
```

`graph_repository.py`'de `"report_v2"` key'iyle register et (mevcut `"report"` key'ini bozmadan).

**Step 3: Commit**
```bash
git add src/graphs/graph_entrypoints.py src/graphs/graph_repository.py
git commit -m "feat: register report_v2 graph in entrypoints"
```

---

## Task 10: Tüm testleri çalıştır

```bash
pytest tests/graphs/report_v2/ -v --tb=short
```

Expected: Tüm testler PASSED.

```bash
git add .
git commit -m "feat: complete report_v2 network architecture with full state separation"
```

---

## Sonraki Adımlar (Kapsam Dışı — Ayrı PR)

1. **LLM injection**: `build_*_agent()` factory'lerine LLM-powered node'lar ekle (mevcut `conversation_manager.py`, `business_context_tracker.py` vb. kullanarak)
2. **Conversation history management**: SQL başarılıysa `conversation_history`'yi güncelle (mevcut `update_conversation_history_node` mantığı)
3. **Visualization rendering**: `analysis_result.viz_decision.needs_graph == True` ise `data_visualization` subgraph'ı çağır
4. **Old report graph deprecate**: `report/graph.py` ve `report/nodes.py` kaldır, `report/state.py` sadece `ActiveQueryContext` vb. shared types için bırak
5. **E2E integration test**: Gerçek LLM + DB ile uçtan uca test

---

## Önemli Notlar

- `src/graphs/report/` altındaki business logic dosyaları bu plan boyunca **değiştirilmez**
- `report_v2/` eski `report/` ile paralel çalışır — geçiş kademeli
- Her sub-agent `tests/` altında bağımsız test edilebilir (LLM mock)
- Bridge node pattern, LangGraph'ın native `input`/`output` schema özelliğine göre daha explicit ama daha kontrol edilebilir
