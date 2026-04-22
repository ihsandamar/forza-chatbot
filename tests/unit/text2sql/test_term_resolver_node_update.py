"""
Tests for the updated term_resolver_node that consumes SemanticIntent
entities/metrics instead of raw user_query.
"""
import asyncio
from unittest.mock import MagicMock

import pytest

from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
from src.graphs.report_agent.subagents.text2sql.semantic_models import (
    SemanticEntity,
    SemanticIntent,
    SemanticMetric,
)
from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_store(return_value: dict) -> MagicMock:
    store = MagicMock()
    store.resolve_terms.return_value = return_value
    return store


# ---------------------------------------------------------------------------
# Test: resolve_terms is called with entity/metric raw_texts
# ---------------------------------------------------------------------------

def test_term_resolver_node_uses_semantic_intent():
    """term_resolver_node reads semantic_intent from state and calls resolve_terms."""
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="dürümler", entity_type="filter_value")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="dürümler ciro",
    )

    mock_store = _make_store({})  # no resolutions — keeps it simple

    node = create_term_resolver_node(mock_store)
    state = {
        "semantic_intent": intent.model_dump(),
        "messages": [],
    }
    result = _run(node(state))

    # resolve_terms should have been called with the raw texts
    mock_store.resolve_terms.assert_called_once()
    call_args = mock_store.resolve_terms.call_args[0][0]
    assert "dürümler" in call_args
    assert "ciro" in call_args
    assert "term_resolution" in result


# ---------------------------------------------------------------------------
# Test: backward compat — no semantic_intent → falls back to resolve(user_query)
# ---------------------------------------------------------------------------

def test_term_resolver_node_falls_back_to_user_query():
    """Without semantic_intent in state, node should use the old resolve() path."""
    mock_store = MagicMock()
    mock_store.resolve.return_value = TermResolverOutput(
        term_filters=[],
        candidate_filter_terms=[],
        hints_text="Özel terim eşleşmesi bulunamadı.",
        ambiguous=[],
    )

    node = create_term_resolver_node(mock_store)
    state = {
        "user_query": "toplam ciro",
        "messages": [],
    }
    result = _run(node(state))

    # Old path should call resolve(), NOT resolve_terms()
    mock_store.resolve.assert_called_once_with("toplam ciro")
    mock_store.resolve_terms.assert_not_called()


# ---------------------------------------------------------------------------
# Test: resolved outputs are converted to term_resolution dict
# ---------------------------------------------------------------------------

def test_term_resolution_populated_from_resolved_output():
    """
    When resolve_terms returns a TermResolverOutput with candidate_filter_terms,
    term_resolution should contain a TermMatch-compatible dict for that raw_text.
    """
    cft = {
        "term_id": "t1",
        "term": "dürüm",
        "column": "ProductName",
        "filter_structured": {
            "column": "ProductName",
            "operator": "=",
            "value": "Dürüm",
        },
        "hint": "Ürün filtresi",
    }
    output = TermResolverOutput(
        term_filters=[{**cft["filter_structured"], "logical_operator": "AND"}],
        candidate_filter_terms=[cft],
        hints_text="...",
        ambiguous=[],
    )

    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="dürümler", entity_type="filter_value")],
        metrics=[],
        raw_query="dürümler",
    )

    node = create_term_resolver_node(_make_store({"dürümler": output}))
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    assert "term_resolution" in result
    tr = result["term_resolution"]
    assert "dürümler" in tr

    match = tr["dürümler"]
    assert match["column_name"] == "ProductName"
    assert match["filter_structured"] == cft["filter_structured"]
    # specificity and similarity are present (may be defaults)
    assert "specificity" in match
    assert "similarity" in match


# ---------------------------------------------------------------------------
# Test: candidate_filter_terms is aggregated from all outputs
# ---------------------------------------------------------------------------

def test_candidate_filter_terms_aggregated():
    """
    candidate_filter_terms in state should be the union of all
    candidate_filter_terms from every resolved TermResolverOutput.
    """
    cft1 = {
        "term_id": "t1",
        "term": "dürüm",
        "column": "ProductName",
        "filter_structured": {"column": "ProductName", "operator": "=", "value": "Dürüm"},
        "hint": "",
    }
    cft2 = {
        "term_id": "t2",
        "term": "içecek",
        "column": "CategoryName",
        "filter_structured": {"column": "CategoryName", "operator": "=", "value": "İçecek"},
        "hint": "",
    }
    out1 = TermResolverOutput(term_filters=[], candidate_filter_terms=[cft1], hints_text="", ambiguous=[])
    out2 = TermResolverOutput(term_filters=[], candidate_filter_terms=[cft2], hints_text="", ambiguous=[])

    intent = SemanticIntent(
        entities=[
            SemanticEntity(raw_text="dürümler", entity_type="filter_value"),
            SemanticEntity(raw_text="içecek", entity_type="filter_value"),
        ],
        metrics=[],
        raw_query="dürümler içecek",
    )

    node = create_term_resolver_node(_make_store({"dürümler": out1, "içecek": out2}))
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    cfts = result.get("candidate_filter_terms", [])
    term_ids = {c["term_id"] for c in cfts}
    assert "t1" in term_ids
    assert "t2" in term_ids


