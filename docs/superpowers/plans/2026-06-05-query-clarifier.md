# Query Clarifier Subgraph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bir `query_clarifier` subgraph'ı ekleyerek NEW_QUERY / MODIFY_QUERY / VAGUE_QUERY niyetlerini SQL üretimine göndermeden önce netlik analizi yapacak şekilde; eksiklik/belirsizlik tespitinde kullanıcıya optimize edilmiş sorgu önerisi sunacak.

**Architecture:** LangGraph subgraph pattern'i izlenerek `text2sql` ve `visualization_v2` ile aynı yapıda bağımsız bir subgraph oluşturulur. `classify_intent` sonrası `_intent_router` NEW_QUERY / MODIFY_QUERY / VAGUE_QUERY niyetlerini `query_clarifier`'a yönlendirir; subgraph içindeki tek node LLM ile netlik analizi yapar, gerekirse `interrupt()` ile kullanıcıya tek bir öneri sunar ve yanıta göre `user_query`'yi günceller ya da geçer. Subgraph çıktısı yeni `_clarifier_router` tarafından `text2sql` / `modify_sql` / `report_chat`'e yönlendirilir.

**Tech Stack:** Python 3.11+, LangGraph (StateGraph, interrupt, START, END), Pydantic v2 (BaseModel, field_validator), langchain-core, pytest + pytest-asyncio, unittest.mock

---

## Dosya Haritası

| Durum | Dosya | Sorumluluk |
|---|---|---|
| YENİ | `src/graphs/report_agent/subagents/query_clarifier/__init__.py` | Package export |
| YENİ | `src/graphs/report_agent/subagents/query_clarifier/state.py` | QueryClarifierState TypedDict |
| YENİ | `src/graphs/report_agent/subagents/query_clarifier/prompts.py` | LLM promptları + ClarityAnalysisResult modeli |
| YENİ | `src/graphs/report_agent/subagents/query_clarifier/nodes.py` | clarity_analyzer_node factory |
| YENİ | `src/graphs/report_agent/subagents/query_clarifier/graph.py` | Subgraph builder |
| YENİ | `tests/test_query_clarifier.py` | Node + router unit testleri |
| DEĞİŞİK | `src/graphs/report_agent/state.py` | `clarifier_decision`, `suggested_query` alanları |
| DEĞİŞİK | `src/graphs/report_agent/configuration.py` | `enable_query_clarifier`, `query_clarity_threshold` |
| DEĞİŞİK | `src/graphs/report_agent/graph.py` | Subgraph node, `_intent_router`, `_clarifier_router`, edge'ler |
| DEĞİŞİK | `src/graphs/report_agent/nodes.py` | `classify_intent_node` return dict'ine 2 alan ekle |
| DEĞİŞİK | `src/graphs/report_agent/prompts.py` | INTENT_CLASSIFIER_PROMPT VAGUE_QUERY bölümü |

---

## Task 1: State & Pydantic Modelleri

**Files:**
- Create: `src/graphs/report_agent/subagents/query_clarifier/state.py`
- Create: `src/graphs/report_agent/subagents/query_clarifier/prompts.py`

- [ ] **Step 1: `state.py` oluştur**

```python
# src/graphs/report_agent/subagents/query_clarifier/state.py
from typing import List, Optional, TypedDict


class QueryClarifierState(TypedDict, total=False):
    # Parent ReportState ile örtüşen anahtarlar (otomatik senkronize edilir)
    user_query: str
    intent_type: Optional[str]        # NEW_QUERY | MODIFY_QUERY | VAGUE_QUERY
    active_sql: Optional[str]         # MODIFY_QUERY bağlamı için

    # Subgraph çıktıları — parent ReportState'e yazılır
    clarifier_decision: Optional[str]  # PASS | CLARIFIED
    suggested_query: Optional[str]     # Kabul edilirse user_query'yi replace eder
```

- [ ] **Step 2: `prompts.py` oluştur — Pydantic modeller + LLM promptları**

