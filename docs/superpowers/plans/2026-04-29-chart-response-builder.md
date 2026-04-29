# Chart Response Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded technical metadata summary in chart responses with a section-based, strategy-selectable (LLM or Python) natural-language response builder.

**Architecture:** New `response_builder.py` module owns all response text assembly. `build_response_node` in `nodes.py` becomes a factory (`create_build_response_node(llm=None)`) that delegates summary text to `build_chart_response()`. `graph.py` registers the factory. Mode is controlled via `CHART_INSIGHT_MODE` env var (`llm` | `python` | `off`, default `python`).

**Tech Stack:** Python, dataclasses, pytest, pytest-asyncio, unittest.mock, langchain-core AIMessage

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/graphs/report_agent/response_builder.py` | **Create** | Section builders, strategy selection, `ResponseConfig`, `build_chart_response` |
| `src/graphs/report_agent/nodes.py` | **Modify** | Factory-ify `build_response_node` → `create_build_response_node(llm)`, import + call `build_chart_response` |
| `src/graphs/report_agent/graph.py` | **Modify** | Update import + node registration to `create_build_response_node(llm)` |
| `tests/graphs/report/test_response_builder.py` | **Create** | Unit tests for `response_builder.py` in isolation |
| `tests/graphs/report/test_build_response_node.py` | **Modify** | Update all tests to use `create_build_response_node()`, add format regression test |

---

### Task 1: Create `response_builder.py` with tests

**Files:**
- Create: `src/graphs/report_agent/response_builder.py`
- Create: `tests/graphs/report/test_response_builder.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/graphs/report/test_response_builder.py`:

```python
"""Unit tests for response_builder — isolated from nodes/graph."""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# _insight_python
# ---------------------------------------------------------------------------

def test_insight_python_finds_top_entry():
    from src.graphs.report_agent.response_builder import _insight_python
    results = [
        {"City": "Ankara", "Amount": 2400000},
        {"City": "Istanbul", "Amount": 1800000},
        {"City": "Izmir", "Amount": 900000},
    ]
    viz = {"x_field": "City", "y_field": "Amount", "title": "Sehir Satislari"}
    result = _insight_python(results, viz)
    assert "Ankara" in result
    assert "2,400,000" in result
    assert "3 kayıt" in result


def test_insight_python_no_xy_fields():
    from src.graphs.report_agent.response_builder import _insight_python
    results = [{"A": 1}, {"A": 2}]
    result = _insight_python(results, {})
    assert "2 kayıt" in result


def test_insight_python_handles_non_numeric_y():
    from src.graphs.report_agent.response_builder import _insight_python
    results = [{"City": "X", "Amount": "not_a_number"}]
    viz = {"x_field": "City", "y_field": "Amount", "title": ""}
    result = _insight_python(results, viz)
    assert "1 kayıt" in result


def test_insight_python_includes_title_prefix():
    from src.graphs.report_agent.response_builder import _insight_python
    results = [{"Cat": "A", "Val": 10}]
    viz = {"x_field": "Cat", "y_field": "Val", "title": "Kategori Analizi"}
    result = _insight_python(results, viz)
    assert result.startswith("Kategori Analizi:")


# ---------------------------------------------------------------------------
# _metadata_section
# ---------------------------------------------------------------------------

def test_metadata_section_known_chart_type():
    from src.graphs.report_agent.response_builder import _metadata_section
    result = _metadata_section({"chart_type": "sunburst"}, 64)
    assert "Sunburst" in result
    assert "64 kayıt" in result


def test_metadata_section_bar_chart_label():
    from src.graphs.report_agent.response_builder import _metadata_section
    result = _metadata_section({"chart_type": "bar_chart"}, 10)
    assert "Cubuk Grafik" in result or "ubuk" in result


def test_metadata_section_unknown_type_uses_fallback():
    from src.graphs.report_agent.response_builder import _metadata_section
    result = _metadata_section({"chart_type": "unknown_type"}, 5)
    assert "5 kayıt" in result


