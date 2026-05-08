# Report Agent Context & Intent Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Konuşma bağlamını doğru taşı — `active_filters` bug'ı kapat, cross-turn entity birikimi ekle, zamir çözmeyi tek noktaya çek, çoğul entity desteği ekle.

**Architecture:** `sql_executor_node` hem `active_filters`'ı doğru kaynaktan dolduracak hem de yeni `accumulated_entities` birikimini güncelleyecek. `context_builder` bu birikimi alıp LLM'e tek bir tutarlı bağlam paketi olarak sunacak. `semantic_extractor` + `modify_sql` bu bağlamı tüketecek.

**Tech Stack:** Python 3.11, LangGraph, Pydantic v2, pytest-asyncio

---

## Etkilenen Dosyalar

| Dosya | Değişiklik |
|-------|-----------|
| `src/graphs/report_agent/state.py` | `accumulated_entities` field ekle |
| `src/graphs/report_agent/subagents/text2sql/state.py` | `accumulated_entities` overlapping field ekle |
| `src/graphs/report_agent/context_builder.py` | 3. parametre + yeni bölüm |
| `src/graphs/report_agent/nodes.py` | classify_intent reset + modify_sql bağlam |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | active_filters fix + executor entity merge + semantic_extractor bağlam |
| `src/graphs/report_agent/prompts.py` | EntityExtractionResult çoğul + ENTITY_EXTRACTOR_PROMPT + classify_intent truncation |
| `src/graphs/report_agent/subagents/text2sql/prompts.py` | SEMANTIC_EXTRACTOR_PROMPT çoğul zamir kuralı |
| `tests/graphs/report/test_sql_executor_active_filters.py` | YENİ — Task 1 test |
| `tests/graphs/report/test_accumulated_entities.py` | YENİ — Task 2-6 testler |
| `tests/graphs/report/test_extract_entity_node.py` | GÜNCELLE — entity_name → entity_names |

---

## Task 1: `active_filters` Bug — `query_plan` → `query_schema`

**Problem:** `sql_executor_node` `state.get("query_plan")` okuyarak `active_filters` dolduruyor. Ama `query_plan` `ReportState`'de tanımsız — hiçbir node yazmıyor. Sonuç: `active_filters` her zaman `[]`. `modify_sql_node` ve `semantic_extractor` hiçbir zaman hangi filtrelerin aktif olduğunu göremez.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1300-1315`
- Create: `tests/graphs/report/test_sql_executor_active_filters.py`

- [ ] **Step 1: Failing testi yaz**

`tests/graphs/report/test_sql_executor_active_filters.py`:
```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from src.graphs.report_agent.subagents.text2sql.nodes import create_sql_executor_node


@pytest.fixture
def mock_results():
    return [{"BranchName": "Ankara", "ToplamCiro": 1000.0}]


def test_active_filters_populated_from_query_schema(mock_results):
    """sql_executor_node active_filters'ı query_schema'dan okumalı, query_plan'dan değil."""
    state = {
        "sql_queries": ["SELECT [BranchName], SUM([RowAmount]) FROM [T] WHERE [BranchName] = 'Ankara'"],
        "retry_count": 0,
        "query_schema": {
            "filters": [
                {
                    "column": "BranchName",
                    "operator": "=",
                    "value": "Ankara",
                    "resolved_value": "Ankara",
                    "value_hint": "ankara",
                    "date_descriptor": None,
                }
            ]
        },
    }

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql_async",
        new=AsyncMock(return_value=mock_results),
    ):
        node = create_sql_executor_node("mssql+pyodbc://dummy")
        result = asyncio.run(node(state))

    assert result["active_filters"] == [{"field": "BranchName", "value": "Ankara"}]
    assert result["error"] is None


def test_active_filters_excludes_date_filters(mock_results):
    """Tarih filtreleri active_filters'a girmemeli — LLM için gereksiz gürültü."""
    state = {
        "sql_queries": ["SELECT * FROM [T]"],
        "retry_count": 0,
        "query_schema": {
            "filters": [
                {
                    "column": "DocumentDate",
                    "operator": ">=",
                    "date_descriptor": {"type": "relative", "unit": "year", "amount": -1},
                    "value": None,
                    "resolved_value": None,
                    "value_hint": "son 1 yıl",
                },
                {
                    "column": "BranchName",
                    "operator": "=",
                    "value": "Istanbul",
                    "resolved_value": "Istanbul",
                    "value_hint": "istanbul",
                    "date_descriptor": None,
                },
            ]
        },
    }

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql_async",
        new=AsyncMock(return_value=mock_results),
    ):
        node = create_sql_executor_node("mssql+pyodbc://dummy")
        result = asyncio.run(node(state))

    assert result["active_filters"] == [{"field": "BranchName", "value": "Istanbul"}]


def test_active_filters_empty_when_no_query_schema(mock_results):
    """query_schema yoksa active_filters boş liste olmalı — hata fırlatmamalı."""
    state = {
        "sql_queries": ["SELECT * FROM [T]"],
        "retry_count": 0,
        # query_schema yok
    }

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql_async",
        new=AsyncMock(return_value=mock_results),
    ):
        node = create_sql_executor_node("mssql+pyodbc://dummy")
        result = asyncio.run(node(state))

    assert result["active_filters"] == []
```

