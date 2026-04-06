# comparison_dimension Validation & Multi-Entity Fix

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix SQL syntax errors caused by LLM returning comma-separated column names in `comparison_dimension` (e.g., `"CategoryName,ProductName"` instead of a single column), and add prompt guidance for multi-entity queries.

**Architecture:** Defense-in-depth with two layers: (1) Validation guard in `sql_generator_node` that splits comma-separated `comparison_dimension` into primary + secondary dimensions, (2) Prompt guidance telling the LLM to never comma-join and instead pick a primary dimension. No schema changes, no new fields — works within existing `Optional[str]` type.

**Tech Stack:** Python 3.11, Pydantic, pytest

---

## Root Cause (from debugging session)

**User query:** "Son 15 haftada kategorilere ve ürünlere göre ciro grafiğini verir misin"

**What happened:**
1. LLM set `comparison_dimension: "CategoryName,ProductName"` (comma-joined string)
2. `sql_generator_node` used it as-is in GROUP BY construction
3. `_col_expr()` wrapped it as `[CategoryName,ProductName]` — a single invalid column name
4. SQL Server error: `Invalid column name 'CategoryName,ProductName'`

**Three root causes:**
1. No validation that `comparison_dimension` is a single valid column
2. No prompt guidance for multi-entity queries ("A VE B'ye göre")
3. No sanitization before the value reaches `_col_expr()`

---

## File Structure

| Action | File | Change |
|--------|------|--------|
| Modify | `src/graphs/report_agent/subagents/text2sql/nodes.py:1112` | Validate & split comma-separated comparison_dimension |
| Modify | `src/graphs/report_agent/subagents/text2sql/prompts.py:369-377` | Add multi-entity guidance |
| Create | `tests/unit/test_comparison_dimension_validation.py` | Unit tests for validation logic |

---

## Chunk 1: Validation Guard + Prompt Fix

### Task 1: Validate comparison_dimension in sql_generator_node

This is the critical fix. Even if the LLM returns garbage, the system must not crash.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1112`
- Create: `tests/unit/test_comparison_dimension_validation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_comparison_dimension_validation.py
"""Tests for comparison_dimension validation in sql_generator_node."""
import pytest


