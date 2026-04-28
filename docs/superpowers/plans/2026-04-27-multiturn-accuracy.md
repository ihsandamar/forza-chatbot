# Multi-Turn Conversation Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-turn konuşmalarda 3 accuracy hatasını gider: granularity-only crash (K1), filtre kayıpları (K2), zamir referans çözümsüzlüğü (K3).

**Architecture:** LLM structured delta çıktısı (`SqlDelta`) → Python deterministik SQL uygulaması (`SqlDeltaApplicator`); `build_query_context_summary` ile active_results/filters LLM'e human-readable olarak iletilir. `SqlModificationResult` → `SqlDelta` migration blast radius küçük (1 tanım, 1 import, 1 test dosyası).

**Tech Stack:** Python 3.11+, Pydantic v2, langgraph, pytest-asyncio, re (stdlib)

---

## Uygulama Sırası

```
Task 1  K1  → crash fix (bağımsız, ilk yapılır)
Task 2  K2a → sql_delta.py yeni dosya (bağımsız)
Task 3  K3a → context_builder.py yeni dosya (bağımsız)
Task 4  K2b → prompts migration + SQL_MODIFIER_PROMPT + modify_sql_node  ← ATOMIK COMMIT
Task 5  K3c → SEMANTIC_EXTRACTOR_PROMPT + semantic_extractor_node        ← ATOMIK COMMIT
```

---

## Task 1: K1 — Crash Fix (schema_builder null guard + prompt raw_text kuralı)

**Files:**
- Test: `tests/unit/text2sql/test_schema_builder.py`
- Modify: `src/graphs/report_agent/subagents/text2sql/schema_builder.py:173`
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py:828`

- [ ] **Step 1: Failing test yaz**

`tests/unit/text2sql/test_schema_builder.py` dosyasının sonuna ekle:

```python
def test_granularity_only_raw_text_null_no_crash():
    """raw_text=None, granularity='daily' → crash yok, date filter eklenmez."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticTime,
    )

    intent = SemanticIntent(
        entities=[],
        metrics=[],
        time=SemanticTime(raw_text=None, breakdown=True, granularity="daily"),
        raw_query="bunu gün bazında kır",
    )
    result = build_query_schema(intent, time_breakdown=True)

    assert result.time_granularity == "daily"
    assert not any(f.column == "DocumentDate" for f in result.filters)


def test_granularity_only_raw_text_empty_string_no_crash():
    """raw_text='' (boş string) → crash yok, granularity korunur."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticTime,
    )

    intent = SemanticIntent(
        entities=[],
        metrics=[],
        time=SemanticTime(raw_text="", breakdown=True, granularity="monthly"),
        raw_query="aylık göster",
    )
    result = build_query_schema(intent, time_breakdown=True)

    assert result.time_granularity == "monthly"
    assert not any(f.column == "DocumentDate" for f in result.filters)
```

- [ ] **Step 2: Testi çalıştır — FAIL olduğunu doğrula**

```
pytest tests/unit/text2sql/test_schema_builder.py::test_granularity_only_raw_text_null_no_crash -v
```

Expected: `FAILED` — `SchemaBuilderError: Tarih ifadesi çözümlenemedi: None`

- [ ] **Step 3: schema_builder.py null guard uygula**

`src/graphs/report_agent/subagents/text2sql/schema_builder.py:173` — mevcut kod:

```python
        try:
            date_descriptor, gran = parse_semantic_time(effective_st, today)
        except SemanticExtractionError as exc:
            raise SchemaBuilderError(
                f"Tarih ifadesi çözümlenemedi: {intent.time.raw_text!r}",
                error_code="DATE_PARSE_ERROR",
                context={"raw_text": intent.time.raw_text, "cause": str(exc)},
            ) from exc
```

Yeni kod (`try/except` bloğunu `if/else` ile sar):

```python
        if not effective_st.raw_text:
            date_descriptor = None
            gran = effective_st.granularity
        else:
            try:
                date_descriptor, gran = parse_semantic_time(effective_st, today)
            except SemanticExtractionError as exc:
                raise SchemaBuilderError(
                    f"Tarih ifadesi çözümlenemedi: {intent.time.raw_text!r}",
                    error_code="DATE_PARSE_ERROR",
                    context={"raw_text": intent.time.raw_text, "cause": str(exc)},
                ) from exc
```

- [ ] **Step 4: Testleri çalıştır — PASS olduğunu doğrula**

```
pytest tests/unit/text2sql/test_schema_builder.py -v
```

Expected: tüm testler PASS

- [ ] **Step 5: SEMANTIC_EXTRACTOR_PROMPT'a raw_text kuralı ekle**

`src/graphs/report_agent/subagents/text2sql/prompts.py:828` — `## time.granularity KURALI` bölümünden sonra, `**Örnekler:**` satırından önce ekle:

```python
## time.raw_text KURALI (KRİTİK — CRASH ÖNLEME)
raw_text YALNIZCA date_parser'ın çözebileceği bir tarih aralığı ifadesi olmalıdır.
Granularity kelimesi ("gün", "ay", "hafta", "yıl") tek başına raw_text OLAMAZ.

DOĞRU:
  "bunu gün bazında kır"          → time: {raw_text: null, breakdown: true,  granularity: "daily"}
  "bunu aylık göster"             → time: {raw_text: null, breakdown: true,  granularity: "monthly"}
  "son 1 yılda aylık karşılaştır" → time: {raw_text: "son 1 yılda", breakdown: true, granularity: "monthly"}
  "son 3 ayda satışlar"           → time: {raw_text: "son 3 ayda", breakdown: false, granularity: null}

YANLIŞ — CRASH YARATIR:
  "bunu gün bazında kır" → time: {raw_text: "gün", ...}
  "aylık göster"         → time: {raw_text: "aylık", ...}

Kural: Sorguda açık bir tarih aralığı yoksa → raw_text: null

```

- [ ] **Step 6: Prompt testini çalıştır**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py -v
```

Expected: tüm testler PASS (prompt değişikliği mevcut testleri kırmamalı)

- [ ] **Step 7: Commit**

```bash
git add tests/unit/text2sql/test_schema_builder.py \
        src/graphs/report_agent/subagents/text2sql/schema_builder.py \
        src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "fix(text2sql): guard raw_text=null in schema_builder, add prompt crash prevention rule"
```

---

## Task 2: K2a — SqlDeltaApplicator (yeni dosya)

**Files:**
- Create: `tests/unit/text2sql/test_sql_delta_applicator.py`
- Create: `src/graphs/report_agent/subagents/text2sql/sql_delta.py`

- [ ] **Step 1: Test dosyasını oluştur**

Yeni dosya `tests/unit/text2sql/test_sql_delta_applicator.py`:

```python
"""SqlDeltaApplicator birim testleri."""
import pytest
from src.graphs.report_agent.subagents.text2sql.sql_delta import SqlDeltaApplicator
from src.graphs.report_agent.prompts import FilterDelta, SqlDelta

BASE_SQL = (
    "SELECT TOP 10 [BranchName], SUM([RowAmount]) AS Total "
    "FROM [MasterReportDocumentTable] "
    "WHERE [CategoryName] = 'Kahve' "
    "ORDER BY Total DESC"
)


def _delta(**kwargs) -> SqlDelta:
    return SqlDelta(explanation="test", confidence=0.9, **kwargs)


def test_add_filter_appends_and_to_existing_where():
    d = _delta(add_filters=[FilterDelta(column="BranchName", operator="=", value="'Ankara'")])
    result = SqlDeltaApplicator().apply(BASE_SQL, d)
    assert "[CategoryName] = 'Kahve'" in result
    assert "[BranchName] = 'Ankara'" in result
    assert result.count("WHERE") == 1


def test_add_filter_creates_where_when_absent():
    sql = "SELECT TOP 10 [BranchName] FROM [MasterReportDocumentTable] ORDER BY [BranchName]"
    d = _delta(add_filters=[FilterDelta(column="BranchName", operator="=", value="'Ankara'")])
    result = SqlDeltaApplicator().apply(sql, d)
    assert "WHERE [BranchName] = 'Ankara'" in result
    assert result.index("WHERE") < result.index("ORDER BY")


def test_add_filter_inserts_before_order_by():
    d = _delta(add_filters=[FilterDelta(column="BranchName", operator="=", value="'İzmir'")])
    result = SqlDeltaApplicator().apply(BASE_SQL, d)
    assert result.index("[BranchName] = 'İzmir'") < result.index("ORDER BY")


def test_remove_filter_middle_condition():
    sql = "SELECT TOP 5 * FROM T WHERE [A] = '1' AND [B] = '2' AND [C] = '3'"
    result = SqlDeltaApplicator().apply(sql, _delta(remove_filter_columns=["B"]))
    assert "[B]" not in result
    assert "[A] = '1'" in result
    assert "[C] = '3'" in result


def test_remove_filter_first_condition():
    sql = (
        "SELECT * FROM T "
        "WHERE [CategoryName] = 'Kahve' AND [BranchName] = 'Ankara' "
        "ORDER BY x"
    )
    result = SqlDeltaApplicator().apply(sql, _delta(remove_filter_columns=["CategoryName"]))
    assert "[CategoryName]" not in result
    assert "[BranchName] = 'Ankara'" in result