- [ ] **Step 2: Testi çalıştır — FAIL bekliyoruz**

```bash
pytest tests/graphs/report/test_sql_executor_active_filters.py -v
```
Expected: `FAILED` — `active_filters` şu an `[]` döndürüyor.

- [ ] **Step 3: `sql_executor_node` fix uygula**

`src/graphs/report_agent/subagents/text2sql/nodes.py` satır ~1300-1315 içinde:

```python
# ÖNCE (kırık):
query_plan = state.get("query_plan") or {}
active_filters = [
    {"field": f.get("field_hint"), "value": f.get("resolved_value") or f.get("value_hint")}
    for f in query_plan.get("filters", [])
]

# SONRA (düzeltilmiş):
query_schema = state.get("query_schema") or {}
active_filters = [
    {
        "field": f.get("column"),
        "value": f.get("resolved_value") or f.get("value_hint") or f.get("value"),
    }
    for f in query_schema.get("filters", [])
    if not f.get("date_descriptor") and f.get("column")
]
```

- [ ] **Step 4: Testleri çalıştır — PASS bekliyoruz**

```bash
pytest tests/graphs/report/test_sql_executor_active_filters.py -v
```
Expected: 3 test PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/graphs/report/test_sql_executor_active_filters.py
git commit -m "fix(sql-executor): read active_filters from query_schema not query_plan"
```

---

## Task 2: `accumulated_entities` — State Altyapısı

**Problem:** `active_results` her turda overwrite ediliyor. Tur 1'de görülen "LAS VEGAS UC PEYNIRLI BAGEL", tur 2'nin sonuçları gelince kayboluyor. Tur 3'te "bu 3 ürün" dendiğinde sistem tur 1'deki entity'yi göremez.

**Files:**
- Modify: `src/graphs/report_agent/state.py`
- Modify: `src/graphs/report_agent/subagents/text2sql/state.py`
- Create: `tests/graphs/report/test_accumulated_entities.py` (testler Task 4'e kadar adım adım eklenir)

- [ ] **Step 1: `ReportState`'e field ekle**

`src/graphs/report_agent/state.py` içinde `active_filters` satırının altına:

```python
# Conversation Context (MODIFY ve USE_RESULT için)
active_sql: Optional[str]
active_results: Optional[List[Dict[str, Any]]]
active_filters: Optional[List[Dict[str, Any]]]
accumulated_entities: Optional[List[Dict[str, Any]]]  # cross-turn {column, value} listesi; NEW_QUERY'de sıfırlanır
```

Aynı dosyada `create_initial_state()` fonksiyonuna:
```python
accumulated_entities=None,
```

- [ ] **Step 2: `Text2SQLState`'e overlapping field ekle**

`src/graphs/report_agent/subagents/text2sql/state.py` içinde `# --- ReportState overlapping ---` bölümüne `active_results`'ın altına:

```python
active_results: Optional[List[Dict[str, Any]]]
accumulated_entities: Optional[List[Dict[str, Any]]]  # cross-turn entity accumulator
```

- [ ] **Step 3: Temel unit test yaz**

`tests/graphs/report/test_accumulated_entities.py`:
```python
"""Tests for accumulated_entities cross-turn context mechanism."""
from src.graphs.report_agent.state import create_initial_state


def test_initial_state_has_accumulated_entities_none():
    state = create_initial_state()
    assert "accumulated_entities" in state
    assert state["accumulated_entities"] is None
```

