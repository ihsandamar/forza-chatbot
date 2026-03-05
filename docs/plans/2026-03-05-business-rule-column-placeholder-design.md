# Business Rule Aggregation Column Placeholder Fix - Design

## Problem

`iade_dusulmus` business rule (`business_rules.json:9`) has `[RowAmount]` hardcoded in its aggregation template. The `sql_builder.py` code at line 185 tries to replace `{column}` placeholders, but the template has none. This causes ALL SUM aggregations to use `[RowAmount]` regardless of what the SQL architect specifies — even `SUM(Quantity)` becomes `SUM(CASE WHEN ... -[RowAmount] ELSE [RowAmount] END)`.

## Solution

Replace the hardcoded `[RowAmount]` in the aggregation template with `[{column}]` placeholder. Remove the outer `SUM()` wrapper — `sql_builder` adds it automatically when `_AGG_EXPR_RE` doesn't match.

**Before:** `"SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END)"`

**After:** `"CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[{column}] ELSE [{column}] END"`

## How It Works

1. `sql_builder.py:185` → `.replace("{column}", agg["column"])` replaces placeholder with actual column
2. `sql_builder.py:187` → `_AGG_EXPR_RE.match(inner)` returns False (no SUM prefix)
3. `sql_builder.py:190` → `f"{func}({inner}) AS [{alias}]"` wraps with SUM

## Scope

- Rule applies to ALL SUM aggregations (user decision: returns should reduce both amount and quantity)
- Single file change: `business_rules.json`
- Zero Python code changes
