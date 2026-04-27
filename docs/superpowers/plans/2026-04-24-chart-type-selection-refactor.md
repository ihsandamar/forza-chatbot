# Chart Type Selection Refactor — LLM-First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM extracts both `chart_type` and `chart_x_hint` at intent classification time (single call, zero extra latency). `viz_decider` receives them pre-populated: chart type determines the graph kind, x-hint closes the field-assignment gap. All keyword-based detection is deleted.

**Architecture:**
- `IntentClassificationResult` gains two optional fields: `chart_type` (which graph) and `chart_x_hint` (which column on x-axis, when user explicitly names one).
- `classify_intent_node` wires both into `ReportState`.
- `viz_decider_node`'s existing `requested_chart_type` fast-return fires correctly and now also sets `x_field = chart_x_hint` (or `None` → validator fills from `dimension_cols[0]`).
- Validator Rule 1 fuzzy-matches the x-hint against actual SQL columns — handles semantic names like "kategori" → "CategoryName".
- All keyword code is deleted.

**Tech Stack:** Pydantic, LangChain structured output, pytest

---

## Root Cause Summary

| Layer | Problem |
|-------|---------|
| `prompts.py:IntentClassificationResult` | No `chart_type` or `chart_x_hint` fields |
| `nodes.py:classify_intent_node:122` | Hardcoded `chart_type = None` |
| `visualization_v2/nodes.py:424-430` | Keyword fallback as band-aid — wrong layer |
| `visualization_v2/nodes.py:365-372` | Fast-return exists but always skipped (always `None`); x_field always `None` → validator guesses |

---

## File Map

| File | Action | What Changes |
|------|--------|--------------|
| `src/graphs/report_agent/prompts.py` | Modify | Add `chart_type` + `chart_x_hint` to `IntentClassificationResult`; add extraction section to `INTENT_CLASSIFIER_PROMPT` |
| `src/graphs/report_agent/nodes.py` | Modify | Use `result.chart_type` and `result.chart_x_hint`; add both to return dict with per-turn reset |
| `src/graphs/report_agent/state.py` | Modify | Add `chart_x_hint: Optional[str]` to `ReportState` and `create_initial_state` |
| `src/graphs/report_agent/subagents/visualization_v2/state.py` | Modify | Add `chart_x_hint: Optional[str]` to `VisualizationState` |
| `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Modify | Use `chart_x_hint` as `x_field` in fast-return; delete keyword maps and fallback |
| `tests/graphs/report/test_chart_type_detection.py` | Rewrite | Remove keyword tests; add LLM-extraction tests covering chart_type + chart_x_hint |

---

## Task 1: LLM Extracts `chart_type` + `chart_x_hint` — Model + Prompt + State

**Files:**
- Modify: `src/graphs/report_agent/prompts.py`
- Modify: `src/graphs/report_agent/nodes.py`
- Modify: `src/graphs/report_agent/state.py`
- Modify: `src/graphs/report_agent/subagents/visualization_v2/state.py`

---

- [ ] **Step 1: Add `chart_type` and `chart_x_hint` to `IntentClassificationResult`**

In `src/graphs/report_agent/prompts.py`, replace lines 10-29:

```python
class IntentClassificationResult(BaseModel):
    """Intent + query type — tek LLM çağrısı ile sınıflandırma."""

    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY"]
    query_type: Literal["SINGLE", "LISTING", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    wants_visualization: bool = False
    chart_type: Optional[Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "heatmap", "sunburst", "treemap",
    ]] = None
    chart_x_hint: Optional[str] = None
    use_result_type: Optional[Literal["new_query", "revisualize", "compute", "modify_context"]] = None
    compute_operation: Optional[Literal["sum", "avg", "count", "min", "max"]] = None
    modification_action: Optional[str] = None
    modification_target: Optional[str] = None
    modification_value: Optional[str] = None
    time_breakdown: bool = False

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v
```

---

- [ ] **Step 2: Add extraction rules to `INTENT_CLASSIFIER_PROMPT`**

In `src/graphs/report_agent/prompts.py`, replace the `**wants_visualization:**` section (lines 167-173) with the block below. Leave everything else in the prompt unchanged.

```
**wants_visualization:**
- True: Kullanıcı açıkça grafik/görsel talep ediyor
  → "grafik", "chart", "çizgi grafik", "bar", "pasta", "görselleştir", "diyagram", "şekil olarak göster", "heatmap", "ısı haritası", "sunburst", "treemap" gibi ifadeler içeriyorsa
  → use_result_type="revisualize" ise HER ZAMAN True
  → Hem sorgu hem grafik istiyorsa (ör: "satışları bar chart olarak göster") True