- [ ] **Step 4: Testi çalıştır**

```bash
pytest tests/graphs/report/test_accumulated_entities.py -v
```
Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/state.py src/graphs/report_agent/subagents/text2sql/state.py tests/graphs/report/test_accumulated_entities.py
git commit -m "feat(state): add accumulated_entities field to ReportState and Text2SQLState"
```

---

## Task 3: `context_builder.py` — Accumulated Entities Bölümü

**Files:**
- Modify: `src/graphs/report_agent/context_builder.py`

- [ ] **Step 1: Failing test ekle**

`tests/graphs/report/test_accumulated_entities.py` dosyasına ekle:

```python
from src.graphs.report_agent.context_builder import build_query_context_summary


def test_context_builder_includes_accumulated_entities():
    """Accumulated entities, son sorgu sonuçlarından ayrı bölüm olarak görünmeli."""
    accumulated = [
        {"column": "ProductName", "value": "LAS VEGAS UC PEYNIRLI BAGEL"},
        {"column": "ProductName", "value": "LATTE"},
    ]
    result = build_query_context_summary(
        active_results=None,
        active_filters=None,
        accumulated_entities=accumulated,
    )
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in result
    assert "LATTE" in result
    assert "ProductName" in result


def test_context_builder_deduplicates_accumulated_vs_active():
    """Aynı değer hem active_results hem accumulated_entities'de varsa tekrar gösterilmemeli."""
    active_results = [{"ProductName": "LATTE", "ToplamCiro": 45000.0}]
    accumulated = [
        {"column": "ProductName", "value": "LAS VEGAS UC PEYNIRLI BAGEL"},
        {"column": "ProductName", "value": "LATTE"},
    ]
    result = build_query_context_summary(
        active_results=active_results,
        active_filters=None,
        accumulated_entities=accumulated,
    )
    # Her iki kaynak da sonuçta görünmeli
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in result
    assert "LATTE" in result


def test_context_builder_without_accumulated_unchanged():
    """accumulated_entities=None olduğunda eski davranış korunmalı."""
    active_results = [{"BranchName": "Ankara", "ToplamCiro": 1000.0}]
    result = build_query_context_summary(
        active_results=active_results,
        active_filters=None,
        accumulated_entities=None,
    )
    assert "Ankara" in result
    assert "Konuşmada geçen" not in result  # sadece active_results bölümü olmalı
```

- [ ] **Step 2: Testleri çalıştır — FAIL bekliyoruz**

```bash
pytest tests/graphs/report/test_accumulated_entities.py -v
```
Expected: `TypeError` — `build_query_context_summary` 3. parametre almıyor.

- [ ] **Step 3: `context_builder.py` güncelle**

`src/graphs/report_agent/context_builder.py` dosyasını tamamen şu içerikle değiştir:

```python
from __future__ import annotations


def build_query_context_summary(
    active_results: list[dict] | None,
    active_filters: list[dict] | None,
    accumulated_entities: list[dict] | None = None,
    max_rows: int = 10,
    max_values_per_col: int = 5,
) -> str:
    """active_results + active_filters + accumulated_entities → LLM-readable context string."""
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
            parts.append("Son sorgu sonuçlarındaki değerler:\n" + "\n".join(entity_lines))

    if accumulated_entities:
        col_acc: dict[str, list] = {}
        for e in accumulated_entities:
            col = e.get("column", "")
            val = e.get("value", "")
            if col and val:
                col_acc.setdefault(col, [])
                if val not in col_acc[col]:
                    col_acc[col].append(val)

        acc_lines = [
            f"  - {col}: {vals[:10]}"
            for col, vals in col_acc.items()
        ]
        if acc_lines:
            parts.append("Konuşmada geçen tüm değerler (önceki turlar dahil):\n" + "\n".join(acc_lines))

    return "\n".join(parts) if parts else "Önceki bağlam yok."
```

- [ ] **Step 4: Testleri çalıştır — PASS bekliyoruz**

```bash
pytest tests/graphs/report/test_accumulated_entities.py -v
```
Expected: Tüm testler PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/context_builder.py tests/graphs/report/test_accumulated_entities.py
git commit -m "feat(context-builder): add accumulated_entities section to query context summary"
```

---

## Task 4: `sql_executor_node` — Entity Birikimi

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

- [ ] **Step 1: Failing test ekle**

`tests/graphs/report/test_accumulated_entities.py` dosyasına ekle:

```python
import asyncio
from unittest.mock import AsyncMock, patch
from src.graphs.report_agent.subagents.text2sql.nodes import (
    create_sql_executor_node,
    _merge_accumulated_entities,
)


def test_merge_accumulated_entities_adds_new_string_values():
    """Sonuçlardaki yeni string değerler accumulated listesine eklenmeli."""
    existing = [{"column": "ProductName", "value": "LATTE"}]
    results = [
        {"ProductName": "FINCAN CAY", "ToplamCiro": 1000.0},
        {"ProductName": "LATTE", "ToplamCiro": 500.0},  # duplicate — eklenmemeli
    ]
    merged = _merge_accumulated_entities(existing, results)
    values = [e["value"] for e in merged if e["column"] == "ProductName"]
    assert "LATTE" in values
    assert "FINCAN CAY" in values
    assert values.count("LATTE") == 1  # duplicate yok


def test_merge_accumulated_entities_caps_at_max():
    """100 üzeri entity kesilmeli."""
    existing = [{"column": "ProductName", "value": f"P{i}"} for i in range(95)]
    results = [{"ProductName": f"Q{i}", "ToplamCiro": float(i)} for i in range(20)]
    merged = _merge_accumulated_entities(existing, results)
    assert len(merged) <= 100


def test_merge_accumulated_entities_skips_non_string():
    """Sayısal değerler entity olarak birikmemeli."""
    results = [{"ProductName": "LATTE", "ToplamCiro": 45000.0, "Quantity": 100}]
    merged = _merge_accumulated_entities(None, results)
    cols = [e["column"] for e in merged]
    assert "ToplamCiro" not in cols
    assert "Quantity" not in cols
    assert "ProductName" in cols


def test_sql_executor_node_updates_accumulated_entities():
    """Başarılı SQL sonrası accumulated_entities güncellenmiş olmalı."""
    existing = [{"column": "ProductName", "value": "LAS VEGAS UC PEYNIRLI BAGEL"}]
    results = [{"ProductName": "LATTE", "ToplamCiro": 45000.0}]
    state = {
        "sql_queries": ["SELECT * FROM T"],
        "retry_count": 0,
        "query_schema": {},
        "accumulated_entities": existing,
    }

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql_async",
        new=AsyncMock(return_value=results),
    ):
        node = create_sql_executor_node("mssql+pyodbc://dummy")
        output = asyncio.run(node(state))

    acc = output["accumulated_entities"]
    values = [e["value"] for e in acc]
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in values  # önceki tur korundu
    assert "LATTE" in values                         # yeni tur eklendi
```

- [ ] **Step 2: Testleri çalıştır — FAIL bekliyoruz**

```bash
pytest tests/graphs/report/test_accumulated_entities.py::test_merge_accumulated_entities_adds_new_string_values tests/graphs/report/test_accumulated_entities.py::test_sql_executor_node_updates_accumulated_entities -v
```
Expected: `ImportError` — `_merge_accumulated_entities` henüz yok.

- [ ] **Step 3: `_merge_accumulated_entities` fonksiyonu ekle**

`src/graphs/report_agent/subagents/text2sql/nodes.py` içinde `_execute_sql_async` fonksiyonundan hemen önce:

```python
def _merge_accumulated_entities(
    existing: list[dict] | None,
    results: list[dict],
    max_total: int = 100,
) -> list[dict]:
    """Sonuçlardaki string değerleri cross-turn entity listesine birleştir."""
    current = list(existing or [])
    existing_set = {(e["column"], e["value"]) for e in current}

    for row in results[:20]:  # tüm satırları değil sample al
        for col, val in row.items():
            if isinstance(val, str) and val.strip() and len(val) < 200:
                key = (col, val)
                if key not in existing_set:
                    current.append({"column": col, "value": val})
                    existing_set.add(key)

    return current[-max_total:]  # en son max_total kadar tut
```

- [ ] **Step 4: `sql_executor_node` return dict'ine ekle**

`sql_executor_node` içinde başarı durumundaki return dict'e:

```python
return {
    "results": results,
    "error": None,
    "sql_error": None,
    "retry_count": 0,
    "active_sql": sql,
    "active_results": results[:10],
    "active_filters": active_filters,
    "accumulated_entities": _merge_accumulated_entities(   # ← YENİ
        state.get("accumulated_entities"),
        results,
    ),
}
```