```python
# src/graphs/report_agent/subagents/query_clarifier/prompts.py
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator


class ClarityIssue(BaseModel):
    type: Literal[
        "missing_date_filter",
        "ambiguous_metric",
        "missing_grouping",
        "ambiguous_filter_value",
        "large_result_warning",
    ]
    description: str
    severity: Literal["low", "medium", "high"]


class ClarityAnalysisResult(BaseModel):
    clarity_score: float
    issues: List[ClarityIssue]
    suggested_query: Optional[str] = None
    suggestion_message: Optional[str] = None
    can_suggest: bool

    @field_validator("clarity_score")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


CLARITY_ANALYZER_PROMPT = """Sen bir Türkçe ERP rapor sorgu analizcisisin.

Kullanıcının raporlama sorgusunu analiz et ve netlik skoru (0.0–1.0) hesapla.
Eksiklik/belirsizlik varsa tespit et ve optimize edilmiş bir versiyon öner.

BAĞLAM:
- Niyet tipi: {intent_type}
- Aktif SQL var mı: {has_active_sql}
- Aktif SQL özeti (MODIFY_QUERY için): {active_sql_summary}

KONTROL LİSTESİ:
□ Tarih/dönem filtresi belirtilmiş mi? (DocumentDate, bu ay, geçen hafta vb.)
□ Metrik/ölçüm net mi? (RowAmount=tutar, Quantity=adet, Count=kayıt sayısı)
□ Gruplama/boyut belirtilmiş mi? (BranchName, CategoryName, ProductName vb.)
□ Filtre değerleri spesifik mi? (belirsiz terimler yerine tam değerler)
□ Büyük veri riski var mı? (limit/sıralama gerekliyse belirtilmiş mi)

NETLIK SKORU REHBERİ:
- 0.85–1.0 → Net sorgu — tarih + metrik + gruplama hepsi açık → can_suggest: false
- 0.65–0.84 → Küçük eksiklik — genellikle yeterince net → can_suggest: false
- 0.40–0.64 → Birden fazla eksiklik → can_suggest: true, öneri üret
- <0.40     → Çok belirsiz (VAGUE_QUERY bu range'i zaten yakalar, beklenmez)

MEVCUT VERİTABANI KOLONLARI:
RowAmount, Quantity, DocumentDate, BranchName, ProductName,
CategoryName, BranchCityName, CustomerName

KULLANICI SORGUSU: {user_query}

Eğer öneri üretebiliyorsan (can_suggest=true):
- suggested_query: Türkçe, doğal dilde optimize edilmiş sorgu metni
- suggestion_message: "Şunu mu sormak istediniz?\\n\\n📊 <suggested_query>\\n\\nEvet ise onaylayın, değilse 'hayır' yazın."

Eğer sorgu netsek veya öneri üretemiyorsan:
- can_suggest: false
- suggested_query: null
- suggestion_message: null"""


VAGUE_CLARITY_PROMPT = """Sen bir Türkçe ERP rapor yorumlayıcısısın.

Kullanıcının sorgusu çok genel — spesifik bir SQL sorgusuna doğrudan dönüştürülemez.
Bu sorguyu en makul ERP raporu yorumuyla somutlaştır.

ÖRNEKLER:
- "satışları göster" → "Bu ayki toplam RowAmount, CategoryName bazında gruplandırılmış, büyükten küçüğe"
- "ne sattık" → "Son 30 günde en çok satan ilk 10 ProductName (Quantity bazında)"
- "şubelerin durumu" → "Bu ay her BranchName için toplam RowAmount"
- "kategorilere bak" → "Bu ay CategoryName bazında toplam RowAmount, büyükten küçüğe"

MEVCUT VERİTABANI KOLONLARI:
RowAmount, Quantity, DocumentDate, BranchName, ProductName,
CategoryName, BranchCityName, CustomerName

KULLANICI SORGUSU: {user_query}

Her zaman döndür:
- clarity_score: 0.0
- can_suggest: true
- issues: en az bir ClarityIssue (genellikle missing_date_filter + missing_grouping)
- suggested_query: spesifik, doğal Türkçe
- suggestion_message: "Şunu mu sormak istediniz?\\n\\n📊 <suggested_query>\\n\\nEvet ise onaylayın, değilse 'hayır' yazın." """
```

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/query_clarifier/state.py \
        src/graphs/report_agent/subagents/query_clarifier/prompts.py