def test_remove_filter_only_condition_removes_where():
    sql = "SELECT * FROM T WHERE [CategoryName] = 'Kahve' ORDER BY x"
    result = SqlDeltaApplicator().apply(sql, _delta(remove_filter_columns=["CategoryName"]))
    assert "WHERE" not in result
    assert "ORDER BY" in result


def test_change_limit():
    result = SqlDeltaApplicator().apply(BASE_SQL, _delta(change_limit=50))
    assert "TOP 50" in result
    assert "TOP 10" not in result


def test_change_orderby():
    result = SqlDeltaApplicator().apply(BASE_SQL, _delta(change_orderby="Total ASC"))
    assert "ORDER BY Total ASC" in result
    assert "ORDER BY Total DESC" not in result


def test_change_groupby():
    sql = (
        "SELECT [BranchName], SUM([RowAmount]) FROM T "
        "GROUP BY [BranchName] ORDER BY 1"
    )
    result = SqlDeltaApplicator().apply(
        sql, _delta(change_groupby="[BranchName], [CategoryName]")
    )
    assert "GROUP BY [BranchName], [CategoryName]" in result


def test_change_select_preserves_top_n():
    result = SqlDeltaApplicator().apply(
        BASE_SQL,
        _delta(change_select="DATEPART(month, [DocumentDate]) AS Month, SUM([RowAmount]) AS Total"),
    )
    assert "TOP 10" in result
    assert "DATEPART(month, [DocumentDate]) AS Month" in result
    assert "FROM [MasterReportDocumentTable]" in result


def test_ensure_date_cast_applied_after_add_filter():
    sql = "SELECT * FROM T WHERE [x] = '1'"
    d = _delta(add_filters=[FilterDelta(column="DocumentDate", operator=">=", value="'2024-01-01'")])
    result = SqlDeltaApplicator().apply(sql, d)
    assert "CAST([DocumentDate] AS DATE)" in result
```

- [ ] **Step 2: Testleri çalıştır — FAIL olduğunu doğrula**

```
pytest tests/unit/text2sql/test_sql_delta_applicator.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: sql_delta` ve `ImportError: FilterDelta`

- [ ] **Step 3: sql_delta.py implementasyonunu yaz**

Yeni dosya `src/graphs/report_agent/subagents/text2sql/sql_delta.py`:

```python
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graphs.report_agent.prompts import FilterDelta, SqlDelta


