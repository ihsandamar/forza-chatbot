# MODIFY_QUERY Value Resolution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the dead zone where `MODIFY_QUERY` embeds literal user values (e.g. `'dürümler'`) into SQL without resolving them against the database.

**Architecture:** `modify_sql_node` returns `modification_hints` (structured list of embedded values + their columns). `value_resolver_node` gains a new MODIFY_QUERY branch that resolves each hint via `ValueResolverService` and patches `pre_built_sql` using a column-aware regex replace. No new nodes, no routing changes.

**Tech Stack:** Python, Pydantic v2, LangGraph, rapidfuzz (via ValueResolverService), re (stdlib)

---

### Task 1: Extend `SqlModificationResult` schema in `prompts.py`

**Files:**
- Modify: `src/graphs/report_agent/prompts.py:1` (imports)
- Modify: `src/graphs/report_agent/prompts.py:31-35` (`SqlModificationResult`)
- Modify: `src/graphs/report_agent/prompts.py:120-144` (`SQL_MODIFIER_PROMPT`)
- Test: `tests/graphs/report/test_llm_components.py`

**Step 1: Write the failing test**

Add to `tests/graphs/report/test_llm_components.py`:

```python
def test_sql_modification_result_has_modification_hints():
    """SqlModificationResult şeması modification_hints alanını içermeli."""
    from src.graphs.report_agent.prompts import SqlModificationResult, ModificationHint

    result = SqlModificationResult(
        modified_sql="SELECT * FROM T WHERE [CategoryName] = 'DURUMLER'",
        explanation="Kategori filtresi eklendi",
        modification_hints=[
            ModificationHint(column="CategoryName", embedded_value="dürümler")
        ],
    )
    assert len(result.modification_hints) == 1
    assert result.modification_hints[0].column == "CategoryName"
    assert result.modification_hints[0].embedded_value == "dürümler"


def test_sql_modification_result_hints_default_empty():
    """modification_hints default boş liste olmalı (geriye dönük uyumluluk)."""
    from src.graphs.report_agent.prompts import SqlModificationResult

    result = SqlModificationResult(
        modified_sql="SELECT * FROM T",
        explanation="test",
    )
    assert result.modification_hints == []
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/graphs/report/test_llm_components.py::test_sql_modification_result_has_modification_hints tests/graphs/report/test_llm_components.py::test_sql_modification_result_hints_default_empty -v
```

Expected: `ImportError: cannot import name 'ModificationHint'`

**Step 3: Implement**

In `src/graphs/report_agent/prompts.py`:

Line 1 — update imports:
```python
from typing import List, Literal, Optional
```

After line 35 (after `class SqlModificationResult`), insert `ModificationHint` BEFORE `SqlModificationResult`, then update `SqlModificationResult`:

```python
class ModificationHint(BaseModel):
    """modify_sql_node'un SQL'e gömdüğü bir filtre değerini tanımlar."""

    column: str          # DB kolon adı (örn: "CategoryName")
    embedded_value: str  # SQL'e yazılan birebir string (örn: "dürümler")


class SqlModificationResult(BaseModel):
    """MODIFY_QUERY — mevcut SQL üzerine delta uygular."""

    modified_sql: str
    explanation: str
    modification_hints: List[ModificationHint] = []
```

**Step 4: Update `SQL_MODIFIER_PROMPT`** — prompt sonuna (son `"""` öncesine) ekle:

```python
SQL_MODIFIER_PROMPT = """...mevcut içerik...

## MODIFICATION_HINTS
Kullanıcının yazdığı ve SQL'e literal olarak gömdüğün her STRING FİLTRE DEĞERİ için bir hint ver:
- column: hangi DB kolonunu kullandığın (örn: "CategoryName")
- embedded_value: SQL'e yazdığın BİREBİR string — büyük/küçük harf dahil (örn: "dürümler")

ÖNEMLİ KURALLAR:
- Sadece kullanıcı inputundan gelen STRING değerleri için hint ver
- Tarih ifadeleri (DATEADD, BETWEEN, '2024-01-01'), sayısal değerler (TOP 10) için hint VERME
- Kolon adları için hint VERME — sadece WHERE koşulundaki değerler
- Zaten çözülmüş değerler (active_filters içindeki resolved değerler) için hint VERME
"""
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/graphs/report/test_llm_components.py::test_sql_modification_result_has_modification_hints tests/graphs/report/test_llm_components.py::test_sql_modification_result_hints_default_empty -v
```