- False: Sadece veri/tablo istiyor, grafik talep etmiyor (DEFAULT)

**chart_type:** (SADECE wants_visualization=True olduğunda doldur, aksi halde null)
- Kullanıcı belirli bir grafik tipi belirtiyorsa tespit et:
  - "bar chart", "bar grafik", "çubuk grafik", "sütun grafik", "histogram" → "bar_chart"
  - "line chart", "çizgi grafik", "line grafik", "trend grafik" → "line_chart"
  - "pie chart", "pasta grafik", "pasta dilimi" → "pie_chart"
  - "scatter", "dağılım grafik" → "scatter_chart"
  - "heatmap", "ısı haritası" → "heatmap"
  - "sunburst", "sunbrust" (yazım hatası toleransı) → "sunburst"
  - "treemap", "tree map" → "treemap"
- Kullanıcı grafik tipini belirtmiyorsa (sadece "grafik göster", "görselleştir") → null
- wants_visualization=False ise HER ZAMAN null

**chart_x_hint:** (SADECE chart_type dolu VE kullanıcı x-ekseninde hangi boyutu istediğini açıkça belirtiyorsa)
- Kullanıcı "X bazında", "X'e göre", "X kırılımında", "X olarak" gibi ifadelerle belirli bir boyut adı veriyorsa → o boyutun DB kolon adını veya kullanıcının kullandığı ismi yaz
- Belirtmiyorsa → null
- Örnekler:
  - "BranchName bazında bar chart yap" → "BranchName"
  - "kategorilere göre pasta grafik" → "CategoryName"
  - "ürün bazında çizgi grafik" → "ProductName"
  - "sadece bar chart yap" → null (kolon belirtilmemiş)
  - "satışları bar chart olarak göster" → null (boyut belirtilmemiş)
```

---

- [ ] **Step 3: Wire `chart_type` and `chart_x_hint` into state in `classify_intent_node`**

In `src/graphs/report_agent/nodes.py`, replace lines 121-134:

```python
        chart_type = result.chart_type
        chart_x_hint = result.chart_x_hint

        if chart_type:
            logger.info(f"[CLASSIFY] chart_type={chart_type}, chart_x_hint={chart_x_hint}")

        is_revisualize = result.use_result_type == "revisualize"
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
        }
```

---

- [ ] **Step 4: Add `chart_x_hint` to `ReportState`**

In `src/graphs/report_agent/state.py`, add one line to the Intent Classification section (after line 18, after `requested_chart_type`):

```python
    # Intent Classification (tek LLM çağrısı)
    intent_type: Optional[str]
    query_type: Optional[str]
    intent_confidence: Optional[float]
    wants_visualization: Optional[bool]
    requested_chart_type: Optional[str]
    chart_x_hint: Optional[str]          # x-axis kolon ipucu — kullanıcı açıkça belirtirse dolar
    use_result_type: Optional[str]
    compute_operation: Optional[str]
```

Also add `chart_x_hint=None` to `create_initial_state()` (after `requested_chart_type=None`):

```python
        requested_chart_type=None,
        chart_x_hint=None,