git commit -m "feat(query-clarifier): add state and pydantic models"
```

---

## Task 2: Node + Testler

**Files:**
- Create: `src/graphs/report_agent/subagents/query_clarifier/nodes.py`
- Test: `tests/test_query_clarifier.py`

- [ ] **Step 1: Testleri yaz (kırmızı faz)**

```python
# tests/test_query_clarifier.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.graphs.report_agent.subagents.query_clarifier.prompts import (
    ClarityAnalysisResult,
    ClarityIssue,
)


def _make_llm(result: ClarityAnalysisResult) -> MagicMock:
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=result)
    return mock_llm


def _high_clarity_result() -> ClarityAnalysisResult:
    return ClarityAnalysisResult(
        clarity_score=0.90,
        issues=[],
        suggested_query=None,
        suggestion_message=None,
        can_suggest=False,
    )


def _low_clarity_result() -> ClarityAnalysisResult:
    return ClarityAnalysisResult(
        clarity_score=0.50,
        issues=[
            ClarityIssue(
                type="missing_date_filter",
                description="Tarih filtresi yok",
                severity="high",
            )
        ],
        suggested_query="Bu ayki CategoryName bazında toplam RowAmount",
        suggestion_message=(
            "Şunu mu sormak istediniz?\n\n"
            "📊 Bu ayki CategoryName bazında toplam RowAmount\n\n"
            "Evet ise onaylayın, değilse 'hayır' yazın."
        ),
        can_suggest=True,
    )


def _vague_result() -> ClarityAnalysisResult:
    return ClarityAnalysisResult(
        clarity_score=0.0,
        issues=[
            ClarityIssue(
                type="missing_date_filter",
                description="Tarih filtresi yok",
                severity="high",
            ),
            ClarityIssue(
                type="missing_grouping",
                description="Gruplama belirtilmemiş",
                severity="high",
            ),
        ],
        suggested_query="Bu ayki CategoryName bazında toplam RowAmount, büyükten küçüğe",
        suggestion_message=(
            "Şunu mu sormak istediniz?\n\n"
            "📊 Bu ayki CategoryName bazında toplam RowAmount, büyükten küçüğe\n\n"
            "Evet ise onaylayın, değilse 'hayır' yazın."
        ),
        can_suggest=True,
    )


# --- Tests ---


@pytest.mark.asyncio
async def test_clarifier_disabled_returns_pass():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        MagicMock(), clarity_threshold=0.65, enable_clarifier=False
    )
    result = await node({"user_query": "satışları göster", "intent_type": "NEW_QUERY"})
    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_high_clarity_score_passes_without_interrupt():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_high_clarity_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )
    result = await node(
        {
            "user_query": "Ocak 2025 BranchName bazında RowAmount toplamı",
            "intent_type": "NEW_QUERY",
        }
    )
    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_low_clarity_user_accepts_updates_query():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_low_clarity_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt",
        return_value="Evet, devam et",
    ):
        result = await node({"user_query": "kategorilere bak", "intent_type": "NEW_QUERY"})

    assert result["clarifier_decision"] == "CLARIFIED"
    assert result["user_query"] == "Bu ayki CategoryName bazında toplam RowAmount"
    assert result["suggested_query"] == "Bu ayki CategoryName bazında toplam RowAmount"


@pytest.mark.asyncio
async def test_low_clarity_user_rejects_returns_pass():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_low_clarity_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt",
        return_value="Hayır",
    ):
        result = await node({"user_query": "kategorilere bak", "intent_type": "NEW_QUERY"})

    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_vague_query_always_triggers_suggestion():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_vague_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt",
        return_value="Evet, devam et",
    ) as mock_interrupt:
        result = await node({"user_query": "satışlar", "intent_type": "VAGUE_QUERY"})

    mock_interrupt.assert_called_once()
    assert result["clarifier_decision"] == "CLARIFIED"