- [ ] **Step 5: Testleri çalıştır — PASS bekliyoruz**

```bash
pytest tests/graphs/report/test_accumulated_entities.py -v
```
Expected: Tüm testler PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/graphs/report/test_accumulated_entities.py
git commit -m "feat(sql-executor): accumulate cross-turn entities after successful SQL execution"
```

---

## Task 5: `classify_intent_node` — NEW_QUERY'de Sıfırla

**Neden:** Kullanıcı tamamen farklı bir konu açtığında önceki entity birikimi alakasız olur. Ör: "LAS VEGAS" için analiz yaptıktan sonra "Ankara şubelerini göster" dediğinde eski ürünler bağlamda görünmemeli.

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`

- [ ] **Step 1: Failing test ekle**

`tests/graphs/report/test_accumulated_entities.py` dosyasına ekle:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import HumanMessage
from src.graphs.report_agent.nodes import create_classify_intent_node
from src.graphs.report_agent.prompts import IntentClassificationResult


def _make_classify_node(intent_type: str, query_type: str = "RANKING"):
    mock_llm = MagicMock()
    result = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=0.95,
        wants_visualization=False,
        time_breakdown=False,
    )
    mock_structured = MagicMock()
    mock_structured.ainvoke = AsyncMock(return_value=result)
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
    return create_classify_intent_node(mock_llm)


def test_classify_intent_resets_accumulated_entities_on_new_query():
    """NEW_QUERY intent'inde accumulated_entities sıfırlanmalı."""
    node = _make_classify_node("NEW_QUERY")
    state = {
        "messages": [HumanMessage(content="farklı bir soru")],
        "active_sql": None,
        "active_results": [],
        "accumulated_entities": [{"column": "ProductName", "value": "LATTE"}],
        "_clarification_count": 0,
        "_skip_vague_check": False,
    }
    result = asyncio.run(node(state))
    assert result["accumulated_entities"] is None


def test_classify_intent_preserves_accumulated_entities_on_modify_query():
    """MODIFY_QUERY'de accumulated_entities korunmalı."""
    node = _make_classify_node("MODIFY_QUERY")
    accumulated = [{"column": "ProductName", "value": "LATTE"}]
    state = {
        "messages": [HumanMessage(content="filtrele")],
        "active_sql": "SELECT * FROM T",
        "active_results": [],
        "accumulated_entities": accumulated,
        "_clarification_count": 0,
        "_skip_vague_check": False,
    }
    result = asyncio.run(node(state))
    assert result["accumulated_entities"] == accumulated
```

- [ ] **Step 2: Testleri çalıştır — FAIL bekliyoruz**

```bash
pytest tests/graphs/report/test_accumulated_entities.py::test_classify_intent_resets_accumulated_entities_on_new_query tests/graphs/report/test_accumulated_entities.py::test_classify_intent_preserves_accumulated_entities_on_modify_query -v
```
Expected: FAILED — `accumulated_entities` return_dict'te yok.

- [ ] **Step 3: `classify_intent_node` return_dict'e ekle**

`src/graphs/report_agent/nodes.py` içinde `classify_intent_node` fonksiyonunun `return_dict` tanımına:

```python
return_dict = {
    "user_query": user_query,
    # ... mevcut alanlar ...
    "accumulated_entities": None if result.intent_type == "NEW_QUERY" else state.get("accumulated_entities"),  # ← YENİ
}
```

- [ ] **Step 4: Testleri çalıştır — PASS bekliyoruz**

```bash
pytest tests/graphs/report/test_accumulated_entities.py -v
```
Expected: Tüm testler PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_accumulated_entities.py
git commit -m "feat(classify-intent): reset accumulated_entities on NEW_QUERY intent"
```

---

## Task 6: Node Consumers — Bağlamı Kullan

`semantic_extractor_node` ve `modify_sql_node` artık `accumulated_entities`'i bağlam paketine dahil etmeli.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py` (semantic_extractor)
- Modify: `src/graphs/report_agent/nodes.py` (modify_sql)

- [ ] **Step 1: `semantic_extractor_node` güncelle**

`src/graphs/report_agent/subagents/text2sql/nodes.py` içinde `semantic_extractor_node` fonksiyonunda:

