# Context Consistency Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report agent'ın multi-turn konuşmalarında `active_filters`, `wants_visualization` ve ilgili context field'larının kaybolmasını önlemek; yeni sorgu geçişini temiz yönetmek.

**Architecture:** Dört ayrı root cause vardır: (1) `classify_intent_node` return dict'inde `active_filters` eksik → LangGraph subgraph'tan dönen [] değerini preserve eder, (2) `sql_executor_node` pre_built_sql bypass yolunda `query_schema` boş olduğu için `active_filters = []` yazar üzerine, (3) MODIFY_QUERY'de `wants_visualization` her tur LLM'den yeniden hesaplanıyor, önceki grafik talebi kaybolabiliyor, (4) `modify_sql_node` SqlDelta uygularken güncellenmiş `active_filters`'ı state'e yazmıyor. Tüm düzeltmeler sıfır ek LLM çağrısı, sıfır latency artışı.

**Tech Stack:** Python 3.11+, LangGraph `StateGraph` + `TypedDict`, Pydantic v2, pytest-asyncio

---

## Etkilenen Dosyalar

| Dosya | İşlem | Kapsam |
|---|---|---|
| `src/graphs/report_agent/prompts.py` | Modify | `IntentClassificationResult` + `INTENT_CLASSIFIER_PROMPT` |
| `src/graphs/report_agent/nodes.py` | Modify | `classify_intent_node`, `modify_sql_node` |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | Modify | `sql_executor_node` |
| `tests/graphs/report/test_context_preservation.py` | Create | Yeni test dosyası |
| `tests/graphs/report/test_sql_executor_active_filters.py` | Modify | Mevcut test genişletme |

---

## Task 1 — `active_filters` explicit preservation in `classify_intent_node`

**Amaç:** Her turda `active_filters` LangGraph subgraph dönüşünden sonra [] olarak preserve edilebiliyor. classify_intent bunu açıkça yönetmeli: NEW_QUERY'de temizle, diğer intent'lerde koru.

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:147`
- Create: `tests/graphs/report/test_context_preservation.py`

- [ ] **Step 1: Failing test yaz**

```python
# tests/graphs/report/test_context_preservation.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import HumanMessage

from src.graphs.report_agent.prompts import IntentClassificationResult


def _make_llm_mock(intent_type: str, query_type: str = "RANKING", wants_viz: bool = False) -> MagicMock:
    result = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=0.95,
        wants_visualization=wants_viz,
        visualization_explicitly_set=False,
    )
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result)
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


@pytest.mark.asyncio
async def test_active_filters_preserved_on_modify_query():
    """MODIFY_QUERY'de active_filters state'den taşınmalı."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("MODIFY_QUERY")
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Ankara'yı ekle")],
        "active_sql": "SELECT * FROM T",
        "active_results": [{"BranchName": "Ankara", "RowAmount": 100}],
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["active_filters"] == [{"field": "CategoryName", "value": "Dürüm"}]


@pytest.mark.asyncio
async def test_active_filters_cleared_on_new_query():
    """NEW_QUERY'de active_filters temizlenmeli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("NEW_QUERY")
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Tüm şubeleri listele")],
        "active_sql": "SELECT * FROM T WHERE CategoryName='Dürüm'",
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["active_filters"] is None