@pytest.mark.asyncio
async def test_vague_query_user_rejects_returns_pass():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_vague_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt",
        return_value="hayır",
    ):
        result = await node({"user_query": "satışlar", "intent_type": "VAGUE_QUERY"})

    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_llm_failure_returns_pass_silently():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(
        side_effect=Exception("LLM zaman aşımı")
    )

    node = create_clarity_analyzer_node(
        mock_llm, clarity_threshold=0.65, enable_clarifier=True
    )
    result = await node({"user_query": "test", "intent_type": "NEW_QUERY"})
    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_no_suggestion_available_skips_interrupt():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    # Low score but can_suggest=False (no suggestion generated)
    result_no_suggest = ClarityAnalysisResult(
        clarity_score=0.50,
        issues=[
            ClarityIssue(type="ambiguous_metric", description="Metrik belirsiz", severity="medium")
        ],
        suggested_query=None,
        suggestion_message=None,
        can_suggest=False,
    )

    node = create_clarity_analyzer_node(
        _make_llm(result_no_suggest),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt"
    ) as mock_interrupt:
        result = await node({"user_query": "satış ne oldu", "intent_type": "NEW_QUERY"})

    mock_interrupt.assert_not_called()
    assert result == {"clarifier_decision": "PASS"}


# --- Router tests ---


def test_clarifier_router_new_query_pass():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "NEW_QUERY", "clarifier_decision": "PASS"}) == "text2sql"


def test_clarifier_router_new_query_clarified():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "NEW_QUERY", "clarifier_decision": "CLARIFIED"}) == "text2sql"


def test_clarifier_router_modify_query():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "MODIFY_QUERY", "clarifier_decision": "PASS"}) == "modify_sql"
    assert _clarifier_router({"intent_type": "MODIFY_QUERY", "clarifier_decision": "CLARIFIED"}) == "modify_sql"


def test_clarifier_router_vague_pass_goes_to_report_chat():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "VAGUE_QUERY", "clarifier_decision": "PASS"}) == "report_chat"


def test_clarifier_router_vague_clarified_goes_to_text2sql():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "VAGUE_QUERY", "clarifier_decision": "CLARIFIED"}) == "text2sql"
```

- [ ] **Step 2: Testleri çalıştır — başarısız olduklarını doğrula**

```bash
pytest tests/test_query_clarifier.py -v
```

Beklenen: `ImportError: cannot import name 'create_clarity_analyzer_node'` (henüz yazılmadı)

- [ ] **Step 3: `nodes.py` implementasyonu**

```python
# src/graphs/report_agent/subagents/query_clarifier/nodes.py
import logging
import re
from typing import Optional

from langgraph.types import interrupt

from .prompts import (
    CLARITY_ANALYZER_PROMPT,
    VAGUE_CLARITY_PROMPT,
    ClarityAnalysisResult,
)

logger = logging.getLogger(__name__)


def _extract_sql_summary(sql: str) -> str:
    """WHERE ve GROUP BY kısımlarını çıkararak MODIFY_QUERY bağlamı oluşturur."""
    sql_upper = sql.upper()
    parts = []

    where_match = re.search(r"\bWHERE\b(.+?)(?:\bGROUP BY\b|\bORDER BY\b|\bLIMIT\b|$)", sql, re.IGNORECASE | re.DOTALL)
    if where_match:
        parts.append(f"WHERE: {where_match.group(1).strip()[:200]}")

    groupby_match = re.search(r"\bGROUP BY\b(.+?)(?:\bORDER BY\b|\bLIMIT\b|$)", sql, re.IGNORECASE | re.DOTALL)
    if groupby_match:
        parts.append(f"GROUP BY: {groupby_match.group(1).strip()[:100]}")

    return "; ".join(parts) if parts else "—"


def _is_accepted(answer: str) -> bool:
    return answer.lower().strip() in ("evet", "evet, devam et", "e", "yes", "y", "1", "ok", "tamam")


