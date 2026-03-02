# Design: MODIFY_QUERY Value Resolution Dead Zone Fix

**Date:** 2026-03-02
**Status:** Approved
**Approach:** Structured hints from modify_sql → value_resolver patches pre_built_sql

---

## Problem

When `MODIFY_QUERY` runs, `modify_sql_node` generates SQL with literal user text
(e.g., `WHERE [CategoryName] = 'dürümler'`) and puts it in `pre_built_sql`.

When `text2sql` subgraph runs, `sql_generator_node` detects `pre_built_sql` and
returns immediately — bypassing `value_resolver_node`'s resolution logic.

Result: unresolved literal values cause SQL Server to return no rows or wrong results.

### Root Cause

`value_resolver_node` works on `query_schema.filters[].value_hint`. For the
MODIFY_QUERY path, even though `value_resolver_node` runs, its output is
irrelevant — `sql_generator` ignores `query_schema` when `pre_built_sql` exists.

---

## Solution: Structured Modification Hints

Extend `modify_sql_node` to return `modification_hints` alongside `pre_built_sql`.
`value_resolver_node` gains a new branch that resolves these hints and patches
`pre_built_sql` directly before `sql_generator` sees it.

### New Data Flow

```
User: "dürümler kategorisini göster"
  ↓
modify_sql_node (LLM)
  pre_built_sql:      "... WHERE [CategoryName] = 'dürümler' ..."
  modification_hints: [{column: "CategoryName", embedded_value: "dürümler"}]
  ↓
text2sql subgraph (routing unchanged)
  ↓
value_resolver_node  [NEW: MODIFY_QUERY branch]
  → value_resolver.resolve("dürümler", "CategoryName")
  → {resolved: "DURUMLER", confidence: 95}
  → regex replace [CategoryName] = 'dürümler' → [CategoryName] = 'DURUMLER'
  return {pre_built_sql: "...WHERE [CategoryName] = 'DURUMLER'...", modification_hints: None}
  ↓
sql_generator
  pre_built_sql exists → return {sql_queries: ["... 'DURUMLER' ..."]}  ✓
```

---

## Components

### 1. `prompts.py` — Schema + Prompt

Add `ModificationHint` model:
```python
class ModificationHint(BaseModel):
    column: str          # DB column name (e.g. "CategoryName")
    embedded_value: str  # Exact literal string embedded in SQL (e.g. "dürümler")

class SqlModificationResult(BaseModel):
    modified_sql: str
    explanation: str
    modification_hints: List[ModificationHint] = []
```

Add to `SQL_MODIFIER_PROMPT`:
```
## MODIFICATION_HINTS
Kullanıcının yazdığı ve SQL'e literal olarak gömdüğün her STRING FİLTRE DEĞERİ için hint ver:
- column: hangi DB kolonunu kullandığın (örn: "CategoryName")
- embedded_value: SQL'e yazdığın BİREBİR string — büyük/küçük harf dahil

Tarih ifadeleri, sayısal değerler (TOP N) ve kolon adları için hint VERME.
```

### 2. `state.py` + `text2sql/state.py`

```python
modification_hints: Optional[List[Dict[str, Any]]]  # modify_sql → value_resolver
```

### 3. `nodes.py` (main graph) — `modify_sql_node`

```python
return {
    "pre_built_sql": result.modified_sql,
    "modification_hints": [h.model_dump() for h in result.modification_hints],
}
```

Also add to `classify_intent_node` return dict:
```python
"modification_hints": None,  # reset each turn
```

### 4. `text2sql/nodes.py` — `value_resolver_node`

Prepend new branch before existing NEW_QUERY logic:

```python
async def value_resolver_node(state: dict) -> dict:
    pre_built_sql = state.get("pre_built_sql")
    modification_hints = state.get("modification_hints") or []

    # ── MODIFY_QUERY BRANCH (NEW) ─────────────────────────────────
    if pre_built_sql and modification_hints:
        resolved_sql = pre_built_sql
        for hint in modification_hints:
            column       = hint.get("column", "")
            embedded_val = hint.get("embedded_value", "")
            if not embedded_val:
                continue
            # Skip dates and pure numbers
            if re.match(r'^\d+$', embedded_val) or re.search(r'\d{4}-\d{2}-\d{2}', embedded_val):
                continue

            result = await value_resolver.resolve(embedded_val, column)

            if not result:
                answer = interrupt({
                    "type": "input",
                    "question": f"'{embedded_val}' veritabanında bulunamadı. Doğru değeri girin:",
                })
                resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, answer)
                continue

            confidence = result.get("confidence", 0)
            candidate  = result.get("resolved", "")

            if confidence >= 75:
                resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, candidate)
                logger.info(f"[VALUE_RESOLVER/MODIFY] '{embedded_val}' → '{candidate}' (conf={confidence})")
            else:
                answer = interrupt({
                    "type": "choice",
                    "question": f"'{embedded_val}' için ne kullanılmalı?",
                    "options": [candidate, _MANUAL_ENTRY_OPTION],
                })
                if answer == _MANUAL_ENTRY_OPTION:
                    answer = interrupt({
                        "type": "input",
                        "question": f"'{embedded_val}' için doğru değeri girin:",
                    })
                resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, answer)

        return {"pre_built_sql": resolved_sql, "modification_hints": None}

    # ── NEW_QUERY BRANCH (existing, unchanged) ────────────────────
    ...
```

Helper for safe, column-aware regex replace:
```python
def _replace_in_sql(sql: str, column: str, old_val: str, new_val: str) -> str:
    """Column-aware regex replace to avoid collisions when same value appears in multiple columns."""
    pattern = re.compile(
        rf"(\[{re.escape(column)}\]\s*=\s*)'{re.escape(old_val)}'",
        re.IGNORECASE
    )
    result = pattern.sub(rf"\g<1>'{new_val}'", sql)
    if result == sql:
        # Fallback: plain replace if column-aware pattern didn't match
        result = re.sub(
            rf"'{re.escape(old_val)}'",
            f"'{new_val}'",
            sql,
            count=1,
            flags=re.IGNORECASE
        )
    return result
```

### 5. `text2sql/graph.py` — NO CHANGE

`value_resolver_node` already runs before `sql_generator_node`. No routing changes needed.

---

## Edge Cases

| Risk | Mitigation |
|------|-----------|
| LLM returns wrong case in embedded_value | `re.IGNORECASE` on replace |
| LLM hints date/number values | Skip pattern (regex) before resolve |
| Same value in multiple columns | Column-aware regex `[Column] = 'value'` |
| LLM returns empty hints list | Log warning; existing behavior preserved (no crash) |
| Hint state leaking across turns | `classify_intent_node` resets `modification_hints: None` |

---

## Files Changed

| File | Change | Lines (est.) |
|------|--------|-------------|
| `prompts.py` | `ModificationHint` model + prompt instruction | ~20 |
| `state.py` | `modification_hints` field | ~1 |
| `text2sql/state.py` | `modification_hints` field | ~1 |
| `nodes.py` (main) | `modify_sql_node` return + `classify_intent_node` reset | ~5 |
| `text2sql/nodes.py` | `value_resolver_node` MODIFY_QUERY branch + helper | ~50 |

**Total: ~77 lines. No new nodes. No routing changes.**