@pytest.mark.asyncio
async def test_active_filters_none_when_state_empty():
    """State'de active_filters yoksa MODIFY_QUERY'de de None gelmeli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("MODIFY_QUERY")
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Limit'i 20 yap")],
        "active_sql": "SELECT * FROM T",
        "active_filters": None,
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["active_filters"] is None
```

- [ ] **Step 2: Test'i çalıştır, FAIL bekliyoruz**

```
pytest tests/graphs/report/test_context_preservation.py::test_active_filters_preserved_on_modify_query -v
```

Expected: `KeyError: 'active_filters'` veya `AssertionError` — field return dict'te yok.

- [ ] **Step 3: `classify_intent_node` return_dict'e `active_filters` ekle**

`src/graphs/report_agent/nodes.py` satır 147 — `accumulated_entities` satırının hemen altına:

```python
        return_dict = {
            "user_query": user_query,
            "viz_request": user_query if is_revisualize else None,
            "intent_type": result.intent_type,
            "query_type": result.query_type,
            "intent_confidence": result.confidence,
            "wants_visualization": wants_viz,
            "requested_chart_type": chart_type,
            "chart_x_hint": chart_x_hint,
            "use_result_type": result.use_result_type,
            "compute_operation": result.compute_operation,
            "visualization_output": None,
            "pre_built_sql": None,
            "time_granularity": None,
            "time_breakdown": result.time_breakdown,
            "modification_hints": None,
            "semantic_intent": None,
            "term_resolution": None,
            "_clarification_count": 0 if result.intent_type != "VAGUE_QUERY" else state.get("_clarification_count", 0),
            "_skip_vague_check": False,
            "text2sql_clarification": None,
            "text2sql_answers": None,
            "_hitl_answered": False,
            "accumulated_entities": state.get("accumulated_entities"),
            "active_filters": None if result.intent_type == "NEW_QUERY" else state.get("active_filters"),  # ← YENİ
        }
```

- [ ] **Step 4: Test'leri çalıştır, PASS bekliyoruz**

```
pytest tests/graphs/report/test_context_preservation.py -v
```

Expected: 3 test PASS.

- [ ] **Step 5: Mevcut testlerin kırmadığını doğrula**

```
pytest tests/graphs/report/test_graph_routing.py tests/graphs/report/test_compute_results_node.py -v
```

Expected: Tümü PASS.

- [ ] **Step 6: Commit**

```
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_context_preservation.py
git commit -m "fix(context): preserve active_filters across turns in classify_intent_node"
```

---

## Task 2 — `visualization_explicitly_set` field — MODIFY'de grafik inherit

**Amaç:** `wants_visualization: False` LLM default'udur — "kullanıcı grafik söylemedi" anlamına gelir. MODIFY_QUERY'de kullanıcı grafikten bahsetmediyse önceki tur `wants_visualization` state'i korunmalı.

**Files:**
- Modify: `src/graphs/report_agent/prompts.py:10` (model) ve `:206` (prompt)
- Modify: `src/graphs/report_agent/nodes.py:112-132` (inheritance logic)
- Modify: `tests/graphs/report/test_context_preservation.py` (yeni test'ler ekle)

- [ ] **Step 1: Failing test yaz — `test_context_preservation.py`'ye ekle**

```python
@pytest.mark.asyncio
async def test_wants_visualization_inherited_on_modify_when_not_addressed():
    """MODIFY_QUERY'de kullanıcı grafikten bahsetmemişse önceki wants_visualization korunmalı."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    # LLM: kullanıcı grafikten bahsetmedi → False (default), chart_type=None
    llm = _make_llm_mock("MODIFY_QUERY", wants_viz=False)
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Ankara'yı ekle")],
        "active_sql": "SELECT * FROM T",
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "wants_visualization": True,          # önceki turda grafik istenmiş
        "requested_chart_type": "bar_chart",  # önceki turda bar chart seçilmiş
        "chart_x_hint": "BranchName",
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["wants_visualization"] is True
    assert result["requested_chart_type"] == "bar_chart"
    assert result["chart_x_hint"] == "BranchName"


