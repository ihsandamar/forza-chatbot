# Visualization Memory Optimization Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce state serialization overhead in the visualization subgraph by eliminating data duplication, capping Plotly trace count, and adding HTML size guards.

**Architecture:** Three targeted changes to `visualization/nodes.py` — remove dead `data` field from `visualization_output`, add a trace-count guard after `exec()` in `_execute_plotly_code`, and add HTML size logging. No graph structure or state schema changes needed.

**Tech Stack:** Python, LangGraph, Plotly, pytest

---

### Task 1: Remove `data` duplication from `visualization_output`

**Context:**
`response_builder_node` at `visualization/nodes.py:372` stores the full `results` list inside `visualization_output["data"]`. This duplicates `state["results"]` (e.g., 1482 rows = ~300KB extra). Nothing downstream ever reads `visualization_output["data"]` — verified by codebase-wide grep.

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization/nodes.py:369-378`
- Test: `tests/graphs/report/test_viz_optimization.py` (create)

**Step 1: Write the failing test**

```python
# tests/graphs/report/test_viz_optimization.py
"""Tests for visualization memory optimizations."""

import pytest


@pytest.mark.asyncio
async def test_response_builder_excludes_full_data():
    """visualization_output should NOT contain full results (memory optimization)."""
    from src.graphs.report_agent.subagents.visualization.nodes import response_builder_node

    state = {
        "results": [{"col": i} for i in range(100)],
        "viz_decision": {"chart_type": "bar_chart", "needs_graph": True},
        "data_profile": {"row_count": 100, "column_count": 1},
        "plotly_html_snippet": "<div>plotly</div>",
    }
    output = await response_builder_node(state)
    viz = output["visualization_output"]

    # data key should not exist — it was dead weight
    assert "data" not in viz
    # Other fields must still be present
    assert viz["needs_graph"] is True
    assert viz["chart_type"] == "bar_chart"
    assert viz["plotly_html_snippet"] == "<div>plotly</div>"
    assert "summary" in viz
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/graphs/report/test_viz_optimization.py::test_response_builder_excludes_full_data -v`
Expected: FAIL — `assert "data" not in viz` fails because `response_builder_node` currently sets `"data": results`

**Step 3: Write minimal implementation**

In `src/graphs/report_agent/subagents/visualization/nodes.py`, in `response_builder_node`, remove line 372 (`"data": results,`) from the `visualization_output` dict:

```python
# BEFORE (line 369-378):
visualization_output = {
    "needs_graph": needs_graph,
    "chart_type": chart_type,
    "data": results,                    # <-- DELETE THIS LINE
    "plotly_html_snippet": html_snippet,
    "summary": summary,
    "x_field": viz_decision.get("x_field"),
    "y_field": viz_decision.get("y_field"),
    "title": viz_decision.get("title"),
}

# AFTER:
visualization_output = {
    "needs_graph": needs_graph,
    "chart_type": chart_type,
    "plotly_html_snippet": html_snippet,
    "summary": summary,
    "x_field": viz_decision.get("x_field"),
    "y_field": viz_decision.get("y_field"),
    "title": viz_decision.get("title"),
}
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/graphs/report/test_viz_optimization.py::test_response_builder_excludes_full_data -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/graphs/report/test_viz_optimization.py src/graphs/report_agent/subagents/visualization/nodes.py
git commit -m "perf: remove duplicated results from visualization_output"
```

---

### Task 2: Cap Plotly trace count in `_execute_plotly_code`

**Context:**
LLM-generated Plotly code sometimes creates one trace per data row (e.g., 335 traces for 20 expected products). This causes:
- Slow `fig` construction and `to_html()` serialization
- Bloated HTML output (469KB instead of ~50KB)
- Large state checkpoint size

Add a post-exec guard: if `fig.data` has more than `MAX_TRACES` (50), keep only the first 50 and log a warning.

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization/nodes.py:284-308`
- Test: `tests/graphs/report/test_viz_optimization.py` (append)

**Step 1: Write the failing test**

Append to `tests/graphs/report/test_viz_optimization.py`:

```python
def test_execute_plotly_code_caps_traces():
    """_execute_plotly_code should cap traces at MAX_TRACES to prevent HTML bloat."""
    from src.graphs.report_agent.subagents.visualization.nodes import _execute_plotly_code

    # Generate code that creates 100 individual traces
    code = """
import plotly.graph_objects as go
fig = go.Figure()
for i in range(100):
    fig.add_trace(go.Bar(x=[i], y=[i], name=f"trace_{i}"))
fig.update_layout(title="Test", autosize=True)
"""
    data = [{"x": i, "y": i} for i in range(100)]
    html = _execute_plotly_code(code, data)

    # HTML should be generated but with capped traces
    assert "plotly" in html.lower() or "<div" in html
    # We can't easily check trace count in HTML, but we verify it doesn't error
    # and the HTML size is reasonable (< 200KB for capped traces)
    assert len(html) < 200_000, f"HTML too large: {len(html)} chars — traces likely not capped"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/graphs/report/test_viz_optimization.py::test_execute_plotly_code_caps_traces -v`
