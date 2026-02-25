# Continuing Query: Compute & Modify-Context Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `USE_RESULT` akışına iki yeni yol ekle: `compute` (active_results üzerinde sıfır-LLM matematiksel işlem) ve `modify_context` (entity'yi sonuçtan çıkarıp mevcut SQL'i değiştir — `new_query`'den daha ucuz).

**Architecture:** `IntentClassificationResult`'a iki yeni `use_result_type` değeri (`compute`, `modify_context`) ve `compute_operation` alanı ekleniyor. `compute` yolu pure-Python `compute_results_node`'a gidiyor (SQL yok, LLM yok). `modify_context` yolu mevcut `extract_entity` → `modify_sql` → `text2sql` zincirini kullanıyor (`new_query`'e göre 1-2 LLM çağrısı az). Var olan `new_query` ve `revisualize` yolları hiç değişmiyor.

**Tech Stack:** Python, LangGraph, Pydantic, pytest-asyncio

---

## Mevcut Akış (Değişmeyecek)

```
USE_RESULT
  ├── "revisualize" → visualization → build_response
  └── "new_query"   → extract_entity → text2sql → ...
```

## Hedef Akış

```
USE_RESULT
  ├── "revisualize"      → visualization → build_response          (2 LLM)
  ├── "new_query"        → extract_entity → text2sql → ...          (3+ LLM)  [değişmez]
  ├── "compute"          → compute_results → build_response         (0 LLM)   [YENİ]
  └── "modify_context"   → extract_entity → modify_sql → text2sql  (2 LLM)   [YENİ]
```

---

## Task 1: `prompts.py` + `state.py` — Schema Genişletme

**Files:**
- Modify: `src/graphs/report_agent/prompts.py:10-19` (IntentClassificationResult)
- Modify: `src/graphs/report_agent/prompts.py:67-70` (INTENT_CLASSIFIER_PROMPT USE_RESULT kuralları)
- Modify: `src/graphs/report_agent/state.py:18` (use_result_type + compute_operation)
- Modify: `src/graphs/report_agent/state.py:47-56` (create_initial_state)

**Step 1: `prompts.py` — IntentClassificationResult'ı güncelle**

`src/graphs/report_agent/prompts.py` satır 17-18'i replace et:

```python
# ÖNCE (satır 17):
    use_result_type: Optional[Literal["new_query", "revisualize"]] = None

# SONRA:
    use_result_type: Optional[Literal["new_query", "revisualize", "compute", "modify_context"]] = None
    compute_operation: Optional[Literal["sum", "avg", "count", "min", "max"]] = None
```

**Step 2: `prompts.py` — INTENT_CLASSIFIER_PROMPT USE_RESULT kurallarını güncelle**

`INTENT_CLASSIFIER_PROMPT` içindeki satır 68-69'u (USE_RESULT kısmı) replace et:

```python
# ÖNCE:
  → use_result_type="new_query": Sonuçtaki bir entity için yeni sorgu oluştur
  → use_result_type="revisualize": Aynı veriyi farklı chart/format ile göster

# SONRA:
  → use_result_type="new_query": Sonuçtaki bir entity için tamamen yeni sorgu oluştur
  → use_result_type="revisualize": Aynı veriyi farklı chart/format ile göster
  → use_result_type="compute": Sonuçlardaki sayısal kolonlar üzerinde matematiksel işlem yap (SQL gerekmez)
    compute_operation="sum"   → "toplamı", "topla", "toplam ne kadar"
    compute_operation="avg"   → "ortalaması", "ortalama al", "ortalama nedir"
    compute_operation="count" → "kaç tane", "kaç satır", "sayısı"
    compute_operation="min"   → "en düşük", "minimum", "en az"
    compute_operation="max"   → "en yüksek", "maksimum", "en fazla"
  → use_result_type="modify_context": Sonuçtaki entity'yi kullanarak mevcut SQL'i değiştir
    (ör: "bu ürün için şehirlere göre kır" → entity + active_sql'e GROUP BY/filtre ekle)
    DIKKAT: "new_query"dan farkı — entity zaten belli, sadece aktif sorgu değiştirilecek
```

**Step 3: `state.py` — compute_operation field ekle**

`state.py` satır 18'i replace et:

```python
# ÖNCE:
    use_result_type: Optional[str]     # "new_query" | "revisualize"

# SONRA:
    use_result_type: Optional[str]     # "new_query" | "revisualize" | "compute" | "modify_context"
    compute_operation: Optional[str]   # "sum" | "avg" | "count" | "min" | "max" (compute için)
```

**Step 4: `state.py` — create_initial_state güncelle**

`create_initial_state()` içinde `use_result_type=None,` satırından SONRA ekle:

```python
        compute_operation=None,
```

**Step 5: Doğrula**

```bash
python -c "
from src.graphs.report_agent.prompts import IntentClassificationResult
from src.graphs.report_agent.state import create_initial_state
r = IntentClassificationResult(intent_type='USE_RESULT', query_type='SINGLE', confidence=0.9, use_result_type='compute', compute_operation='sum')
print('OK:', r.use_result_type, r.compute_operation)
s = create_initial_state()
print('State compute_operation:', s.get('compute_operation'))
"
```

Beklenen çıktı:
```
OK: compute sum
State compute_operation: None
```

**Step 6: Commit**

```bash
git add src/graphs/report_agent/prompts.py src/graphs/report_agent/state.py
git commit -m "feat(intent): add compute + modify_context use_result_type options

Extends IntentClassificationResult with two new use_result_type values:
- compute: in-memory math on active_results (sum/avg/count/min/max)
- modify_context: entity from results -> modify active SQL

Adds compute_operation field to IntentClassificationResult and ReportState.
Updates INTENT_CLASSIFIER_PROMPT with classification rules for both paths.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: `nodes.py` — `compute_results_node` Ekle

**Files:**
- Modify: `src/graphs/report_agent/nodes.py` (yeni node + module-level sabit)
- Test: `tests/graphs/report/test_compute_results_node.py` (yeni)

**Step 1: Test dosyasını yaz (TDD — önce test)**

`tests/graphs/report/test_compute_results_node.py` oluştur:

```python
"""Tests for compute_results_node — pure Python, no LLM."""
import pytest


@pytest.fixture
def sample_results():
    return [
        {"ProductName": "Vegan Dürüm", "TotalQuantity": 100.0, "TotalAmount": 500.0},
        {"ProductName": "Klasik Dürüm", "TotalQuantity": 200.0, "TotalAmount": 1000.0},
        {"ProductName": "Tavuk Dürüm",  "TotalQuantity": 150.0, "TotalAmount": 750.0},
    ]


@pytest.mark.asyncio
async def test_compute_sum(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "sum"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "750" in result["final_response"]   # TotalQuantity sum
    assert "2250" in result["final_response"]  # TotalAmount sum


@pytest.mark.asyncio
async def test_compute_avg(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "avg"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "150" in result["final_response"]   # TotalQuantity avg


@pytest.mark.asyncio
async def test_compute_count(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "count"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "3" in result["final_response"]


@pytest.mark.asyncio
async def test_compute_min(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "min"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "100" in result["final_response"]   # TotalQuantity min


@pytest.mark.asyncio
async def test_compute_max(sample_results):
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results, "compute_operation": "max"}
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "200" in result["final_response"]   # TotalQuantity max


@pytest.mark.asyncio
async def test_compute_empty_results():
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": [], "compute_operation": "sum"}
    result = await compute_results_node(state)
    assert "bulunamadı" in result["final_response"].lower()


@pytest.mark.asyncio
async def test_compute_no_numeric_cols():
    from src.graphs.report_agent.nodes import compute_results_node
    state = {
        "active_results": [{"ProductName": "A"}, {"ProductName": "B"}],
        "compute_operation": "sum",
    }
    result = await compute_results_node(state)
    assert "sayısal" in result["final_response"].lower()


@pytest.mark.asyncio
async def test_compute_default_operation_is_sum(sample_results):
    """compute_operation yoksa sum varsayılan olmalı."""
    from src.graphs.report_agent.nodes import compute_results_node
    state = {"active_results": sample_results}  # compute_operation yok
    result = await compute_results_node(state)
    assert result["error"] is None
    assert "750" in result["final_response"]
```

**Step 2: Testlerin başarısız olduğunu doğrula**

```bash
python -m pytest tests/graphs/report/test_compute_results_node.py -v 2>&1 | head -20
```

Beklenen: `ImportError: cannot import name 'compute_results_node'`

**Step 3: `nodes.py`'a `compute_results_node` ekle**

`src/graphs/report_agent/nodes.py`'da `build_response_node` fonksiyonundan (satır 167) ÖNCE ekle:

```python
# =============================================================================
# COMPUTE LABELS (module-level sabit)
# =============================================================================
_COMPUTE_OP_LABELS = {
    "sum":   "Toplam",
    "avg":   "Ortalama",
    "count": "Adet",
    "min":   "Minimum",
    "max":   "Maksimum",
}


async def compute_results_node(state: dict) -> dict:
    """Pure Python: active_results üzerinde matematiksel işlem. LLM yok, SQL yok."""
    results = state.get("active_results") or []
    operation = state.get("compute_operation") or "sum"

    if not results:
        return {
            "final_response": "Hesaplama için önceki sorgu sonuçları bulunamadı.",
            "error": None,
        }

    # Sayısal kolonları bul (str/None dışı)
    numeric_cols = [
        col for col in results[0].keys()
        if isinstance(results[0].get(col), (int, float))
    ]

    if not numeric_cols:
        return {
            "final_response": "Sonuçlarda sayısal kolon bulunamadı.",
            "error": None,
        }

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
        formatted = f"{computed:,.2f}" if isinstance(computed, float) else f"{computed:,}"
        lines.append(f"**{col}** → {label}: {formatted}")

    response = "\n".join(lines) if lines else "Hesaplama yapılamadı."
    logger.info(
        f"[COMPUTE_RESULTS] op={operation}, cols={numeric_cols}, "
        f"rows={len(results)}, result_lines={len(lines)}"
    )
    return {"final_response": response, "error": None}
```

**Step 4: Testleri çalıştır**

```bash
python -m pytest tests/graphs/report/test_compute_results_node.py -v
```

Beklenen: 8/8 PASSED

**Step 5: Commit**

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_compute_results_node.py
git commit -m "feat(compute-results): add pure-Python in-memory computation node

compute_results_node performs sum/avg/count/min/max over active_results
without any SQL or LLM calls. Zero token cost for math-on-results queries.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: `nodes.py` — `extract_entity_node` modify_context Desteği

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:149-162` (extract_entity_node)
- Test: `tests/graphs/report/test_extract_entity_node.py` (yeni)

**Mevcut kod (satır 149-162):**
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
    logger.info(f"[EXTRACT_ENTITY] {result.entity_name} ({result.entity_type})")
    return {"user_query": result.new_query_seed}
```

**Step 1: Test dosyasını yaz (TDD — önce test)**

`tests/graphs/report/test_extract_entity_node.py` oluştur:

```python
"""Tests for extract_entity_node — modify_context path."""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_llm_mock(entity_name: str, entity_type: str, new_query_seed: str):
    """EntityExtractionResult döndüren mock LLM oluştur."""
    from src.graphs.report_agent.prompts import EntityExtractionResult
    mock_result = EntityExtractionResult(
        entity_name=entity_name,
        entity_type=entity_type,
        new_query_seed=new_query_seed,
    )
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=mock_result)
    mock_llm.with_structured_output = MagicMock(return_value=structured)
    return mock_llm


@pytest.mark.asyncio
async def test_new_query_path_unchanged():
    """use_result_type=new_query → new_query_seed olarak user_query döner (eski davranış)."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    llm = _make_llm_mock("KLASİK DÜRÜM", "product", "KLASİK DÜRÜM'ün şehirlere göre satışları")
    node = create_extract_entity_node(llm)
    state = {
        "active_results": [{"ProductName": "KLASİK DÜRÜM", "TotalAmount": 34617}],
        "user_query": "bu ürünün detaylarına bak",
        "use_result_type": "new_query",
    }
    result = await node(state)
    assert result["user_query"] == "KLASİK DÜRÜM'ün şehirlere göre satışları"


@pytest.mark.asyncio
async def test_modify_context_enriches_query():
    """use_result_type=modify_context → entity adı user_query'ye inject edilir."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    llm = _make_llm_mock("KLASİK DÜRÜM", "product", "KLASİK DÜRÜM'ün şehirlere göre satışları")
    node = create_extract_entity_node(llm)
    state = {
        "active_results": [{"ProductName": "KLASİK DÜRÜM", "TotalAmount": 34617}],
        "user_query": "bu ürün için şehirlere göre kır",
        "use_result_type": "modify_context",
    }
    result = await node(state)
    # Enriched query hem entity adını hem de orijinal isteği içermeli
    assert "KLASİK DÜRÜM" in result["user_query"]
    assert "şehirlere göre kır" in result["user_query"]


@pytest.mark.asyncio
async def test_empty_results_fallback():
    """active_results boşsa NEW_QUERY'ye fallback."""
    from src.graphs.report_agent.nodes import create_extract_entity_node
    llm = _make_llm_mock("X", "product", "X sorgusu")
    node = create_extract_entity_node(llm)
    state = {"active_results": [], "user_query": "test", "use_result_type": "new_query"}
    result = await node(state)
    assert result.get("intent_type") == "NEW_QUERY"
```

**Step 2: Testlerin başarısız olduğunu doğrula**

```bash
python -m pytest tests/graphs/report/test_extract_entity_node.py::test_modify_context_enriches_query -v
```

Beklenen: FAIL — `test_modify_context_enriches_query` başarısız (entity adı query'e inject edilmiyor)

**Step 3: `extract_entity_node` güncelle**

`nodes.py` içinde `extract_entity_node` async fonksiyonunun son `return` satırını replace et:

```python
# ÖNCE (satır 161-162):
        result: EntityExtractionResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[EXTRACT_ENTITY] {result.entity_name} ({result.entity_type})")
        return {"user_query": result.new_query_seed}

# SONRA:
        result: EntityExtractionResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[EXTRACT_ENTITY] {result.entity_name} ({result.entity_type})")

        if state.get("use_result_type") == "modify_context":
            # modify_sql_node'a gidecek: entity adını orijinal sorguya inject et
            original_query = state.get("user_query", "")
            enriched = f"{result.entity_name} için: {original_query}"
            logger.info(f"[EXTRACT_ENTITY] modify_context → enriched query: {enriched[:80]}")
            return {"user_query": enriched}

        return {"user_query": result.new_query_seed}
```

**Step 4: Testleri çalıştır**

```bash
python -m pytest tests/graphs/report/test_extract_entity_node.py -v
```

Beklenen: 3/3 PASSED

**Step 5: Commit**

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_extract_entity_node.py
git commit -m "feat(extract-entity): support modify_context path via enriched query

When use_result_type=modify_context, extract_entity_node injects the
resolved entity name into user_query before routing to modify_sql_node.
This lets modify_sql use active_sql as a base instead of generating
a new query from scratch (saves 1-2 LLM calls vs new_query path).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: `graph.py` — Yeni Routing Ekle

**Files:**
- Modify: `src/graphs/report_agent/graph.py` (tüm dosya değişiyor)
- Test: `tests/graphs/report/test_graph_routing.py` (yeni)

**Step 1: Router fonksiyon testlerini yaz (TDD — önce test)**

`tests/graphs/report/test_graph_routing.py` oluştur:

```python
"""Tests for report agent graph routing pure functions."""
import pytest


def test_intent_router_new_query():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "NEW_QUERY"}) == "text2sql"


def test_intent_router_modify_query():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "MODIFY_QUERY"}) == "modify_sql"