@pytest.mark.asyncio
async def test_wants_visualization_updated_when_explicitly_set():
    """MODIFY_QUERY'de kullanıcı açıkça grafik istedi → güncellenmeli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    result_obj = IntentClassificationResult(
        intent_type="MODIFY_QUERY",
        query_type="RANKING",
        confidence=0.95,
        wants_visualization=True,
        chart_type="pie_chart",
        visualization_explicitly_set=True,
    )
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result_obj)
    llm.with_structured_output = MagicMock(return_value=structured)
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Pasta grafik olarak göster")],
        "active_sql": "SELECT * FROM T",
        "active_filters": [],
        "wants_visualization": True,
        "requested_chart_type": "bar_chart",  # önceki tur bar chart
        "chart_x_hint": None,
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["wants_visualization"] is True
    assert result["requested_chart_type"] == "pie_chart"  # güncellenmiş


@pytest.mark.asyncio
async def test_wants_visualization_explicitly_removed():
    """MODIFY_QUERY'de kullanıcı açıkça grafiği kaldırdı → False olmalı."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    result_obj = IntentClassificationResult(
        intent_type="MODIFY_QUERY",
        query_type="RANKING",
        confidence=0.95,
        wants_visualization=False,
        visualization_explicitly_set=True,  # "grafiği kaldır" → explicitly_set=True
    )
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result_obj)
    llm.with_structured_output = MagicMock(return_value=structured)
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Grafiği kaldır")],
        "active_sql": "SELECT * FROM T",
        "active_filters": [],
        "wants_visualization": True,
        "requested_chart_type": "bar_chart",
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["wants_visualization"] is False