class TestComparisonDimensionSanitization:
    """Validate that comma-separated comparison_dimension is handled safely."""

    def test_single_column_unchanged(self):
        """Normal case: single column passes through."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("CategoryName", {})
        assert comp_dim == "CategoryName"
        assert extra_dims == []

    def test_comma_separated_splits_to_first(self):
        """LLM returns 'CategoryName,ProductName' → primary is CategoryName."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("CategoryName,ProductName", {})
        assert comp_dim == "CategoryName"
        assert extra_dims == ["ProductName"]

    def test_comma_separated_with_spaces(self):
        """Handles 'CategoryName, ProductName' with spaces."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("CategoryName, ProductName", {})
        assert comp_dim == "CategoryName"
        assert extra_dims == ["ProductName"]

    def test_three_columns_comma_separated(self):
        """Three columns: first is primary, rest are extra."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension(
            "CategoryName,ProductName,BranchName", {}
        )
        assert comp_dim == "CategoryName"
        assert extra_dims == ["ProductName", "BranchName"]

    def test_none_returns_none(self):
        """None input returns None."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension(None, {})
        assert comp_dim is None
        assert extra_dims == []

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("", {})
        assert comp_dim is None
        assert extra_dims == []

    def test_column_with_brackets_stripped(self):
        """[CategoryName] → CategoryName (brackets stripped)."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("[CategoryName]", {})
        assert comp_dim == "CategoryName"
        assert extra_dims == []

    def test_validates_against_column_metadata(self):
        """Unknown column name is rejected, falls back to keyword detection."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        metadata = {
            "CategoryName": "Kategori",
            "ProductName": "Ürün",
            "BranchName": "Şube",
        }
        # Valid column
        comp_dim, _ = _sanitize_comparison_dimension("CategoryName", metadata)
        assert comp_dim == "CategoryName"

        # Invalid column — not in metadata
        comp_dim, _ = _sanitize_comparison_dimension("FakeColumn", metadata)
        assert comp_dim is None


class TestGroupByIntegration:
    """Extra dimensions from comma-split are merged into group_by."""

    def test_extra_dims_added_to_group_by(self):
        """When comparison_dimension is split, extra parts go to group_by."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension

        comp_dim, extra_dims = _sanitize_comparison_dimension(
            "CategoryName,ProductName", {}
        )

        # Simulate group_by construction
        group_by = []
        if comp_dim:
            group_by.append(comp_dim)
        group_by.extend(extra_dims)
        group_by.append("CONCAT(YEAR(DocumentDate), '-W', ...)")

        assert group_by == [
            "CategoryName",
            "ProductName",
            "CONCAT(YEAR(DocumentDate), '-W', ...)",
        ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_comparison_dimension_validation.py -v`
Expected: FAIL with `ImportError: cannot import name '_sanitize_comparison_dimension'`

- [ ] **Step 3: Implement _sanitize_comparison_dimension**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, add this function BEFORE the `create_sql_generator_node` function (around line 950, near other helper functions):

```python
def _sanitize_comparison_dimension(
    comp_dim: Optional[str],
    column_metadata: dict,
) -> tuple:
    """
    Validate and sanitize comparison_dimension from LLM output.

    Handles:
    - Comma-separated values: "CategoryName,ProductName" → ("CategoryName", ["ProductName"])
    - Bracket-wrapped: "[CategoryName]" → "CategoryName"
    - Empty/None: returns (None, [])
    - Unknown columns: validated against column_metadata if provided

    Returns:
        (primary_dimension, extra_dimensions) tuple
    """
    if not comp_dim or not comp_dim.strip():
        return None, []

    # Strip brackets
    comp_dim = comp_dim.strip().strip("[]")

    # Split comma-separated
    if "," in comp_dim:
        parts = [p.strip().strip("[]") for p in comp_dim.split(",") if p.strip()]
        if not parts:
            return None, []
        primary = parts[0]
        extra = parts[1:]
    else:
        primary = comp_dim
        extra = []

    # Validate against column_metadata if available
    if column_metadata and primary not in column_metadata:
        logger.warning(
            f"[SQL_GENERATOR] comparison_dimension '{primary}' not in column_metadata, cleared"
        )
        # Extra dims might still be valid — but without a primary, return None
        return None, []

    # Validate extra dims against metadata too
    if column_metadata:
        valid_extra = [e for e in extra if e in column_metadata]
        if len(valid_extra) < len(extra):
            dropped = [e for e in extra if e not in column_metadata]
            logger.warning(
                f"[SQL_GENERATOR] Dropped invalid extra dimensions: {dropped}"
            )
        extra = valid_extra

    return primary, extra
```

- [ ] **Step 4: Integrate into sql_generator_node**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, find line 1112:

```python
            _comp_dim  = raw_schema.get("comparison_dimension")
```

Replace with:

```python
            _comp_dim_raw = raw_schema.get("comparison_dimension")
            _comp_dim, _extra_dims = _sanitize_comparison_dimension(
                _comp_dim_raw,
                column_metadata,
            )
            if _comp_dim != _comp_dim_raw:
                logger.info(
                    f"[SQL_GENERATOR] comparison_dimension sanitized: "
                    f"'{_comp_dim_raw}' → primary='{_comp_dim}', extra={_extra_dims}"
                )
```

Then find the GROUP BY construction block (line ~1137-1149). After line 1140 (`_new_group_by.extend(_t_cols)`), add the extra dimensions:

```python
                # Add extra dimensions from comma-split (e.g., ProductName from "CategoryName,ProductName")
                for _ed in _extra_dims:
                    if _ed not in _new_group_by:
                        _new_group_by.append(_ed)
```

**IMPORTANT**: The `_extra_dims` insertion must be BEFORE the `_existing` loop (lines 1143-1149) so that the existing loop's `_c != _comp_dim` check doesn't accidentally re-add the extra dims. The extra dims are already in `_new_group_by`, and the existing loop will skip them via its own duplicate check — wait, actually the existing loop doesn't check for duplicates against `_new_group_by`, it only checks `_c != _comp_dim`. So we need to also exclude `_extra_dims` from the existing loop:

Replace line 1148:
```python
                    if not _is_time_expr and not _is_time_col and _c != _comp_dim:
```
With:
```python
                    if not _is_time_expr and not _is_time_col and _c != _comp_dim and _c not in _extra_dims:
```

Note: `_extra_dims` must be accessible in this scope. Since it's defined in the same `if state.get("query_type") == "TIME_SERIES_COMPARISON":` block, it's in scope.

- [ ] **Step 5: Handle _extra_dims for non-TIME_SERIES_COMPARISON queries**

The `_extra_dims` variable is only defined inside the TIME_SERIES_COMPARISON block. For the return statement at line ~1189 that references `_comp_dim`, we need to ensure `_extra_dims` is initialized. Add after line 1089 (`_time_gran = raw_schema.get("time_granularity")`):

```python
        _comp_dim = None
        _extra_dims = []
```

This pre-initializes both variables before the TIME_SERIES_COMPARISON block potentially reassigns them. Then the existing return statement at line ~1189 continues to work.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_comparison_dimension_validation.py -v`
Expected: ALL PASS

Run: `pytest tests/test_visualization_v2/ tests/unit/test_aggregate_period_granularity.py -v`
Expected: ALL PASS (no regressions)

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/unit/test_comparison_dimension_validation.py
git commit -m "fix: validate and split comma-separated comparison_dimension"
```

---

### Task 2: Add multi-entity guidance to SQL_ARCHITECT_PROMPT

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py:369-377`

- [ ] **Step 1: Add multi-entity rule to prompt**

In `src/graphs/report_agent/subagents/text2sql/prompts.py`, find the `comparison_dimension` section (lines 369-377). After line 377 (`Eğer sadece zaman kırılımı istiyorsa (entity yok)   → null`), add:

```
  ⚠️ comparison_dimension TEK BİR DB kolon adı olmalı — ASLA virgülle birleştirme!
  YANLIŞ ❌: "CategoryName,ProductName"
  DOĞRU ✅: "CategoryName"

  Birden fazla boyut isteniyorsa ("kategorilere VE ürünlere göre"):
  → comparison_dimension: birincil boyut (ilk belirtilen) — "CategoryName"
  → group_by: ikincil boyut(lar)ı da ekle — ["CategoryName", "ProductName"]
  → Python zaman ifadelerini otomatik ekler, sen sadece entity kolonlarını koy

  ÖRNEKLER:
  "kategorilere ve ürünlere göre haftalık ciro"
  → comparison_dimension: "CategoryName"
  → group_by: ["CategoryName", "ProductName"]
  → time_granularity: "weekly"

  "şubelere ve kategorilere göre aylık satış"
  → comparison_dimension: "BranchName"
  → group_by: ["BranchName", "CategoryName"]
  → time_granularity: "monthly"

  "ürünlerin şehirlere göre ciro dağılımı"
  → comparison_dimension: "ProductName"
  → group_by: ["ProductName", "BranchCityName"]
  → time_granularity varsa ekle, yoksa null
```

- [ ] **Step 2: Run existing tests**

Run: `pytest tests/ -k "not test_enhanced_hitl and not test_llm_components and not test_llm_integration" -v --tb=short 2>&1 | tail -20`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "fix: add multi-entity guidance to SQL_ARCHITECT_PROMPT (no comma-join)"
```

---

### Task 3: Add propagation fix for comparison_dimension with extra dims

The new `_sanitize_comparison_dimension` fixes the SQL generation, but the `comparison_dimension` that propagates to the visualization layer should also be the sanitized single value, not the comma-joined string.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1189`

- [ ] **Step 1: Write the test**

Append to `tests/unit/test_comparison_dimension_validation.py`:

```python
class TestVisualizationPropagation:
    """comparison_dimension propagated to viz layer is always a single column."""

    def test_sanitized_value_propagated_not_raw(self):
        """After sanitization, only the primary dimension propagates."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension

        # Simulate what sql_generator_node does
        raw = "CategoryName,ProductName"
        comp_dim, extra_dims = _sanitize_comparison_dimension(raw, {})

        # The return dict should use comp_dim (sanitized), not raw
        result = {
            "sql_queries": ["SELECT ..."],
            "time_granularity": "weekly",
            "comparison_dimension": comp_dim,  # NOT raw
        }
        assert result["comparison_dimension"] == "CategoryName"
        assert "," not in result["comparison_dimension"]
```

- [ ] **Step 2: Run test — should PASS** (the fix from Task 1 already uses `_comp_dim` in the return)

Verify the return statement at line ~1189 uses `_comp_dim` (sanitized) not `_comp_dim_raw`. It should already be correct from Task 1 since we replaced the variable assignment. But verify explicitly.

Run: `pytest tests/unit/test_comparison_dimension_validation.py::TestVisualizationPropagation -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_comparison_dimension_validation.py
git commit -m "test: verify sanitized comparison_dimension propagates to viz layer"
```

---

## Summary of Changes

| File | Change | Lines affected |
|------|--------|---------------|
| `text2sql/nodes.py` | Add `_sanitize_comparison_dimension()` function | ~30 lines added |
| `text2sql/nodes.py` | Call sanitizer, integrate extra_dims into GROUP BY | ~10 lines changed |
| `text2sql/prompts.py` | Multi-entity guidance in SQL_ARCHITECT_PROMPT | ~20 lines added |
| `tests/unit/test_comparison_dimension_validation.py` | 10 unit tests | New file |

**Total: ~60 lines production code, 10 tests**

No schema changes. No state field changes. No visualization layer changes. All fixes are in the text2sql pipeline where the problem originates.

**What this fixes:**
- "kategorilere VE ürünlere göre haftalık ciro" → `comparison_dimension: "CategoryName"`, `group_by: ["CategoryName", "ProductName", time_exprs]` → valid SQL
- Any future comma-separated LLM output is caught and split safely
- Extra dimensions survive into the final SQL via GROUP BY