def test_intent_router_use_result_revisualize():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "revisualize"}) == "visualization"


def test_intent_router_use_result_new_query():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "new_query"}) == "extract_entity"


def test_intent_router_use_result_compute():
    """compute → compute_results (YENİ)."""
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "compute"}) == "compute_results"


def test_intent_router_use_result_modify_context():
    """modify_context → extract_entity gibi davranır (YENİ)."""
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "modify_context"}) == "extract_entity"


def test_intent_router_fallback():
    """Bilinmeyen intent → text2sql."""
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({}) == "text2sql"


def test_after_extract_entity_router_new_query():
    from src.graphs.report_agent.graph import _after_extract_entity_router
    assert _after_extract_entity_router({"use_result_type": "new_query"}) == "text2sql"


def test_after_extract_entity_router_modify_context():
    """modify_context → modify_sql (YENİ)."""
    from src.graphs.report_agent.graph import _after_extract_entity_router
    assert _after_extract_entity_router({"use_result_type": "modify_context"}) == "modify_sql"


def test_after_extract_entity_router_default():
    """use_result_type yoksa text2sql."""
    from src.graphs.report_agent.graph import _after_extract_entity_router
    assert _after_extract_entity_router({}) == "text2sql"
```

**Step 2: Testlerin başarısız olduğunu doğrula**

```bash
python -m pytest tests/graphs/report/test_graph_routing.py -v 2>&1 | head -20
```

Beklenen: `ImportError: cannot import name '_after_extract_entity_router'` + `compute_results` test'i FAIL

**Step 3: `graph.py`'ı güncelle**

Tam dosya replace:

```python
"""
Report Agent — Ana Graph

START → classify_intent → [intent_router]
  ├── NEW_QUERY          → text2sql → visualization → build_response → END
  ├── MODIFY_QUERY       → modify_sql → text2sql → visualization → build_response → END
  ├── USE_RESULT(A)      → extract_entity → text2sql → visualization → build_response → END
  ├── USE_RESULT(B)      → visualization → build_response → END
  ├── USE_RESULT(compute)→ compute_results → build_response → END           [YENİ]
  └── USE_RESULT(modify) → extract_entity → modify_sql → text2sql → ...     [YENİ]
"""
import logging
from typing import Any, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.configuration import ReportAgentConfiguration
from src.graphs.report_agent.nodes import (
    build_response_node,
    compute_results_node,
    create_classify_intent_node,
    create_extract_entity_node,
    create_modify_sql_node,
)
from src.graphs.report_agent.state import ReportState
from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph
from src.graphs.report_agent.subagents.visualization.graph import build_visualization_graph