def create_clarity_analyzer_node(llm, clarity_threshold: float = 0.65, enable_clarifier: bool = True):
    """Factory: returns async clarity_analyzer_node with dependencies baked in."""

    structured_llm = llm.with_structured_output(ClarityAnalysisResult)

    async def clarity_analyzer_node(state: dict) -> dict:
        if not enable_clarifier:
            return {"clarifier_decision": "PASS"}

        user_query: str = state.get("user_query", "")
        intent_type: str = state.get("intent_type", "NEW_QUERY")
        active_sql: Optional[str] = state.get("active_sql")

        logger.info(f"[CLARITY_ANALYZER] intent={intent_type} query={user_query[:80]!r}")

        if intent_type == "VAGUE_QUERY":
            prompt = VAGUE_CLARITY_PROMPT.format(user_query=user_query)
        else:
            active_sql_summary = _extract_sql_summary(active_sql) if active_sql and intent_type == "MODIFY_QUERY" else "—"
            prompt = CLARITY_ANALYZER_PROMPT.format(
                intent_type=intent_type,
                has_active_sql="Evet" if active_sql else "Hayır",
                active_sql_summary=active_sql_summary,
                user_query=user_query,
            )

        try:
            result: ClarityAnalysisResult = await structured_llm.ainvoke(prompt)
        except Exception as exc:
            logger.warning(f"[CLARITY_ANALYZER] LLM failed ({exc!r}), returning PASS")
            return {"clarifier_decision": "PASS"}

        logger.info(f"[CLARITY_ANALYZER] score={result.clarity_score:.2f} can_suggest={result.can_suggest}")

        needs_clarification = result.can_suggest and result.suggested_query is not None and (
            intent_type == "VAGUE_QUERY"
            or result.clarity_score < clarity_threshold
        )

        if not needs_clarification:
            logger.info("[CLARITY_ANALYZER] Score sufficient or no suggestion — PASS")
            return {"clarifier_decision": "PASS"}

        answer = interrupt({
            "type": "clarification",
            "question": result.suggestion_message,
            "suggested_query": result.suggested_query,
            "options": ["Evet, devam et", "Hayır, orijinal sorguyu kullan"],
        })

        if _is_accepted(str(answer)):
            logger.info(f"[CLARITY_ANALYZER] User accepted → CLARIFIED: {result.suggested_query!r}")
            return {
                "user_query": result.suggested_query,
                "suggested_query": result.suggested_query,
                "clarifier_decision": "CLARIFIED",
            }
        else:
            logger.info("[CLARITY_ANALYZER] User rejected → PASS")
            return {"clarifier_decision": "PASS"}

    return clarity_analyzer_node
```

- [ ] **Step 4: Testleri çalıştır — geçtiklerini doğrula**

```bash
pytest tests/test_query_clarifier.py -v -k "not router"
```

Beklenen: 8 test PASS (router testleri Task 5 sonrasına kaldı)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/query_clarifier/nodes.py tests/test_query_clarifier.py
git commit -m "feat(query-clarifier): add clarity_analyzer_node with tests"
```

---

## Task 3: Subgraph Builder

**Files:**
- Create: `src/graphs/report_agent/subagents/query_clarifier/__init__.py`
- Create: `src/graphs/report_agent/subagents/query_clarifier/graph.py`

- [ ] **Step 1: `graph.py` oluştur**

```python
# src/graphs/report_agent/subagents/query_clarifier/graph.py
from langgraph.graph import END, START, StateGraph

from .nodes import create_clarity_analyzer_node
from .state import QueryClarifierState


def build_query_clarifier_graph(
    llm,
    clarity_threshold: float = 0.65,
    enable_clarifier: bool = True,
):
    """Compile and return the query_clarifier subgraph."""
    clarity_analyzer = create_clarity_analyzer_node(
        llm,
        clarity_threshold=clarity_threshold,
        enable_clarifier=enable_clarifier,
    )

    graph = StateGraph(QueryClarifierState)
    graph.add_node("clarity_analyzer", clarity_analyzer)
    graph.add_edge(START, "clarity_analyzer")
    graph.add_edge("clarity_analyzer", END)

    return graph.compile()
```

- [ ] **Step 2: `__init__.py` oluştur**

```python
# src/graphs/report_agent/subagents/query_clarifier/__init__.py
from .graph import build_query_clarifier_graph

__all__ = ["build_query_clarifier_graph"]
```

- [ ] **Step 3: Import testi**

```bash
python -c "from src.graphs.report_agent.subagents.query_clarifier import build_query_clarifier_graph; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/query_clarifier/__init__.py \
        src/graphs/report_agent/subagents/query_clarifier/graph.py
git commit -m "feat(query-clarifier): add subgraph builder"
```

---

## Task 4: Parent State & Configuration Güncellemesi

**Files:**
- Modify: `src/graphs/report_agent/state.py`
- Modify: `src/graphs/report_agent/configuration.py`