Expected: `2 passed`

**Step 6: Commit**

```bash
git add src/graphs/report_agent/prompts.py tests/graphs/report/test_llm_components.py
git commit -m "feat(modify-query): add ModificationHint schema + prompt instruction"
```

---

### Task 2: Add `modification_hints` to state + wire `modify_sql_node`

**Files:**
- Modify: `src/graphs/report_agent/state.py:28` (after `pre_built_sql`)
- Modify: `src/graphs/report_agent/subagents/text2sql/state.py:23` (after `pre_built_sql`)
- Modify: `src/graphs/report_agent/nodes.py:161` (`modify_sql_node` return)
- Modify: `src/graphs/report_agent/nodes.py:114` (`classify_intent_node` reset)

**Step 1: Write the failing test**

Add to `tests/graphs/report/test_llm_components.py`:

```python
def test_modify_sql_node_returns_modification_hints(monkeypatch):
    """modify_sql_node modification_hints döndürmeli."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from src.graphs.report_agent.prompts import SqlModificationResult, ModificationHint

    mock_result = SqlModificationResult(
        modified_sql="SELECT * FROM T WHERE [CategoryName] = 'dürümler'",
        explanation="test",
        modification_hints=[ModificationHint(column="CategoryName", embedded_value="dürümler")],
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_result)

    from src.graphs.report_agent.nodes import create_modify_sql_node
    node = create_modify_sql_node(mock_llm, column_metadata={})

    state = {
        "active_sql": "SELECT * FROM T",
        "active_filters": [],
        "user_query": "dürümler kategorisini göster",
    }
    result = asyncio.get_event_loop().run_until_complete(node(state))

    assert "modification_hints" in result
    assert len(result["modification_hints"]) == 1
    assert result["modification_hints"][0]["column"] == "CategoryName"
    assert result["modification_hints"][0]["embedded_value"] == "dürümler"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/graphs/report/test_llm_components.py::test_modify_sql_node_returns_modification_hints -v
```

Expected: `AssertionError: 'modification_hints' not in result`

**Step 3: Add `modification_hints` to state files**

In `src/graphs/report_agent/state.py`, after line 28 (`pre_built_sql`):
```python
    modification_hints: Optional[List[Dict[str, Any]]]  # modify_sql → value_resolver (MODIFY_QUERY value resolution)
```

Also add to `create_initial_state()`:
```python
        modification_hints=None,
```

In `src/graphs/report_agent/subagents/text2sql/state.py`, after line 23 (`pre_built_sql`):
```python
    modification_hints: Optional[List[Dict[str, Any]]]  # modify_sql → value_resolver (MODIFY_QUERY value resolution)
```

**Step 4: Update `modify_sql_node` return**

In `src/graphs/report_agent/nodes.py`, replace the return at line 161:

```python
        # Mevcut:
        return {"pre_built_sql": result.modified_sql}

        # Yeni:
        logger.info(f"[MODIFY_SQL] {len(result.modification_hints)} hint(s) üretildi")
        return {
            "pre_built_sql": result.modified_sql,
            "modification_hints": [h.model_dump() for h in result.modification_hints],
        }
```

**Step 5: Add reset to `classify_intent_node`**

In `src/graphs/report_agent/nodes.py`, in `return_dict` (around line 110), after `"pre_built_sql": None,` add:
```python
            "modification_hints": None,   # her turda temizle
```

**Step 6: Run test to verify it passes**

```bash
pytest tests/graphs/report/test_llm_components.py::test_modify_sql_node_returns_modification_hints -v
```

Expected: `1 passed`

**Step 7: Commit**

```bash
git add src/graphs/report_agent/state.py src/graphs/report_agent/subagents/text2sql/state.py src/graphs/report_agent/nodes.py tests/graphs/report/test_llm_components.py
git commit -m "feat(modify-query): add modification_hints state field + wire modify_sql_node"
```