```python
# ÖNCE:
query_context = build_query_context_summary(
    state.get("active_results"),
    state.get("active_filters"),
)

# SONRA:
query_context = build_query_context_summary(
    state.get("active_results"),
    state.get("active_filters"),
    state.get("accumulated_entities"),   # ← YENİ
)
```

- [ ] **Step 2: `modify_sql_node` güncelle**

`src/graphs/report_agent/nodes.py` içinde `modify_sql_node` fonksiyonunda:

```python
# ÖNCE:
query_context = build_query_context_summary(
    state.get("active_results"),
    state.get("active_filters"),
)

# SONRA:
query_context = build_query_context_summary(
    state.get("active_results"),
    state.get("active_filters"),
    state.get("accumulated_entities"),   # ← YENİ
)
```

- [ ] **Step 3: Tüm testleri çalıştır**

```bash
pytest tests/graphs/report/ -v
```
Expected: Tüm testler PASSED.

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py src/graphs/report_agent/nodes.py
git commit -m "feat(nodes): pass accumulated_entities to context builder in semantic_extractor and modify_sql"
```

---

## Task 7: `SEMANTIC_EXTRACTOR_PROMPT` — Çoğul Zamir Kuralı

**Problem:** Mevcut kural "en uygununu seç" → tekil seçim. "Bu 3 ürün" = çoğul referans → 3 ayrı `filter_value` entity üretilmeli.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py`

- [ ] **Step 1: Mevcut zamir kuralını bul ve güncelle**

`src/graphs/report_agent/subagents/text2sql/prompts.py` içinde şu metni bul:

```python
Kullanıcı "bu ürün", "bu şube", "bunu", "şunu" gibi referans kullanıyorsa →
yukarıdaki değerlerden en uygununu seç, direkt isme çevir.

Örnek: "bu ürün için detay" + bağlamda ProductName: ["Latte", "Espresso"]
→ entity: {{raw_text: "Latte", entity_type: "filter_value", column_hint: "ProductName"}}
```

Bu metni şu şekilde değiştir:

```python
Kullanıcı "bu ürün", "bu şube", "bunu", "şunu" gibi referans kullanıyorsa →
yukarıdaki değerlerden en uygununu seç, direkt isme çevir.

Çoğul referanslarda ("bu 3 ürün", "bu şubeler", "bunların hepsi", "bu ikisi") →
bağlamdaki TÜM ilgili değerleri AYRI filter_value entity olarak üret. Kaç entity isteniyorsa o kadar üret.

Örnekler:
"bu ürün için detay" + bağlamda ProductName: ["Latte", "Espresso"]
→ entity: {{raw_text: "Latte", entity_type: "filter_value", column_hint: "ProductName"}}

"bu 3 ürünün satışları" + bağlamda ProductName: ["LAS VEGAS UC PEYNIRLI BAGEL", "LATTE", "FINCAN CAY"]
→ entity: {{raw_text: "LAS VEGAS UC PEYNIRLI BAGEL", entity_type: "filter_value", column_hint: "ProductName"}}
→ entity: {{raw_text: "LATTE", entity_type: "filter_value", column_hint: "ProductName"}}
→ entity: {{raw_text: "FINCAN CAY", entity_type: "filter_value", column_hint: "ProductName"}}
```

- [ ] **Step 2: Tüm testleri çalıştır — regresyon yok**

```bash
pytest tests/ -v --ignore=tests/integration
```
Expected: Tüm testler PASSED (prompt değişikliği unit testleri kırmaz).

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "fix(semantic-extractor): add plural pronoun rule — generate all filter_value entities for multi-entity references"
```

---

## Task 8: `EntityExtractionResult` — Çoğul Entity Desteği

**Problem:** `extract_entity_node` tekil `entity_name: str` üretiyor. "Bu 3 ürünü karşılaştır" gibi sorgularda sadece 1 entity `new_query_seed`'e gömülüyor, `term_resolver + value_resolver` pipeline bypass ediliyor.

**Files:**
- Modify: `src/graphs/report_agent/prompts.py` (model + prompt)
- Modify: `src/graphs/report_agent/nodes.py` (extract_entity_node)
- Modify: `tests/graphs/report/test_extract_entity_node.py` (mevcut testleri güncelle)
- Create: `tests/graphs/report/test_extract_entity_node.py` içine yeni testler

- [ ] **Step 1: Mevcut testleri oku**

```bash
cat tests/graphs/report/test_extract_entity_node.py
```

`entity_name` kullanan test satırlarını not et — bunları güncelleyeceksin.

- [ ] **Step 2: `EntityExtractionResult` modelini güncelle**

`src/graphs/report_agent/prompts.py` içinde:

```python
# ÖNCE:
class EntityExtractionResult(BaseModel):
    """USE_RESULT(A) — önceki result'tan entity çekip yeni sorgu seed'i oluşturur."""
    entity_name: str
    entity_type: str        # product | branch | customer | category | period
    new_query_seed: str     # Text2SQL'e gönderilecek doğal dil sorgu cümlesi