- [ ] **Step 1: `state.py`'ye 2 alan ekle**

`src/graphs/report_agent/state.py` dosyasını aç. `ReportState` TypedDict'in içinde `pre_built_sql` veya `_hitl_answered` satırlarından birine yakın aşağıdakileri ekle:

```python
    # Query Clarifier
    clarifier_decision: Optional[str]    # PASS | CLARIFIED
    suggested_query: Optional[str]       # Kabul edilirse user_query'yi replace eder
```

- [ ] **Step 2: `configuration.py`'ye 2 alan ekle**

`src/graphs/report_agent/configuration.py` dosyasını aç. `ReportAgentConfiguration` sınıfının sonuna ekle:

```python
    enable_query_clarifier: bool = Field(
        default=True,
        description="True ise query_clarifier subgraph devreye girer",
    )
    query_clarity_threshold: float = Field(
        default=0.65,
        description="Bu eşiğin altında LLM öneri üretirse kullanıcıya sunulur (0.0–1.0)",
    )
```

- [ ] **Step 3: Import testi**

```bash
python -c "
from src.graphs.report_agent.state import ReportState
from src.graphs.report_agent.configuration import ReportAgentConfiguration
cfg = ReportAgentConfiguration()
assert cfg.enable_query_clarifier is True
assert cfg.query_clarity_threshold == 0.65
print('OK')
"
```

Beklenen: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/state.py src/graphs/report_agent/configuration.py
git commit -m "feat(query-clarifier): add state fields and configuration options"
```

---

## Task 5: Parent Graph Entegrasyonu

**Files:**
- Modify: `src/graphs/report_agent/graph.py`

Bu task üç değişiklik içerir: (a) `_clarifier_router` fonksiyonu ekle, (b) `_intent_router` güncelle, (c) subgraph node'unu kaydet ve edge'leri güncelle.

- [ ] **Step 1: `_clarifier_router` fonksiyonunu `graph.py`'ye ekle**

`graph.py` dosyasında `_intent_router` fonksiyonunun hemen altına ekle:

```python
def _clarifier_router(state: dict) -> str:
    """query_clarifier çıktısına göre text2sql / modify_sql / report_chat seçer."""
    intent = state.get("intent_type", "NEW_QUERY")
    decision = state.get("clarifier_decision", "PASS")

    if intent == "MODIFY_QUERY":
        return "modify_sql"
    if intent == "VAGUE_QUERY" and decision == "PASS":
        return "report_chat"
    return "text2sql"  # NEW_QUERY her iki durumda da | VAGUE + CLARIFIED
```

- [ ] **Step 2: `_intent_router` fonksiyonunu güncelle**

`graph.py` içindeki mevcut `_intent_router` fonksiyonunu şununla değiştir:

```python
def _intent_router(state: dict) -> str:
    """Pure function — test edilebilir routing."""
    intent = state.get("intent_type", "NEW_QUERY")
    if intent in ("NEW_QUERY", "MODIFY_QUERY", "VAGUE_QUERY"):
        return "query_clarifier"
    if intent == "USE_RESULT":
        use_result = state.get("use_result_type")
        if use_result == "revisualize":
            return "visualization"
        if use_result == "compute":
            return "compute_results"
        return "extract_entity"  # new_query + modify_context
    return "query_clarifier"  # fallback
```

- [ ] **Step 3: `build_query_clarifier_graph` import'u ekle**

`graph.py` dosyasının üstündeki import bloğuna (text2sql import'unun yanına) ekle:

```python
from src.graphs.report_agent.subagents.query_clarifier.graph import build_query_clarifier_graph
```

- [ ] **Step 4: `build_report_agent_graph` içine subgraph örneği ve edge'leri ekle**

`build_report_agent_graph` fonksiyonunun içinde, `text2sql = build_text2sql_graph(...)` satırının hemen altına ekle:

```python
    query_clarifier = build_query_clarifier_graph(
        llm=llm,
        clarity_threshold=0.65,
        enable_clarifier=True,
    )
```

Ardından `graph.add_node(...)` çağrılarının bulunduğu bloğa ekle:

```python
    graph.add_node("query_clarifier", query_clarifier)