@pytest.mark.asyncio
async def test_wants_visualization_not_inherited_on_new_query():
    """NEW_QUERY'de visualization state inherit edilmemeli — LLM kararı geçerli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("NEW_QUERY", wants_viz=False)
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Tüm şubeleri listele")],
        "active_sql": None,
        "active_filters": None,
        "wants_visualization": True,       # önceki turda grafik vardı
        "requested_chart_type": "bar_chart",
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["wants_visualization"] is False  # LLM kararı (False) kullanıldı
```

- [ ] **Step 2: Test'i çalıştır, FAIL bekliyoruz**

```
pytest tests/graphs/report/test_context_preservation.py::test_wants_visualization_inherited_on_modify_when_not_addressed -v
```

Expected: `AssertionError` — wants_visualization False dönüyor çünkü inherit yok.

- [ ] **Step 3: `IntentClassificationResult`'a `visualization_explicitly_set` ekle**

`src/graphs/report_agent/prompts.py` satır 27 — `time_breakdown` field'ından sonra:

```python
class IntentClassificationResult(BaseModel):
    """Intent + query type — tek LLM çağrısı ile sınıflandırma."""

    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY"]
    query_type: Literal["SINGLE", "LISTING", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    wants_visualization: bool = False
    chart_type: Optional[Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "heatmap", "sunburst", "treemap", "comparison", "turkey_map",
    ]] = None
    chart_x_hint: Optional[str] = None
    use_result_type: Optional[Literal["new_query", "revisualize", "compute", "modify_context"]] = None
    compute_operation: Optional[Literal["sum", "avg", "count", "min", "max"]] = None
    modification_action: Optional[str] = None
    modification_target: Optional[str] = None
    modification_value: Optional[str] = None
    time_breakdown: bool = False
    visualization_explicitly_set: bool = False  # ← YENİ: kullanıcı grafik hakkında açıkça bir şey söyledi

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def clear_chart_hints_when_no_chart_type(self) -> "IntentClassificationResult":
        if self.chart_type is None:
            self.chart_x_hint = None
        return self
```

- [ ] **Step 4: `INTENT_CLASSIFIER_PROMPT`'a `visualization_explicitly_set` açıklaması ekle**

`src/graphs/report_agent/prompts.py` — `wants_visualization` bloğunun (satır ~206) hemen altına:

```
**visualization_explicitly_set:** (True/False)
- True: Kullanıcı bu mesajda grafik/görsel hakkında açıkça bir şey söyledi
  → "bar chart yap", "pasta grafik istiyorum", "grafiği kaldır", "tablo olarak göster",
     "görsel olarak göster", "grafik istemiyorum", "sadece sayıları göster"
- False (DEFAULT): Kullanıcı grafik/görsel hakkında hiçbir şey söylemedi
  → "Ankara'yı ekle", "limit'i 20 yap", "en çok satanları getir", "filtre ekle"
  → MODIFY_QUERY'nin büyük çoğunluğunda False olur — kullanıcı sadece veriyi değiştiriyor
```

- [ ] **Step 5: `classify_intent_node`'da visualization inheritance logic ekle**

`src/graphs/report_agent/nodes.py` satır 111–132 — `wants_viz` hesaplamasının hemen altına:

```python
        # revisualize her zaman görselleştirme talebidir.
        wants_viz = (
            result.wants_visualization
            or (result.use_result_type == "revisualize")
        )

        chart_type = result.chart_type
        chart_x_hint = result.chart_x_hint

        if chart_type:
            logger.info(f"[CLASSIFY] chart_type={chart_type}, chart_x_hint={chart_x_hint}")

        # MODIFY_QUERY: kullanıcı grafikten bahsetmediyse önceki turdaki görselleştirme tercihini koru.
        # Böylece "Ankara'yı ekle" gibi sorgularda mevcut grafik kaybolmaz.
        if (
            result.intent_type == "MODIFY_QUERY"
            and not result.visualization_explicitly_set
        ):
            wants_viz = state.get("wants_visualization", False)
            chart_type = chart_type or state.get("requested_chart_type")
            chart_x_hint = chart_x_hint or state.get("chart_x_hint")
            logger.info(
                f"[CLASSIFY] MODIFY_QUERY: visualization inherited from state "
                f"(wants_viz={wants_viz}, chart_type={chart_type})"
            )
```

- [ ] **Step 6: Tüm visualization test'lerini çalıştır**

```
pytest tests/graphs/report/test_context_preservation.py -v
```

Expected: Tüm test'ler PASS.

- [ ] **Step 7: Regresyon kontrolü**

```
pytest tests/graphs/report/ tests/test_visualization_v2/ -v
```

Expected: Tümü PASS.

- [ ] **Step 8: Commit**

```
git add src/graphs/report_agent/prompts.py src/graphs/report_agent/nodes.py tests/graphs/report/test_context_preservation.py
git commit -m "fix(context): inherit wants_visualization on MODIFY_QUERY when user doesn't address it"
```

---

## Task 3 — `modify_sql_node` filter delta hesabı ve propagation

**Amaç:** `modify_sql_node` SqlDelta'yı uygularken güncellenmiş `active_filters` listesini de hesaplayıp state'e yazmalı. Bu sayede `sql_executor_node` doğru filtreleri alır.

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:171-237`
- Modify: `tests/graphs/report/test_context_preservation.py`

- [ ] **Step 1: Failing test yaz — `test_context_preservation.py`'ye ekle**

```python
@pytest.mark.asyncio
async def test_modify_sql_propagates_updated_filters():
    """modify_sql_node SqlDelta'yı uygularken active_filters'ı güncellenmeli."""
    import json
    from unittest.mock import patch
    from src.graphs.report_agent.nodes import create_modify_sql_node
    from src.graphs.report_agent.prompts import SqlDelta, FilterDelta

    delta = SqlDelta(
        add_filters=[FilterDelta(column="BranchName", operator="=", value="'Ankara'")],
        remove_filter_columns=[],
        explanation="Ankara filtresi eklendi",
        confidence=0.95,
    )

    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=delta)
    llm.with_structured_output = MagicMock(return_value=structured)

    column_metadata = {}
    node = create_modify_sql_node(llm, column_metadata)

    state = {
        "active_sql": "SELECT TOP 10 [BranchName], SUM([RowAmount]) FROM T GROUP BY [BranchName]",
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "active_results": [],
        "accumulated_entities": None,
        "user_query": "Ankara şubesini ekle",
    }

    result = await node(state)

    assert "active_filters" in result
    fields = {f["field"] for f in result["active_filters"]}
    assert "CategoryName" in fields  # önceki filtre korunmalı
    assert "BranchName" in fields    # yeni filtre eklenmeli


@pytest.mark.asyncio
async def test_modify_sql_removes_filters_from_active():
    """modify_sql_node remove_filter_columns'daki filtreleri active_filters'dan çıkarmalı."""
    from src.graphs.report_agent.nodes import create_modify_sql_node
    from src.graphs.report_agent.prompts import SqlDelta, FilterDelta

    delta = SqlDelta(
        add_filters=[],
        remove_filter_columns=["CategoryName"],
        explanation="Kategori filtresi kaldırıldı",
        confidence=0.95,
    )

    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=delta)
    llm.with_structured_output = MagicMock(return_value=structured)

    node = create_modify_sql_node(llm, {})

    state = {
        "active_sql": "SELECT * FROM T WHERE CategoryName='Dürüm'",
        "active_filters": [
            {"field": "CategoryName", "value": "Dürüm"},
            {"field": "BranchName", "value": "Ankara"},
        ],
        "active_results": [],
        "accumulated_entities": None,
        "user_query": "Kategori filtresini kaldır",
    }

    result = await node(state)

    assert "active_filters" in result
    fields = [f["field"] for f in result["active_filters"]]
    assert "CategoryName" not in fields  # kaldırılmış olmalı
    assert "BranchName" in fields        # diğer filtre korunmalı
```

- [ ] **Step 2: Test'i çalıştır, FAIL bekliyoruz**

```
pytest tests/graphs/report/test_context_preservation.py::test_modify_sql_propagates_updated_filters -v
```

Expected: `AssertionError` — `active_filters` return dict'te yok.

- [ ] **Step 3: `_merge_filter_delta` helper ekle ve `modify_sql_node` return'e yaz**

`src/graphs/report_agent/nodes.py` — `create_modify_sql_node` fonksiyonunun hemen üstüne, modül düzeyine:

```python
def _merge_filter_delta(
    existing: list[dict] | None,
    delta: "SqlDelta",
) -> list[dict]:
    """Mevcut active_filters listesine SqlDelta add/remove uygula."""
    base = [f for f in (existing or []) if f.get("field") not in delta.remove_filter_columns]
    for f in delta.add_filters:
        if f.operator == "=":
            base.append({"field": f.column, "value": f.value.strip("'")})
    return base
```

Ve `modify_sql_node` return dict'ini güncelle (satır ~232):

```python
        return {
            "pre_built_sql": modified_sql,
            "modification_hints": modification_hints,
            "active_filters": _merge_filter_delta(state.get("active_filters"), delta),  # ← YENİ
        }
```

- [ ] **Step 4: Test'leri çalıştır**

```
pytest tests/graphs/report/test_context_preservation.py::test_modify_sql_propagates_updated_filters tests/graphs/report/test_context_preservation.py::test_modify_sql_removes_filters_from_active -v
```

Expected: 2 test PASS.

- [ ] **Step 5: Commit**

```
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_context_preservation.py
git commit -m "fix(context): modify_sql_node propagates updated active_filters via SqlDelta merge"
```

---

## Task 4 — `sql_executor_node` pre_built_sql bypass'ta filtre koruması

**Amaç:** MODIFY_QUERY yolunda `pre_built_sql` kullanıldığında `query_schema` boş gelir. `sql_executor_node` bu durumda `active_filters = []` yazar. Bunun yerine state'deki mevcut `active_filters`'ı (Task 3'te `modify_sql_node` tarafından güncellenmiş) preserve etmeli.

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1326-1345`
- Modify: `tests/graphs/report/test_sql_executor_active_filters.py`

- [ ] **Step 1: Mevcut test dosyasını oku**

```
pytest tests/graphs/report/test_sql_executor_active_filters.py -v
```

Expected: Mevcut test'ler geçiyor. Yeni test için içeriği gözden geçir.

- [ ] **Step 2: Failing test — mevcut dosyaya ekle**

`tests/graphs/report/test_sql_executor_active_filters.py` dosyasına şu test'i ekle:

```python
@pytest.mark.asyncio
async def test_sql_executor_preserves_active_filters_when_query_schema_empty():
    """
    pre_built_sql yolu: query_schema boş olduğunda sql_executor,
    state'deki mevcut active_filters'ı korumalı (üzerine [] yazmamalı).
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_sql_executor_node

    captured_filters = {}

    async def fake_execute(conn_str, sql):
        return [{"BranchName": "Ankara", "Total": 500}]

    node = create_sql_executor_node("fake_conn")

    import src.graphs.report_agent.subagents.text2sql.nodes as nodes_mod
    original = nodes_mod._execute_sql_async

    async def patched_execute(conn_str, sql):
        return [{"BranchName": "Ankara", "Total": 500}]

    nodes_mod._execute_sql_async = patched_execute
    try:
        state = {
            "sql_queries": ["SELECT [BranchName], SUM([RowAmount]) FROM T WHERE [CategoryName]='Dürüm' AND [BranchName]='Ankara' GROUP BY [BranchName]"],
            "query_schema": None,   # pre_built_sql bypass: query_schema YOK
            "active_filters": [    # modify_sql_node tarafından güncellenmiş
                {"field": "CategoryName", "value": "Dürüm"},
                {"field": "BranchName", "value": "Ankara"},
            ],
            "accumulated_entities": None,
            "retry_count": 0,
        }

        result = await node(state)

        assert result.get("error") is None
        filters = result.get("active_filters", [])
        fields = {f["field"] for f in filters}
        assert "CategoryName" in fields, "CategoryName filtresi korunmalıydı"
        assert "BranchName" in fields, "BranchName filtresi korunmalıydı"
    finally:
        nodes_mod._execute_sql_async = original