# SONRA:
class EntityExtractionResult(BaseModel):
    """USE_RESULT(A) — önceki result'tan entity çekip yeni sorgu seed'i oluşturur."""
    entity_names: List[str]   # Seçilen değerlerin tam adları — tekil için [tek_isim]
    entity_type: str           # product | branch | customer | category | period
    new_query_seed: str        # Text2SQL'e gönderilecek doğal dil sorgu cümlesi
```

- [ ] **Step 3: `ENTITY_EXTRACTOR_PROMPT` güncelle**

`src/graphs/report_agent/prompts.py` içinde `ENTITY_EXTRACTOR_PROMPT`:

```python
ENTITY_EXTRACTOR_PROMPT = """Kullanıcı önceki sorgu sonuçlarından bir veya daha fazla entity seçmek istiyor.

## ÖNCEKİ SONUÇLAR (ilk 5 satır)
{active_results}

## KULLANICI İSTEĞİ
{user_query}

## GÖREV
Kullanıcının hangi entity'leri seçtiğini belirle ve yeni bir sorgu için seed oluştur.

- entity_names: Seçilen değerlerin tam adları listesi (ör: ["iPhone 15 Pro", "Samsung S24"])
  Tekil referans için tek elemanlı liste: ["Ankara Şubesi"]
  Çoğul referans için tüm seçilenleri listele: ["LATTE", "FINCAN CAY", "LAS VEGAS UC PEYNIRLI BAGEL"]
- entity_type: product | branch | customer | category | period
- new_query_seed: Bu entity'ler için doğal dil sorgu cümlesi (Text2SQL'e gönderilecek)
  Örnek: "LATTE, FINCAN CAY ve LAS VEGAS UC PEYNIRLI BAGEL ürünlerinin son 1 yıldaki satış detayları"
"""
```

- [ ] **Step 4: `extract_entity_node` güncelle**

`src/graphs/report_agent/nodes.py` içinde `extract_entity_node`:

```python
async def extract_entity_node(state: dict) -> dict:
    active_results = state.get("active_results") or []
    if not active_results:
        logger.warning("[EXTRACT_ENTITY] No results, fallback to NEW_QUERY")
        return {"intent_type": "NEW_QUERY"}

    prompt = ENTITY_EXTRACTOR_PROMPT.format(
        active_results=json.dumps(active_results[:5], ensure_ascii=False, indent=2),
        user_query=state.get("user_query", ""),
    )

    result: EntityExtractionResult = await structured_llm.ainvoke(prompt)
    logger.info(f"[EXTRACT_ENTITY] {result.entity_names} ({result.entity_type})")

    if state.get("use_result_type") == "modify_context":
        names_str = ", ".join(result.entity_names)
        original_query = state.get("user_query", "")
        enriched = f"{names_str} için: {original_query}"
        logger.info(f"[EXTRACT_ENTITY] modify_context → enriched query: {enriched[:80]}")
        return {"user_query": enriched}

    return {"user_query": result.new_query_seed}
```

- [ ] **Step 5: Mevcut testleri `entity_name` → `entity_names` olarak güncelle**

`tests/graphs/report/test_extract_entity_node.py` içindeki tüm `entity_name=` ifadelerini `entity_names=["..."]` ile değiştir.

- [ ] **Step 6: Yeni çoğul test ekle**

`tests/graphs/report/test_extract_entity_node.py` dosyasına:

```python
def test_extract_entity_plural_enriches_query(make_node_with_result):
    """Çoğul entity seçiminde tüm isimler query'ye yansımalı."""
    from src.graphs.report_agent.prompts import EntityExtractionResult

    result = EntityExtractionResult(
        entity_names=["LATTE", "FINCAN CAY", "LAS VEGAS UC PEYNIRLI BAGEL"],
        entity_type="product",
        new_query_seed="LATTE, FINCAN CAY ve LAS VEGAS UC PEYNIRLI BAGEL ürünlerinin günlük satışı",
    )
    node = make_node_with_result(result)
    state = {
        "active_results": [
            {"ProductName": "LATTE", "ToplamCiro": 45000.0},
            {"ProductName": "FINCAN CAY", "ToplamCiro": 26000.0},
        ],
        "user_query": "bu 3 ürünü grafik olarak göster",
        "use_result_type": "new_query",
    }
    import asyncio
    output = asyncio.run(node(state))
    assert "LATTE" in output["user_query"]
    assert "FINCAN CAY" in output["user_query"]