logger = logging.getLogger(__name__)


def _intent_router(state: dict) -> str:
    """Pure function — test edilebilir routing."""
    intent = state.get("intent_type", "NEW_QUERY")
    if intent == "MODIFY_QUERY":
        return "modify_sql"
    if intent == "USE_RESULT":
        use_result = state.get("use_result_type")
        if use_result == "revisualize":
            return "visualization"
        if use_result == "compute":
            return "compute_results"
        return "extract_entity"  # new_query + modify_context
    return "text2sql"  # NEW_QUERY + fallback


def _after_extract_entity_router(state: dict) -> str:
    """extract_entity sonrası: modify_context → modify_sql, diğerleri → text2sql."""
    return "modify_sql" if state.get("use_result_type") == "modify_context" else "text2sql"


def _visualization_router(state: dict) -> str:
    """text2sql sonrası: grafik istendiyse visualization, istenmemişse direkt build_response."""
    return "visualization" if state.get("wants_visualization", False) else "build_response"


def build_report_agent_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    connection_string: str,
    business_rules_path: str,
    chroma_persist_dir: str,
    checkpointer=None,
):
    text2sql = build_text2sql_graph(
        llm,
        table_name,
        column_metadata,
        connection_string,
        business_rules_path,
        chroma_persist_dir,
    )
    visualization = build_visualization_graph(llm)

    graph = StateGraph(ReportState, config_schema=ReportAgentConfiguration)

    graph.add_node("classify_intent", create_classify_intent_node(llm))
    graph.add_node("modify_sql", create_modify_sql_node(llm, column_metadata))
    graph.add_node("extract_entity", create_extract_entity_node(llm))
    graph.add_node("compute_results", compute_results_node)   # YENİ
    graph.add_node("text2sql", text2sql)
    graph.add_node("visualization", visualization)
    graph.add_node("build_response", build_response_node)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        _intent_router,
        {
            "text2sql":        "text2sql",
            "modify_sql":      "modify_sql",
            "extract_entity":  "extract_entity",
            "visualization":   "visualization",
            "compute_results": "compute_results",   # YENİ
        },
    )
    graph.add_edge("modify_sql", "text2sql")
    graph.add_conditional_edges(          # DEĞİŞTİ: düz edge → conditional
        "extract_entity",
        _after_extract_entity_router,
        {
            "modify_sql": "modify_sql",
            "text2sql":   "text2sql",
        },
    )
    graph.add_edge("compute_results", "build_response")  # YENİ
    graph.add_conditional_edges(
        "text2sql",
        _visualization_router,
        {"visualization": "visualization", "build_response": "build_response"},
    )
    graph.add_edge("visualization", "build_response")
    graph.add_edge("build_response", END)

    compiled = graph.compile(checkpointer=checkpointer or MemorySaver())
    logger.info("[REPORT_AGENT] Built: 7 nodes, compute=0-LLM, modify_context=2-LLM")
    return compiled