```

- [ ] **Step 3: Test'i çalıştır, FAIL bekliyoruz**

```
pytest tests/graphs/report/test_sql_executor_active_filters.py::test_sql_executor_preserves_active_filters_when_query_schema_empty -v
```

Expected: `AssertionError` — `active_filters = []` geliyor.

- [ ] **Step 4: `sql_executor_node` filter logic'ini güncelle**

`src/graphs/report_agent/subagents/text2sql/nodes.py` satır 1326–1345:

Mevcut kod:
```python
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

Yeni kod:
```python
            query_schema = state.get("query_schema") or {}
            schema_filters = [
                {
                    "field": f.get("column"),
                    "value": f.get("resolved_value") or f.get("value_hint") or f.get("value"),
                }
                for f in query_schema.get("filters", [])
                if not f.get("date_descriptor") and f.get("column")
            ]
            # pre_built_sql bypass yolunda query_schema boştur; modify_sql_node'un
            # güncelleyip yazdığı active_filters'ı koru.
            active_filters = schema_filters if schema_filters else (state.get("active_filters") or [])
```

- [ ] **Step 5: Test'i çalıştır**

```
pytest tests/graphs/report/test_sql_executor_active_filters.py -v
```

Expected: Tüm test'ler PASS.

- [ ] **Step 6: Tam regresyon çalıştır**

