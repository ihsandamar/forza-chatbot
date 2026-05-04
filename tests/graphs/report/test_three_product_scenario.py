"""
Data-structure integration tests for 'bu 3 ürün' multi-turn context propagation.

Scope: _merge_accumulated_entities (merge logic) and build_query_context_summary
(context output). Classifier routing (RC-1) is covered in test_accumulated_entities.py.
Tests use only data structures — no LLM, no DB.
"""
from src.graphs.report_agent.context_builder import build_query_context_summary
from src.graphs.report_agent.subagents.text2sql.nodes import _merge_accumulated_entities


def _simulate_turn1_executor_output():
    """Simulates sql_executor after Turn 1 (kahvaltı top product)."""
    results = [
        {"ProductName": "LAS VEGAS UC PEYNIRLI BAGEL", "CategoryName": "KAHVALTI", "ToplamCiro": 80000.0},
    ]
    return _merge_accumulated_entities(None, results)


def _simulate_turn2_executor_output(accumulated_from_turn1):
    """Simulates sql_executor after Turn 2 (second most popular product, different result set)."""
    results = [
        {"ProductName": "LATTE", "ToplamCiro": 120000.0},
        {"ProductName": "FINCAN CAY", "ToplamCiro": 95000.0},
    ]
    # RC-1: Turn 2 is NEW_QUERY — but we no longer wipe, so accumulated_from_turn1 is passed in
    return _merge_accumulated_entities(accumulated_from_turn1, results)


def test_las_vegas_survives_into_turn3_context():
    """
    RC-1 + RC-2 together: LAS VEGAS must be present in query_context
    sent to semantic_extractor at Turn 3.
    """
    # Turn 1: executor accumulates LAS VEGAS
    acc_turn1 = _simulate_turn1_executor_output()
    assert any(e["value"] == "LAS VEGAS UC PEYNIRLI BAGEL" for e in acc_turn1), \
        "Turn 1 must add LAS VEGAS to accumulated_entities"

    # Turn 2: RC-1 means we pass accumulated_from_turn1 (not None) to executor
    acc_turn2 = _simulate_turn2_executor_output(acc_turn1)

    # All 3 products must be in accumulated_entities after Turn 2
    values = {e["value"] for e in acc_turn2 if e["column"] == "ProductName"}
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in values, "LAS VEGAS must survive after Turn 2"
    assert "LATTE" in values
    assert "FINCAN CAY" in values

    # Turn 3: semantic_extractor receives query_context with accumulated_entities
    # active_results = Turn 2 results (LATTE, FINCAN CAY only — NOT LAS VEGAS)
    active_results_turn2 = [
        {"ProductName": "LATTE", "ToplamCiro": 120000.0},
        {"ProductName": "FINCAN CAY", "ToplamCiro": 95000.0},
    ]
    active_filters_turn2 = []

    context = build_query_context_summary(
        active_results=active_results_turn2,
        active_filters=active_filters_turn2,
        accumulated_entities=list(acc_turn2),
    )

    # LAS VEGAS must be visible in the context despite not being in active_results
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in context, \
        "LAS VEGAS must appear in query_context at Turn 3 — RC-1 fix required"
    assert "LATTE" in context
    assert "FINCAN CAY" in context


def test_query_context_deduplicates_active_and_accumulated():
    """
    Values already in active_results must NOT appear twice in the context
    (shown in active_results section; accumulated section skips them).
    """
    active_results = [{"ProductName": "LATTE"}]
    accumulated = [
        {"column": "ProductName", "value": "LATTE"},
        {"column": "ProductName", "value": "LAS VEGAS UC PEYNIRLI BAGEL"},
    ]
    context = build_query_context_summary(
        active_results=active_results,
        active_filters=None,
        accumulated_entities=accumulated,
    )
    assert context.count("LATTE") == 1
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in context


def test_per_column_cap_prevents_budget_starvation():
    """
    A single high-cardinality column must not consume the entire budget.
    After fix: max 10 values per column.
    """
    existing = [{"column": "ProductName", "value": f"PRODUCT_{i}"} for i in range(10)]
    new_results = [
        {"ProductName": f"NEW_PRODUCT_{i}", "BranchName": "ANKARA"} for i in range(5)
    ] + [{"BranchName": "ISTANBUL"}]

    merged = _merge_accumulated_entities(existing, new_results)

    product_values = [e["value"] for e in merged if e["column"] == "ProductName"]
    branch_values = [e["value"] for e in merged if e["column"] == "BranchName"]

    assert len(product_values) <= 10
    assert "ANKARA" in branch_values
    assert "ISTANBUL" in branch_values