# ---------------------------------------------------------------------------
# build_chart_response — python mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_chart_response_python_includes_insight_and_metadata():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"City": "A", "Amount": 100}, {"City": "B", "Amount": 50}]
    viz = {"x_field": "City", "y_field": "Amount", "title": "Test", "chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="python", show_metadata=True)
    result = await build_chart_response(results, viz, "satis?", config)
    assert "A" in result          # top entry
    assert "kayıt" in result      # row count appears


@pytest.mark.asyncio
async def test_build_chart_response_metadata_off():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"City": "A", "Amount": 100}]
    viz = {"x_field": "City", "y_field": "Amount", "title": "", "chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="python", show_metadata=False)
    result = await build_chart_response(results, viz, "", config)
    # metadata separator not present
    assert "·" not in result


@pytest.mark.asyncio
async def test_build_chart_response_off_mode_returns_count():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"A": 1}, {"A": 2}]
    viz = {"chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="off", show_metadata=False)
    result = await build_chart_response(results, viz, "", config)
    assert "2 kayıt" in result


# ---------------------------------------------------------------------------
# build_chart_response — llm mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_chart_response_llm_calls_llm_and_returns_content():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"City": "Ankara", "Amount": 500}]
    viz = {"x_field": "City", "y_field": "Amount", "title": "T", "chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="llm", show_metadata=True)
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Ankara one cikiyor."
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    result = await build_chart_response(results, viz, "satis?", config, llm=mock_llm)
    assert "Ankara one cikiyor." in result
    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_build_chart_response_llm_falls_back_on_error():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"City": "B", "Amount": 500}]
    viz = {"x_field": "City", "y_field": "Amount", "title": "T", "chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="llm", show_metadata=False)
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM down"))
    result = await build_chart_response(results, viz, "", config, llm=mock_llm)
    assert "B" in result   # python fallback used
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/graphs/report/test_response_builder.py -v
```

Expected: All tests FAIL with `ModuleNotFoundError` for `response_builder`.

- [ ] **Step 3: Create `src/graphs/report_agent/response_builder.py`**

```python
"""
Chart Response Builder

Section-based, strategy-selectable response text for chart responses.
Consumed by create_build_response_node in nodes.py.

Sections (order preserved):
  1. insight  — natural language summary (llm | python | off)
  2. metadata — compact chart info line (on | off)

Adding a new section: add a function + a field to ResponseConfig.
build_chart_response calls it conditionally. No other files change.
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

logger = logging.getLogger(__name__)


@dataclass
class ResponseConfig:
    insight_mode: Literal["llm", "python", "off"] = "python"
    show_metadata: bool = True


DEFAULT_CONFIG = ResponseConfig(
    insight_mode=os.getenv("CHART_INSIGHT_MODE", "python"),  # type: ignore[arg-type]
    show_metadata=os.getenv("CHART_SHOW_METADATA", "true").lower() != "false",
)

_CHART_TYPE_LABELS = {
    "bar_chart":     "Çubuk Grafik",
    "line_chart":    "Çizgi Grafik",
    "pie_chart":     "Pasta Grafik",
    "scatter_chart": "Dağılım Grafik",
    "scatter":       "Dağılım Grafik",
    "sunburst":      "Sunburst",
    "treemap":       "Treemap",
    "comparison":    "Karşılaştırma",
    "heatmap":       "Isı Haritası",
    "turkey_map":    "Türkiye Haritası",
}


def _insight_python(results: list, viz: dict) -> str:
    x = viz.get("x_field")
    y = viz.get("y_field")
    title = viz.get("title") or ""
    n = len(results)
    prefix = f"{title}: " if title else ""

    if x and y:
        try:
            top = max(results, key=lambda r: float(r.get(y) or 0))
            top_label = top.get(x, "?")
            top_val = float(top.get(y) or 0)
            return f"{prefix}{top_label} en yüksek değerde ({top_val:,.0f}). {n} kayıt analiz edildi."
        except (TypeError, ValueError, KeyError):
            pass
    return f"{prefix}{n} kayıt analiz edildi."


async def _insight_llm(results: list, viz: dict, user_query: str, llm) -> str:
    title = viz.get("title") or ""
    sample = results[:10]
    prompt = (
        f"Kullanıcı sorusu: {user_query}\n"
        f"Grafik başlığı: {title}\n"
        f"Veri ({len(sample)} kayıt): {json.dumps(sample, ensure_ascii=False, default=str)}\n\n"
        "Yukarıdaki verilere dayanarak 1-2 cümlelik Türkçe bir içgörü yaz. "
        "Sadece içgörü cümlesini yaz, başlık veya ek açıklama ekleme."
    )
    try:
        response = await llm.ainvoke(prompt)
        return response.content.strip()
    except Exception as e:
        logger.warning(f"[RESPONSE_BUILDER] LLM insight failed, falling back to python: {e}")
        return _insight_python(results, viz)


def _metadata_section(viz: dict, row_count: int) -> str:
    chart_type = viz.get("chart_type", "")
    label = _CHART_TYPE_LABELS.get(
        chart_type,
        chart_type.replace("_", " ").title() if chart_type else "Grafik",
    )
    return f"{label} · {row_count} kayıt"


async def build_chart_response(
    results: list,
    viz: dict,
    user_query: str,
    config: ResponseConfig,
    llm=None,
) -> str:
    """Assemble chart response text from enabled sections."""
    parts: list[str] = []

    if config.insight_mode == "llm" and llm is not None:
        insight = await _insight_llm(results, viz, user_query, llm)
    elif config.insight_mode == "python":
        insight = _insight_python(results, viz)
    else:
        insight = None

    if insight:
        parts.append(insight)

    if config.show_metadata:
        parts.append(_metadata_section(viz, len(results)))

    return "\n".join(parts) if parts else f"{len(results)} kayıt analiz edildi."
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/graphs/report/test_response_builder.py -v
```

Expected: All 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/response_builder.py tests/graphs/report/test_response_builder.py
git commit -m "feat(response-builder): add section-based chart response builder

- ResponseConfig controls insight mode (llm/python/off) and metadata
- _insight_python: top entry + row count from x/y fields
- _insight_llm: GPT call with fallback to python on error
- _metadata_section: compact chart type label + row count
- CHART_INSIGHT_MODE / CHART_SHOW_METADATA env vars"
```

---

### Task 2: Refactor `nodes.py` — factory + wire `build_chart_response`

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`
- Modify: `tests/graphs/report/test_build_response_node.py`

- [ ] **Step 6: Update existing node tests to use factory**

In `tests/graphs/report/test_build_response_node.py`, every test currently does:
```python
from src.graphs.report_agent.nodes import build_response_node
result = await build_response_node(_make_chart_state())
```

Replace ALL 6 test imports + calls with the factory pattern. Also add one new test for the format regression. Full updated file:

```python
"""Tests for create_build_response_node — iframe output format + response text."""
import pytest


def _make_chart_state(chart_type: str = "bar_chart", snippet: str = '<div id="x"></div>') -> dict:
    return {
        "results": [{"City": "Ankara", "Amount": 1000}],
        "user_query": "satis raporu",
        "visualization_output": {
            "needs_graph": True,
            "chart_type": chart_type,
            "plotly_html_snippet": snippet,
            "summary": "Test chart",
            "x_field": "City",
            "y_field": "Amount",
            "title": "Test Grafik",
        },
    }


@pytest.mark.asyncio
async def test_build_response_uses_srcdoc():
    """iframe uses srcdoc (embedding) + src data URI (new tab support)."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state())
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert '<iframe ' in chart_html
    assert 'srcdoc=' in chart_html
    assert 'src="data:text/html' in chart_html


@pytest.mark.asyncio
async def test_build_response_iframe_height_default():
    """Regular charts get 480px height."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state(chart_type="bar_chart"))
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'height:480px' in chart_html


@pytest.mark.asyncio
async def test_build_response_iframe_height_turkey_map():
    """turkey_map gets 600px height."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state(chart_type="turkey_map"))
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'height:600px' in chart_html


@pytest.mark.asyncio
async def test_build_response_srcdoc_escaping():
    """Double quotes in snippet must be escaped as &quot; in srcdoc."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    snippet = '<div id="myChart" data-x="a&b" style="color:red"></div>'
    result = await node_fn(_make_chart_state(snippet=snippet))
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'srcdoc="' in chart_html
    assert '&quot;' in chart_html
    assert '"myChart"' not in chart_html
    assert '&amp;' in chart_html


@pytest.mark.asyncio
async def test_build_response_inner_css_present():
    """Inner HTML must contain responsive CSS for plotly-graph-div."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state())
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'plotly-graph-div' in chart_html
    assert '.plotly-graph-div{width:100%' in chart_html


@pytest.mark.asyncio
async def test_build_response_no_graph_falls_back_to_table():
    """When needs_graph is False, markdown table is returned (no iframe)."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    state = {
        "results": [{"Name": "A", "Value": 1}],
        "visualization_output": {"needs_graph": False},
    }
    result = await node_fn(state)
    assert "chart_html" not in result["messages"][0].additional_kwargs
    assert "iframe" not in result["final_response"]
    assert "Name" in result["final_response"]


@pytest.mark.asyncio
async def test_build_response_summary_text_uses_response_builder():
    """AIMessage.content must come from response_builder, not the old hardcoded format."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state())
    content = result["messages"][0].content
    # Old hardcoded format must be gone
    assert "Görselleştirme Tipi" not in content
    assert "Grafik Gerekli" not in content
    # New format: insight + metadata from response_builder
    assert "kayıt" in content
```

- [ ] **Step 7: Run updated tests — expect FAIL on the new test only**

```bash
pytest tests/graphs/report/test_build_response_node.py -v
```

Expected: `test_build_response_summary_text_uses_response_builder` FAILS (old format still present). The other 6 tests FAIL too because `create_build_response_node` doesn't exist yet (`ImportError`).

- [ ] **Step 8: Refactor `nodes.py`**

At the top of `src/graphs/report_agent/nodes.py`, add this import after the existing imports:

```python
from src.graphs.report_agent.response_builder import build_chart_response, DEFAULT_CONFIG
```

Then find `async def build_response_node(state: dict) -> dict:` (currently around line 530) and replace the entire function with the factory:

```python
def create_build_response_node(llm=None):
    """Factory: returns build_response_node with optional LLM for insight generation."""
    async def build_response_node(state: dict) -> dict:
        import base64
        error = state.get("error")
        results = state.get("results") or []
        viz = state.get("visualization_output") or {}

        if state.get("use_result_type") == "compute" and state.get("final_response"):
            response = state["final_response"]
        elif error:
            response = f"Sorgu hatası: {error}"
        elif not results:
            response = "Bu sorgu için sonuç bulunamadı."
        elif viz.get("needs_graph") and viz.get("plotly_html_snippet"):
            html_snippet = viz["plotly_html_snippet"]
            chart_type = viz.get("chart_type", "chart")

            inner_html = (
                '<!DOCTYPE html><html><head>'
                '<meta charset="UTF-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
                '<style>'
                'html,body{margin:0;padding:0;height:100%;overflow:hidden;}'
                '.plotly-graph-div{width:100%!important;height:100%!important;}'
                '</style>'
                '</head><body>'
                f'{html_snippet}'
                '</body></html>'
            )
            srcdoc = inner_html.replace('&', '&amp;').replace('"', '&quot;')
            src_b64 = base64.b64encode(inner_html.encode("utf-8")).decode("utf-8")
            height = '600px' if chart_type == 'turkey_map' else '480px'
            iframe = (
                f'<iframe srcdoc="{srcdoc}" '
                f'src="data:text/html;charset=utf-8;base64,{src_b64}" '
                f'style="width:100%;height:{height};border:none;display:block;"></iframe>'
            )

            summary_text = await build_chart_response(
                results, viz, state.get("user_query", ""), DEFAULT_CONFIG, llm
            )

            return {
                "final_response": f"{summary_text}\n\n{iframe}",
                "messages": [AIMessage(
                    content=summary_text,
                    additional_kwargs={"chart_html": iframe},
                )],
            }
        else:
            response = _results_to_markdown_table(results)

        return {
            "final_response": response,
            "messages": [AIMessage(content=response)],
        }
    return build_response_node
```

- [ ] **Step 9: Run all node tests**

```bash
pytest tests/graphs/report/test_build_response_node.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 10: Run response_builder tests to confirm no regression**

```bash
pytest tests/graphs/report/test_response_builder.py tests/graphs/report/test_build_response_node.py -v
```

Expected: All 20 tests PASS.

- [ ] **Step 11: Commit**

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_build_response_node.py
git commit -m "refactor(nodes): factory-ify build_response_node, delegate summary to response_builder

- create_build_response_node(llm=None) replaces bare build_response_node
- summary_text now comes from build_chart_response() instead of hardcoded block
- existing iframe/srcdoc logic unchanged"
```

---

### Task 3: Update `graph.py` — import + registration

**Files:**
- Modify: `src/graphs/report_agent/graph.py:21-29,102`

- [ ] **Step 12: Update the import in `graph.py`**

In `src/graphs/report_agent/graph.py`, find the import block (lines 21–29):

```python
from src.graphs.report_agent.nodes import (
    build_response_node,
    create_classify_intent_node,
    create_compute_results_node,
    create_extract_entity_node,
    create_modify_sql_node,
    create_report_chat_node,
    hitl_check_node,
)
```

Replace `build_response_node` with `create_build_response_node`:

```python
from src.graphs.report_agent.nodes import (
    create_build_response_node,
    create_classify_intent_node,
    create_compute_results_node,
    create_extract_entity_node,
    create_modify_sql_node,
    create_report_chat_node,
    hitl_check_node,
)
```

- [ ] **Step 13: Update node registration in `graph.py`**

Find line 102:
```python
graph.add_node("build_response", build_response_node)
```

Replace with:
```python
graph.add_node("build_response", create_build_response_node(llm))
```

- [ ] **Step 14: Run routing tests to confirm graph builds correctly**

```bash
pytest tests/graphs/report/test_graph_routing.py -v
```

Expected: All tests PASS (graph builds, routing works).

- [ ] **Step 15: Run full report test suite**

```bash
pytest tests/graphs/report/ -v --tb=short -q
```

Expected: Same pass/fail ratio as before this task (pre-existing failures in `test_llm_components.py` and `test_hitl_subgraph_lift.py` are unrelated to this change).

- [ ] **Step 16: Commit**

```bash
git add src/graphs/report_agent/graph.py
git commit -m "fix(graph): register create_build_response_node factory with llm"
```
