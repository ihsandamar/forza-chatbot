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