```
pytest tests/graphs/report/ tests/unit/text2sql/ -v
```

Expected: Tümü PASS.

- [ ] **Step 7: Commit**

```
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/graphs/report/test_sql_executor_active_filters.py
git commit -m "fix(context): sql_executor preserves active_filters in pre_built_sql bypass path"
```

---

## Task 5 — `state.py` field dokümantasyonu güncelle

**Amaç:** `active_filters` field comment'ini güncelle; `visualization_explicitly_set` state'te değil prompts.py'da olduğunu netleştir. Sonraki geliştiriciler için kılavuz.

**Files:**
- Modify: `src/graphs/report_agent/state.py:26`

- [ ] **Step 1: `active_filters` field comment'ini güncelle**

`src/graphs/report_agent/state.py` satır 26:

```python
    active_filters: Optional[List[Dict[str, Any]]]  # Son SQL'in WHERE filtreleri [{field, value}]; classify_intent: NEW_QUERY'de None, diğerlerinde korunur; modify_sql günceller; sql_executor query_schema boşsa preserve eder
```

- [ ] **Step 2: `wants_visualization` comment'i güncelle**

```python
    wants_visualization: Optional[bool]  # Kullanıcı açıkça grafik istedi mi? MODIFY_QUERY'de visualization_explicitly_set=False ise önceki turdan inherit edilir
```