---

### Task 3: Add `_replace_in_sql` helper + MODIFY_QUERY branch to `value_resolver_node`

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:15` (imports)
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:47` (after `_MANUAL_ENTRY_OPTION`)
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:477` (`create_value_resolver_node`)
- Test: `tests/graphs/report/test_enhanced_hitl.py`

**Step 1: Write failing tests**

Add to `tests/graphs/report/test_enhanced_hitl.py`:

```python
# ── _replace_in_sql helper ────────────────────────────────────────────────────

def test_replace_in_sql_column_aware():
    """[Column] = 'old' kalıbını column-aware olarak değiştirmeli."""
    from src.graphs.report_agent.subagents.text2sql.nodes import _replace_in_sql

    sql = "SELECT * FROM T WHERE [CategoryName] = 'dürümler' AND [BranchName] = 'istanbul'"
    result = _replace_in_sql(sql, "CategoryName", "dürümler", "DURUMLER")
    assert "'DURUMLER'" in result
    assert "'istanbul'" in result            # diğer kolon dokunulmaz
    assert "'dürümler'" not in result


def test_replace_in_sql_case_insensitive():
    """embedded_value büyük/küçük harf farkı gözetmeksizin eşleşmeli."""
    from src.graphs.report_agent.subagents.text2sql.nodes import _replace_in_sql

    sql = "SELECT * FROM T WHERE [CategoryName] = 'Dürümler'"
    result = _replace_in_sql(sql, "CategoryName", "dürümler", "DURUMLER")
    assert "'DURUMLER'" in result


def test_replace_in_sql_fallback_when_no_column_match():
    """Kolon-aware pattern eşleşmezse plain replace fallback çalışmalı."""
    from src.graphs.report_agent.subagents.text2sql.nodes import _replace_in_sql

    # LLM bazen [Col] yerine Col yazmış olabilir
    sql = "SELECT * FROM T WHERE CategoryName = 'dürümler'"
    result = _replace_in_sql(sql, "CategoryName", "dürümler", "DURUMLER")
    assert "'DURUMLER'" in result


# ── value_resolver_node MODIFY_QUERY branch ─────────────────────────────────

def test_value_resolver_node_modify_query_branch():
    """pre_built_sql + modification_hints varsa SQL patch edilmeli."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock(return_value={
        "resolved": "DURUMLER",
        "confidence": 95,
        "column": "CategoryName",
    })

    from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node
    node = create_value_resolver_node(mock_resolver)

    state = {
        "pre_built_sql": "SELECT * FROM T WHERE [CategoryName] = 'dürümler'",
        "modification_hints": [{"column": "CategoryName", "embedded_value": "dürümler"}],
        "query_schema": None,
    }
    result = asyncio.get_event_loop().run_until_complete(node(state))

    assert "pre_built_sql" in result
    assert "'DURUMLER'" in result["pre_built_sql"]
    assert "'dürümler'" not in result["pre_built_sql"]
    assert result["modification_hints"] is None      # temizlenmeli


def test_value_resolver_node_modify_query_skips_numeric():
    """Sayısal embedded_value atlanmalı (TOP 10 gibi değerlere dokunulmamalı)."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock()

    from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node
    node = create_value_resolver_node(mock_resolver)

    state = {
        "pre_built_sql": "SELECT TOP 10 * FROM T",
        "modification_hints": [{"column": "TOP", "embedded_value": "10"}],
        "query_schema": None,
    }
    asyncio.get_event_loop().run_until_complete(node(state))

    # resolve hiç çağrılmamalı
    mock_resolver.resolve.assert_not_called()


