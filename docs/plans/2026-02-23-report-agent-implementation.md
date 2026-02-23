# Report Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `src/graphs/report_agent/` altında sıfırdan, sade ve native LangGraph patterns kullanan yeni bir report agent inşa etmek.

**Architecture:** Shared-state subgraph pattern. Ana graph + Text2SQL subgraph + Visualization subgraph aynı `ReportState`'i paylaşır. AskUser için `interrupt()` + `Command(resume=...)` native HITL. Max 2 LLM çağrısı/tur.

**Tech Stack:** LangGraph, LangChain, ChatOpenAI, Pydantic v2, pyodbc, Python 3.12

---

## Yazılım Prensipleri

Her dosya yazılırken aşağıdaki prensiplere uyulacak:

**SOLID:**
- **S** — Single Responsibility: Her node tek bir iş yapar (plan, generate, execute ayrı)
- **O** — Open/Closed: Node factory pattern ile genişletilebilir, mevcut kodu değiştirmeden
- **L** — Liskov: State TypedDict hiyerarşisi bozulmaz, subgraph parent state ile uyumlu
- **I** — Interface Segregation: Her subgraph sadece kendi kullandığı state field'larına dokunur
- **D** — Dependency Inversion: Node'lar somut sınıfa değil LLM interface'e bağlıdır

**KISS:**
- Tek LLM çağrısı yeterli olan yerde iki çağrı yapma
- Pure Python çözebiliyorsan LLM kullanma
- Conditional edge yoksa normal edge yaz
- Helper class/abstraction sadece 3+ yerde kullanılıyorsa yaz

**YAGNI:**
- Caching sistemi kurma (henüz gerek yok)
- Business rules vector store kurma (JSON yeterli)
- Retry sayısını configurable yapma (sabit 2)

---

## Genel Kural: Her Subagent İçin Önce Plan

> **ÖNEMLİ:** Her subagent (Text2SQL, Visualization) için implementasyona başlamadan önce:
> 1. Subagent'ın node yapısı, prompt tasarımı ve state akışı için ayrı bir plan belgesi oluştur
> 2. Kullanıcıya sun ve onay al
> 3. Onay sonrası implementasyona geç

---

## Referans Dosyalar

Yeni kod yazarken bunlara **bak, mantığı anla, ama kopyalama:**
- `src/graphs/generic_text2sql/nodekit.py` — DB bağlantı pattern'i (pyodbc, async executor)
- `src/graphs/generic_text2sql/prompts.py` — SQL prompt örnekleri (Türkçe domain)
- `src/graphs/data_visualization/nodes/` — Visualization node mantığı
- `src/graphs/generic_text2sql/business_rules.json` — Business rules formatı

---

## Task 1: Klasör Yapısı

**Files:**
- Create: `src/graphs/report_agent/__init__.py`
- Create: `src/graphs/report_agent/subagents/__init__.py`
- Create: `src/graphs/report_agent/subagents/text2sql/__init__.py`
- Create: `src/graphs/report_agent/subagents/visualization/__init__.py`

**Step 1: Klasörleri oluştur**

```bash
mkdir -p src/graphs/report_agent/subagents/text2sql
mkdir -p src/graphs/report_agent/subagents/visualization
```

**Step 2: `__init__.py` dosyalarını oluştur**

`src/graphs/report_agent/__init__.py`:
```python
from .graph import build_report_agent_graph

__all__ = ["build_report_agent_graph"]
```

`src/graphs/report_agent/subagents/__init__.py`:
```python
```

`src/graphs/report_agent/subagents/text2sql/__init__.py`:
```python
from .graph import build_text2sql_graph

__all__ = ["build_text2sql_graph"]
```

`src/graphs/report_agent/subagents/visualization/__init__.py`:
```python
from .graph import build_visualization_graph

__all__ = ["build_visualization_graph"]
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/
git commit -m "feat(report-agent): scaffold folder structure"
```

---

## Task 2: ReportState

**File:** `src/graphs/report_agent/state.py`

