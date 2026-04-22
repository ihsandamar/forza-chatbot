"""
Tests for term_store.py refactor:
  - _keyword_pre_resolve() removed
  - resolve_terms() batch wrapper added
  - per-entry similarity_threshold support
"""
import pytest
from unittest.mock import MagicMock, patch


def test_resolve_terms_returns_dict():
    """resolve_terms returns a dict keyed by raw_text."""
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore
    store = TermStore.__new__(TermStore)
    store._initialized = True

    # Mock resolve() to return a TermMatch for "ciro" and None for "bilinmeyen"
    from src.graphs.report_agent.subagents.text2sql.semantic_models import TermMatch
    mock_tm = TermMatch(column_name="RowAmount", filter_structured=None, specificity=1.0, similarity=0.9)

    original_resolve = store.__class__.resolve
    calls = []

    def fake_resolve(self, text, **kwargs):
        calls.append(text)
        if text == "ciro":
            return mock_tm
        return None

    store.__class__.resolve = fake_resolve
    result = store.resolve_terms(["ciro", "bilinmeyen"])
    store.__class__.resolve = original_resolve  # restore

    assert "ciro" in result
    assert "bilinmeyen" in result
    assert result["ciro"] == mock_tm
    assert result["bilinmeyen"] is None


def test_keyword_pre_resolve_removed():
    """_keyword_pre_resolve should NOT exist on TermStore (regex layer removed)."""
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore
    assert not hasattr(TermStore, "_keyword_pre_resolve"), \
        "_keyword_pre_resolve() should be removed — regex layer eliminated"


def test_resolve_terms_calls_resolve_for_each_text():
    """resolve_terms calls resolve() once per input text."""
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore
    store = TermStore.__new__(TermStore)
    store._initialized = True

    calls = []

    def fake_resolve(self, text, **kwargs):
        calls.append(text)
        return None

    original_resolve = store.__class__.resolve
    store.__class__.resolve = fake_resolve

    store.resolve_terms(["a", "b", "c"])
    store.__class__.resolve = original_resolve

    assert calls == ["a", "b", "c"]


def test_resolve_terms_empty_list():
    """resolve_terms on empty input returns empty dict."""
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore
    store = TermStore.__new__(TermStore)
    store._initialized = True

    result = store.resolve_terms([])
    assert result == {}


def test_resolve_terms_preserves_raw_text_keys():
    """resolve_terms result keys match the original raw_text inputs exactly."""
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore
    store = TermStore.__new__(TermStore)
    store._initialized = True

    inputs = ["Ciro", "Net Satış", "brüt kâr"]
    calls = []

    def fake_resolve(self, text, **kwargs):
        calls.append(text)
        return None

    original_resolve = store.__class__.resolve
    store.__class__.resolve = fake_resolve

    result = store.resolve_terms(inputs)
    store.__class__.resolve = original_resolve

    assert set(result.keys()) == set(inputs)


def test_keyword_patterns_attribute_removed():
    """_keyword_patterns attribute should NOT exist on TermStore instances."""
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore
    # Check the class itself has no _keyword_patterns default
    # (instance might still have it if __init__ sets it; we verify __init__ doesn't set it)
    import inspect
    source = inspect.getsource(TermStore.__init__)
    assert "_keyword_patterns" not in source, \
        "_keyword_patterns should be removed from __init__"


def test_per_entry_threshold_stored():
    """
    If a term_dictionary entry has 'similarity_threshold', it is stored in _entry_thresholds.
    """
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore

    sample_terms = [
        {
            "id": "t1",
            "term": "ciro",
            "category": "metric",
            "column": "RowAmount",
            "specificity": 1.0,
            "hint": "test hint",
            "similarity_threshold": 0.92,
        },
        {
            "id": "t2",
            "term": "adet",
            "category": "metric",
            "column": "Quantity",
            "specificity": 1.0,
            "hint": "test hint 2",
            # no similarity_threshold → uses default
        },
    ]

    store = TermStore.__new__(TermStore)
    store._initialized = False
    store._terms_data = sample_terms
    store._entry_thresholds = {}

    # Call _build_index equivalent: manually trigger threshold extraction
    # We test the method indirectly by checking _entry_thresholds after _build_index
    # Patch the collection to avoid ChromaDB calls
    mock_collection = MagicMock()
    mock_collection.count.return_value = 0
    store._collection = mock_collection
    store.similarity_threshold = 0.75

    # Call _build_index directly (it should populate _entry_thresholds)
    store._build_index()

    assert "t1" in store._entry_thresholds
    assert store._entry_thresholds["t1"] == 0.92
    # t2 has no override, so it should NOT be in _entry_thresholds (or be None/absent)
    assert store._entry_thresholds.get("t2") is None


def test_semantic_search_uses_entry_threshold():
    """
    _semantic_search uses per-entry threshold when available, falling back to collection default.
    """
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermStore

    store = TermStore.__new__(TermStore)
    store._initialized = True
    store.similarity_threshold = 0.75
    store._entry_thresholds = {
        "term_high": 0.92,   # high threshold — will be excluded at sim=0.85
        "term_low": 0.60,    # low threshold  — will be included at sim=0.65
    }

    mock_collection = MagicMock()
    mock_collection.count.return_value = 2
    mock_collection.query.return_value = {
        "ids": [["term_high", "term_low"]],
        "distances": [[0.15, 0.35]],   # sim = 0.85 and 0.65
        "metadatas": [[
            {
                "term_id": "term_high",
                "category": "metric",
                "term": "yüksek eşik",
                "column": "ColA",
                "specificity": "1.0",
                "hint": "",
                "filter_structured_json": "{}",
                "ambiguous_columns_json": "[]",
            },
            {
                "term_id": "term_low",
                "category": "metric",
                "term": "düşük eşik",
                "column": "ColB",
                "specificity": "1.0",
                "hint": "",
                "filter_structured_json": "{}",
                "ambiguous_columns_json": "[]",
            },
        ]],
    }
    store._collection = mock_collection

    candidates = store._semantic_search("test query")

    # term_high: sim=0.85, threshold=0.92 → EXCLUDED
    # term_low:  sim=0.65, threshold=0.60 → INCLUDED (below collection default 0.75 but above entry threshold)
    term_ids = [c.term_id for c in candidates]
    assert "term_high" not in term_ids, "term_high should be excluded (sim 0.85 < entry threshold 0.92)"
    assert "term_low" in term_ids, "term_low should be included (sim 0.65 >= entry threshold 0.60)"
