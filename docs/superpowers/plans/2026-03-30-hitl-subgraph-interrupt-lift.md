# HITL Subgraph Interrupt Lift — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** text2sql subgraph içindeki `interrupt()` çağrılarını report_agent seviyesine taşıyarak nested subgraph'larda interrupt'ın kaybolmasını önlemek.

**Architecture:** text2sql node'ları ambiguity'yi `text2sql_clarification` state field'ı üzerinden sinyal verir ve erken çıkar. report_agent'taki yeni `hitl_check_node` bu sinyali alarak `interrupt()` çağırır (bu seviyede checkpointer çalışır). Cevap, `text2sql_answers` listesine eklenerek bir sonraki text2sql re-run'unda ilgili node tarafından okunur.

**Tech Stack:** Python 3.11+, LangGraph, pytest, pytest-asyncio, TypedDict

---

## Dosya Haritası

| Dosya | Değişiklik |
|-------|-----------|
| `src/graphs/report_agent/state.py` | 3 yeni field |
| `src/graphs/report_agent/nodes.py` | `hitl_check_node` ekle + classify_intent cleanup |
| `src/graphs/report_agent/graph.py` | hitl_check node + routing değişikliği |
| `src/graphs/report_agent/subagents/text2sql/state.py` | 2 overlapping field |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | `_get_cached_answer` helper + interrupt→signal pattern |
| `src/graphs/report_agent/subagents/text2sql/graph.py` | conditional early-exit edges |
| `tests/graphs/report/test_hitl_subgraph_lift.py` | YENİ — tüm feature testleri |

---

### Task 1: ReportState ve Text2SQLState'e yeni field'lar ekle

**Files:**
- Modify: `src/graphs/report_agent/state.py`
- Modify: `src/graphs/report_agent/subagents/text2sql/state.py`

- [ ] **Step 1: `report_agent/state.py`'a 3 field ekle**

`ReportState` class'ına `final_response` field'ından sonra ekle:

```python
    # HITL subgraph clarification pipeline
    text2sql_clarification: Optional[dict]
    # Payload: {"type","question","options","source"}
    # text2sql node set eder → hitl_check okur → None'a resetler

    text2sql_answers: Optional[list]
    # Birikimli cevaplar: [{"source": str, "answer": str}, ...]
    # hitl_check append eder → text2sql node'ları okur
    # classify_intent her turda None'a resetler

    _hitl_answered: bool
    # True → hitl_check'ten sonra text2sql tekrar çalıştır
    # False → normal visualization/build_response akışı
```

`create_initial_state()` fonksiyonuna ekle:

```python
        text2sql_clarification=None,
        text2sql_answers=None,
        _hitl_answered=False,
```

- [ ] **Step 2: `text2sql/state.py`'a 2 overlapping field ekle**

`Text2SQLState` class'ının `# --- ReportState overlapping ---` bölümüne ekle (LangGraph otomatik parent ↔ child sync yapar):