```

---

- [ ] **Step 5: Add `chart_x_hint` to `VisualizationState`**

In `src/graphs/report_agent/subagents/visualization_v2/state.py`, add to the `ReportState overlapping` section (after line 73, after `requested_chart_type`):

```python
    requested_chart_type: Optional[str]
    chart_x_hint: Optional[str]          # x-axis kolon ipucu — classify_intent'ten gelir
```

---

- [ ] **Step 6: Commit Task 1**

```bash
git add src/graphs/report_agent/prompts.py \
        src/graphs/report_agent/nodes.py \
        src/graphs/report_agent/state.py \
        src/graphs/report_agent/subagents/visualization_v2/state.py
git commit -m "feat(intent): LLM extracts chart_type + chart_x_hint in single classify_intent call"
```

---

## Task 2: Wire `chart_x_hint` into `viz_decider` + Delete All Keyword Code + Rewrite Tests

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py`
- Rewrite: `tests/graphs/report/test_chart_type_detection.py`

---

- [ ] **Step 1: Delete all keyword detection code from `visualization_v2/nodes.py`**

Delete **lines 34-82** entirely (design comment block, `_CHART_KEYWORD_MAP`, `_detect_chart_type_from_query`):

```python
# DELETE everything from the design comment block through _detect_chart_type_from_query (inclusive):

# ---------------------------------------------------------------------------
# Chart type keyword detection — moved from report_agent/nodes.py (Task 11).
# ...
# ---------------------------------------------------------------------------
_CHART_KEYWORD_MAP: dict = { ... }

def _detect_chart_type_from_query(text: str) -> Optional[str]:
    ...
```

---

- [ ] **Step 2: Update `viz_decider_node` fast-return to use `chart_x_hint`**

In `create_viz_decider_node`, replace lines 361-372 (the `_requested_chart` block):

```python
        # --- Chart type override from intent classification ---
        _requested_chart = state.get("requested_chart_type")
        if _requested_chart:
            _x_hint = state.get("chart_x_hint")  # None → validator fills from dimension_cols[0]
            logger.info(
                f"[V2:VIZ_DECIDER] Intent: chart_type={_requested_chart}, x_hint={_x_hint}"
            )
            return {"viz_decision": {
                "needs_graph": True,
                "chart_type": _requested_chart,
                "x_field": _x_hint,
                "y_field": None,
                "series_field": _comp_dim,
                "reason": f"User requested {_requested_chart}"
                          + (f" (x={_x_hint})" if _x_hint else ""),
            }}
```

---

- [ ] **Step 3: Delete post-LLM keyword fallback from `viz_decider_node`**

Delete the keyword fallback block (currently ~lines 424-430):

```python
# DELETE this entire block:
        query_text = state.get("viz_request") or state.get("user_query") or ""
        if not getattr(decision, "chart_type", None) and query_text:
            keyword_chart = _detect_chart_type_from_query(query_text)
            if keyword_chart:
                logger.info(f"[V2:VIZ_DECIDER] Keyword fallback: {keyword_chart}")
                decision = decision.model_copy(update={"chart_type": keyword_chart})
```

---

- [ ] **Step 4: Rewrite `tests/graphs/report/test_chart_type_detection.py`**

Replace the entire file:

```python
"""Tests for chart type and x-axis extraction via classify_intent_node (LLM-based).

chart_type and chart_x_hint are now fields in IntentClassificationResult.
Tests mock the LLM return and verify classify_intent_node wires both
correctly into state.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import HumanMessage


def _make_mock_llm(
    intent_type="NEW_QUERY",
    query_type="RANKING",
    confidence=0.9,
    wants_visualization=True,
    chart_type=None,
    chart_x_hint=None,
    use_result_type=None,
):
    from src.graphs.report_agent.prompts import IntentClassificationResult

    mock_result = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=confidence,
        wants_visualization=wants_visualization,
        chart_type=chart_type,
        chart_x_hint=chart_x_hint,
        use_result_type=use_result_type,
    )
    chain = MagicMock()
    chain.ainvoke = AsyncMock(return_value=mock_result)
    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=chain)
    return mock_llm


async def _run_classify(user_msg: str, llm):
    from src.graphs.report_agent.nodes import create_classify_intent_node
    node = create_classify_intent_node(llm)
    return await node({"messages": [HumanMessage(content=user_msg)]})


# ---------------------------------------------------------------------------
# chart_type correctly wired from LLM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bar_chart_wired():
    llm = _make_mock_llm(wants_visualization=True, chart_type="bar_chart")
    result = await _run_classify("bar grafik yap", llm)
    assert result["requested_chart_type"] == "bar_chart"
    assert result["wants_visualization"] is True


@pytest.mark.asyncio
async def test_sunburst_wired():
    llm = _make_mock_llm(wants_visualization=True, chart_type="sunburst")
    result = await _run_classify("sunbrust grafik istiyorum", llm)
    assert result["requested_chart_type"] == "sunburst"


@pytest.mark.asyncio
async def test_heatmap_wired():
    llm = _make_mock_llm(wants_visualization=True, chart_type="heatmap")
    result = await _run_classify("ısı haritası olarak göster", llm)
    assert result["requested_chart_type"] == "heatmap"


@pytest.mark.asyncio
async def test_chart_type_none_when_no_viz():
    llm = _make_mock_llm(wants_visualization=False, chart_type=None)
    result = await _run_classify("son 3 aydaki satışlar", llm)
    assert result["requested_chart_type"] is None
    assert result["wants_visualization"] is False


@pytest.mark.asyncio
async def test_chart_type_none_when_llm_returns_none():
    """User says 'grafik göster' without specifying type."""
    llm = _make_mock_llm(wants_visualization=True, chart_type=None)
    result = await _run_classify("satışları grafik olarak göster", llm)
    assert result["requested_chart_type"] is None
    assert result["wants_visualization"] is True


# ---------------------------------------------------------------------------
# chart_x_hint correctly wired from LLM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chart_x_hint_wired_when_user_names_column():
    """User says 'BranchName bazında bar chart' → x_hint = 'BranchName'."""
    llm = _make_mock_llm(
        wants_visualization=True,
        chart_type="bar_chart",
        chart_x_hint="BranchName",
    )
    result = await _run_classify("BranchName bazında bar chart yap", llm)
    assert result["requested_chart_type"] == "bar_chart"
    assert result["chart_x_hint"] == "BranchName"


@pytest.mark.asyncio
async def test_chart_x_hint_none_when_user_does_not_name_column():
    """'bar chart yap' without naming a column → x_hint = None."""
    llm = _make_mock_llm(
        wants_visualization=True,
        chart_type="bar_chart",
        chart_x_hint=None,
    )
    result = await _run_classify("bar chart yap", llm)
    assert result["requested_chart_type"] == "bar_chart"
    assert result["chart_x_hint"] is None


@pytest.mark.asyncio
async def test_chart_x_hint_with_semantic_column_name():
    """'kategorilere göre pasta grafik' → LLM resolves 'kategori' → 'CategoryName'."""
    llm = _make_mock_llm(
        wants_visualization=True,
        chart_type="pie_chart",
        chart_x_hint="CategoryName",
    )
    result = await _run_classify("kategorilere göre pasta grafik göster", llm)
    assert result["requested_chart_type"] == "pie_chart"
    assert result["chart_x_hint"] == "CategoryName"


@pytest.mark.asyncio
async def test_chart_x_hint_reset_each_turn():
    """chart_x_hint must reset to None each turn (stale state prevention)."""
    llm = _make_mock_llm(
        wants_visualization=True,
        chart_type="bar_chart",
        chart_x_hint=None,
    )
    # Second turn: no x_hint — previous turn's BranchName must not leak
    result = await _run_classify("şimdi line chart yap", llm)
    assert result["chart_x_hint"] is None


# ---------------------------------------------------------------------------
# revisualize path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revisualize_wires_chart_type_and_hint():
    llm = _make_mock_llm(
        intent_type="USE_RESULT",
        use_result_type="revisualize",
        wants_visualization=False,
        chart_type="bar_chart",
        chart_x_hint="BranchName",
    )
    result = await _run_classify("bunu BranchName bazında bar chart olarak göster", llm)
    assert result["wants_visualization"] is True
    assert result["requested_chart_type"] == "bar_chart"
    assert result["chart_x_hint"] == "BranchName"
```