**Prensipler:**
- S: State sadece veri taşır, iş mantığı içermez
- I: Her subgraph sadece kendi alanlarını okur/yazar
- KISS: 15 field, fazlası yok

```python
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ReportState(TypedDict):
    # Core
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    session_id: Optional[str]

    # Intent Classification (tek LLM çağrısı)
    intent_type: Optional[str]         # NEW_QUERY | MODIFY_QUERY | USE_RESULT
    query_type: Optional[str]          # SINGLE | RANKING | COMPARISON | TIME_SERIES_COMPARISON
    intent_confidence: Optional[float]
    use_result_type: Optional[str]     # "new_query" | "revisualize"

    # Conversation Context (MODIFY ve USE_RESULT için)
    active_sql: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]
    active_filters: Optional[List[Dict[str, Any]]]

    # Text2SQL I/O (subgraph shared fields)
    sql_queries: Optional[List[str]]
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]

    # Visualization
    visualization_output: Optional[Dict[str, Any]]

    # Response
    final_response: Optional[str]


def create_initial_state() -> ReportState:
    return ReportState(
        messages=[],
        user_query="",
        session_id=None,
        intent_type=None,
        query_type=None,
        intent_confidence=None,
        use_result_type=None,
        active_sql=None,
        active_results=None,
        active_filters=None,
        sql_queries=None,
        results=None,
        error=None,
        visualization_output=None,
        final_response=None,
    )
```

**Commit:**
```bash
git add src/graphs/report_agent/state.py
git commit -m "feat(report-agent): add lean ReportState (15 fields)"
```

---

## Task 3: Ana Agent Promptları

**File:** `src/graphs/report_agent/prompts.py`

**Prensipler:**
- S: Her Pydantic model tek bir node'un output'unu temsil eder
- KISS: Prompt içinde tek sorumluluk — ya classify, ya modify, ya extract

```python
from typing import Literal, Optional
from pydantic import BaseModel, field_validator


class IntentClassificationResult(BaseModel):
    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT"]
    query_type: Literal["SINGLE", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    use_result_type: Optional[Literal["new_query", "revisualize"]] = None
    modification_action: Optional[str] = None
    modification_target: Optional[str] = None
    modification_value: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v


class SqlModificationResult(BaseModel):
    modified_sql: str
    explanation: str


class EntityExtractionResult(BaseModel):
    entity_name: str
    entity_type: str
    new_query_seed: str


INTENT_CLASSIFIER_PROMPT = """Sen bir rapor asistanısın. Kullanıcının mesajını analiz edip intent'ini belirle.

## KONUŞMA GEÇMİŞİ
{conversation_history}

## KULLANICI MESAJI
{user_query}

## MEVCUT SORGU DURUMU
- Aktif SQL var mı: {has_active_sql}
- Son sonuç satır sayısı: {result_count}

## KURALLAR

**intent_type:**
- NEW_QUERY: Kullanıcı yeni bir sorgu istiyor
- MODIFY_QUERY: Önceki sorguyu değiştirmek istiyor → Aktif SQL olmadan seçme
- USE_RESULT: Önceki SONUÇLARI kullanmak istiyor
  → use_result_type="new_query": Sonuçtaki entity için yeni sorgu
  → use_result_type="revisualize": Aynı veriyi farklı göster

**query_type:**
- SINGLE: Tek metrik veya liste
- RANKING: Sıralama / top-N
- COMPARISON: İki grubun karşılaştırması
- TIME_SERIES_COMPARISON: Dönemler arası karşılaştırma

**confidence:** 0.0-1.0. 0.70 altında kullanıcıya sor.
"""

SQL_MODIFIER_PROMPT = """Mevcut SQL sorgusunu kullanıcının isteğine göre değiştir.

## MEVCUT SQL
{active_sql}

## AKTİF FİLTRELER
{active_filters}

## KULLANICI İSTEĞİ
{modification_request}

## KOLON BİLGİLERİ
{column_metadata}

## KURALLAR
- Sadece istenilen değişikliği yap, geri kalanı koru
- Geçerli T-SQL üret
"""

ENTITY_EXTRACTOR_PROMPT = """Kullanıcı önceki sorgu sonuçlarından bir entity seçmek istiyor.

## ÖNCEKİ SONUÇLAR (ilk 5 satır)
{active_results}

## KULLANICI İSTEĞİ
{user_query}

## GÖREV
- entity_name: Seçilen değer
- entity_type: product | branch | customer | category | period
- new_query_seed: Entity için yeni doğal dil sorgu
"""
```