# ---------------------------------------------------------------------------
# Test: None/empty TermResolverOutput is skipped in term_resolution
# ---------------------------------------------------------------------------

def test_empty_resolver_output_not_included_in_term_resolution():
    """
    If resolve_terms returns an empty TermResolverOutput for a raw_text
    (no candidate_filter_terms and no term_filters), that key should
    not appear in term_resolution (or appear with empty/no data only).
    """
    empty_output = TermResolverOutput(
        term_filters=[],
        candidate_filter_terms=[],
        hints_text="Özel terim eşleşmesi bulunamadı.",
        ambiguous=[],
    )

    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="ciro", entity_type="filter_value")],
        metrics=[],
        raw_query="ciro",
    )

    node = create_term_resolver_node(_make_store({"ciro": empty_output}))
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    assert "term_resolution" in result
    # "ciro" should NOT be in term_resolution since output has no resolutions
    assert "ciro" not in result["term_resolution"]


# ---------------------------------------------------------------------------
# Test: metrics raw_text is also passed to resolve_terms
# ---------------------------------------------------------------------------

def test_metrics_raw_text_included_in_resolve_call():
    """Metric raw_texts (not just entity raw_texts) should be passed to resolve_terms."""
    intent = SemanticIntent(
        entities=[],
        metrics=[
            SemanticMetric(raw_text="toplam satış", aggregation_hint="SUM"),
            SemanticMetric(raw_text="ortalama sipariş", aggregation_hint="AVG"),
        ],
        raw_query="toplam satış ortalama sipariş",
    )

    mock_store = _make_store({})

    node = create_term_resolver_node(mock_store)
    _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    call_args = mock_store.resolve_terms.call_args[0][0]
    assert "toplam satış" in call_args
    assert "ortalama sipariş" in call_args


# ---------------------------------------------------------------------------
# Test: column_hint normalization via value_resolver
# ---------------------------------------------------------------------------

def test_column_hint_normalized_when_no_term_match():
    """
    Eğer ChromaDB bir raw_text için eşleşme bulamazsa ama entity'nin column_hint'i varsa,
    value_resolver.resolve_column_name(column_hint) çağrılmalı ve sonuç term_resolution'a eklenmeli.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    # ChromaDB eşleşme bulamıyor
    mock_store = _make_store({"kahve": TermResolverOutput(
        term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[],
    )})
    mock_vr = MagicMock()
    mock_vr.resolve_column_name.return_value = "CategoryName"

    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="kahve", entity_type="filter_value", column_hint="Kategori")],
        metrics=[],
        raw_query="kahve kategorisi",
    )
    node = create_term_resolver_node(mock_store, mock_vr)
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    # resolve_column_name çağrılmalı
    mock_vr.resolve_column_name.assert_called_once_with("Kategori")
    # Sentetik TermMatch eklenmiş olmalı
    assert "kahve" in result["term_resolution"]
    assert result["term_resolution"]["kahve"]["column_name"] == "CategoryName"


def test_column_hint_not_called_when_term_already_resolved():
    """
    ChromaDB zaten eşleşme bulduysa, value_resolver.resolve_column_name çağrılmamalı.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    cft = {
        "term_id": "t1", "term": "dürüm", "column": "ProductName",
        "filter_structured": {"column": "ProductName", "operator": "=", "value": "Dürüm"},
        "hint": "",
    }
    output = TermResolverOutput(
        term_filters=[], candidate_filter_terms=[cft], hints_text="", ambiguous=[],
    )
    mock_store = _make_store({"dürüm": output})
    mock_vr = MagicMock()

    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="dürüm", entity_type="filter_value", column_hint="ProductName")],
        metrics=[],
        raw_query="dürüm",
    )
    node = create_term_resolver_node(mock_store, mock_vr)
    _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    mock_vr.resolve_column_name.assert_not_called()


def test_column_hint_skipped_when_resolve_column_name_returns_none():
    """
    resolve_column_name None dönerse, raw_text term_resolution'a eklenmemeli.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    mock_store = _make_store({"bilinmeyen": TermResolverOutput(
        term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[],
    )})
    mock_vr = MagicMock()
    mock_vr.resolve_column_name.return_value = None  # çözülemedi

    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="bilinmeyen", entity_type="filter_value", column_hint="BilinmeyenKolon")],
        metrics=[],
        raw_query="bilinmeyen",
    )
    node = create_term_resolver_node(mock_store, mock_vr)
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    assert "bilinmeyen" not in result["term_resolution"]


def test_term_resolver_node_works_without_value_resolver():
    """
    value_resolver=None ile çağrıldığında node yine de çalışmalı (backward compat).
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    mock_store = _make_store({"espresso": TermResolverOutput(
        term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[],
    )})
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="espresso", entity_type="filter_value", column_hint="CategoryName")],
        metrics=[],
        raw_query="espresso",
    )
    node = create_term_resolver_node(mock_store, None)
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    # Hata vermemeli, term_resolution boş olabilir
    assert "term_resolution" in result
