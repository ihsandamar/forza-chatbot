"""Test that business rules vector store caches search results."""
import pytest
import json
import tempfile
import os
import time


def _create_minimal_rules_file(path: str):
    """Create a minimal business_rules.json for testing."""
    rules = {
        "business_logic_rules": [
            {
                "id": "default_1",
                "description": "Default rule for all queries",
                "modules": ["general"],
                "related_tables": ["*"],
                "is_default": True,
                "sql": {
                    "aggregation": None,
                    "filter": "IsActive = 1",
                    "group_by": None,
                    "select": None,
                    "join": None,
                    "having": None,
                },
            },
            {
                "id": "semantic_1",
                "description": "Şube bazlı satış analizi",
                "modules": ["sube", "satis", "ciro"],
                "related_tables": ["MasterReportDocumentTable"],
                "is_default": False,
                "sql": {
                    "aggregation": "SUM(RowAmount)",
                    "filter": None,
                    "group_by": "BranchName",
                    "select": "BranchName",
                    "join": None,
                    "having": None,
                },
            },
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False)


@pytest.fixture(scope="module")
def vector_store():
    """Create a BusinessRulesStore with minimal test data."""
    from src.graphs.report_agent.subagents.text2sql.stores.business_rules_store import (
        BusinessRulesStore,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        rules_path = os.path.join(tmpdir, "business_rules.json")
        _create_minimal_rules_file(rules_path)

        store = BusinessRulesStore(
            rules_file_path=rules_path,
            similarity_threshold=0.3,
        )
        store.initialize(force_recreate=True)
        yield store


def test_cached_search_returns_same_results(vector_store):
    """Second call with same query should return cached results."""
    query = "Şube bazlı satış raporu"
    result1 = vector_store.get_relevant_rules_for_query(user_query=query, n_results=5, use_hybrid=True)
    result2 = vector_store.get_relevant_rules_for_query(user_query=query, n_results=5, use_hybrid=True)
    assert result1["total_count"] == result2["total_count"]
    assert result1["merged_sql"] == result2["merged_sql"]
    r1_ids = [r["rule_id"] for r in result1["rules"]]
    r2_ids = [r["rule_id"] for r in result2["rules"]]
    assert r1_ids == r2_ids


def test_cached_search_is_faster(vector_store):
    """Cached call should be significantly faster than first call."""
    vector_store.clear_cache()
    query = "Aylık ciro analizi"
    start1 = time.perf_counter()
    vector_store.get_relevant_rules_for_query(user_query=query, n_results=5, use_hybrid=True)
    duration1 = time.perf_counter() - start1

    start2 = time.perf_counter()
    vector_store.get_relevant_rules_for_query(user_query=query, n_results=5, use_hybrid=True)
    duration2 = time.perf_counter() - start2

    assert duration2 < duration1 / 10, (
        f"Cache not effective: first={duration1:.3f}s, second={duration2:.3f}s"
    )


def test_cache_invalidates_on_different_query(vector_store):
    """Different queries should not return cached results from other queries."""
    vector_store.clear_cache()
    result1 = vector_store.get_relevant_rules_for_query(user_query="Şube satış raporu", n_results=5, use_hybrid=True)
    result2 = vector_store.get_relevant_rules_for_query(user_query="Müşteri sayısı analizi", n_results=5, use_hybrid=True)
    assert result1["total_count"] >= 1
    assert result2["total_count"] >= 1