```

- [ ] **Step 7: Testleri çalıştır**

```bash
pytest tests/graphs/report/test_extract_entity_node.py -v
```
Expected: Tüm testler PASSED.

- [ ] **Step 8: Commit**

```bash
git add src/graphs/report_agent/prompts.py src/graphs/report_agent/nodes.py tests/graphs/report/test_extract_entity_node.py
git commit -m "feat(extract-entity): support plural entity extraction — entity_names list replaces entity_name"
```

---

## Task 9: `classify_intent_node` — Konuşma Geçmişi Truncation Düzeltmesi

**Problem:** `classify_intent_node` konuşma geçmişini `msg.content[:100]` ile kesiyor. Markdown tablo yanıtları veya uzun ürün isimleri bu limitin içine sığmıyor. LLM `MODIFY_QUERY` / `USE_RESULT` kararını eski mesajların içeriğini göremeden veriyor.

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`

- [ ] **Step 1: Değişikliği uygula**

`src/graphs/report_agent/nodes.py` içinde `classify_intent_node` fonksiyonundaki history döngüsü:

```python
# ÖNCE:
for msg in messages[-4:]:
    if isinstance(msg, HumanMessage):
        history_parts.append(f"Kullanıcı: {msg.content[:100]}")
    elif isinstance(msg, AIMessage):
        history_parts.append(f"Asistan: {msg.content[:100]}")

# SONRA:
for msg in messages[-6:]:   # 4 → 6 mesaj (3 tam tur)
    if isinstance(msg, HumanMessage):
        history_parts.append(f"Kullanıcı: {msg.content[:400]}")   # 100 → 400
    elif isinstance(msg, AIMessage):
        # Grafik yanıtlarda content summary_text — tablolarda markdown
        # 400 karakter çoğu ürün/şube adını kapsar
        history_parts.append(f"Asistan: {msg.content[:400]}")     # 100 → 400
```

- [ ] **Step 2: Tüm testleri çalıştır**

```bash
pytest tests/ -v --ignore=tests/integration
```
Expected: Tüm testler PASSED.

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/nodes.py
git commit -m "fix(classify-intent): expand conversation history window from 4x100 to 6x400 chars"
```

---

## Self-Review

### Spec Coverage

| Bug | Task |
|-----|------|
| `active_filters` daima boş (query_plan bug) | Task 1 ✓ |
| Cross-turn entity kaybı (active_results overwrite) | Task 2-6 ✓ |
| Çoğul zamir kuralı eksik (tekil → çoğul) | Task 7 ✓ |
| `extract_entity_node` tekil tasarım | Task 8 ✓ |
| `classify_intent` conversation truncation | Task 9 ✓ |

### Bağımlılık Sırası

```
Task 1 (bağımsız)
Task 2 → Task 3 → Task 4 → Task 5 → Task 6  (sıralı)
Task 7 (Task 6'dan bağımsız, prompt değişikliği)
Task 8 (bağımsız)
Task 9 (bağımsız)
```

Tasks 1, 7, 8, 9 birbirinden bağımsız — paralel çalışılabilir.
Tasks 2-6 sıralı bağımlı — state altyapısı olmadan consumer'lar çalışmaz.

### Tip Tutarlılığı

- `accumulated_entities: Optional[List[Dict[str, Any]]]` — state.py, text2sql/state.py, ve `_merge_accumulated_entities` dönüş tipi birbiriyle tutarlı.
- `entity_names: List[str]` — `EntityExtractionResult`, `ENTITY_EXTRACTOR_PROMPT`, ve `extract_entity_node` içinde tutarlı kullanım.
- `build_query_context_summary` signature: `(active_results, active_filters, accumulated_entities=None)` — 3. parametre optional, mevcut çağrılar kırılmaz.