- [ ] **Step 3: Dosyayı kaydet ve testleri çalıştır**

```
pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

Expected: Tüm test'ler PASS, hiçbir import hatası yok.

- [ ] **Step 4: Commit**

```
git add src/graphs/report_agent/state.py
git commit -m "docs(state): update active_filters and wants_visualization field comments for new behavior"
```

---

## Task 6 — `_make_llm_mock` helper'ını test dosyasında `visualization_explicitly_set` ile uyumlu hale getir

**Amaç:** Task 1'de yazdığımız `_make_llm_mock` helper'ı `visualization_explicitly_set=False` default'u ile çalışıyor olmalı — Task 2 sonrası mevcut mock'lar bozulmamalı.

**Files:**
- Modify: `tests/graphs/report/test_context_preservation.py`

- [ ] **Step 1: Test dosyasını çalıştır, tüm test'lerin geçtiğini doğrula**

```
pytest tests/graphs/report/test_context_preservation.py -v
```

Expected: Tüm test'ler PASS. Helper zaten `visualization_explicitly_set=False` default kullanıyor.

- [ ] **Step 2: Tam test suite**

```
pytest tests/ -x -q --tb=short
```

Expected: Tüm test'ler PASS.

- [ ] **Step 3: Final commit — plan tamamlandı işareti**

```
git add tests/graphs/report/test_context_preservation.py
git commit -m "test(context): finalize context preservation test suite — all 4 RCs covered"
```

---

## Gelecek İş: Multi-Query Karşılaştırma Hatası

> **Şimdilik implemente edilmeyecek.** Aşağıdaki senaryo için plan notu bırakılmıştır.

**Senaryo:**
1. User: "En çok satan içecek" (NEW_QUERY A → context: A)
2. User: "Kahvaltı ürünleri" (NEW_QUERY B → context: B, A context temizlendi)
3. User: "Bunları karşılaştır" → context yalnızca B var, A kayıp

**Beklenen Davranış:** "Bu iki sorguyu şu an karşılaştıramam. Lütfen karşılaştırmayı tek sorguda belirtin."

**Mevcut Durum:** `MODIFY_AMBIGUITY_THRESHOLD = 0.85` → "Bunları karşılaştır" confidence < 0.85 ise kullanıcıya "Yeni sorgu mu, mevcut sorguyu değiştir mi?" diye soruluyor. Bu kısmi koruma sağlıyor.

**Gelecekteki Tam Fix:**
1. `state.py`'e `query_session_id: Optional[str]` ekle — her NEW_QUERY'de UUID üret
2. `classify_intent_node`'da: COMPARISON intent + "bunlar" referansı + mevcut session farklıysa → interrupt
3. `IntentClassificationResult`'a `references_previous_result: bool` ekle
4. Prompt: "Kullanıcı önceki FARKLI sorgu sonucuna atıf yapıyor mu?" → True ise interrupt ile hata mesajı ver

---

## Özet Tablo

| Task | Root Cause | Dosya | Satır | Token | Latency |
|---|---|---|---|---|---|
| 1 | RC #1: active_filters kaybolması | nodes.py | 147 | 0 | 0 |
| 2 | RC #3: wants_visualization recalc | prompts.py, nodes.py | 10, 112 | +1 field | 0 |
| 3 | RC #2a: modify_sql filter delta | nodes.py | 171 | 0 | 0 |
| 4 | RC #2b: sql_executor filter wipe | text2sql/nodes.py | 1326 | 0 | 0 |
| 5 | Docs | state.py | 26 | 0 | 0 |
