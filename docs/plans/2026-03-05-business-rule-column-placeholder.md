# Business Rule Column Placeholder Fix - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the `iade_dusulmus` business rule so its aggregation template uses `{column}` placeholder instead of hardcoded `[RowAmount]`, allowing correct SQL generation for all SUM aggregations (Quantity, RowAmount, etc.).

**Architecture:** Single JSON template change — replace `"SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END)"` with `"CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[{column}] ELSE [{column}] END"`. The existing `sql_builder.py` code already has `.replace("{column}", agg["column"])` support. Removing the outer `SUM()` lets the builder wrap it correctly via its `_AGG_EXPR_RE` detection path.

**Tech Stack:** Python, JSON, pytest

---

### Task 1: Write tests for the fix

**Files:**
- Create: `tests/graphs/report/test_business_rule_aggregation.py`
- Reference: `src/graphs/report_agent/subagents/text2sql/sql_builder.py:149-194`

**Step 1: Write failing test for Quantity aggregation**

```python
"""Tests for business rule aggregation template with {column} placeholder."""

import json
from datetime import date
from pathlib import Path

from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql


def _load_default_rules() -> list:
    """Load business rules and return only default rules (matching sql_generator behavior)."""
    rules_path = Path(__file__).parents[3] / "src" / "graphs" / "generic_text2sql" / "business_rules.json"
    with open(rules_path, encoding="utf-8") as f:
        data = json.load(f)
    return [r for r in data["business_logic_rules"] if r.get("is_default")]


class TestBusinessRuleAggregation:
    """iade_dusulmus rule must use {column} placeholder, not hardcoded RowAmount."""

    def test_quantity_aggregation_uses_quantity_column(self):
        """SUM(Quantity) should produce CASE WHEN with [Quantity], not [RowAmount]."""
        schema = {
            "aggregations": [
                {"function": "SUM", "column": "Quantity", "alias": "ToplamAdet"}
            ],
            "filters": [],
            "group_by": ["CategoryName"],
            "select_columns": [],
            "order_by_column": None,
            "order_by_direction": None,
            "limit": None,
        }
        rules = _load_default_rules()
        sql = generate_sql(schema, "MasterReportDocumentTable", rules, date(2026, 3, 5))

        assert "[Quantity]" in sql, f"SQL should contain [Quantity] but got: {sql}"
        assert "AS [ToplamAdet]" in sql
        # RowAmount should NOT appear when aggregating Quantity
        assert "[RowAmount]" not in sql, f"SQL should NOT contain [RowAmount] but got: {sql}"

    def test_row_amount_aggregation_uses_row_amount_column(self):
        """SUM(RowAmount) should still produce CASE WHEN with [RowAmount]."""
        schema = {
            "aggregations": [
                {"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}
            ],
            "filters": [],
            "group_by": ["CategoryName"],
            "select_columns": [],
            "order_by_column": None,
            "order_by_direction": None,
            "limit": None,
        }
        rules = _load_default_rules()
        sql = generate_sql(schema, "MasterReportDocumentTable", rules, date(2026, 3, 5))

        assert "[RowAmount]" in sql
        assert "AS [ToplamCiro]" in sql
        assert "DocumentTypeIsReturn" in sql

    def test_mixed_aggregation_uses_correct_columns(self):
        """Query with both SUM(Quantity) and SUM(RowAmount) should use respective columns."""
        schema = {
            "aggregations": [
                {"function": "SUM", "column": "Quantity", "alias": "ToplamAdet"},
                {"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"},
            ],
            "filters": [],
            "group_by": ["CategoryName"],
            "select_columns": [],
            "order_by_column": None,
            "order_by_direction": None,
            "limit": None,
        }
        rules = _load_default_rules()
        sql = generate_sql(schema, "MasterReportDocumentTable", rules, date(2026, 3, 5))

        # Both columns should appear
        assert "[Quantity]" in sql, f"SQL should contain [Quantity]: {sql}"
        assert "[RowAmount]" in sql, f"SQL should contain [RowAmount]: {sql}"
        # Correct alias mapping
        assert "AS [ToplamAdet]" in sql
        assert "AS [ToplamCiro]" in sql

    def test_count_aggregation_not_affected_by_rule(self):
        """COUNT aggregations should NOT be wrapped with the business rule."""
        schema = {
            "aggregations": [
                {"function": "COUNT", "column": "DocumentId", "alias": "ToplamAdisyon"}
            ],
            "filters": [],
            "group_by": [],
            "select_columns": [],
            "order_by_column": None,
            "order_by_direction": None,
            "limit": None,
        }
        rules = _load_default_rules()
        sql = generate_sql(schema, "MasterReportDocumentTable", rules, date(2026, 3, 5))

        assert "COUNT([DocumentId])" in sql
        assert "DocumentTypeIsReturn" not in sql
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/graphs/report/test_business_rule_aggregation.py -v`
Expected: `test_quantity_aggregation_uses_quantity_column` FAILS (RowAmount appears instead of Quantity), `test_mixed_aggregation_uses_correct_columns` FAILS. The RowAmount-only and COUNT tests should PASS.

### Task 2: Fix the business rule template

**Files:**
- Modify: `src/graphs/generic_text2sql/business_rules.json:9`

**Step 1: Update the aggregation template**

Change line 9 from:

```json
"aggregation": "SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END)",
```

To:

```json
"aggregation": "CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[{column}] ELSE [{column}] END",
```

**Why this works:**
- `sql_builder.py:185` → `.replace("{column}", agg["column"])` now replaces the placeholder
- `sql_builder.py:187` → `_AGG_EXPR_RE.match(inner)` returns `False` (no SUM prefix)
- `sql_builder.py:190` → `f"{func}({inner}) AS [{alias}]"` wraps with the correct function

**Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/graphs/report/test_business_rule_aggregation.py -v`
Expected: ALL 4 tests PASS

**Step 3: Run full diagnostics**

Run: `python -m pytest tests/ -v --tb=short` (or project's standard test command)
Expected: No regressions

**Step 4: Commit**

```bash
git add src/graphs/generic_text2sql/business_rules.json tests/graphs/report/test_business_rule_aggregation.py
git commit -m "fix: use {column} placeholder in iade_dusulmus business rule aggregation template

The hardcoded [RowAmount] in the aggregation template caused ALL SUM
aggregations to use RowAmount, even SUM(Quantity). Now uses [{column}]
placeholder which sql_builder replaces with the actual column name."
```

### Task 3: Verify end-to-end with diagnostics

**Step 1: Check modified files for errors**

Run diagnostics on:
- `src/graphs/generic_text2sql/business_rules.json` — valid JSON
- `tests/graphs/report/test_business_rule_aggregation.py` — no import errors

**Step 2: Manual verification**

Trace the "kategorilere göre satış adedi ve cirosu" query:
1. sql_architect produces: `aggregations: [{function: SUM, column: Quantity, alias: ToplamAdet}, {function: SUM, column: RowAmount, alias: ToplamCiro}]`
2. `iade_dusulmus` rule applied:
   - Quantity: `CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[Quantity] ELSE [Quantity] END` → `SUM(...) AS [ToplamAdet]`
   - RowAmount: `CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END` → `SUM(...) AS [ToplamCiro]`
3. Final SQL has correct columns for each metric
