# Compute Agent: LLM Tool Selection + Tool Execution

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `compute_results_node`'u LLM-assisted tool-based yapıya dönüştür — min/max sorgularında ilişkili satır bilgisini (ürün adı, şube vb.) cevaba dahil et.

**Architecture:** Mevcut `compute_results_node` (pure Python) yerine hybrid node: (1) LLM structured output ile tool seçimi + hedef kolon + gösterilecek kolonlar belirlenir, (2) seçilen tool pure Python ile çalıştırılır, (3) sonuç formatlanır. Graph routing değişmez, sadece node iç yapısı değişir.

**Tech Stack:** Python, LangGraph, Pydantic structured output

---

## Context

**Mevcut sorun:**
- Kullanıcı: "Bu ürünlerin en çok ciro yapan nedir?"
- Beklenen: "**LATTE** — 1,791,610.08 TL"
- Gelen: "ToplamCiro → Maksimum: 1791610.08" (hangi ürün olduğu kayıp)

**Kök neden:** `compute_results_node` sadece sayısal değer hesaplıyor, ilişkili satır bilgisini (ProductName) döndürmüyor. Hangi kolon üzerinde işlem yapacağını da LLM'den değil, tüm sayısal kolonları iterate ederek yapıyor.

---

## Task 1: Pydantic model + prompt ekle

**Files:**
- Modify: `src/graphs/report_agent/prompts.py`

### Step 1: Add ComputeToolSelection model and COMPUTE_TOOL_PROMPT