```python
    text2sql_clarification: Optional[dict]   # node → parent (sinyal)
    text2sql_answers: Optional[list]         # parent → node (cevaplar)
```

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/state.py src/graphs/report_agent/subagents/text2sql/state.py
git commit -m "feat: add text2sql HITL clarification state fields"
```

---

### Task 2: `hitl_check_node` — test yaz ve implement et

**Files:**
- Create: `tests/graphs/report/test_hitl_subgraph_lift.py`
- Modify: `src/graphs/report_agent/nodes.py`

- [ ] **Step 1: Test dosyası oluştur ve failing testleri yaz**

`tests/graphs/report/test_hitl_subgraph_lift.py` dosyasını oluştur:

```python
"""
Tests for HITL Subgraph Interrupt Lift

Tests for:
- hitl_check_node: passthrough, interrupt call, answer accumulation
- _get_cached_answer: lookup helper
- term_resolver_node: signal pattern, cache usage
- value_resolver_node: signal pattern (new_query + modify branches), two-step manual entry
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# BÖLÜM 1: hitl_check_node
# =============================================================================

class TestHitlCheckNode:

    @pytest.mark.asyncio
    async def test_passthrough_when_no_clarification(self):
        """Clarification yoksa _hitl_answered=False döner, başka yan etki yok."""
        from src.graphs.report_agent.nodes import hitl_check_node

        state = {"text2sql_clarification": None, "text2sql_answers": None}
        result = await hitl_check_node(state)

        assert result == {"_hitl_answered": False}

    @pytest.mark.asyncio
    async def test_fires_interrupt_and_stores_answer(self):
        """Clarification varsa interrupt() çağrılır, answer answers listesine eklenir."""
        from src.graphs.report_agent.nodes import hitl_check_node

        payload = {
            "type": "choice",
            "question": "ne kadar sattı?",
            "options": ["RowAmount: Satış tutarı (TL)", "Quantity: Satış miktarı (Adet)"],
            "source": "vr_new_choice__ne kadar",
        }
        state = {
            "text2sql_clarification": payload,
            "text2sql_answers": None,
        }

        with patch("src.graphs.report_agent.nodes.interrupt", return_value="RowAmount: Satış tutarı (TL)") as mock_interrupt:
            result = await hitl_check_node(state)

        mock_interrupt.assert_called_once_with(payload)
        assert result["_hitl_answered"] is True
        assert result["text2sql_clarification"] is None
        assert result["text2sql_answers"] == [
            {"source": "vr_new_choice__ne kadar", "answer": "RowAmount: Satış tutarı (TL)"}
        ]

    @pytest.mark.asyncio
    async def test_accumulates_existing_answers(self):
        """Mevcut answers listesine yeni cevap append edilir."""
        from src.graphs.report_agent.nodes import hitl_check_node

        payload = {
            "type": "choice",
            "question": "hangi şube?",
            "options": ["A", "B"],
            "source": "vr_new_choice__istanbul",
        }
        state = {
            "text2sql_clarification": payload,
            "text2sql_answers": [{"source": "term__sube", "answer": "BranchName: Şube"}],
        }

        with patch("src.graphs.report_agent.nodes.interrupt", return_value="A"):
            result = await hitl_check_node(state)

        assert len(result["text2sql_answers"]) == 2
        assert result["text2sql_answers"][0] == {"source": "term__sube", "answer": "BranchName: Şube"}
        assert result["text2sql_answers"][1] == {"source": "vr_new_choice__istanbul", "answer": "A"}


# =============================================================================
# BÖLÜM 2: _get_cached_answer
# =============================================================================

class TestGetCachedAnswer:

    def test_returns_answer_when_found(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _get_cached_answer

        answers = [
            {"source": "term__sube", "answer": "BranchName: Şube"},
            {"source": "vr_new_choice__istanbul", "answer": "İstanbul"},
        ]
        assert _get_cached_answer(answers, "term__sube") == "BranchName: Şube"
        assert _get_cached_answer(answers, "vr_new_choice__istanbul") == "İstanbul"

    def test_returns_none_when_not_found(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _get_cached_answer

        answers = [{"source": "term__sube", "answer": "BranchName"}]
        assert _get_cached_answer(answers, "term__other") is None

    def test_returns_none_for_empty_or_none(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _get_cached_answer

        assert _get_cached_answer(None, "any") is None
        assert _get_cached_answer([], "any") is None


# =============================================================================
# BÖLÜM 3: term_resolver_node
# =============================================================================

def _make_mock_term_store(ambiguous_terms):
    """ambiguous_terms = [{"term": str, "options": [{"column":str,"description":str}]}]"""
    mock_store = MagicMock()
    ambiguous = []
    for item in ambiguous_terms:
        amb = MagicMock()
        amb.term = item["term"]
        amb.options = item["options"]
        ambiguous.append(amb)

    mock_result = MagicMock()
    mock_result.ambiguous = ambiguous
    mock_result.term_filters = []
    mock_result.hints_text = ""
    mock_result.candidate_filter_terms = []
    mock_store.resolve.return_value = mock_result
    return mock_store


class TestTermResolverSignalPattern:

    @pytest.mark.asyncio
    async def test_returns_signal_when_no_cached_answer(self):
        """Ambiguous term için cache yoksa clarification sinyali döner (interrupt() çağrılmaz)."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node

        mock_store = _make_mock_term_store([{
            "term": "ne kadar",
            "options": [
                {"column": "RowAmount", "description": "Satış tutarı (TL)"},
                {"column": "Quantity", "description": "Satış miktarı (Adet)"},
            ],
        }])
        node = create_term_resolver_node(mock_store)
        state = {"user_query": "ne kadar sattı", "text2sql_answers": None}

        result = await node(state)

        assert result.get("text2sql_clarification") is not None
        assert result["text2sql_clarification"]["source"] == "term__ne kadar"
        assert result["text2sql_clarification"]["type"] == "choice"
        assert "RowAmount: Satış tutarı (TL)" in result["text2sql_clarification"]["options"]
        assert "Quantity: Satış miktarı (Adet)" in result["text2sql_clarification"]["options"]
        # interrupt() çağrılmamalı
        assert "term_filters" not in result

    @pytest.mark.asyncio
    async def test_uses_cached_answer_skips_signal(self):
        """Cache'de cevap varsa term_hints normal dönüş içerir, sinyal yok."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node

        mock_store = _make_mock_term_store([{
            "term": "ne kadar",
            "options": [
                {"column": "RowAmount", "description": "Satış tutarı (TL)", "filter_structured": None},
                {"column": "Quantity", "description": "Satış miktarı (Adet)", "filter_structured": None},
            ],
        }])
        node = create_term_resolver_node(mock_store)
        state = {
            "user_query": "ne kadar sattı",
            "text2sql_answers": [
                {"source": "term__ne kadar", "answer": "RowAmount: Satış tutarı (TL)"}
            ],
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is None
        assert "term_hints" in result  # normal dönüş

    @pytest.mark.asyncio
    async def test_processes_first_term_signals_second(self):
        """İlk term cevaplandı ama ikincisi için cache yoksa ikinci için sinyal döner."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node

        mock_store = _make_mock_term_store([
            {
                "term": "ne kadar",
                "options": [
                    {"column": "RowAmount", "description": "Satış tutarı (TL)", "filter_structured": None},
                ],
            },
            {
                "term": "hangi şube",
                "options": [
                    {"column": "BranchName", "description": "Şube adı", "filter_structured": None},
                ],
            },
        ])
        node = create_term_resolver_node(mock_store)
        state = {
            "user_query": "ne kadar sattı hangi şubede",
            "text2sql_answers": [
                {"source": "term__ne kadar", "answer": "RowAmount: Satış tutarı (TL)"}
            ],
        }

        result = await node(state)

        # İkinci term için sinyal dönmeli
        assert result.get("text2sql_clarification") is not None
        assert result["text2sql_clarification"]["source"] == "term__hangi şube"