Expected: FAIL — 100 traces generate HTML > 200KB (uncapped)

**Step 3: Write minimal implementation**

In `src/graphs/report_agent/subagents/visualization/nodes.py`, modify `_execute_plotly_code`:

```python
MAX_TRACES = 50

def _execute_plotly_code(code: str, data: List[Dict[str, Any]]) -> str:
    """
    Plotly kodunu calistir ve HTML snippet dondur.
    go, px, pd ve data onceden inject edilmis ortamda calisir.
    """
    import plotly.graph_objects as go
    import plotly.express as px
    import pandas as pd

    exec_globals = {
        "__builtins__": __builtins__,
        "data": data,
        "go": go,
        "px": px,
        "pd": pd,
    }
    exec_locals: dict = {}

    exec(code, exec_globals, exec_locals)  # noqa: S102

    fig = exec_locals.get("fig") or exec_globals.get("fig")
    if fig is None:
        raise ValueError("Plotly kodu 'fig' degiskeni olusturmadi")

    # Guard: cap trace count to prevent HTML bloat from bad LLM code
    if hasattr(fig, "data") and len(fig.data) > MAX_TRACES:
        logger.warning(
            f"[CHART_GENERATOR] Trace count {len(fig.data)} exceeds {MAX_TRACES}, capping"
        )
        fig.data = fig.data[:MAX_TRACES]

    return fig.to_html(include_plotlyjs="cdn", full_html=False)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/graphs/report/test_viz_optimization.py::test_execute_plotly_code_caps_traces -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization/nodes.py tests/graphs/report/test_viz_optimization.py
git commit -m "perf: cap Plotly traces at 50 to prevent HTML bloat"
```

---

### Task 3: Add HTML size logging in `chart_generator_node`

**Context:**
Currently `chart_generator_node` logs `len(html_snippet)` chars but doesn't warn when HTML is unusually large. Add a warning threshold (100KB) so large HTML is visible in logs for debugging. This is a logging-only change — no behavior change.

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization/nodes.py:339-342`

**Step 1: Write the failing test**

Append to `tests/graphs/report/test_viz_optimization.py`:

```python
def test_execute_plotly_code_normal_case():
    """Normal Plotly code with few traces should work without capping."""
    from src.graphs.report_agent.subagents.visualization.nodes import _execute_plotly_code

    code = """
fig = px.bar(pd.DataFrame(data), x='category', y='value', title='Test')
fig.update_layout(autosize=True)
"""
    data = [{"category": f"cat_{i}", "value": i * 10} for i in range(20)]
    html = _execute_plotly_code(code, data)

    assert "<div" in html
    assert len(html) > 100  # Sanity check: HTML is not empty
```

**Step 2: Run test to verify it passes (this is a safety test)**

Run: `python -m pytest tests/graphs/report/test_viz_optimization.py::test_execute_plotly_code_normal_case -v`
Expected: PASS (normal code should work with or without the guard)

**Step 3: Add HTML size warning log**

In `chart_generator_node` inside `create_chart_generator_node`, after the `_execute_plotly_code` call (around line 340-341):

```python
# BEFORE:
try:
    html_snippet = _execute_plotly_code(code, results)
    logger.info(f"[CHART_GENERATOR] HTML snippet: {len(html_snippet)} chars")
    return {"plotly_html_snippet": html_snippet}

# AFTER:
try:
    html_snippet = _execute_plotly_code(code, results)
    html_size = len(html_snippet)
    if html_size > 100_000:
        logger.warning(f"[CHART_GENERATOR] Large HTML snippet: {html_size} chars (>100KB)")
    else:
        logger.info(f"[CHART_GENERATOR] HTML snippet: {html_size} chars")
    return {"plotly_html_snippet": html_snippet}
```

**Step 4: Run all tests**

Run: `python -m pytest tests/graphs/report/test_viz_optimization.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization/nodes.py tests/graphs/report/test_viz_optimization.py
git commit -m "perf: add HTML size warning for large chart outputs"
```

---

## Impact Summary

| Change | State Size Reduction | Files |
|--------|---------------------|-------|
| Remove `"data": results` | ~300KB per checkpoint (1482 rows) | `visualization/nodes.py` |
| Cap traces at 50 | HTML from ~469KB to ~50KB | `visualization/nodes.py` |
| HTML size logging | Debugging aid, no size change | `visualization/nodes.py` |
| **Total** | **~720KB less per checkpoint** | **1 source file, 1 test file** |