class SqlDeltaApplicator:
    """LLM SqlDelta'sını active_sql'e deterministik uygular."""

    _DATE_CAST_RE = re.compile(
        r"\[DocumentDate\]\s*(>=?|<=?|=)\s*'([^']+)'",
        re.IGNORECASE,
    )
    _TAIL_RE = re.compile(r"\b(ORDER\s+BY|GROUP\s+BY|HAVING)\b", re.IGNORECASE)
    _WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)

    def apply(self, original_sql: str, delta: "SqlDelta") -> str:
        sql = original_sql
        if delta.remove_filter_columns:
            sql = self._remove_filters(sql, delta.remove_filter_columns)
        if delta.add_filters:
            sql = self._add_filters(sql, delta.add_filters)
        if delta.change_select is not None:
            sql = self._change_select(sql, delta.change_select)
        if delta.change_limit is not None:
            sql = self._change_limit(sql, delta.change_limit)
        if delta.change_groupby is not None:
            sql = self._change_groupby(sql, delta.change_groupby)
        if delta.change_orderby is not None:
            sql = self._change_orderby(sql, delta.change_orderby)
        return self._ensure_date_cast(sql)

    def _add_filters(self, sql: str, filters: list["FilterDelta"]) -> str:
        new_clause = " AND ".join(
            f"[{f.column}] {f.operator} {f.value}" for f in filters
        )
        tail_match = self._TAIL_RE.search(sql)
        insert_pos = tail_match.start() if tail_match else len(sql)

        if self._WHERE_RE.search(sql):
            return sql[:insert_pos].rstrip() + f" AND {new_clause} " + sql[insert_pos:]
        return sql[:insert_pos].rstrip() + f" WHERE {new_clause} " + sql[insert_pos:]

    def _remove_filters(self, sql: str, columns: list[str]) -> str:
        for col in columns:
            esc = re.escape(col)
            cond = (
                r"(?:CAST\s*\(\s*)?"
                rf"\[{esc}\][^)]*\)?"
                r"\s*(?:NOT\s+)?(?:LIKE|=|!=|>=|<=|>|<)\s*"
                r"(?:'[^']*'|[\w.(),-]+)"
            )
            sql = re.sub(r"\s+AND\s+" + cond, "", sql, flags=re.IGNORECASE)
            sql = re.sub(cond + r"\s+AND\s+", "", sql, flags=re.IGNORECASE)
            sql = re.sub(
                r"\bWHERE\s+" + cond + r"(?=\s+(?:ORDER|GROUP|HAVING)|\s*$)",
                "",
                sql,
                flags=re.IGNORECASE,
            )
        return sql.strip()

    def _change_limit(self, sql: str, n: int) -> str:
        return re.sub(r"\bTOP\s+\d+\b", f"TOP {n}", sql, flags=re.IGNORECASE)

    def _change_orderby(self, sql: str, orderby: str) -> str:
        return re.sub(
            r"\bORDER\s+BY\b.*$",
            f"ORDER BY {orderby}",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _change_groupby(self, sql: str, groupby: str) -> str:
        return re.sub(
            r"\bGROUP\s+BY\b.*?(?=\s+(?:ORDER\s+BY|HAVING)|\s*$)",
            f"GROUP BY {groupby} ",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _change_select(self, sql: str, select_list: str) -> str:
        def replacer(m: re.Match) -> str:
            top_clause = m.group(1) or ""
            return f"SELECT{top_clause} {select_list} FROM"

        return re.sub(
            r"\bSELECT\b(\s+TOP\s+\d+)?\s+.+?\s+\bFROM\b",
            replacer,
            sql,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _ensure_date_cast(self, sql: str) -> str:
        return self._DATE_CAST_RE.sub(
            r"CAST([DocumentDate] AS DATE) \1 CAST('\2' AS DATE)",
            sql,
        )
```

- [ ] **Step 4: Testleri çalıştır — PASS olduğunu doğrula**

```
pytest tests/unit/text2sql/test_sql_delta_applicator.py -v
```

Expected: 11/11 PASS  
(Bazı test'ler `FilterDelta` import hatası verebilir — Task 4'te prompts.py'e eklenecek. Şimdilik `ImportError` beklen.)

> **Not:** `FilterDelta` Task 4'te `prompts.py`'e ekleneceğinden bu testler Task 4 sonrasında tam yeşil olacak. Şimdiye kadar `SqlDeltaApplicator` mantık testleri geçmeli; import hataları test runner'ı `ERROR` değil `FAIL` ile gösterecek.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/sql_delta.py \
        tests/unit/text2sql/test_sql_delta_applicator.py
git commit -m "feat(text2sql): add SqlDeltaApplicator — deterministic SQL delta application"
```

---

## Task 3: K3a — ContextBuilder (yeni dosya)

**Files:**
- Create: `tests/unit/report/test_context_builder.py`
- Create: `src/graphs/report_agent/context_builder.py`

- [ ] **Step 1: Test dosyasını oluştur**

Yeni dosya `tests/unit/report/test_context_builder.py`:

```python
"""build_query_context_summary birim testleri."""
from src.graphs.report_agent.context_builder import build_query_context_summary


def test_both_none_returns_default_message():
    assert build_query_context_summary(None, None) == "Önceki bağlam yok."


def test_filters_appear_in_output():
    result = build_query_context_summary(
        None,
        [{"field": "CategoryName", "value": "Kahve"}],
    )
    assert "CategoryName = 'Kahve'" in result


def test_string_values_from_results_appear():
    rows = [{"ProductName": "Latte"}, {"ProductName": "Espresso"}]
    result = build_query_context_summary(rows, None)
    assert "Latte" in result
    assert "Espresso" in result


def test_numeric_values_excluded():
    rows = [{"ProductName": "Latte", "RowAmount": 100.0}]
    result = build_query_context_summary(rows, None)
    assert "100" not in result
    assert "Latte" in result


def test_deduplicates_values():
    rows = [{"ProductName": "Latte"}, {"ProductName": "Latte"}, {"ProductName": "Latte"}]
    result = build_query_context_summary(rows, None)
    assert result.count("Latte") == 1


def test_max_rows_respected():
    rows = [{"Col": f"Val{i}"} for i in range(20)]
    result = build_query_context_summary(rows, None, max_rows=3)
    assert "Val0" in result
    assert "Val3" not in result


def test_filters_with_missing_field_key_skipped():
    result = build_query_context_summary(
        None,
        [{"field": "CategoryName", "value": "Kahve"}, {"value": "orphan"}],
    )
    assert "orphan" not in result
    assert "CategoryName" in result
```

- [ ] **Step 2: Testleri çalıştır — FAIL olduğunu doğrula**

```
pytest tests/unit/report/test_context_builder.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: context_builder`

- [ ] **Step 3: context_builder.py yaz**

Yeni dosya `src/graphs/report_agent/context_builder.py`:

```python
from __future__ import annotations


def build_query_context_summary(
    active_results: list[dict] | None,
    active_filters: list[dict] | None,
    max_rows: int = 10,
    max_values_per_col: int = 5,
) -> str:
    """active_results + active_filters → LLM-readable context string."""
    parts: list[str] = []

    if active_filters:
        filter_strs = [
            f"{f['field']} = '{f['value']}'"
            for f in active_filters
            if f.get("field") and f.get("value")
        ]
        if filter_strs:
            parts.append(f"Aktif filtreler: {', '.join(filter_strs)}")

    if active_results:
        col_values: dict[str, list] = {}
        for row in active_results[:max_rows]:
            for col, val in row.items():
                if isinstance(val, str) and val:
                    col_values.setdefault(col, [])
                    if val not in col_values[col]:
                        col_values[col].append(val)

        entity_lines = [
            f"  - {col}: {vals[:max_values_per_col]}"
            for col, vals in col_values.items()
        ]
        if entity_lines:
            parts.append("Önceki sonuçlardaki değerler:\n" + "\n".join(entity_lines))

    return "\n".join(parts) if parts else "Önceki bağlam yok."
```

- [ ] **Step 4: Testleri çalıştır — PASS olduğunu doğrula**

```
pytest tests/unit/report/test_context_builder.py -v
```

Expected: 7/7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/context_builder.py \
        tests/unit/report/test_context_builder.py
git commit -m "feat(report): add build_query_context_summary for LLM-readable context"
```

---

## Task 4: K2b — prompts.py migration + SQL_MODIFIER_PROMPT + modify_sql_node (ATOMIK)

> **⚠️ ATOMIK COMMIT:** `SQL_MODIFIER_PROMPT`'ta `{active_results}` → `{query_context}` yeniden adlandırması ve `modify_sql_node`'daki `.format()` güncellemesi **aynı commit'te** yapılmalı. Aksi hâlde `KeyError` fırlatır.

**Files:**
- Modify: `src/graphs/report_agent/prompts.py:51-64` (model migration)
- Modify: `src/graphs/report_agent/prompts.py:224-291` (SQL_MODIFIER_PROMPT rewrite)
- Modify: `src/graphs/report_agent/nodes.py:13` (import güncelle)
- Modify: `src/graphs/report_agent/nodes.py:174-262` (modify_sql_node rewrite)
- Modify: `src/graphs/report_agent/nodes.py:23-26` (\_DATE\_EQ\_RE sil)
- Test: `tests/graphs/report/test_modify_sql_results_context.py` (mock güncelle)

- [ ] **Step 1: Test dosyasını güncelle**

`tests/graphs/report/test_modify_sql_results_context.py` dosyasını aşağıdaki içerikle değiştir:

```python
"""modify_sql_node'un SqlDelta akışını ve DocumentDate CAST davranışını doğrula."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.graphs.report_agent.prompts import SQL_MODIFIER_PROMPT


def test_modifier_prompt_has_query_context_placeholder():
    assert "{query_context}" in SQL_MODIFIER_PROMPT


def test_modifier_prompt_no_longer_has_raw_results_placeholder():
    assert "{active_results}" not in SQL_MODIFIER_PROMPT


def test_modifier_prompt_has_cast_instruction():
    assert "CAST" in SQL_MODIFIER_PROMPT


def _make_mock_llm(delta_overrides: dict | None = None):
    """SqlDelta döndüren mock LLM oluştur."""
    captured: dict = {}

    class FakeDelta:
        explanation = "test"
        confidence = 0.9
        add_filters = []
        remove_filter_columns = []
        change_limit = None
        change_orderby = None
        change_groupby = None
        change_select = None

    if delta_overrides:
        for k, v in delta_overrides.items():
            setattr(FakeDelta, k, v)

    mock_structured = MagicMock()

    async def capture_invoke(prompt):
        captured["prompt"] = prompt
        return FakeDelta()

    mock_structured.ainvoke = capture_invoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    return mock_llm, captured


@pytest.mark.asyncio
async def test_modify_sql_node_includes_context_in_prompt():
    from src.graphs.report_agent.nodes import create_modify_sql_node

    mock_llm, captured = _make_mock_llm()
    node_fn = create_modify_sql_node(mock_llm, {"DocumentDate": "Tarih"})

    state = {
        "active_sql": "SELECT TOP 1 * FROM T ORDER BY X DESC",
        "active_filters": [{"field": "CategoryName", "value": "Kahve"}],
        "active_results": [{"ProductName": "Latte"}],
        "user_query": "bu ürünü listele",
        "messages": [],
    }
    await node_fn(state)

    assert "CategoryName = 'Kahve'" in captured["prompt"]
    assert "Latte" in captured["prompt"]


@pytest.mark.asyncio
async def test_modify_sql_node_returns_pre_built_sql():
    from src.graphs.report_agent.nodes import create_modify_sql_node
    from src.graphs.report_agent.prompts import FilterDelta

    mock_llm, _ = _make_mock_llm(
        delta_overrides={"add_filters": [FilterDelta(column="BranchName", operator="=", value="'Ankara'")]}
    )
    node_fn = create_modify_sql_node(mock_llm, {})

    state = {
        "active_sql": "SELECT TOP 10 [BranchName] FROM T WHERE [CategoryName] = 'Kahve' ORDER BY 1",
        "active_filters": [],
        "active_results": [],
        "user_query": "Ankara şubesi ekle",
        "messages": [],
    }
    result = await node_fn(state)

    assert "pre_built_sql" in result
    assert "[BranchName] = 'Ankara'" in result["pre_built_sql"]
    assert "[CategoryName] = 'Kahve'" in result["pre_built_sql"]


@pytest.mark.asyncio
async def test_modify_sql_node_derives_modification_hints():
    from src.graphs.report_agent.nodes import create_modify_sql_node
    from src.graphs.report_agent.prompts import FilterDelta

    mock_llm, _ = _make_mock_llm(
        delta_overrides={"add_filters": [FilterDelta(column="CategoryName", operator="=", value="'Dürümler'")]}
    )
    node_fn = create_modify_sql_node(mock_llm, {})

    state = {
        "active_sql": "SELECT TOP 10 * FROM T",
        "active_filters": [],
        "active_results": [],
        "user_query": "dürümler kategorisi",
        "messages": [],
    }
    result = await node_fn(state)

    hints = result.get("modification_hints", [])
    assert len(hints) == 1
    assert hints[0]["column"] == "CategoryName"
    assert hints[0]["embedded_value"] == "Dürümler"
```

- [ ] **Step 2: Testleri çalıştır — FAIL olduğunu doğrula**

```
pytest tests/graphs/report/test_modify_sql_results_context.py -v
```

Expected: ilk 2 test FAIL (`{query_context}` henüz prompt'ta yok)

- [ ] **Step 3: prompts.py — SqlModificationResult sil, FilterDelta + SqlDelta ekle**

`src/graphs/report_agent/prompts.py:58-64` — `SqlModificationResult` class'ını tamamen kaldır, yerine ekle:

```python
class FilterDelta(BaseModel):
    """Tek bir WHERE koşulu değişikliği."""

    column: str
    operator: Literal["=", "!=", "LIKE", "NOT LIKE", ">", "<", ">=", "<=", "BETWEEN"]
    value: str  # SQL-ready: "'Ankara'", "'%latte%'", "DATEADD(month,-1,GETDATE())"


class SqlDelta(BaseModel):
    """MODIFY_QUERY — LLM ne değişsin söyler, Python uygular."""

    add_filters:           List[FilterDelta] = []
    remove_filter_columns: List[str] = []
    change_limit:          Optional[int] = None
    change_orderby:        Optional[str] = None
    change_groupby:        Optional[str] = None
    change_select:         Optional[str] = None
    explanation:           str
    confidence:            float
```

Ayrıca dosyanın başındaki import'lara `Literal` ekle (henüz yoksa):
```python
from typing import List, Literal, Optional
```

- [ ] **Step 4: SQL_MODIFIER_PROMPT'u yeniden yaz**

`src/graphs/report_agent/prompts.py:224-291` — `SQL_MODIFIER_PROMPT` içeriğini tamamen değiştir:

```python
SQL_MODIFIER_PROMPT = """Kullanıcının isteğini anlayıp SADECE ne değişmesi gerektiğini SqlDelta formatında döndür.
SQL yazmana gerek yok — değişiklikleri struct olarak belirt, Python uygulayacak.

## MEVCUT SQL
{active_sql}

## AKTİF BAĞLAM
{query_context}

Aktif filtreler zaten SQL'de var — bunları add_filters'a EKLEME.
Sadece kullanıcının talep ettiği YENİ değişiklikleri yaz.

## KULLANICI İSTEĞİ
{modification_request}

## KOLON BİLGİLERİ
{column_metadata}

## KURALLAR

⚠️ add_filters: Kullanıcı yeni bir filtre ekliyorsa (ör: "Ankara şubesi için"):
  column = DB kolon adı ("BranchName"), operator = "=", value = SQL-ready string ("'Ankara'")

⚠️ remove_filter_columns: Kullanıcı mevcut filtreyi kaldırıyorsa sadece kolon adını listele.
  AKTİF BAĞLAM'da gösterilmeyen filtreleri kaldırma — onlar SQL'de zaten yok.

⚠️ change_select: SADECE yapısal değişiklikler için (farklı GROUP BY, zaman kırılımı).
  Örnek — "aylık kır": change_select="DATEPART(month, [DocumentDate]) AS Month, SUM([RowAmount]) AS Total"

⚠️ TARİH DEĞERİ: add_filters ile tarih eklerken SQL-ready date string kullan.
  CAST EKLEMENİ GEREKMEZ — Python otomatik ekler.
  Örnek: value="'2024-01-01'" veya value="DATEADD(month,-1,GETDATE())"

⚠️ LIKE: Kısmi arama için her zaman % wildcard kullan. Örnek: value="'%LATTE%'"

⚠️ SONUÇ REFERANSI: "bu ürün", "bu şube" → AKTİF BAĞLAM'daki gerçek değeri kullan.
  Bağlamda ProductName: ["Latte", "Espresso"] varsa "bu ürün" → value="'Latte'"

## CONFIDENCE
- 1.0: İstek açık, referanslar net
- 0.7-0.9: Küçük belirsizlikler var
- 0.5-0.7: Referans belirsiz
- <0.5: Ne istendiği çözülemedi — interrupt tetiklenecek
"""
```

- [ ] **Step 5: nodes.py — import güncelle, \_DATE\_EQ\_RE sil, modify\_sql\_node yeniden yaz**

`src/graphs/report_agent/nodes.py:13` — import satırını güncelle:

```python
from src.graphs.report_agent.prompts import (
    EntityExtractionResult,
    FilterDelta,
    IntentClassificationResult,
    QueryClarificationResult,
    SqlDelta,
    ENTITY_EXTRACTOR_PROMPT,
    INTENT_CLASSIFIER_PROMPT,
    QUERY_CLARIFICATION_PROMPT,
    SQL_MODIFIER_PROMPT,
)
```

`src/graphs/report_agent/nodes.py:23-26` — `_DATE_EQ_RE` tanımını sil (artık SqlDeltaApplicator içinde):

```python
# Bu satırları sil:
# _DATE_EQ_RE = re.compile(
#     r"\[DocumentDate\]\s*(=|BETWEEN)",
#     re.IGNORECASE,
# )
```

`src/graphs/report_agent/nodes.py:174-262` — `create_modify_sql_node` fonksiyonunu tamamen yeniden yaz:

```python
def create_modify_sql_node(llm, column_metadata: dict) -> Callable:
    """SQL Modifier: active_sql + delta → modified_sql."""
    from src.graphs.report_agent.context_builder import build_query_context_summary
    from src.graphs.report_agent.subagents.text2sql.sql_delta import SqlDeltaApplicator

    structured_llm = llm.with_structured_output(SqlDelta)

    async def modify_sql_node(state: dict) -> dict:
        active_sql = state.get("active_sql", "")
        if not active_sql:
            logger.warning("[MODIFY_SQL] No active SQL, fallback to NEW_QUERY")
            return {"intent_type": "NEW_QUERY"}

        query_context = build_query_context_summary(
            state.get("active_results"),
            state.get("active_filters"),
        )

        prompt = SQL_MODIFIER_PROMPT.format(
            active_sql=active_sql,
            query_context=query_context,
            modification_request=state.get("user_query", ""),
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
        )

        delta: SqlDelta = await structured_llm.ainvoke(prompt)

        logger.info(
            f"[MODIFY_SQL] confidence={delta.confidence:.2f} "
            f"explanation={delta.explanation[:80]}"
        )

        if delta.confidence < 0.5:
            logger.warning(
                f"[MODIFY_SQL] Low confidence ({delta.confidence:.2f}), interrupting user"
            )
            answer = interrupt({
                "type": "clarification",
                "question": (
                    f"İsteğinizi tam anlayamadım: \"{state.get('user_query', '')}\"\n"
                    f"Şu şekilde anladım: {delta.explanation}\n"
                    "Doğru mu, yoksa daha açık belirtir misiniz?"
                ),
            })
            if answer and isinstance(answer, str) and answer.strip():
                return {
                    "user_query": answer.strip(),
                    "intent_type": "MODIFY_QUERY",
                }

        modified_sql = SqlDeltaApplicator().apply(active_sql, delta)
        logger.info(f"[MODIFY_SQL] → {modified_sql[:120]}")

        modification_hints = [
            {"column": f.column, "embedded_value": f.value.strip("'")}
            for f in delta.add_filters
            if f.operator == "="
        ]
        logger.info(f"[MODIFY_SQL] {len(modification_hints)} hint(s) üretildi")

        return {
            "pre_built_sql": modified_sql,
            "modification_hints": modification_hints,
        }

    return modify_sql_node
```

- [ ] **Step 6: Tüm testleri çalıştır — PASS olduğunu doğrula**

```
pytest tests/graphs/report/test_modify_sql_results_context.py \
       tests/unit/text2sql/test_sql_delta_applicator.py -v
```

Expected: tüm testler PASS

- [ ] **Step 7: Mevcut test suite'inin kırılmadığını doğrula**

```
pytest tests/ -v --ignore=tests/unit/report/test_context_builder.py -x
```

Expected: tüm testler PASS

- [ ] **Step 8: ATOMIK commit**

```bash
git add src/graphs/report_agent/prompts.py \
        src/graphs/report_agent/nodes.py \
        tests/graphs/report/test_modify_sql_results_context.py
git commit -m "feat(report): SqlDelta migration — LLM returns struct, Python applies SQL delta deterministically"
```

---

## Task 5: K3c — Context Injection (SEMANTIC_EXTRACTOR_PROMPT + node) (ATOMIK)

> **⚠️ ATOMIK COMMIT:** `SEMANTIC_EXTRACTOR_PROMPT`'a `{query_context}` eklenmesi ve `semantic_extractor_node`'daki `.format()` güncellemesi aynı commit'te olmalı.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py:765-770` (SEMANTIC_EXTRACTOR_PROMPT yeni bölüm)
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1377-1383` (format call güncelle)

- [ ] **Step 1: Mevcut test suite baseline'ını doğrula**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py -v
```

Expected: tüm testler PASS (baseline)

- [ ] **Step 2: SEMANTIC_EXTRACTOR_PROMPT'a query_context bölümü ekle**

`src/graphs/report_agent/subagents/text2sql/prompts.py` — mevcut `## KONUŞMA BAĞLAMI` bölümünden (satır 765) SONRA, `## ÖNCEKİ SQL HATASI` satırından ÖNCE ekle:

```
## ÖNCEKİ SORGU BAĞLAMI
{query_context}

Kullanıcı "bu ürün", "bu şube", "bunu", "şunu" gibi referans kullanıyorsa →
yukarıdaki değerlerden en uygununu seç, direkt isme çevir.

Örnek: "bu ürün için detay" + bağlamda ProductName: ["Latte", "Espresso"]
→ entity: {{raw_text: "Latte", entity_type: "filter_value", column_hint: "ProductName"}}

```

Sonuç olarak `SEMANTIC_EXTRACTOR_PROMPT` içindeki bölüm sırası şöyle olmalı:
```
## KULLANICI SORUSU
{user_query}

## SORGU TİPİ
{query_type}

## MEVCUT KOLON ADLARI
{column_names}

## KONUŞMA BAĞLAMI
{conversation_context}

## ÖNCEKİ SORGU BAĞLAMI       ← YENİ
{query_context}                ← YENİ
...                            ← YENİ

## ÖNCEKİ SQL HATASI
{sql_error}
```

- [ ] **Step 3: semantic_extractor_node format call'unu güncelle**

`src/graphs/report_agent/subagents/text2sql/nodes.py:1377-1383` — mevcut:

```python
        prompt = SEMANTIC_EXTRACTOR_PROMPT.format(
            user_query=user_query,
            query_type=query_type,
            column_names=column_names,
            conversation_context=conversation_context,
            sql_error=sql_error,
        )
```

Yeni (import + query_context hesaplama + format):

```python
        from src.graphs.report_agent.context_builder import build_query_context_summary

        query_context = build_query_context_summary(
            state.get("active_results"),
            state.get("active_filters"),
        )

        prompt = SEMANTIC_EXTRACTOR_PROMPT.format(
            user_query=user_query,
            query_type=query_type,
            column_names=column_names,
            conversation_context=conversation_context,
            sql_error=sql_error,
            query_context=query_context,
        )
```

- [ ] **Step 4: Testleri çalıştır — PASS olduğunu doğrula**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py -v
```

Expected: tüm testler PASS

- [ ] **Step 5: Tam test suite — regresyon yok**

```
pytest tests/ -v -x
```

Expected: tüm testler PASS

- [ ] **Step 6: ATOMIK commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py \
        src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(text2sql): inject active context into semantic_extractor_node for pronoun resolution"
```

---

## Son Doğrulama

- [ ] **Tüm başarı kriterlerini kontrol et**

```
pytest tests/ -v
```

Expected: tüm testler PASS — başarı kriterleri:

1. "bunu gün bazında kır" → `test_granularity_only_raw_text_null_no_crash` PASS
2. "kategoriye filtrele → tarihe göre sırala" → `test_modify_sql_node_returns_pre_built_sql` PASS (kategori WHERE korunur)
3. "bu ürün için detay" → `test_modify_sql_node_includes_context_in_prompt` PASS
4. Mevcut testler kırılmaz → tam suite PASS
5. `test_sql_delta_applicator.py` 11 test → PASS
6. `test_context_builder.py` 7 test → PASS