# =============================================================================
# BÖLÜM 4: value_resolver_node — NEW_QUERY branch
# =============================================================================

class TestValueResolverNewQuerySignalPattern:

    @pytest.mark.asyncio
    async def test_returns_signal_for_not_found_value(self):
        """resolve() None döndürünce not_found sinyali verilir."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node

        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value=None)

        node = create_value_resolver_node(mock_resolver)
        state = {
            "pre_built_sql": None,
            "modification_hints": None,
            "query_schema": {"filters": [{"column": "BranchCityName", "value_hint": "istanbul"}]},
            "text2sql_answers": None,
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is not None
        assert result["text2sql_clarification"]["type"] == "input"
        assert result["text2sql_clarification"]["source"] == "vr_new_not_found__istanbul"

    @pytest.mark.asyncio
    async def test_uses_cached_not_found_answer(self):
        """not_found için cache varsa resolved_value set edilir."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node

        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value=None)

        node = create_value_resolver_node(mock_resolver)
        state = {
            "pre_built_sql": None,
            "modification_hints": None,
            "query_schema": {"filters": [{"column": "BranchCityName", "value_hint": "istanbul"}]},
            "text2sql_answers": [
                {"source": "vr_new_not_found__istanbul", "answer": "İSTANBUL MAĞAZA"}
            ],
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is None
        assert result["query_schema"]["filters"][0]["resolved_value"] == "İSTANBUL MAĞAZA"

    @pytest.mark.asyncio
    async def test_returns_signal_for_low_confidence(self):
        """confidence < 75 için choice sinyali verilir."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node

        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value={"resolved": "İstanbul Bölge", "confidence": 60})

        node = create_value_resolver_node(mock_resolver)
        state = {
            "pre_built_sql": None,
            "modification_hints": None,
            "query_schema": {"filters": [{"column": "BranchCityName", "value_hint": "istanbul"}]},
            "text2sql_answers": None,
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is not None
        assert result["text2sql_clarification"]["type"] == "choice"
        assert result["text2sql_clarification"]["source"] == "vr_new_choice__istanbul"
        assert "İstanbul Bölge" in result["text2sql_clarification"]["options"]

    @pytest.mark.asyncio
    async def test_uses_cached_choice_resolves_value(self):
        """choice cache varsa resolved_value set edilir."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node

        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value={"resolved": "İstanbul Bölge", "confidence": 60})

        node = create_value_resolver_node(mock_resolver)
        state = {
            "pre_built_sql": None,
            "modification_hints": None,
            "query_schema": {"filters": [{"column": "BranchCityName", "value_hint": "istanbul"}]},
            "text2sql_answers": [
                {"source": "vr_new_choice__istanbul", "answer": "İstanbul Bölge"}
            ],
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is None
        assert result["query_schema"]["filters"][0]["resolved_value"] == "İstanbul Bölge"

    @pytest.mark.asyncio
    async def test_manual_entry_two_step_round2_signals_input(self):
        """choice=MANUAL_ENTRY_OPTION seçilince round 2'de input sinyali döner."""
        from src.graphs.report_agent.subagents.text2sql.nodes import (
            create_value_resolver_node, _MANUAL_ENTRY_OPTION
        )

        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value={"resolved": "İstanbul Bölge", "confidence": 60})

        node = create_value_resolver_node(mock_resolver)
        state = {
            "pre_built_sql": None,
            "modification_hints": None,
            "query_schema": {"filters": [{"column": "BranchCityName", "value_hint": "istanbul"}]},
            "text2sql_answers": [
                {"source": "vr_new_choice__istanbul", "answer": _MANUAL_ENTRY_OPTION}
            ],
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is not None
        assert result["text2sql_clarification"]["type"] == "input"
        assert result["text2sql_clarification"]["source"] == "vr_new_manual__istanbul"

    @pytest.mark.asyncio
    async def test_manual_entry_two_step_round3_uses_manual(self):
        """manual cache varsa resolved_value = manual cevap."""
        from src.graphs.report_agent.subagents.text2sql.nodes import (
            create_value_resolver_node, _MANUAL_ENTRY_OPTION
        )

        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value={"resolved": "İstanbul Bölge", "confidence": 60})

        node = create_value_resolver_node(mock_resolver)
        state = {
            "pre_built_sql": None,
            "modification_hints": None,
            "query_schema": {"filters": [{"column": "BranchCityName", "value_hint": "istanbul"}]},
            "text2sql_answers": [
                {"source": "vr_new_choice__istanbul", "answer": _MANUAL_ENTRY_OPTION},
                {"source": "vr_new_manual__istanbul", "answer": "ISTANBUL MERKEZ"},
            ],
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is None
        assert result["query_schema"]["filters"][0]["resolved_value"] == "ISTANBUL MERKEZ"
        assert result["query_schema"]["filters"][0].get("resolution_confidence") == 100


# =============================================================================
# BÖLÜM 5: value_resolver_node — MODIFY_QUERY branch
# =============================================================================

class TestValueResolverModifyQuerySignalPattern:

    @pytest.mark.asyncio
    async def test_modify_returns_signal_for_not_found(self):
        """MODIFY branch: resolve() None → not_found sinyali."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node

        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value=None)

        node = create_value_resolver_node(mock_resolver)
        state = {
            "pre_built_sql": "SELECT * FROM T WHERE [CategoryName] = 'dürüm'",
            "modification_hints": [{"column": "CategoryName", "embedded_value": "dürüm"}],
            "text2sql_answers": None,
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is not None
        assert result["text2sql_clarification"]["type"] == "input"
        assert result["text2sql_clarification"]["source"] == "vr_mod_not_found__dürüm"

    @pytest.mark.asyncio
    async def test_modify_uses_cached_not_found(self):
        """MODIFY branch: not_found cache varsa SQL patch edilir."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node

        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value=None)

        node = create_value_resolver_node(mock_resolver)
        state = {
            "pre_built_sql": "SELECT * FROM T WHERE [CategoryName] = 'dürüm'",
            "modification_hints": [{"column": "CategoryName", "embedded_value": "dürüm"}],
            "text2sql_answers": [
                {"source": "vr_mod_not_found__dürüm", "answer": "DURUMLER"}
            ],
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is None
        assert "DURUMLER" in result["pre_built_sql"]
        assert result["modification_hints"] is None

    @pytest.mark.asyncio
    async def test_modify_returns_signal_for_low_confidence(self):
        """MODIFY branch: confidence < 75 → choice sinyali."""
        from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node

        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(return_value={"resolved": "DURUMLER", "confidence": 55})

        node = create_value_resolver_node(mock_resolver)
        state = {
            "pre_built_sql": "SELECT * FROM T WHERE [CategoryName] = 'dürüm'",
            "modification_hints": [{"column": "CategoryName", "embedded_value": "dürüm"}],
            "text2sql_answers": None,
        }

        result = await node(state)

        assert result.get("text2sql_clarification") is not None
        assert result["text2sql_clarification"]["type"] == "choice"
        assert result["text2sql_clarification"]["source"] == "vr_mod_choice__dürüm"
```

- [ ] **Step 2: Testleri çalıştır, hepsinin FAIL ettiğini doğrula**

```bash
cd C:\Users\DLL\Documents\Python_Projects\forza-chatbot
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py -v 2>&1 | head -60
```

Expected: ImportError veya AttributeError — `hitl_check_node` ve `_get_cached_answer` henüz yok.

- [ ] **Step 3: `hitl_check_node`'u `report_agent/nodes.py`'a ekle**

`nodes.py` dosyasının en altına (tüm factory function'lardan sonra) ekle:

```python
async def hitl_check_node(state: dict) -> dict:
    """
    text2sql subgraph'tan gelen clarification sinyalini yakalar.
    Varsa report_agent seviyesinde interrupt() çağırır.
    Bu seviyede MemorySaver checkpointer çalışır — interrupt propagate eder.
    """
    clarification = state.get("text2sql_clarification")

    if not clarification:
        return {"_hitl_answered": False}

    answer = interrupt(clarification)

    answers = list(state.get("text2sql_answers") or [])
    answers.append({"source": clarification["source"], "answer": answer})

    return {
        "text2sql_clarification": None,
        "text2sql_answers": answers,
        "_hitl_answered": True,
    }
```

`from langgraph.types import interrupt` importu `nodes.py`'da zaten var (satır 8).

- [ ] **Step 4: `nodes.py` import'larını kontrol et**

```bash
python -c "from src.graphs.report_agent.nodes import hitl_check_node; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: hitl_check_node testlerini çalıştır**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py::TestHitlCheckNode -v
```

Expected: 3 test PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_hitl_subgraph_lift.py
git commit -m "feat: add hitl_check_node to report_agent for subgraph interrupt lift"
```

---

### Task 3: classify_intent cleanup + report_agent graph routing

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`
- Modify: `src/graphs/report_agent/graph.py`

- [ ] **Step 1: `classify_intent_node`'da yeni field'ları temizle**

`nodes.py` içindeki `classify_intent_node` fonksiyonundaki `return_dict` sözlüğüne ekle (yaklaşık satır 228, `"_skip_vague_check": False` satırından sonra):

```python
            "text2sql_clarification": None,   # her tur temizle
            "text2sql_answers": None,           # her tur temizle
            "_hitl_answered": False,            # her tur temizle
```

- [ ] **Step 2: `graph.py`'da hitl_check node ve routing'i ekle**

`report_agent/graph.py` dosyasını aç. Mevcut değişiklikler:

**Import ekle** (`from src.graphs.report_agent.nodes import (` bloğuna):
```python
    hitl_check_node,
```

**Node tanımla** (`graph.add_node("build_response", build_response_node)` satırından sonra):
```python
    graph.add_node("hitl_check", hitl_check_node)
```

**Routing fonksiyonu ekle** (`_visualization_router`'dan sonra):
```python
def _after_hitl_check_router(state: dict) -> str:
    """hitl_check sonrası: cevap verildi → text2sql tekrar, değilse normal akış."""
    if state.get("_hitl_answered"):
        return "text2sql"
    return _visualization_router(state)
```

**Edge değişikliği** — şu satırı **kaldır**:
```python
    graph.add_conditional_edges(
        "text2sql",
        _visualization_router,
        {"visualization": "visualization", "build_response": "build_response"},
    )
```

Yerine **şunu ekle**:
```python
    graph.add_edge("text2sql", "hitl_check")
    graph.add_conditional_edges(
        "hitl_check",
        _after_hitl_check_router,
        {
            "text2sql":       "text2sql",
            "visualization":  "visualization",
            "build_response": "build_response",
        },
    )
```

- [ ] **Step 3: Graph build'ı doğrula**

```bash
python -c "
from src.graphs.report_agent.graph import build_report_agent_graph
print('graph.py import OK')
"
```

Expected: `graph.py import OK` (hata yoksa)

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/nodes.py src/graphs/report_agent/graph.py
git commit -m "feat: add hitl_check routing to report_agent graph"
```

---

### Task 4: `_get_cached_answer` helper ve `term_resolver_node` dönüşümü

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

- [ ] **Step 1: `_get_cached_answer` testlerini çalıştır — başarısız olmalı**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py::TestGetCachedAnswer -v
```

Expected: `ImportError: cannot import name '_get_cached_answer'`

- [ ] **Step 2: `nodes.py`'a `_get_cached_answer` helper ve source key sabitlerini ekle**

`text2sql/nodes.py` dosyasında `_MANUAL_ENTRY_OPTION = "Başka bir değer girin"` satırından (satır ~80) hemen sonra ekle:

```python
# --- HITL subgraph clarification cache key prefixes ---
# Her interrupt noktası için benzersiz prefix.
# Tam key = prefix + value/term string'i (ör. "vr_new_choice__istanbul")
_KEY_PREFIX_TERM            = "term__"
_KEY_PREFIX_VR_NEW_NF       = "vr_new_not_found__"
_KEY_PREFIX_VR_NEW_CHOICE   = "vr_new_choice__"
_KEY_PREFIX_VR_NEW_MANUAL   = "vr_new_manual__"
_KEY_PREFIX_VR_MOD_NF       = "vr_mod_not_found__"
_KEY_PREFIX_VR_MOD_CHOICE   = "vr_mod_choice__"
_KEY_PREFIX_VR_MOD_MANUAL   = "vr_mod_manual__"


def _get_cached_answer(answers: list | None, source_key: str) -> str | None:
    """text2sql_answers listesinde source_key'e ait cevabı döndürür. Yoksa None."""
    return next(
        (a["answer"] for a in (answers or []) if a["source"] == source_key),
        None,
    )
```

- [ ] **Step 3: `_get_cached_answer` testlerini çalıştır**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py::TestGetCachedAnswer -v
```

Expected: 3 test PASS

- [ ] **Step 4: `term_resolver_node`'u dönüştür**

`create_term_resolver_node` içindeki `async def term_resolver_node(state: dict)` fonksiyonunu şu şekilde değiştir:

**Mevcut kod** (satır ~374-428, `for amb in result.ambiguous:` bloğu):
```python
        for amb in result.ambiguous:
            option_labels = [
                f"{opt['column']}: {opt.get('description', '')}"
                for opt in amb.options
            ]
            answer = interrupt({
                "type": "choice",
                "question": f'"{amb.term}" için hangi ölçütü kastetdiniz?',
                "options": option_labels,
            })
            for opt in amb.options:
                key = f"{opt['column']}: {opt.get('description', '')}"
                if key == answer:
                    if opt.get("filter_structured"):
                        fs = dict(opt["filter_structured"])
                        fs.setdefault("logical_operator", "AND")
                        term_filters.append(fs)
                    else:
                        chosen_col = opt["column"]
                        metric_choice_hints.append(
                            f'- Kullanıcı "{amb.term}" için [{chosen_col}] seçti '
                            f'→ aggregations: SUM([{chosen_col}]) kullan, başka kolon KULLANMA'
                        )
                        logger.info(
                            f"[TERM_RESOLVER] Ambiguous metric resolved: "
                            f"'{amb.term}' → '{chosen_col}' (user choice)"
                        )
                    break
```

**Yeni kod**:
```python
        answers = state.get("text2sql_answers") or []

        for amb in result.ambiguous:
            source_key = _KEY_PREFIX_TERM + amb.term
            option_labels = [
                f"{opt['column']}: {opt.get('description', '')}"
                for opt in amb.options
            ]
            cached = _get_cached_answer(answers, source_key)

            if cached is None:
                # Cevap yok → sinyal ver, subgraph'tan erken çık
                return {
                    "text2sql_clarification": {
                        "type": "choice",
                        "question": f'"{amb.term}" için hangi ölçütü kastetdiniz?',
                        "options": option_labels,
                        "source": source_key,
                    }
                }

            # Cevap var → işle
            answer = cached
            for opt in amb.options:
                key = f"{opt['column']}: {opt.get('description', '')}"
                if key == answer:
                    if opt.get("filter_structured"):
                        fs = dict(opt["filter_structured"])
                        fs.setdefault("logical_operator", "AND")
                        term_filters.append(fs)
                    else:
                        chosen_col = opt["column"]
                        metric_choice_hints.append(
                            f'- Kullanıcı "{amb.term}" için [{chosen_col}] seçti '
                            f'→ aggregations: SUM([{chosen_col}]) kullan, başka kolon KULLANMA'
                        )
                        logger.info(
                            f"[TERM_RESOLVER] Ambiguous metric resolved: "
                            f"'{amb.term}' → '{chosen_col}' (user choice)"
                        )
                    break
```

Ayrıca `from langgraph.types import interrupt` import'unu nodes.py'dan **kaldırma** (value_resolver değişikliği sonrasında kaldıracağız, şimdilik bırak).

- [ ] **Step 5: term_resolver testlerini çalıştır**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py::TestTermResolverSignalPattern -v
```

Expected: 3 test PASS

- [ ] **Step 6: Mevcut testlerin hâlâ geçtiğini kontrol et**

```bash
python -m pytest tests/graphs/report/test_enhanced_hitl.py -v -k "replace_in_sql or value_resolver or normalize_document"
```

Expected: tüm testler PASS

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/graphs/report/test_hitl_subgraph_lift.py
git commit -m "feat: replace term_resolver interrupt() with state signal pattern"
```

---

### Task 5: `value_resolver_node` NEW_QUERY branch dönüşümü

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

- [ ] **Step 1: NEW_QUERY branch testlerini çalıştır — başarısız olmalı**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py::TestValueResolverNewQuerySignalPattern -v
```

Expected: bir kısmı FAIL — `interrupt()` hâlâ doğrudan çağrılıyor.

- [ ] **Step 2: NEW_QUERY branch'indeki `interrupt()` çağrılarını dönüştür**

`value_resolver_node` içindeki `# ── NEW_QUERY BRANCH` bölümü (satır ~777-843). `for f in filters:` döngüsünü şu şekilde değiştir:

```python
        answers = state.get("text2sql_answers") or []

        for f in filters:
            column     = f.get("column", "")
            value_hint = f.get("value_hint", "")

            if (
                f.get("resolved_value")
                or f.get("date_descriptor")
                or not value_hint
                or f.get("operator") in ("IS NULL", "IS NOT NULL")
            ):
                continue

            result = await value_resolver.resolve(value_hint, column)

            if not result:
                source_nf = _KEY_PREFIX_VR_NEW_NF + value_hint
                cached_nf = _get_cached_answer(answers, source_nf)
                if cached_nf is None:
                    return {
                        "text2sql_clarification": {
                            "type": "input",
                            "question": f"'{value_hint}' veritabanında bulunamadı. Lütfen tam adı girin:",
                            "source": source_nf,
                        }
                    }
                f["resolved_value"] = cached_nf
                resolved_any = True
                continue

            confidence = result.get("confidence", 0)
            candidate  = result.get("resolved", "")

            if confidence >= 75:
                f["resolved_value"] = candidate
                f["resolution_confidence"] = confidence
                resolved_any = True
                logger.info(f"[VALUE_RESOLVER] '{value_hint}' → '{candidate}' (conf={confidence})")
            else:
                source_choice = _KEY_PREFIX_VR_NEW_CHOICE + value_hint
                cached_choice = _get_cached_answer(answers, source_choice)

                if cached_choice is None:
                    label = candidate if confidence >= 50 else f"{candidate} (%{confidence:.0f} eşleşme)"
                    return {
                        "text2sql_clarification": {
                            "type": "choice",
                            "question": f"'{value_hint}' için ne kullanılmalı?",
                            "options": [label, _MANUAL_ENTRY_OPTION],
                            "source": source_choice,
                        }
                    }

                if cached_choice == _MANUAL_ENTRY_OPTION:
                    source_manual = _KEY_PREFIX_VR_NEW_MANUAL + value_hint
                    cached_manual = _get_cached_answer(answers, source_manual)
                    if cached_manual is None:
                        return {
                            "text2sql_clarification": {
                                "type": "input",
                                "question": f"'{value_hint}' için doğru değeri girin:",
                                "source": source_manual,
                            }
                        }
                    f["resolved_value"] = cached_manual
                    f["resolution_confidence"] = 100
                else:
                    f["resolved_value"] = candidate
                    f["resolution_confidence"] = confidence
                    logger.info(
                        f"[VALUE_RESOLVER] '{value_hint}' → '{candidate}' (user_selected, conf={confidence})"
                    )
                resolved_any = True
```

- [ ] **Step 3: NEW_QUERY testlerini çalıştır**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py::TestValueResolverNewQuerySignalPattern -v
```

Expected: 6 test PASS

- [ ] **Step 4: Mevcut testler hâlâ geçiyor mu kontrol et**

```bash
python -m pytest tests/graphs/report/test_enhanced_hitl.py -v -k "value_resolver_node_new_query or value_resolver_node_modify_query_skips"
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat: replace value_resolver NEW_QUERY interrupt() with state signal pattern"
```

---

### Task 6: `value_resolver_node` MODIFY_QUERY branch dönüşümü

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

- [ ] **Step 1: MODIFY branch testlerini çalıştır — başarısız olmalı**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py::TestValueResolverModifyQuerySignalPattern -v
```

Expected: bir kısmı FAIL.

- [ ] **Step 2: MODIFY_QUERY branch'indeki `interrupt()` çağrılarını dönüştür**

`# ── MODIFY_QUERY BRANCH ───` bölümü (satır ~728-775). `for hint in modification_hints:` döngüsünü şu şekilde değiştir:

```python
            answers_list = state.get("text2sql_answers") or []

            for hint in modification_hints:
                column       = hint.get("column", "")
                embedded_val = hint.get("embedded_value", "")

                if not embedded_val:
                    continue

                # Tarih ve saf sayıları atla
                if re.match(r"^[\d.,]+$", embedded_val) or re.search(r"\d{4}-\d{2}-\d{2}", embedded_val):
                    logger.debug(f"[VALUE_RESOLVER/MODIFY] Atlandı (tarih/sayı): '{embedded_val}'")
                    continue

                result = await value_resolver.resolve(embedded_val, column)

                if not result:
                    source_nf = _KEY_PREFIX_VR_MOD_NF + embedded_val
                    cached_nf = _get_cached_answer(answers_list, source_nf)
                    if cached_nf is None:
                        return {
                            "text2sql_clarification": {
                                "type": "input",
                                "question": f"'{embedded_val}' veritabanında bulunamadı. Doğru değeri girin:",
                                "source": source_nf,
                            }
                        }
                    resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, cached_nf)
                    continue

                confidence = result.get("confidence", 0)
                candidate  = result.get("resolved", "")

                if confidence >= 75:
                    resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, candidate)
                    logger.info(
                        f"[VALUE_RESOLVER/MODIFY] '{embedded_val}' → '{candidate}' (conf={confidence})"
                    )
                else:
                    source_choice = _KEY_PREFIX_VR_MOD_CHOICE + embedded_val
                    cached_choice = _get_cached_answer(answers_list, source_choice)

                    if cached_choice is None:
                        label = candidate if confidence >= 50 else f"{candidate} (%{confidence:.0f} eşleşme)"
                        return {
                            "text2sql_clarification": {
                                "type": "choice",
                                "question": f"'{embedded_val}' için ne kullanılmalı?",
                                "options": [label, _MANUAL_ENTRY_OPTION],
                                "source": source_choice,
                            }
                        }

                    if cached_choice == _MANUAL_ENTRY_OPTION:
                        source_manual = _KEY_PREFIX_VR_MOD_MANUAL + embedded_val
                        cached_manual = _get_cached_answer(answers_list, source_manual)
                        if cached_manual is None:
                            return {
                                "text2sql_clarification": {
                                    "type": "input",
                                    "question": f"'{embedded_val}' için doğru değeri girin:",
                                    "source": source_manual,
                                }
                            }
                        resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, cached_manual)
                    else:
                        resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, cached_choice)
```

- [ ] **Step 3: MODIFY testlerini çalıştır**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py::TestValueResolverModifyQuerySignalPattern -v
```

Expected: 3 test PASS

- [ ] **Step 4: Mevcut MODIFY testlerini çalıştır**

```bash
python -m pytest tests/graphs/report/test_enhanced_hitl.py -v -k "value_resolver_node_modify"
```

Expected: PASS (high-confidence path değişmedi)

- [ ] **Step 5: `interrupt` import'unu nodes.py'dan kaldır**

Artık `interrupt` doğrudan text2sql/nodes.py'da kullanılmıyor. En üstteki import satırından kaldır:

```python
# KALDIR bu satırı text2sql/nodes.py'dan:
from langgraph.types import interrupt
```

Import'un başka bir yerde kullanılmadığını doğrula:

```bash
grep -n "interrupt(" src/graphs/report_agent/subagents/text2sql/nodes.py
```

Expected: hiç sonuç yok.

- [ ] **Step 6: Import kaldırıldıktan sonra testleri tekrar çalıştır**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py -v
```

Expected: TÜM testler PASS

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat: replace value_resolver MODIFY_QUERY interrupt() with state signal pattern"
```

---

### Task 7: text2sql graph'a early-exit conditional edge'ler ekle

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/graph.py`

- [ ] **Step 1: `graph.py`'daki mevcut düz edge'leri kaldır ve conditional ekle**

`build_text2sql_graph` fonksiyonu içinde şu değişiklikleri yap:

**Kaldır** (3 ayrı `add_edge` satırı):
```python
    graph.add_edge("term_resolver",     "sql_architect")
    graph.add_edge("term_resolver",     "schema_validator")
    graph.add_edge("term_resolver",     "term_validator")
```
ve
```python
    graph.add_edge("value_resolver",    "sql_generator")
```

**Ekle** (bu satırları `graph.add_edge("business_rules", "term_resolver")` satırından sonra, fan-out öncesinde):

```python
    def _route_after_term_resolver(state: dict):
        """Clarification sinyali varsa END, yoksa fan-out."""
        if state.get("text2sql_clarification"):
            return END
        return ["sql_architect", "schema_validator", "term_validator"]

    def _route_after_value_resolver(state: dict):
        """Clarification sinyali varsa END, yoksa sql_generator."""
        if state.get("text2sql_clarification"):
            return END
        return "sql_generator"

    graph.add_conditional_edges("term_resolver", _route_after_term_resolver)
    graph.add_conditional_edges(
        "value_resolver",
        _route_after_value_resolver,
        {END: END, "sql_generator": "sql_generator"},
    )
```

`END` import'u dosyanın başında `from langgraph.graph import END, START, StateGraph` içinde zaten var.

- [ ] **Step 2: Graph build doğrula**

```bash
python -c "
from unittest.mock import MagicMock, AsyncMock
# Minimal stub ile graph build test
print('Testing text2sql graph build...')
import sys
sys.path.insert(0, '.')
# graph build sadece import hatası vermemeli
from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph
print('build_text2sql_graph import OK')
"
```

Expected: `build_text2sql_graph import OK`

- [ ] **Step 3: Tüm testleri çalıştır**

```bash
python -m pytest tests/graphs/report/test_hitl_subgraph_lift.py tests/graphs/report/test_enhanced_hitl.py -v 2>&1 | tail -20
```

Expected: test_hitl_subgraph_lift'in tüm testleri PASS, test_enhanced_hitl'deki mevcut testler de PASS.

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py
git commit -m "feat: add early-exit conditional edges to text2sql graph for HITL signal propagation"
```

---

### Task 8: Son doğrulama ve regresyon kontrolü

**Files:**
- Test

- [ ] **Step 1: Tüm report agent testlerini çalıştır**

```bash
python -m pytest tests/graphs/report/ -v 2>&1 | tail -30
```

Expected: Tüm testler PASS (eski testler bozulmamış olmalı). `test_enhanced_hitl.py` içinde `ImportError` olan eski testler (AmbiguityFramework) daha önce de fail ediyorsa bu beklenen durumdur — regresyon değil.

- [ ] **Step 2: graph_entrypoints smoke test**

```bash
python -c "
import os
os.environ.setdefault('TESTING', '1')
from src.graphs.graph_entrypoints import _get_config
print('Config load — skipping (requires env vars)')
print('Import smoke test: nodes, graph, state')
from src.graphs.report_agent.nodes import hitl_check_node, create_classify_intent_node
from src.graphs.report_agent.state import ReportState, create_initial_state
from src.graphs.report_agent.subagents.text2sql.nodes import _get_cached_answer
from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
state = create_initial_state()
assert state['text2sql_clarification'] is None
assert state['text2sql_answers'] is None
assert state['_hitl_answered'] == False
print('Initial state fields OK')
print('ALL SMOKE TESTS PASSED')
"
```

Expected: `ALL SMOKE TESTS PASSED`

- [ ] **Step 3: Final commit**

```bash
git add .
git status
git commit -m "chore: finalize HITL subgraph interrupt lift implementation"
```

---

## Özet

8 task, 6 dosya. Sıra önemli:
1. State field'ları → 2. hitl_check_node → 3. Graph routing → 4. term_resolver → 5. value_resolver NEW → 6. value_resolver MODIFY → 7. Graph early-exit edges → 8. Doğrulama

Her task bağımsız commit alır. Her adımda test çalıştır.