```

- [ ] **Step 5: `add_conditional_edges("classify_intent", ...)` çağrısını güncelle**

Mevcut:
```python
graph.add_conditional_edges(
    "classify_intent",
    _intent_router,
    {
        "text2sql":        "text2sql",
        "modify_sql":      "modify_sql",
        "extract_entity":  "extract_entity",
        "visualization":   "visualization",
        "compute_results": "compute_results",
        "report_chat":     "report_chat",
    },
)
```

Yeni (text2sql, modify_sql, report_chat kaldırıldı — query_clarifier eklendi):
```python
graph.add_conditional_edges(
    "classify_intent",
    _intent_router,
    {
        "query_clarifier": "query_clarifier",
        "extract_entity":  "extract_entity",
        "visualization":   "visualization",
        "compute_results": "compute_results",
    },
)
graph.add_conditional_edges(
    "query_clarifier",
    _clarifier_router,
    {
        "text2sql":   "text2sql",
        "modify_sql": "modify_sql",
        "report_chat": "report_chat",
    },
)
```

- [ ] **Step 6: Router testlerini çalıştır**

```bash
pytest tests/test_query_clarifier.py -v -k "router"
```

Beklenen: 5 router testi PASS

- [ ] **Step 7: Tüm query clarifier testlerini çalıştır**

```bash
pytest tests/test_query_clarifier.py -v
```

Beklenen: 13 test PASS

- [ ] **Step 8: Commit**

```bash
git add src/graphs/report_agent/graph.py
git commit -m "feat(query-clarifier): integrate subgraph into report agent graph"
```

---

## Task 6: `classify_intent_node` & Prompt Güncellemesi

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`
- Modify: `src/graphs/report_agent/prompts.py`

- [ ] **Step 1: `classify_intent_node` return dict'ine 2 alan ekle**

`src/graphs/report_agent/nodes.py` dosyasında `classify_intent_node`'un return dict'ini bul (`return_dict = {...}`). Dict'in sonuna ekle:

```python
    "clarifier_decision": None,
    "suggested_query": None,
```

- [ ] **Step 2: `INTENT_CLASSIFIER_PROMPT` VAGUE_QUERY bölümünü güncelle**

`src/graphs/report_agent/prompts.py` dosyasında `VAGUE_QUERY:` ile başlayan bölümü bul.

Mevcut son satır:
```
  → SADECE gerçekten belirsiz, spesifik olmayan sorgularda VAGUE_QUERY seç
```

Bu satırı şununla değiştir:
```
  → NOT: VAGUE_QUERY seçersen sorgu clarifier tarafından daha net hale getirilecek.
    Emin değilsen VAGUE_QUERY seç — NEW_QUERY'ye zorlamaya çalışma.
```

- [ ] **Step 3: Mevcut test paketini çalıştır**

```bash
pytest tests/ -v --ignore=tests/test_query_clarifier.py -x
```

Beklenen: Önceden geçen testler hâlâ geçiyor (regresyon yok)

- [ ] **Step 4: Tüm testleri çalıştır**

```bash
pytest tests/ -v
```

Beklenen: Tüm testler geçiyor

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/nodes.py src/graphs/report_agent/prompts.py
git commit -m "feat(query-clarifier): reset clarifier state in classify_intent, relax VAGUE_QUERY threshold"
```

---

## Self-Review Notu

Plan bu kontrolleri geçti:

1. **Spec coverage:** Tüm spec bölümleri (§2 graf akışı, §3 subgraph, §4 state, §5 Pydantic, §6 prompt, §7 config, §8 classify_intent prompt, §9 hata yönetimi) en az bir task'ta karşılanıyor.
2. **Placeholder yok:** Tüm adımlarda gerçek kod var.
3. **Tip tutarlılığı:** `ClarityAnalysisResult`, `ClarityIssue`, `_clarifier_router`, `create_clarity_analyzer_node` — tüm task'larda aynı isimler kullanılıyor.
4. **Hata yönetimi:** Task 2 Step 3'te `try/except` ile LLM hatası PASS'a düşürülüyor (spec §9).
5. **Fail-safe:** `can_suggest=False` veya `suggested_query=None` durumunda interrupt açılmıyor (Task 2 Step 3 + Test 8).