Dosyanın sonuna (`ENTITY_EXTRACTOR_PROMPT`'tan sonra) ekle:

```python
class ComputeToolSelection(BaseModel):
    """LLM compute tool seçimi — hangi işlem, hangi kolon, hangi kolonlar gösterilsin."""

    tool: Literal["find_max", "find_min", "sum_column", "avg_column", "count_rows"]
    target_column: str                # işlem yapılacak sayısal kolon (e.g., "ToplamCiro")
    display_columns: List[str]        # sonuçta gösterilecek kolonlar (e.g., ["ProductName", "ToplamCiro"])


COMPUTE_TOOL_PROMPT = """Kullanıcı önceki sorgu sonuçları üzerinde bir hesaplama istiyor.

## MEVCUT SONUÇLAR (ilk 5 satır)
{active_results}

## KOLON BİLGİSİ
Sayısal kolonlar: {numeric_columns}
Metin kolonları: {text_columns}

## KULLANICI İSTEĞİ
{user_query}

## GÖREV
Kullanıcının isteğine göre doğru tool'u seç:
- find_max: "en çok", "en yüksek", "en fazla", "maksimum", "birinci" → ilgili satırı bul
- find_min: "en az", "en düşük", "minimum", "sonuncu" → ilgili satırı bul
- sum_column: "topla", "toplam", "toplam ne kadar" → kolondaki tüm değerleri topla
- avg_column: "ortalama", "ortalama nedir" → kolondaki değerlerin ortalaması
- count_rows: "kaç tane", "kaç satır", "sayısı" → satır sayısı

## KURALLAR
- target_column: İşlem yapılacak sayısal kolon adını AYNEN yaz (büyük/küçük harf dahil)
- display_columns: Kullanıcının görmek isteyeceği kolonları seç
  → find_max/find_min: İlişkili metin kolonu + hedef sayısal kolon (ör: ["ProductName", "ToplamCiro"])
  → sum_column/avg_column: Sadece hedef kolon (ör: ["ToplamCiro"])
  → count_rows: Boş liste []
- Birden fazla sayısal kolon varsa, kullanıcının bahsettiği kolonu seç (ciro=amount, adet=quantity)
"""
```

### Step 2: Update imports at top of prompts.py

`Literal` import'unu ekle (zaten `from typing import List, Literal, Optional` var — kontrol et, yoksa ekle).

### Step 3: Commit

```bash
git add src/graphs/report_agent/prompts.py
git commit -m "feat: add ComputeToolSelection model and COMPUTE_TOOL_PROMPT"
```

---

## Task 2: Refactor compute_results_node — tool execution + LLM selection

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:225-268`
- Test: `tests/graphs/report/test_compute_results_node.py`

### Step 1: Write failing tests

`tests/graphs/report/test_compute_results_node.py` dosyasını tamamen yeniden yaz:

```python
"""Tests for compute_results_node — LLM tool selection + pure Python execution."""
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def sample_results():
    return [
        {"ProductName": "Vegan Dürüm", "TotalQuantity": 100.0, "TotalAmount": 500.0},
        {"ProductName": "Klasik Dürüm", "TotalQuantity": 200.0, "TotalAmount": 1000.0},
        {"ProductName": "Tavuk Dürüm", "TotalQuantity": 150.0, "TotalAmount": 750.0},
    ]


# ---------------------------------------------------------------------------
# Tool execution unit tests (pure Python, no LLM)
# ---------------------------------------------------------------------------
def test_tool_find_max(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "find_max", "TotalAmount", ["ProductName", "TotalAmount"])
    assert result["row"]["ProductName"] == "Klasik Dürüm"
    assert result["row"]["TotalAmount"] == 1000.0
    assert result["value"] == 1000.0


def test_tool_find_min(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "find_min", "TotalAmount", ["ProductName", "TotalAmount"])
    assert result["row"]["ProductName"] == "Vegan Dürüm"
    assert result["value"] == 500.0


def test_tool_sum(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "sum_column", "TotalAmount", ["TotalAmount"])
    assert result["value"] == 2250.0
    assert result["row"] is None


def test_tool_avg(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "avg_column", "TotalAmount", ["TotalAmount"])
    assert result["value"] == 750.0
    assert result["row"] is None


def test_tool_count(sample_results):
    from src.graphs.report_agent.nodes import _execute_compute_tool

    result = _execute_compute_tool(sample_results, "count_rows", "TotalAmount", [])
    assert result["value"] == 3
    assert result["row"] is None


# ---------------------------------------------------------------------------
# Full node tests (mocked LLM)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_compute_node_find_max_includes_row(sample_results):
    """find_max cevabında ilişkili satır bilgisi (ProductName) olmalı."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    class FakeSelection:
        tool = "find_max"
        target_column = "TotalAmount"
        display_columns = ["ProductName", "TotalAmount"]

    mock_structured = MagicMock()
    mock_structured.ainvoke = lambda _: __import__('asyncio').coroutine(lambda: FakeSelection())()

    # Python 3.12+ compatible async mock
    async def fake_ainvoke(prompt):
        return FakeSelection()
    mock_structured.ainvoke = fake_ainvoke

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    node_fn = create_compute_results_node(mock_llm)
    state = {"active_results": sample_results, "user_query": "en çok satış yapan ürün"}
    result = await node_fn(state)

    assert result["error"] is None
    assert "Klasik Dürüm" in result["final_response"]
    assert "1000" in result["final_response"] or "1,000" in result["final_response"]


@pytest.mark.asyncio
async def test_compute_node_sum(sample_results):
    """sum cevabı toplam değeri içermeli."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    class FakeSelection:
        tool = "sum_column"
        target_column = "TotalAmount"
        display_columns = ["TotalAmount"]

    async def fake_ainvoke(prompt):
        return FakeSelection()

    mock_structured = MagicMock()
    mock_structured.ainvoke = fake_ainvoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    node_fn = create_compute_results_node(mock_llm)
    state = {"active_results": sample_results, "user_query": "toplam tutar"}
    result = await node_fn(state)

    assert result["error"] is None
    assert "2250" in result["final_response"] or "2,250" in result["final_response"]


@pytest.mark.asyncio
async def test_compute_node_empty_results():
    """Boş sonuç → hata mesajı."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    mock_llm = MagicMock()
    node_fn = create_compute_results_node(mock_llm)
    state = {"active_results": [], "user_query": "topla"}
    result = await node_fn(state)

    assert "bulunamadı" in result["final_response"].lower()


@pytest.mark.asyncio
async def test_compute_node_no_numeric_cols():
    """Sayısal kolon yoksa → hata mesajı."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    mock_llm = MagicMock()
    node_fn = create_compute_results_node(mock_llm)
    state = {
        "active_results": [{"ProductName": "A"}, {"ProductName": "B"}],
        "user_query": "topla",
    }
    result = await node_fn(state)

    assert "sayısal" in result["final_response"].lower()


@pytest.mark.asyncio
async def test_compute_node_fallback_without_llm(sample_results):
    """LLM hata verirse compute_operation fallback'i çalışmalı."""
    from src.graphs.report_agent.nodes import create_compute_results_node

    async def failing_ainvoke(prompt):
        raise Exception("LLM error")

    mock_structured = MagicMock()
    mock_structured.ainvoke = failing_ainvoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    node_fn = create_compute_results_node(mock_llm)
    state = {
        "active_results": sample_results,
        "user_query": "en çok satan",
        "compute_operation": "max",
    }
    result = await node_fn(state)

    # Fallback: eski davranış — en azından sayısal değer dönsün
    assert result["error"] is None
    assert "200" in result["final_response"]  # TotalQuantity max
```

Run: `python -m pytest tests/graphs/report/test_compute_results_node.py -v`
Expected: FAIL — `_execute_compute_tool` ve `create_compute_results_node` bulunamaz.

### Step 2: Implement _execute_compute_tool and create_compute_results_node

`src/graphs/report_agent/nodes.py` — compute bölümünü refactor et:

```python
# =============================================================================
# COMPUTE TOOLS — Pure Python, deterministic
# =============================================================================
_COMPUTE_OP_LABELS = {
    "sum":   "Toplam",
    "avg":   "Ortalama",
    "count": "Adet",
    "min":   "Minimum",
    "max":   "Maksimum",
}

_TOOL_TO_OP = {
    "find_max": "max", "find_min": "min",
    "sum_column": "sum", "avg_column": "avg", "count_rows": "count",
}


def _execute_compute_tool(
    results: list[dict],
    tool: str,
    target_column: str,
    display_columns: list[str],
) -> dict:
    """
    Pure Python tool execution. Returns:
      {"value": <computed>, "row": <full_row_or_None>, "display": {col: val}}
    """
    values = [
        (i, row[target_column])
        for i, row in enumerate(results)
        if target_column in row
        and row[target_column] is not None
        and isinstance(row[target_column], (int, float))
    ]

    if not values and tool != "count_rows":
        return {"value": None, "row": None, "display": {}}

    if tool == "find_max":
        idx, val = max(values, key=lambda x: x[1])
        row = results[idx]
        display = {c: row.get(c) for c in display_columns}
        return {"value": val, "row": row, "display": display}

    elif tool == "find_min":
        idx, val = min(values, key=lambda x: x[1])
        row = results[idx]
        display = {c: row.get(c) for c in display_columns}
        return {"value": val, "row": row, "display": display}

    elif tool == "sum_column":
        total = sum(v for _, v in values)
        return {"value": total, "row": None, "display": {target_column: total}}

    elif tool == "avg_column":
        avg = sum(v for _, v in values) / len(values)
        return {"value": avg, "row": None, "display": {target_column: avg}}

    elif tool == "count_rows":
        count = len(results)
        return {"value": count, "row": None, "display": {"count": count}}

    return {"value": None, "row": None, "display": {}}


def _format_compute_result(tool: str, tool_result: dict, display_columns: list[str]) -> str:
    """Tool sonucunu insan-okunabilir formata çevir."""
    val = tool_result["value"]
    if val is None:
        return "Hesaplama yapılamadı."

    if tool in ("find_max", "find_min"):
        label = "En yüksek" if tool == "find_max" else "En düşük"
        row = tool_result["row"] or {}
        # Metin kolonlarını bul (hedef sayısal kolon dışındakiler)
        text_parts = []
        num_parts = []
        for col in display_columns:
            v = row.get(col)
            if v is None:
                continue
            if isinstance(v, (int, float)):
                num_parts.append(f"{col}: {v:,.2f}")
            else:
                text_parts.append(str(v))

        entity = ", ".join(text_parts) if text_parts else ""
        value_str = " | ".join(num_parts) if num_parts else f"{val:,.2f}"

        if entity:
            return f"{label}: **{entity}** — {value_str}"
        return f"{label}: {value_str}"

    elif tool == "count_rows":
        return f"Toplam satır sayısı: **{val:,}**"

    else:
        op_label = "Toplam" if tool == "sum_column" else "Ortalama"
        formatted = f"{val:,.2f}" if isinstance(val, float) else f"{val:,}"
        return f"{op_label}: **{formatted}**"


def create_compute_results_node(llm) -> Callable:
    """Hybrid compute node: LLM tool selection + pure Python execution."""

    from src.graphs.report_agent.prompts import ComputeToolSelection, COMPUTE_TOOL_PROMPT
    structured_llm = llm.with_structured_output(ComputeToolSelection)

    async def compute_results_node(state: dict) -> dict:
        results = state.get("active_results") or []

        if not results:
            return {
                "final_response": "Hesaplama için önceki sorgu sonuçları bulunamadı.",
                "error": None,
            }

        # Kolon tipleri
        numeric_cols = [
            col for col in results[0]
            if isinstance(results[0].get(col), (int, float))
            and not isinstance(results[0].get(col), bool)
        ]
        text_cols = [col for col in results[0] if col not in numeric_cols]

        if not numeric_cols:
            return {
                "final_response": "Sonuçlarda sayısal kolon bulunamadı.",
                "error": None,
            }

        # Phase 1: LLM tool selection
        try:
            prompt = COMPUTE_TOOL_PROMPT.format(
                active_results=json.dumps(results[:5], ensure_ascii=False, default=str),
                numeric_columns=", ".join(numeric_cols),
                text_columns=", ".join(text_cols),
                user_query=state.get("user_query", ""),
            )
            selection = await structured_llm.ainvoke(prompt)
            tool = selection.tool
            target = selection.target_column
            display = selection.display_columns
            logger.info(f"[COMPUTE] LLM selected: {tool}({target}) display={display}")
        except Exception as e:
            # Fallback: compute_operation state field'ından eski davranış
            logger.warning(f"[COMPUTE] LLM failed ({e}), falling back to compute_operation")
            op = state.get("compute_operation") or "sum"
            return _compute_fallback(results, numeric_cols, op)

        # Phase 2: Tool execution
        tool_result = _execute_compute_tool(results, tool, target, display)

        # Phase 3: Format
        response = _format_compute_result(tool, tool_result, display)
        logger.info(f"[COMPUTE] Response: {response[:100]}")

        return {"final_response": response, "error": None}

    return compute_results_node


def _compute_fallback(results: list[dict], numeric_cols: list[str], operation: str) -> dict:
    """LLM başarısız olursa eski pure-Python davranış."""
    lines = []
    for col in numeric_cols:
        values = [
            row[col] for row in results
            if row.get(col) is not None and isinstance(row.get(col), (int, float))
        ]
        if not values:
            continue

        if operation == "sum":
            computed = sum(values)
        elif operation == "avg":
            computed = sum(values) / len(values)
        elif operation == "count":
            computed = len(values)
        elif operation == "min":
            computed = min(values)
        elif operation == "max":
            computed = max(values)
        else:
            computed = sum(values)

        label = _COMPUTE_OP_LABELS.get(operation, operation.upper())
        formatted = f"{computed:.2f}" if isinstance(computed, float) else f"{computed:,}"
        lines.append(f"**{col}** → {label}: {formatted}")

    response = "\n".join(lines) if lines else "Hesaplama yapılamadı."
    return {"final_response": response, "error": None}
```

Eski `compute_results_node` fonksiyonu ve `_COMPUTE_OP_LABELS` sabitini sil, yukarıdakiyle değiştir.

### Step 3: Run tests

Run: `python -m pytest tests/graphs/report/test_compute_results_node.py -v`
Expected: PASS

### Step 4: Commit

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_compute_results_node.py
git commit -m "feat: refactor compute_results_node with LLM tool selection"
```

---

## Task 3: Graph'ta node constructor'ı güncelle

**Files:**
- Modify: `src/graphs/report_agent/graph.py:19-25, 87`

### Step 1: Update import

```python
# Eski:
from src.graphs.report_agent.nodes import (
    build_response_node,
    compute_results_node,           # ← sil
    create_classify_intent_node,
    create_extract_entity_node,
    create_modify_sql_node,
)

# Yeni:
from src.graphs.report_agent.nodes import (
    build_response_node,
    create_compute_results_node,    # ← factory function
    create_classify_intent_node,
    create_extract_entity_node,
    create_modify_sql_node,
)
```

### Step 2: Update node registration

```python
# Eski (line 87):
graph.add_node("compute_results", compute_results_node)

# Yeni:
graph.add_node("compute_results", create_compute_results_node(llm))
```

### Step 3: Run all tests

Run: `python -m pytest tests/graphs/report/ --ignore=tests/graphs/report/test_enhanced_hitl.py --ignore=tests/graphs/report/test_llm_components.py --ignore=tests/graphs/report/test_llm_integration.py -v`
Expected: All PASS

### Step 4: Commit

```bash
git add src/graphs/report_agent/graph.py
git commit -m "feat: wire create_compute_results_node with LLM in graph"
```

---

## Verification

Test senaryosu:
1. "Geçen ay en çok satış yapılan gün hangisidir?" → tarih döner
2. "Bu gün gelen satışları ürünlere göre toplam satışlarını verir misin" → ürün listesi
3. "Bu ürünlerin en çok ciro yapan nedir?" → **LATTE — 1,791,610.08 TL** (ürün adı + değer)
4. "Toplamları ne kadar?" → **Toplam: X TL** (tüm değerlerin toplamı)
5. "Ortalaması nedir?" → **Ortalama: Y TL**