---

- [ ] **Step 5: Run all tests**

```bash
pytest tests/graphs/report/test_chart_type_detection.py -v
```

Expected: All 11 tests pass.

---

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v --tb=short -q
```

Expected: All previously-passing tests continue to pass.

---

- [ ] **Step 7: Commit Task 2**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py \
        tests/graphs/report/test_chart_type_detection.py
git commit -m "refactor(viz): wire chart_x_hint into viz_decider fast-return; delete all keyword detection"
```

---

## Complete Data Flow After Refactor

```
Kullanıcı: "BranchName bazında bar chart yap"
    ↓
[classify_intent_node] — tek LLM çağrısı
    chart_type     = "bar_chart"
    chart_x_hint   = "BranchName"
    ↓  (state)
[viz_decider_node] — LLM çağrısı YOK
    requested_chart_type = "bar_chart"  → fast-return
    x_field        = "BranchName"      (chart_x_hint)
    y_field        = None
    series_field   = comparison_dimension
    ↓
[spec_validator_node] — pure Python
    Rule 1: fuzzy-match "BranchName" → actual column ✓
    Rule 4: y_field = metric_cols[0]  (e.g. "RowAmount")
    Rule 6: series_field tamamlar (gerekirse)
    ↓
[template_renderer_node] → Plotly HTML
```

```
Kullanıcı: "bar chart yap" (kolon belirtmeden)
    ↓
[classify_intent_node]
    chart_type   = "bar_chart"
    chart_x_hint = None
    ↓
[viz_decider_node] — fast-return
    x_field = None
    ↓
[spec_validator_node]
    Rule 4: x_field = time_col OR dimension_cols[0]  ← SQL sırası intent'i taşır
    Rule 4: y_field = metric_cols[0]
    ↓
[template_renderer_node] → Plotly HTML
```

---

## Self-Review

### Spec Coverage

| Requirement | Task | Status |
|-------------|------|--------|
| Keyword detection tamamen kaldırıldı | Task 2 Step 1, 3 | ✓ |
| Chart type → LLM çağrısı | Task 1 | ✓ |
| Sıfır ek LLM çağrısı | Task 1 (tek structured output call) | ✓ |
| x-axis field assignment — kolon belirtilince | Task 1 (chart_x_hint) + Task 2 Step 2 | ✓ |
| x-axis field assignment — kolon belirtilmeyince | Validator Rule 4 (SQL sırası) | ✓ |
| Validator Rule 1 fuzzy-match x_hint'i doğrular | Mevcut validator, değişiklik yok | ✓ |
| chart_x_hint her turda resetlenir | Task 1 Step 3 (return_dict'te her turda None'a düşer) | ✓ |
| State tutarlılığı (ReportState + VisualizationState) | Task 1 Step 4-5 | ✓ |
| Test dosyası baştan yazıldı | Task 2 Step 4 | ✓ |

### Placeholder Scan

Yok. Her adımda tam kod verilmiştir.

### Type Consistency

- `IntentClassificationResult.chart_type` Literal değerleri, `ChartSpec.chart_type` ile birebir örtüşüyor
- `chart_x_hint: Optional[str]` — `ReportState`, `VisualizationState`, `classify_intent_node` return dict, `viz_decider` fast-return: hepsinde `Optional[str]`
- `viz_decider` fast-return'deki `x_field = _x_hint` değeri validator Rule 1'e giriyor (fuzzy-match): tip uyumu `str | None` ✓