**Commit:**
```bash
git add src/graphs/report_agent/prompts.py
git commit -m "feat(report-agent): add 3 Pydantic models and prompts"
```

---

## Task 4: Text2SQL Subagent — ÖNCE PLAN, SONRA UYGULAMA

> **DUR.** Bu task'a başlamadan önce:
>
> 1. Text2SQL subagent için ayrı bir plan belgesi oluştur:
>    `docs/plans/2026-02-23-text2sql-subagent-plan.md`
> 2. Planı kullanıcıya sun — node yapısı, prompt tasarımı, state akışı
> 3. Kullanıcı onayladıktan sonra implementasyona geç

**Plan belgesi şunları kapsamalı:**
- Kaç node olacak ve her birinin tek sorumluluğu ne
- Her node'un input/output field'ları (ReportState'den hangilerini okur/yazar)
- Hangi node'lar LLM kullanır, hangisi pure Python
- SQL error retry mekanizması nasıl çalışacak
- Pydantic model tasarımları
- Graph routing mantığı

**Onay sonrası implementasyon:**
- `src/graphs/report_agent/subagents/text2sql/state.py`
- `src/graphs/report_agent/subagents/text2sql/prompts.py`
- `src/graphs/report_agent/subagents/text2sql/nodes.py`
- `src/graphs/report_agent/subagents/text2sql/graph.py`

**Commit:**
```bash
git add src/graphs/report_agent/subagents/text2sql/
git commit -m "feat(report-agent/text2sql): implement text2sql subagent"
```

---

## Task 5: Visualization Subagent — ÖNCE PLAN, SONRA UYGULAMA

> **DUR.** Bu task'a başlamadan önce:
>
> 1. Visualization subagent için ayrı bir plan belgesi oluştur:
>    `docs/plans/2026-02-23-visualization-subagent-plan.md`
> 2. Planı kullanıcıya sun — node yapısı, prompt tasarımı, chart type kararı
> 3. Kullanıcı onayladıktan sonra implementasyona geç

**Plan belgesi şunları kapsamalı:**
- Kaç node, hangi sırada
- Hangi node'lar LLM kullanır (mümkün olan en az)
- Chart type listesi ve seçim kriterleri
- Plotly output formatı (JSON + HTML snippet)
- ReportState'den hangi field'ları okur/yazar

**Onay sonrası implementasyon:**
- `src/graphs/report_agent/subagents/visualization/prompts.py`
- `src/graphs/report_agent/subagents/visualization/nodes.py`
- `src/graphs/report_agent/subagents/visualization/graph.py`

**Commit:**
```bash
git add src/graphs/report_agent/subagents/visualization/
git commit -m "feat(report-agent/visualization): implement visualization subagent"
```

---

## Task 6: Ana Agent Nodes

**File:** `src/graphs/report_agent/nodes.py`

**Prensipler:**
- S: Her node fonksiyonu tek iş yapar
- D: Node'lar llm parametresi alır, somut sınıfa bağlı değil
- KISS: interrupt() doğrudan node içinde, ayrı ask_user node yok

```python
import json
import logging
from typing import Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from src.graphs.report_agent.prompts import (
    EntityExtractionResult,
    IntentClassificationResult,
    SqlModificationResult,
    ENTITY_EXTRACTOR_PROMPT,
    INTENT_CLASSIFIER_PROMPT,
    SQL_MODIFIER_PROMPT,
)

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.70


def create_classify_intent_node(llm) -> Callable:
    """Intent Classifier: user_query → intent_type + query_type.
    Confidence < 0.70 ise interrupt() ile kullanıcıya sorar.
    """
    structured_llm = llm.with_structured_output(IntentClassificationResult)

    async def classify_intent_node(state: dict) -> dict:
        user_query = state.get("user_query", "")
        active_sql = state.get("active_sql")
        active_results = state.get("active_results") or []
        messages = state.get("messages", [])

        history_parts = []
        for msg in messages[-4:]:
            if isinstance(msg, HumanMessage):
                history_parts.append(f"Kullanıcı: {msg.content[:100]}")
            elif isinstance(msg, AIMessage):
                history_parts.append(f"Asistan: {msg.content[:100]}")

        prompt = INTENT_CLASSIFIER_PROMPT.format(
            user_query=user_query,
            conversation_history="\n".join(history_parts) or "İlk mesaj",
            has_active_sql="Evet" if active_sql else "Hayır",
            result_count=len(active_results),
        )

        result: IntentClassificationResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[CLASSIFY] {result.intent_type}/{result.query_type} conf={result.confidence:.2f}")

        if result.confidence < CONFIDENCE_THRESHOLD:
            options = ["Yeni sorgu yap"]
            if active_sql:
                options.append("Mevcut sorguyu değiştir")
            options.append("Sonuçları farklı göster")

            answer = interrupt({
                "type": "confirmation",
                "question": f"'{user_query}' için ne yapmamı istiyorsunuz?",
                "options": options,
            })
            result = _resolve_intent_from_answer(result, answer)

        return {
            "intent_type": result.intent_type,
            "query_type": result.query_type,
            "intent_confidence": result.confidence,
            "use_result_type": result.use_result_type,
            "messages": [HumanMessage(content=user_query)],
        }

    return classify_intent_node


def _resolve_intent_from_answer(
    result: IntentClassificationResult, answer: str
) -> IntentClassificationResult:
    if "Yeni sorgu" in answer:
        result.intent_type = "NEW_QUERY"
    elif "değiştir" in answer:
        result.intent_type = "MODIFY_QUERY"
    elif "farklı göster" in answer:
        result.intent_type = "USE_RESULT"
        result.use_result_type = "revisualize"
    result.confidence = 1.0
    return result


def create_modify_sql_node(llm, column_metadata: dict) -> Callable:
    """SQL Modifier: active_sql + intent → modified_sql.
    Text2SQL subgraph bypass eder, doğrudan executor'a gider.
    """
    structured_llm = llm.with_structured_output(SqlModificationResult)

    async def modify_sql_node(state: dict) -> dict:
        active_sql = state.get("active_sql", "")
        if not active_sql:
            logger.warning("[MODIFY_SQL] No active SQL, fallback to NEW_QUERY")
            return {"intent_type": "NEW_QUERY"}

        prompt = SQL_MODIFIER_PROMPT.format(
            active_sql=active_sql,
            active_filters=json.dumps(state.get("active_filters") or [], ensure_ascii=False),
            modification_request=state.get("user_query", ""),
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
        )

        result: SqlModificationResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[MODIFY_SQL] → {result.modified_sql[:120]}")
        return {"sql_queries": [result.modified_sql]}

    return modify_sql_node


def create_extract_entity_node(llm) -> Callable:
    """Entity Extractor: USE_RESULT(A) → yeni user_query seed'i."""
    structured_llm = llm.with_structured_output(EntityExtractionResult)

    async def extract_entity_node(state: dict) -> dict:
        active_results = state.get("active_results") or []
        if not active_results:
            logger.warning("[EXTRACT_ENTITY] No results, fallback to NEW_QUERY")
            return {"intent_type": "NEW_QUERY"}

        prompt = ENTITY_EXTRACTOR_PROMPT.format(
            active_results=json.dumps(active_results[:5], ensure_ascii=False, indent=2),
            user_query=state.get("user_query", ""),
        )

        result: EntityExtractionResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[EXTRACT_ENTITY] {result.entity_name} ({result.entity_type})")
        return {"user_query": result.new_query_seed}

    return extract_entity_node


async def build_response_node(state: dict) -> dict:
    """Final Response Builder: pure Python, LLM yok."""
    error = state.get("error")
    results = state.get("results") or []
    viz = state.get("visualization_output") or {}

    if error:
        response = f"Sorgu hatası: {error}"
    elif not results:
        response = "Bu sorgu için sonuç bulunamadı."
    elif viz.get("needs_graph") and viz.get("plotly_html_snippet"):
        response = viz["plotly_html_snippet"]
    else:
        response = f"{len(results)} sonuç bulundu."

    return {
        "final_response": response,
        "messages": [AIMessage(content=response)],
    }
```

**Commit:**
```bash
git add src/graphs/report_agent/nodes.py
git commit -m "feat(report-agent): add 4 main nodes with interrupt() HITL"
```

---

## Task 7: Ana Agent Graph

**File:** `src/graphs/report_agent/graph.py`

**Prensipler:**
- S: Graph sadece node'ları wire eder, iş mantığı node'larda
- O: Yeni intent type eklemek için sadece router ve yeni node
- KISS: 6 node, 1 conditional edge, ~80 satır

```python
"""
Report Agent — Ana Graph

START → classify_intent → [intent_router]
  ├── NEW_QUERY      → text2sql → visualization → build_response → END
  ├── MODIFY_QUERY   → modify_sql → text2sql → visualization → build_response → END
  ├── USE_RESULT(A)  → extract_entity → text2sql → visualization → build_response → END
  └── USE_RESULT(B)  → visualization → build_response → END
"""
import logging
from typing import Any, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.nodes import (
    build_response_node,
    create_classify_intent_node,
    create_extract_entity_node,
    create_modify_sql_node,
)
from src.graphs.report_agent.state import ReportState
from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph
from src.graphs.report_agent.subagents.visualization.graph import build_visualization_graph

logger = logging.getLogger(__name__)


def _intent_router(state: dict) -> str:
    """Pure function — test edilebilir routing."""
    intent = state.get("intent_type", "NEW_QUERY")
    if intent == "MODIFY_QUERY":
        return "modify_sql"
    if intent == "USE_RESULT":
        return "visualization" if state.get("use_result_type") == "revisualize" else "extract_entity"
    return "text2sql"  # NEW_QUERY + fallback


def build_report_agent_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    business_rules: Dict[str, Any],
    connection_string: str,
    checkpointer=None,
):
    text2sql = build_text2sql_graph(llm, table_name, column_metadata, business_rules, connection_string)
    visualization = build_visualization_graph(llm)

    graph = StateGraph(ReportState)

    graph.add_node("classify_intent", create_classify_intent_node(llm))
    graph.add_node("modify_sql", create_modify_sql_node(llm, column_metadata))
    graph.add_node("extract_entity", create_extract_entity_node(llm))
    graph.add_node("text2sql", text2sql)
    graph.add_node("visualization", visualization)
    graph.add_node("build_response", build_response_node)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        _intent_router,
        {"text2sql": "text2sql", "modify_sql": "modify_sql",
         "extract_entity": "extract_entity", "visualization": "visualization"},
    )
    graph.add_edge("modify_sql", "text2sql")
    graph.add_edge("extract_entity", "text2sql")
    graph.add_edge("text2sql", "visualization")
    graph.add_edge("visualization", "build_response")
    graph.add_edge("build_response", END)

    compiled = graph.compile(checkpointer=checkpointer or MemorySaver())
    logger.info("[REPORT_AGENT] Built: 6 nodes, max 2 LLM calls/turn")
    return compiled
```

**Commit:**
```bash
git add src/graphs/report_agent/graph.py
git commit -m "feat(report-agent): add main orchestrator graph (~80 lines)"
```

---

## Özet

| Task | Dosya | Onay Gerekli |
|------|-------|--------------|
| 1 | Folder scaffold | — |
| 2 | `state.py` | — |
| 3 | `prompts.py` | — |
| 4 | Text2SQL subagent | **EVET — önce plan sun** |
| 5 | Visualization subagent | **EVET — önce plan sun** |
| 6 | `nodes.py` | — |
| 7 | `graph.py` | — |

**Mevcut `src/graphs/report/` silinmesi** — tüm sistem çalıştıktan sonra ayrı task olarak yapılacak.
