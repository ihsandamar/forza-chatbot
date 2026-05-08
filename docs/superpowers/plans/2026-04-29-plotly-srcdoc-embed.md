# Plotly srcdoc Embed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the base64-encoded iframe with an `srcdoc`-based iframe so Plotly charts embed cleanly in Vue frontend without layout breakage.

**Architecture:** Single function edit in `build_response_node`. The iframe's `src="data:text/html;base64,..."` becomes `srcdoc="..."` with proper HTML entity escaping. Inner HTML gains responsive CSS so the Plotly div fills the iframe. Height changes from `100vh` to `480px` (or `600px` for turkey_map).

**Tech Stack:** Python, pytest, pytest-asyncio, langchain-core AIMessage

---

### Task 1: Write failing test for srcdoc iframe output

**Files:**
- Create: `tests/graphs/report/test_build_response_node.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for build_response_node — iframe output format."""
import pytest
from langchain_core.messages import AIMessage


def _make_chart_state(chart_type: str = "bar_chart", snippet: str = '<div id="x"></div>') -> dict:
    return {
        "results": [{"A": 1}],
        "visualization_output": {
            "needs_graph": True,
            "chart_type": chart_type,
            "plotly_html_snippet": snippet,
            "summary": "Test chart",
        },
    }


@pytest.mark.asyncio
async def test_build_response_uses_srcdoc():
    """iframe must use srcdoc, not base64 data URI."""
    from src.graphs.report_agent.nodes import build_response_node

    result = await build_response_node(_make_chart_state())

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'srcdoc=' in chart_html
    assert 'data:text/html' not in chart_html
    assert 'base64' not in chart_html


@pytest.mark.asyncio
async def test_build_response_iframe_height_default():
    """Regular charts get 480px height."""
    from src.graphs.report_agent.nodes import build_response_node

    result = await build_response_node(_make_chart_state(chart_type="bar_chart"))

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'height:480px' in chart_html


@pytest.mark.asyncio
async def test_build_response_iframe_height_turkey_map():
    """turkey_map gets 600px height for extra vertical space."""
    from src.graphs.report_agent.nodes import build_response_node

    result = await build_response_node(_make_chart_state(chart_type="turkey_map"))

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'height:600px' in chart_html


@pytest.mark.asyncio
async def test_build_response_srcdoc_escaping():
    """Double quotes in the snippet must be escaped as &quot; in srcdoc attribute."""
    from src.graphs.report_agent.nodes import build_response_node

    snippet = '<div id="myChart" style="color:red"></div>'
    result = await build_response_node(_make_chart_state(snippet=snippet))

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    # The " characters in the snippet must appear as &quot; — not raw " — inside the srcdoc value
    assert 'srcdoc="' in chart_html
    assert '&quot;' in chart_html


@pytest.mark.asyncio
async def test_build_response_inner_css_present():
    """Inner HTML must contain responsive CSS for plotly-graph-div."""
    from src.graphs.report_agent.nodes import build_response_node

    result = await build_response_node(_make_chart_state())

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'plotly-graph-div' in chart_html
    assert '100%' in chart_html


@pytest.mark.asyncio
async def test_build_response_no_graph_falls_back_to_table():
    """When needs_graph is False, markdown table is returned (no iframe)."""
    from src.graphs.report_agent.nodes import build_response_node

    state = {
        "results": [{"Name": "A", "Value": 1}],
        "visualization_output": {"needs_graph": False},
    }
    result = await build_response_node(state)

    assert "chart_html" not in result["messages"][0].additional_kwargs
    assert "iframe" not in result["final_response"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/graphs/report/test_build_response_node.py -v
```

Expected: All `test_build_response_uses_srcdoc`, `test_build_response_iframe_height_*`, `test_build_response_srcdoc_escaping`, `test_build_response_inner_css_present` FAIL. `test_build_response_no_graph_falls_back_to_table` may pass already.

---

### Task 2: Implement srcdoc iframe in build_response_node

**Files:**
- Modify: `src/graphs/report_agent/nodes.py:544–565`

- [ ] **Step 3: Replace the base64 block with srcdoc**

In `src/graphs/report_agent/nodes.py`, find the `elif viz.get("needs_graph") and viz.get("plotly_html_snippet"):` branch (starts around line 544). Replace the entire iframe-building block:

**Remove** (lines ~545–565):
```python
        import base64

        html_snippet = viz["plotly_html_snippet"]
        summary = viz.get("summary", "Grafiğiniz oluşturuldu.")
        chart_type = viz.get("chart_type", "chart")
        row_count = len(results)

        # Wrap div snippet in full HTML document
        full_html = (
            '<!DOCTYPE html>\n<html>\n<head>\n'
            '    <meta charset="UTF-8">\n'
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            '</head>\n<body style="margin:0;padding:0;">\n'
            f'{html_snippet}\n'
            '</body>\n</html>'
        )
        b64 = base64.b64encode(full_html.encode("utf-8")).decode("utf-8")
        iframe = (
            f'<iframe src="data:text/html;charset=utf-8;base64,{b64}" '
            f'style="width:100%;height:100vh;border:none;"></iframe>'
        )
```

**Add** (same position):
```python
        html_snippet = viz["plotly_html_snippet"]
        summary = viz.get("summary", "Grafiğiniz oluşturuldu.")
        chart_type = viz.get("chart_type", "chart")
        row_count = len(results)

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
        height = '600px' if chart_type == 'turkey_map' else '480px'
        iframe = (
            f'<iframe srcdoc="{srcdoc}" '
            f'style="width:100%;height:{height};border:none;display:block;"></iframe>'
        )
```

- [ ] **Step 4: Run the tests**

```bash
pytest tests/graphs/report/test_build_response_node.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 5: Run broader test suite to check for regressions**

```bash
pytest tests/graphs/report/ tests/api/ -v --tb=short
```

Expected: All previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/test_build_response_node.py
git commit -m "fix(renderer): replace base64 iframe with srcdoc for embeddable charts

- srcdoc avoids data URI; browser parses HTML directly
- height fixed to 480px (600px for turkey_map) instead of 100vh
- inner CSS forces .plotly-graph-div to fill the iframe
- & and \" properly entity-escaped in srcdoc attribute value"
```