def test_value_resolver_node_new_query_branch_unchanged():
    """pre_built_sql yoksa mevcut NEW_QUERY dalı çalışmaya devam etmeli."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    mock_resolver = MagicMock()
    mock_resolver.resolve = AsyncMock(return_value={
        "resolved": "DURUMLER", "confidence": 90, "column": "CategoryName"
    })

    from src.graphs.report_agent.subagents.text2sql.nodes import create_value_resolver_node
    node = create_value_resolver_node(mock_resolver)

    state = {
        "pre_built_sql": None,
        "modification_hints": None,
        "query_schema": {
            "filters": [{"column": "CategoryName", "value_hint": "dürümler"}]
        },
    }
    result = asyncio.get_event_loop().run_until_complete(node(state))

    # Mevcut NEW_QUERY davranışı: query_schema güncellemeli
    assert "query_schema" in result
    assert result["query_schema"]["filters"][0]["resolved_value"] == "DURUMLER"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/graphs/report/test_enhanced_hitl.py::test_replace_in_sql_column_aware tests/graphs/report/test_enhanced_hitl.py::test_value_resolver_node_modify_query_branch -v
```

Expected: `ImportError: cannot import name '_replace_in_sql'`

**Step 3: Add `re` import to `text2sql/nodes.py`**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, at line 15 (after `import asyncio`):
```python
import re
```

**Step 4: Add `_replace_in_sql` helper**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, after line 47 (`_MANUAL_ENTRY_OPTION`):

```python
def _replace_in_sql(sql: str, column: str, old_val: str, new_val: str) -> str:
    """
    pre_built_sql içindeki bir filtre değerini güvenli şekilde değiştirir.

    1. Kolon-aware pattern: [Column] = 'old_val' → [Column] = 'new_val'
    2. Fallback: plain case-insensitive replace (LLM köşeli parantez kullanmadıysa)
    """
    # 1. Column-aware replace (en güvenli)
    col_pattern = re.compile(
        rf"(\[{re.escape(column)}\]\s*=\s*)'{re.escape(old_val)}'",
        re.IGNORECASE,
    )
    result, n = col_pattern.subn(rf"\g<1>'{new_val}'", sql)
    if n > 0:
        return result

    # 2. Fallback: plain replace (count=1 ile yanlış occurrence'ı engelle)
    plain_pattern = re.compile(rf"'{re.escape(old_val)}'", re.IGNORECASE)
    return plain_pattern.sub(f"'{new_val}'", sql, count=1)
```

**Step 5: Add MODIFY_QUERY branch to `value_resolver_node`**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, replace the existing `value_resolver_node` inner function (lines 484-563) with:

```python
    async def value_resolver_node(state: dict) -> dict:
        pre_built_sql    = state.get("pre_built_sql")
        modification_hints = state.get("modification_hints") or []

        # ── MODIFY_QUERY BRANCH ───────────────────────────────────────────────
        if pre_built_sql and modification_hints:
            resolved_sql = pre_built_sql

            for hint in modification_hints:
                column       = hint.get("column", "")
                embedded_val = hint.get("embedded_value", "")

                if not embedded_val:
                    continue

                # Tarih ve saf sayıları atla
                if re.match(r"^\d+$", embedded_val) or re.search(r"\d{4}-\d{2}-\d{2}", embedded_val):
                    logger.debug(f"[VALUE_RESOLVER/MODIFY] Atlandı (tarih/sayı): '{embedded_val}'")
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
                    logger.info(
                        f"[VALUE_RESOLVER/MODIFY] '{embedded_val}' → '{candidate}' (conf={confidence})"
                    )
                else:
                    label = candidate if confidence >= 50 else f"{candidate} (%{confidence:.0f} eşleşme)"
                    answer = interrupt({
                        "type": "choice",
                        "question": f"'{embedded_val}' için ne kullanılmalı?",
                        "options": [label, _MANUAL_ENTRY_OPTION],
                    })
                    if answer == _MANUAL_ENTRY_OPTION:
                        answer = interrupt({
                            "type": "input",
                            "question": f"'{embedded_val}' için doğru değeri girin:",
                        })
                    resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, answer)

            return {"pre_built_sql": resolved_sql, "modification_hints": None}

        # ── NEW_QUERY BRANCH (mevcut, değişmez) ──────────────────────────────
        raw_schema = state.get("query_schema")
        if not raw_schema:
            return {}

        filters = raw_schema.get("filters", [])
        if not filters:
            return {}

        resolved_any = False

        for f in filters:
            column     = f.get("column", "")
            value_hint = f.get("value_hint", "")

            if (
                f.get("resolved_value")
                or f.get("date_descriptor")
                or not value_hint
                or f.get("operator") in ("IS NULL", "IS NOT NULL")
            ):
                continue

            result = await value_resolver.resolve(value_hint, column)

            if not result:
                answer = interrupt({
                    "type": "input",
                    "question": f"'{value_hint}' veritabanında bulunamadı. Lütfen tam adı girin:",
                })
                f["resolved_value"] = answer
                resolved_any = True
                continue

            confidence = result.get("confidence", 0)
            candidate  = result.get("resolved", "")

            if confidence >= 75:
                f["resolved_value"] = candidate
                f["resolution_confidence"] = confidence
                resolved_any = True
                logger.info(f"[VALUE_RESOLVER] '{value_hint}' → '{candidate}' (conf={confidence})")
            else:
                label = candidate if confidence >= 50 else f"{candidate} (%{confidence:.0f} eşleşme)"
                answer = interrupt({
                    "type": "choice",
                    "question": f"'{value_hint}' için ne kullanılmalı?",
                    "options": [label, _MANUAL_ENTRY_OPTION],
                })
                if answer == _MANUAL_ENTRY_OPTION:
                    manual = interrupt({
                        "type": "input",
                        "question": f"'{value_hint}' için doğru değeri girin:",
                    })
                    f["resolved_value"] = manual
                    f["resolution_confidence"] = 100
                else:
                    f["resolved_value"] = candidate
                    f["resolution_confidence"] = confidence
                    logger.info(
                        f"[VALUE_RESOLVER] '{value_hint}' → '{candidate}' (user_selected, conf={confidence})"
                    )
                resolved_any = True

        if resolved_any:
            return {"query_schema": raw_schema}
        return {}
```

**Step 6: Run all tests**

```bash
pytest tests/graphs/report/test_enhanced_hitl.py::test_replace_in_sql_column_aware tests/graphs/report/test_enhanced_hitl.py::test_replace_in_sql_case_insensitive tests/graphs/report/test_enhanced_hitl.py::test_replace_in_sql_fallback_when_no_column_match tests/graphs/report/test_enhanced_hitl.py::test_value_resolver_node_modify_query_branch tests/graphs/report/test_enhanced_hitl.py::test_value_resolver_node_modify_query_skips_numeric tests/graphs/report/test_enhanced_hitl.py::test_value_resolver_node_new_query_branch_unchanged -v
```

Expected: `6 passed`

**Step 7: Run full test suite to check regressions**

```bash
pytest tests/ -v --tb=short
```

Expected: all previously passing tests still pass.

**Step 8: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/graphs/report/test_enhanced_hitl.py
git commit -m "feat(modify-query): add _replace_in_sql helper + MODIFY_QUERY branch to value_resolver_node"
```

---

### Task 4: Smoke test end-to-end

> No code changes — manual verification only.

**Step 1: Run the chatbot** and execute this two-turn conversation:

Turn 1 (NEW_QUERY):
```
Kategoriye göre satışları göster
```
Expected: SQL runs, results appear, `active_sql` saved.

Turn 2 (MODIFY_QUERY with unresolved value):
```
Sadece dürümler kategorisini göster
```

**Step 2: Check logs for resolution**

Expected log line:
```
[VALUE_RESOLVER/MODIFY] 'dürümler' → 'DURUMLER' (conf=95)
```

**Step 3: Verify SQL in results**

`active_sql` should contain `'DURUMLER'` not `'dürümler'`.

**Step 4: Verify empty hint list doesn't break things**

Turn 3 (MODIFY_QUERY without new filter values):
```
Sadece top 5'i göster
```
Expected: `modification_hints = []`, MODIFY_QUERY branch skipped, SQL gets `TOP 5`, no resolution errors.

**Step 5: Commit design doc**

```bash
git add docs/plans/2026-03-02-modify-query-value-resolution-design.md docs/plans/2026-03-02-modify-query-value-resolution.md
git commit -m "docs: add MODIFY_QUERY value resolution design + implementation plan"
```