```

**Step 4: Testleri çalıştır**

```bash
python -m pytest tests/graphs/report/test_graph_routing.py -v
```

Beklenen: 10/10 PASSED

**Step 5: Tüm testleri çalıştır (regresyon kontrolü)**

```bash
python -m pytest tests/graphs/report/ -v --ignore=tests/graphs/report/test_llm_integration.py
```

Beklenen: Tüm testler PASSED

**Step 6: Commit**

```bash
git add src/graphs/report_agent/graph.py tests/graphs/report/test_graph_routing.py
git commit -m "feat(graph): add compute and modify_context routing paths

- _intent_router: routes USE_RESULT/compute to compute_results node (0 LLM)
- _after_extract_entity_router: routes modify_context to modify_sql
  instead of full text2sql pipeline (saves 1-2 LLM calls)
- compute_results node added to graph (7 nodes total)
- extract_entity now uses conditional edge for post-routing

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Özet

| use_result_type | Yol | Token Maliyeti | Kullanım |
|---|---|---|---|
| `compute` | `compute_results → build_response` | **0 LLM** | "toplamı ne", "ortalaması kaç" |
| `revisualize` | `visualization → build_response` | 2 LLM | "pasta grafik yap" |
| `modify_context` | `extract_entity → modify_sql → text2sql` | **2 LLM** | "bu ürün için şehirlere göre kır" |
| `new_query` | `extract_entity → text2sql` | 3+ LLM | "bu ürünün müşteri detayları" |

**Genişletilebilirlik:** Yeni bir devam eden sorgu tipi eklemek = `use_result_type` enum'a değer + `_intent_router`/`_after_extract_entity_router`'a branch + yeni node (gerekiyorsa).

**Manuel Test Senaryoları:**

```
"Bu sonuçların toplamı kaç?"         → compute/sum  → 0 LLM, direkt hesaplama
"Ortalama değeri nedir?"             → compute/avg  → 0 LLM, direkt hesaplama
"Bu ürün için şehirlere göre kır"   → modify_context → extract → modify_sql
"Bu ürünün müşteri detayları nedir" → new_query → extract → full text2sql
"Pasta grafik yap"                  → revisualize → visualization (değişmedi)
```
