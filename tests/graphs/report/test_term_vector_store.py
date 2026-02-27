"""
Tests for TermVectorStore.

Core logic tested via _semantic_search() mock — no ChromaDB needed.
Focuses on conflict resolution algorithm, not embedding infrastructure.
"""
import pytest
from typing import List
from unittest.mock import MagicMock


# --- Helpers to build fake TermCandidate objects ---

def _make_unambiguous(
    term_id: str,
    column: str,
    specificity: float,
    similarity: float,
    hint: str = "hint",
    filter_structured: dict = None,
    category: str = "metric",
):
    from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermCandidate
    return TermCandidate(
        term_id=term_id,
        category=category,
        term=term_id,
        column=column,
        specificity=specificity,
        hint=hint,
        filter_structured=filter_structured,
        ambiguous_columns=[],
        similarity=similarity,
    )


def _make_ambiguous(
    term_id: str,
    ambiguous_columns: List[dict],
    specificity: float,
    similarity: float,
):
    from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermCandidate
    return TermCandidate(
        term_id=term_id,
        category="metric",
        term=term_id,
        column="",
        specificity=specificity,
        hint="belirsiz",
        filter_structured=None,
        ambiguous_columns=ambiguous_columns,
        similarity=similarity,
    )


def _make_store_with_candidates(candidates):
    """TermVectorStore instance with mocked _semantic_search."""
    from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermVectorStore
    store = TermVectorStore.__new__(TermVectorStore)
    store._semantic_search = MagicMock(return_value=candidates)
    return store


# =============================================================================
# CONFLICT RESOLUTION TESTS
# =============================================================================

class TestConflictResolution:

    def test_clear_term_ciro_no_interrupt(self):
        """
        'ciro' → RowAmount resolved. 'ne kadar sattı' ambiguous [RowAmount, Quantity]
        → RowAmount already resolved → suppress → NO interrupt.
        """
        candidates = [
            _make_unambiguous("metric_revenue", "RowAmount", specificity=1.0, similarity=0.92),
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.71,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ne kadar ciro yaptı")

        assert len(result.ambiguous) == 0, "ciro zaten RowAmount'ı resolve etti → interrupt olmamalı"

    def test_clear_term_ciro_hint_present(self):
        """'ciro' resolve edilince hint LLM'e iletilmeli."""
        candidates = [
            _make_unambiguous("metric_revenue", "RowAmount", specificity=1.0, similarity=0.92, hint="SUM([RowAmount]) kullan"),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ciro")

        assert "RowAmount" in result.hints_text

    def test_ambiguous_alone_triggers_interrupt(self):
        """
        Sadece 'ne kadar sattı' match eder, başka term yok → interrupt tetiklenmeli.
        """
        candidates = [
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.75,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ne kadar sattı")

        assert len(result.ambiguous) == 1
        assert result.ambiguous[0].term == "metric_ambiguous_how_much"

    def test_adet_term_no_interrupt(self):
        """'kaç adet' → Quantity resolved, ambiguous suppressed."""
        candidates = [
            _make_unambiguous("metric_quantity", "Quantity", specificity=1.0, similarity=0.88),
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.65,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("kaç adet sattı")

        assert len(result.ambiguous) == 0

    def test_filter_term_returns_term_filter(self):
        """'ikram' → filter_structured → term_filters listesine eklenmeli."""
        candidates = [
            _make_unambiguous(
                "filter_treat",
                "DocumentDetailIsTreatWasteCancel",
                specificity=1.0,
                similarity=0.90,
                category="status",
                filter_structured={"column": "DocumentDetailIsTreatWasteCancel", "operator": "=", "value": "1"},
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ikram edilen ürünler")

        assert len(result.term_filters) == 1
        assert result.term_filters[0]["column"] == "DocumentDetailIsTreatWasteCancel"
        assert result.term_filters[0]["value"] == "1"
        assert result.term_filters[0]["logical_operator"] == "AND"

    def test_below_threshold_terms_ignored(self):
        """Hiç match yoksa boş TermResolverOutput dönmeli."""
        store = _make_store_with_candidates([])

        result = store.resolve("anlamsız sorgu")

        assert result.term_filters == []
        assert result.ambiguous == []

    def test_paket_servis_and_ciro_combo(self):
        """
        'paket serviste ne kadar ciro' → filter + RowAmount hint, interrupt yok.
        """
        candidates = [
            _make_unambiguous(
                "metric_revenue", "RowAmount", specificity=1.0, similarity=0.91,
                hint="SUM([RowAmount]) kullan",
            ),
            _make_unambiguous(
                "filter_delivery", "DocumentKindName", specificity=1.0, similarity=0.87,
                category="filter",
                filter_structured={"column": "DocumentKindName", "operator": "=", "value": "Paket Servis"},
            ),
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.68,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("paket serviste ne kadar ciro")

        assert len(result.ambiguous) == 0
        assert len(result.term_filters) == 1
        assert result.term_filters[0]["column"] == "DocumentKindName"
        assert "RowAmount" in result.hints_text

    def test_suppress_adds_hint_about_resolved_term(self):
        """
        Suppress edildiğinde hint_lines'a 'ciro ile RowAmount çözüldü' bilgisi eklenmeli.
        Bu LLM'e correct metric'i bildirir.
        """
        candidates = [
            _make_unambiguous("metric_revenue", "RowAmount", specificity=1.0, similarity=0.92, hint="SUM([RowAmount]) kullan"),
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.71,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ne kadar ciro yaptı")

        assert "RowAmount" in result.hints_text
        assert len(result.ambiguous) == 0


# =============================================================================
# TERM RESOLVER OUTPUT STRUCTURE
# =============================================================================

class TestTermResolverOutput:

    def test_term_filters_have_logical_operator(self):
        """Her term_filter'da logical_operator='AND' olmalı."""
        candidates = [
            _make_unambiguous(
                "filter_treat", "DocumentDetailIsTreatWasteCancel", specificity=1.0, similarity=0.88,
                filter_structured={"column": "DocumentDetailIsTreatWasteCancel", "operator": "=", "value": "1"},
            ),
        ]
        store = _make_store_with_candidates(candidates)
        result = store.resolve("ikram")

        for f in result.term_filters:
            assert "logical_operator" in f

    def test_same_column_not_added_twice(self):
        """Aynı column'dan iki unambiguous match gelirse sadece biri (yüksek skoru) alınmalı."""
        candidates = [
            _make_unambiguous("metric_revenue",   "RowAmount", specificity=1.0, similarity=0.95),
            _make_unambiguous("metric_revenue_2", "RowAmount", specificity=0.8, similarity=0.80),
        ]
        store = _make_store_with_candidates(candidates)
        result = store.resolve("ciro ve tutar")

        row_amount_hints = [l for l in result.hints_text.splitlines() if "RowAmount" in l]
        assert len(row_amount_hints) == 1, "Aynı kolon için tek hint olmalı"
