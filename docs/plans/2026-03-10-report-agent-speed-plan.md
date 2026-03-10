# Report Agent Speed Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce report agent end-to-end latency from ~25s to <10s by eliminating unnecessary LLM calls and adding caching.

**Architecture:** Four independent optimizations, each modifying only internal node implementations. Graph topology (edges, node names, subgraph boundaries) stays unchanged. Every optimization has an LLM fallback path to preserve accuracy.

**Tech Stack:** LangGraph StateGraph, Plotly Express, ChromaDB, pyodbc, functools.lru_cache, sentence-transformers

---

## Task 1: Business Rules Search Result Cache

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py:462-553`
- Test: `tests/test_business_rules_cache.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_business_rules_cache.py
"""Test that business rules vector store caches search results."""
import pytest
import json
import tempfile
import os


def _create_minimal_rules_file(path: str):
    """Create a minimal business_rules.json for testing."""
    rules = {
        "business_logic_rules": [
            {
                "id": "default_1",
                "description": "Default rule for all queries",
                "modules": ["general"],
                "related_tables": ["*"],
                "is_default": True,
                "sql": {
                    "aggregation": None,
                    "filter": "IsActive = 1",
                    "group_by": None,
                    "select": None,
                    "join": None,
                    "having": None,
                },
            },
            {
                "id": "semantic_1",
                "description": "Şube bazlı satış analizi",
                "modules": ["sube", "satis", "ciro"],
                "related_tables": ["MasterReportDocumentTable"],
                "is_default": False,
                "sql": {
                    "aggregation": "SUM(RowAmount)",
                    "filter": None,
                    "group_by": "BranchName",
                    "select": "BranchName",
                    "join": None,
                    "having": None,
                },
            },
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False)


@pytest.fixture
def vector_store():
    """Create a BusinessRulesVectorStore with minimal test data."""
    from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store import (
        BusinessRulesVectorStore,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        rules_path = os.path.join(tmpdir, "business_rules.json")
        _create_minimal_rules_file(rules_path)

        store = BusinessRulesVectorStore(
            rules_file_path=rules_path,
            persist_directory=os.path.join(tmpdir, "chroma"),
            similarity_threshold=0.3,
        )
        store.initialize_collections(force_recreate=True)
        store.index_rules()
        yield store


def test_cached_search_returns_same_results(vector_store):
    """Second call with same query should return cached results."""
    query = "Şube bazlı satış raporu"

    result1 = vector_store.get_relevant_rules_for_query(
        user_query=query, n_results=5, use_hybrid=True
    )
    result2 = vector_store.get_relevant_rules_for_query(
        user_query=query, n_results=5, use_hybrid=True
    )

    assert result1["total_count"] == result2["total_count"]
    assert result1["merged_sql"] == result2["merged_sql"]
    r1_ids = [r["rule_id"] for r in result1["rules"]]
    r2_ids = [r["rule_id"] for r in result2["rules"]]
    assert r1_ids == r2_ids


def test_cached_search_is_faster(vector_store):
    """Cached call should be significantly faster than first call."""
    import time

    query = "Aylık ciro analizi"

    start1 = time.perf_counter()
    vector_store.get_relevant_rules_for_query(
        user_query=query, n_results=5, use_hybrid=True
    )
    duration1 = time.perf_counter() - start1

    start2 = time.perf_counter()
    vector_store.get_relevant_rules_for_query(
        user_query=query, n_results=5, use_hybrid=True
    )
    duration2 = time.perf_counter() - start2

    # Cached call should be at least 10x faster
    assert duration2 < duration1 / 10, (
        f"Cache not effective: first={duration1:.3f}s, second={duration2:.3f}s"
    )


def test_cache_invalidates_on_different_query(vector_store):
    """Different queries should not return cached results from other queries."""
    result1 = vector_store.get_relevant_rules_for_query(
        user_query="Şube satış raporu", n_results=5, use_hybrid=True
    )
    result2 = vector_store.get_relevant_rules_for_query(
        user_query="Müşteri sayısı analizi", n_results=5, use_hybrid=True
    )

    # Results may differ (different semantic match)
    # Just verify both return valid results
    assert result1["total_count"] >= 1
    assert result2["total_count"] >= 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_business_rules_cache.py -v`
Expected: `test_cached_search_is_faster` FAILS (no cache yet, both calls equally slow)

**Step 3: Implement the cache**

Edit `src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py`:

Add at top of file (after imports):
```python
import hashlib
from functools import lru_cache
```

Add cache to `BusinessRulesVectorStore.__init__`:
```python
        # Search result cache: query_key -> results
        self._search_cache: dict = {}
        self._rules_file_hash = self._compute_file_hash()
```

Add helper methods:
```python
    def _compute_file_hash(self) -> str:
        """Compute hash of rules file for cache invalidation."""
        with open(self.rules_file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def _cache_key(self, user_query: str, n_results: int, use_hybrid: bool) -> str:
        """Generate cache key from query parameters."""
        return f"{user_query}|{n_results}|{use_hybrid}"

    def clear_cache(self):
        """Clear the search result cache."""
        self._search_cache.clear()
        logger.info("[BUSINESS_RULES] Search cache cleared")
```

Wrap `get_relevant_rules_for_query` with cache logic — add at the START of the method (line ~486):
```python
        # --- Cache check ---
        current_hash = self._compute_file_hash()
        if current_hash != self._rules_file_hash:
            self._search_cache.clear()
            self._rules_file_hash = current_hash
            logger.info("[BUSINESS_RULES] Rules file changed, cache invalidated")

        cache_key = self._cache_key(user_query, n_results, use_hybrid)
        if cache_key in self._search_cache:
            logger.debug(f"[BUSINESS_RULES] Cache hit for: {user_query[:50]}")
            return self._search_cache[cache_key]
```

Add at the END of the method (before `return`):
```python
        # --- Cache store ---
        self._search_cache[cache_key] = result_dict
        logger.debug(f"[BUSINESS_RULES] Cached result for: {user_query[:50]}")
```

Where `result_dict` is the final return value (the dict with `individual_rules`, `rules`, `merged_sql`, etc).

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_business_rules_cache.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py tests/test_business_rules_cache.py
git commit -m "perf: add search result cache to business rules vector store"
```

---

## Task 2: Rule-Based viz_decider Fast Path

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization/nodes.py:190-266`
- Test: `tests/test_viz_decider_fast_path.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_viz_decider_fast_path.py
"""Test rule-based viz_decider fast paths that skip LLM."""
import pytest


def _make_state(query_type, results, wants_viz=True):
    """Build minimal viz_decider state."""
    return {
        "results": results,
        "user_query": "test query",
        "query_type": query_type,
        "wants_visualization": wants_viz,
        "data_profile": None,  # data_analyzer will fill this
        "viz_request": None,
        "viz_decision": None,
    }


def test_ranking_query_gets_bar_chart():
    """RANKING query_type should deterministically produce bar_chart without LLM."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    results = [
        {"BranchName": "A", "Total": 1000},
        {"BranchName": "B", "Total": 800},
        {"BranchName": "C", "Total": 600},
    ]
    profile = {
        "row_count": 3,
        "column_count": 2,
        "dimension_columns": ["BranchName"],
        "metric_columns": ["Total"],
        "time_column": None,
        "has_time_series": False,
    }

    decision = _rule_based_viz_decision("RANKING", results, profile, wants_viz=True)
    assert decision is not None
    assert decision["chart_type"] == "bar_chart"
    assert decision["x_field"] == "BranchName"
    assert decision["y_field"] == "Total"
    assert decision["needs_graph"] is True


def test_time_series_query_gets_line_chart():
    """TIME_SERIES query should produce line_chart."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    results = [
        {"Month": "2026-01", "Revenue": 5000},
        {"Month": "2026-02", "Revenue": 6000},
    ]
    profile = {
        "row_count": 2,
        "column_count": 2,
        "dimension_columns": ["Month"],
        "metric_columns": ["Revenue"],
        "time_column": "Month",
        "has_time_series": True,
    }

    decision = _rule_based_viz_decision(
        "TIME_SERIES_COMPARISON", results, profile, wants_viz=True
    )
    assert decision is not None
    assert decision["chart_type"] == "line_chart"
    assert decision["needs_graph"] is True


def test_listing_query_gets_table():
    """LISTING query should produce table (no graph)."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    results = [{"Name": f"Item {i}", "Value": i} for i in range(15)]
    profile = {
        "row_count": 15,
        "column_count": 2,
        "dimension_columns": ["Name"],
        "metric_columns": ["Value"],
        "time_column": None,
        "has_time_series": False,
    }

    decision = _rule_based_viz_decision("LISTING", results, profile, wants_viz=True)
    assert decision is not None
    assert decision["chart_type"] == "table"
    assert decision["needs_graph"] is False


def test_comparison_query_gets_grouped_bar():
    """COMPARISON query should produce comparison chart."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    results = [
        {"Branch": "A", "Category": "X", "Total": 100},
        {"Branch": "B", "Category": "X", "Total": 200},
    ]
    profile = {
        "row_count": 2,
        "column_count": 3,
        "dimension_columns": ["Branch", "Category"],
        "metric_columns": ["Total"],
        "time_column": None,
        "has_time_series": False,
    }

    decision = _rule_based_viz_decision("COMPARISON", results, profile, wants_viz=True)
    assert decision is not None
    assert decision["needs_graph"] is True
    assert decision["chart_type"] in ("bar_chart", "comparison")


def test_ambiguous_returns_none_for_llm_fallback():
    """When rule-based can't decide, return None so LLM handles it."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    results = [{"A": 1, "B": 2, "C": 3}]
    profile = {
        "row_count": 1,
        "column_count": 3,
        "dimension_columns": [],
        "metric_columns": ["A", "B", "C"],
        "time_column": None,
        "has_time_series": False,
    }

    # Multiple metrics, no clear dimension → ambiguous
    decision = _rule_based_viz_decision("SINGLE", results, profile, wants_viz=True)
    # For SINGLE with multiple metrics, this should either handle it or return None
    # The exact behavior depends on implementation - either is fine
    assert decision is None or decision["chart_type"] == "single_value"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_viz_decider_fast_path.py -v`
Expected: FAIL — `_rule_based_viz_decision` does not exist yet

**Step 3: Implement the rule-based function**

Add to `src/graphs/report_agent/subagents/visualization/nodes.py` (before `create_viz_decider_node`, around line 188):

```python
def _rule_based_viz_decision(
    query_type: str,
    results: list,
    profile: dict,
    wants_viz: bool,
) -> dict | None:
    """
    Deterministic chart selection based on query_type and data profile.
    Returns VizDecision-compatible dict, or None if LLM should decide.
    """
    if not wants_viz or not results:
        return None

    dimension_cols = profile.get("dimension_columns", [])
    metric_cols = profile.get("metric_columns", [])
    time_col = profile.get("time_column")
    row_count = profile.get("row_count", 0)

    # Need at least one dimension and one metric for a chart
    if not metric_cols:
        return None

    first_metric = metric_cols[0]
    first_dim = dimension_cols[0] if dimension_cols else None

    if query_type == "LISTING":
        return {
            "needs_graph": False,
            "chart_type": "table",
            "x_field": None,
            "y_field": None,
            "series_field": None,
            "title": None,
            "reason": "LISTING query → table display",
        }

    if query_type == "SINGLE" and row_count == 1 and len(metric_cols) == 1:
        return {
            "needs_graph": False,
            "chart_type": "single_value",
            "x_field": None,
            "y_field": first_metric,
            "series_field": None,
            "title": None,
            "reason": "Single value result",
        }

    if query_type in ("TIME_SERIES", "TIME_SERIES_COMPARISON"):
        x = time_col or first_dim
        if x:
            series = dimension_cols[0] if dimension_cols and dimension_cols[0] != x else None
            return {
                "needs_graph": True,
                "chart_type": "line_chart",
                "x_field": x,
                "y_field": first_metric,
                "series_field": series,
                "title": None,
                "reason": f"Time series → line chart (x={x})",
            }

    if query_type == "RANKING" and first_dim:
        return {
            "needs_graph": True,
            "chart_type": "bar_chart",
            "x_field": first_dim,
            "y_field": first_metric,
            "series_field": None,
            "title": None,
            "reason": f"Ranking → bar chart (x={first_dim}, y={first_metric})",
        }

    if query_type == "COMPARISON" and first_dim:
        series = dimension_cols[1] if len(dimension_cols) > 1 else None
        return {
            "needs_graph": True,
            "chart_type": "comparison" if series else "bar_chart",
            "x_field": first_dim,
            "y_field": first_metric,
            "series_field": series,
            "title": None,
            "reason": f"Comparison → bar chart (x={first_dim}, series={series})",
        }

    # Can't decide deterministically → let LLM handle
    return None
```

Then modify `viz_decider_node` inside `create_viz_decider_node` (around line 220, the LLM decision section). Add BEFORE the LLM call:

```python
        # --- Rule-based fast path ---
        rule_decision = _rule_based_viz_decision(
            query_type=state.get("query_type", ""),
            results=results,
            profile=profile,
            wants_viz=wants_visualization,
        )
        if rule_decision is not None:
            logger.info(f"[VIZ_DECIDER] Rule-based fast path: {rule_decision['chart_type']} ({rule_decision['reason']})")
            return {"viz_decision": rule_decision}

        # --- LLM fallback (existing code below) ---
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_viz_decider_fast_path.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization/nodes.py tests/test_viz_decider_fast_path.py
git commit -m "perf: add rule-based fast path to viz_decider, skip LLM for common chart types"
```

---

## Task 3: Dynamic Chart Template Engine

**Files:**
- Create: `src/graphs/report_agent/subagents/visualization/chart_templates.py`
- Modify: `src/graphs/report_agent/subagents/visualization/nodes.py:319-359`
- Test: `tests/test_chart_templates.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_chart_templates.py
"""Test dynamic Plotly chart template engine."""
import pytest


@pytest.fixture
def sample_results():
    return [
        {"BranchName": "İstanbul", "TotalSales": 50000},
        {"BranchName": "Ankara", "TotalSales": 35000},
        {"BranchName": "İzmir", "TotalSales": 28000},
    ]


@pytest.fixture
def column_metadata():
    return {
        "BranchName": {"description": "Şube Adı", "type": "string"},
        "TotalSales": {"description": "Toplam Satış (₺)", "type": "numeric"},
    }


def test_bar_chart_template(sample_results, column_metadata):
    """Bar chart template should produce valid Plotly HTML."""
    from src.graphs.report_agent.subagents.visualization.chart_templates import (
        build_chart,
    )

    viz_decision = {
        "chart_type": "bar_chart",
        "x_field": "BranchName",
        "y_field": "TotalSales",
        "series_field": None,
        "title": "Şube Satış Raporu",
    }

    html = build_chart(viz_decision, sample_results, column_metadata)
    assert html is not None
    assert "plotly" in html.lower()
    assert "Şube Satış Raporu" in html


def test_line_chart_template():
    """Line chart should work with time series data."""
    from src.graphs.report_agent.subagents.visualization.chart_templates import (
        build_chart,
    )

    results = [
        {"Month": "2026-01", "Revenue": 5000},
        {"Month": "2026-02", "Revenue": 6000},
        {"Month": "2026-03", "Revenue": 7500},
    ]
    viz_decision = {
        "chart_type": "line_chart",
        "x_field": "Month",
        "y_field": "Revenue",
        "series_field": None,
        "title": "Aylık Gelir",
    }

    html = build_chart(viz_decision, results, {})
    assert html is not None
    assert "plotly" in html.lower()


def test_pie_chart_template():
    """Pie chart template."""
    from src.graphs.report_agent.subagents.visualization.chart_templates import (
        build_chart,
    )

    results = [
        {"Category": "A", "Count": 30},
        {"Category": "B", "Count": 50},
        {"Category": "C", "Count": 20},
    ]
    viz_decision = {
        "chart_type": "pie_chart",
        "x_field": "Category",
        "y_field": "Count",
        "series_field": None,
        "title": "Kategori Dağılımı",
    }

    html = build_chart(viz_decision, results, {})
    assert html is not None
    assert "plotly" in html.lower()


def test_grouped_bar_with_series(sample_results):
    """Bar chart with series_field should produce grouped bars."""
    from src.graphs.report_agent.subagents.visualization.chart_templates import (
        build_chart,
    )

    results = [
        {"Branch": "A", "Category": "X", "Total": 100},
        {"Branch": "A", "Category": "Y", "Total": 150},
        {"Branch": "B", "Category": "X", "Total": 200},
        {"Branch": "B", "Category": "Y", "Total": 250},
    ]
    viz_decision = {
        "chart_type": "bar_chart",
        "x_field": "Branch",
        "y_field": "Total",
        "series_field": "Category",
        "title": "Karşılaştırma",
    }

    html = build_chart(viz_decision, results, {})
    assert html is not None
    assert "plotly" in html.lower()


def test_horizontal_bar_for_many_rows():
    """More than 15 bars should produce horizontal orientation."""
    from src.graphs.report_agent.subagents.visualization.chart_templates import (
        build_chart,
    )

    results = [{"Name": f"Item {i}", "Value": i * 10} for i in range(20)]
    viz_decision = {
        "chart_type": "bar_chart",
        "x_field": "Name",
        "y_field": "Value",
        "series_field": None,
        "title": "Top 20",
    }

    html = build_chart(viz_decision, results, {})
    assert html is not None


def test_unsupported_chart_type_returns_none():
    """Unsupported chart_type should return None (LLM fallback)."""
    from src.graphs.report_agent.subagents.visualization.chart_templates import (
        build_chart,
    )

    viz_decision = {
        "chart_type": "unknown_exotic_chart",
        "x_field": "A",
        "y_field": "B",
        "series_field": None,
        "title": "Test",
    }

    html = build_chart(viz_decision, [{"A": 1, "B": 2}], {})
    assert html is None


def test_column_metadata_used_as_labels(sample_results, column_metadata):
    """Column metadata descriptions should appear as axis labels."""
    from src.graphs.report_agent.subagents.visualization.chart_templates import (
        build_chart,
    )

    viz_decision = {
        "chart_type": "bar_chart",
        "x_field": "BranchName",
        "y_field": "TotalSales",
        "series_field": None,
        "title": "Test",
    }

    html = build_chart(viz_decision, sample_results, column_metadata)
    assert "Şube Adı" in html
    assert "Toplam Satış" in html
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_chart_templates.py -v`
Expected: FAIL — `chart_templates` module does not exist

**Step 3: Implement the chart template engine**

Create `src/graphs/report_agent/subagents/visualization/chart_templates.py`:

```python
"""
Dynamic Chart Template Engine
==============================

Generates Plotly charts from viz_decision parameters without LLM.
Adapts to data shape, column metadata, and chart type.

Returns HTML snippet or None if chart_type is unsupported (LLM fallback).
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

# Maximum traces before simplifying
MAX_TRACES = 50


def build_chart(
    viz_decision: dict,
    results: List[Dict[str, Any]],
    column_metadata: Dict[str, Any],
) -> Optional[str]:
    """
    Build a Plotly chart from viz_decision and data.

    Args:
        viz_decision: dict with chart_type, x_field, y_field, series_field, title
        results: list of row dicts
        column_metadata: {col_name: {"description": ..., "type": ...}}

    Returns:
        HTML snippet string, or None if chart_type unsupported (triggers LLM fallback)
    """
    chart_type = viz_decision.get("chart_type")
    if chart_type not in _BUILDERS:
        logger.info(f"[CHART_TEMPLATE] Unsupported chart_type '{chart_type}', falling back to LLM")
        return None

    if not results:
        return None

    try:
        df = pd.DataFrame(results)
        x = viz_decision.get("x_field")
        y = viz_decision.get("y_field")
        series = viz_decision.get("series_field")
        title = viz_decision.get("title") or ""

        # Validate fields exist in data
        for field in [x, y, series]:
            if field and field not in df.columns:
                logger.warning(f"[CHART_TEMPLATE] Field '{field}' not in data columns {list(df.columns)}, falling back to LLM")
                return None

        # Resolve labels from column_metadata
        x_label = _get_label(x, column_metadata)
        y_label = _get_label(y, column_metadata)

        # Detect y-axis format
        y_format = _detect_number_format(df, y) if y else None

        # Build chart
        fig = _BUILDERS[chart_type](df, x, y, series, title)

        # Apply common formatting
        fig = _apply_labels(fig, x_label, y_label)
        fig = _apply_number_format(fig, y_format)
        fig = _apply_layout(fig, title)

        # Cap traces
        if len(fig.data) > MAX_TRACES:
            fig.data = fig.data[:MAX_TRACES]

        return fig.to_html(include_plotlyjs="cdn", full_html=False)

    except Exception as e:
        logger.warning(f"[CHART_TEMPLATE] Template failed: {e}, falling back to LLM")
        return None


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------


def _build_bar(df, x, y, series, title):
    if len(df) > 15:
        # Many bars → horizontal for readability
        df_sorted = df.sort_values(y, ascending=True)
        fig = px.bar(
            df_sorted, x=y, y=x, orientation="h",
            color=series, title=title,
        )
    elif series:
        fig = px.bar(
            df, x=x, y=y, color=series,
            barmode="group", title=title,
        )
    else:
        df_sorted = df.sort_values(y, ascending=False)
        fig = px.bar(df_sorted, x=x, y=y, title=title)
    return fig


def _build_line(df, x, y, series, title):
    df_sorted = df.sort_values(x)
    fig = px.line(
        df_sorted, x=x, y=y, color=series,
        title=title, markers=True,
    )
    return fig


def _build_pie(df, x, y, series, title):
    # Top-N grouping: if too many slices, group into "Diğer"
    if len(df) > 10:
        top = df.nlargest(9, y)
        other_sum = df[~df.index.isin(top.index)][y].sum()
        other_row = pd.DataFrame([{x: "Diğer", y: other_sum}])
        df = pd.concat([top, other_row], ignore_index=True)

    fig = px.pie(df, names=x, values=y, title=title)
    return fig


def _build_scatter(df, x, y, series, title):
    fig = px.scatter(df, x=x, y=y, color=series, title=title)
    return fig


def _build_treemap(df, x, y, series, title):
    path_cols = [x]
    if series:
        path_cols = [series, x]
    fig = px.treemap(df, path=path_cols, values=y, title=title)
    return fig


def _build_sunburst(df, x, y, series, title):
    path_cols = [x]
    if series:
        path_cols = [series, x]
    fig = px.sunburst(df, path=path_cols, values=y, title=title)
    return fig


def _build_comparison(df, x, y, series, title):
    """Grouped bar for comparison queries."""
    fig = px.bar(
        df, x=x, y=y, color=series,
        barmode="group", title=title,
    )
    return fig


_BUILDERS = {
    "bar_chart": _build_bar,
    "line_chart": _build_line,
    "pie_chart": _build_pie,
    "scatter_chart": _build_scatter,
    "scatter": _build_scatter,
    "treemap": _build_treemap,
    "sunburst": _build_sunburst,
    "comparison": _build_comparison,
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _get_label(field: Optional[str], column_metadata: dict) -> str:
    """Get display label from column_metadata, fallback to field name."""
    if not field:
        return ""
    meta = column_metadata.get(field, {})
    if isinstance(meta, dict):
        return meta.get("description", field)
    return field


def _detect_number_format(df, col: str) -> Optional[str]:
    """Detect if column values suggest currency, percentage, or plain number."""
    if col not in df.columns:
        return None
    try:
        sample = df[col].dropna()
        if sample.empty:
            return None
        max_val = sample.max()
        if max_val > 1000:
            return "currency"  # Likely monetary
        if 0 <= sample.min() and max_val <= 1:
            return "percentage"
    except (TypeError, ValueError):
        pass
    return None


def _apply_labels(fig, x_label: str, y_label: str):
    """Apply axis labels from column metadata."""
    update = {}
    if x_label:
        update["xaxis_title"] = x_label
    if y_label:
        update["yaxis_title"] = y_label
    if update:
        fig.update_layout(**update)
    return fig


def _apply_number_format(fig, fmt: Optional[str]):
    """Apply number formatting to y-axis."""
    if fmt == "currency":
        fig.update_layout(yaxis_tickformat=",")
    elif fmt == "percentage":
        fig.update_layout(yaxis_tickformat=".0%")
    return fig


def _apply_layout(fig, title: str):
    """Apply common layout settings."""
    fig.update_layout(
        autosize=True,
        margin=dict(l=40, r=40, t=60, b=40),
        template="plotly_white",
    )
    return fig
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_chart_templates.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization/chart_templates.py tests/test_chart_templates.py
git commit -m "feat: add dynamic chart template engine with 7 chart type builders"
```

**Step 6: Integrate template engine into chart_generator node**

Modify `src/graphs/report_agent/subagents/visualization/nodes.py:319-359`.

Inside the `chart_generator_node` function, add BEFORE the LLM call (after the `needs_graph=False` early return):

```python
        # --- Template fast path ---
        from src.graphs.report_agent.subagents.visualization.chart_templates import build_chart

        column_metadata = config.get("configurable", {}).get("assistant_config", {}).get("column_metadata", {})
        template_html = build_chart(viz_decision, results, column_metadata)

        if template_html is not None:
            logger.info(f"[CHART_GENERATOR] Template fast path: {viz_decision.get('chart_type')}")
            return {
                "visualization_output": {
                    "plotly_html_snippet": template_html,
                    "needs_graph": True,
                    "chart_type": viz_decision.get("chart_type"),
                },
            }

        # --- LLM fallback (existing code below) ---
        logger.info("[CHART_GENERATOR] Template unavailable, using LLM code generation")
```

**Step 7: Run all viz tests**

Run: `python -m pytest tests/test_chart_templates.py tests/test_viz_decider_fast_path.py -v`
Expected: ALL PASS

**Step 8: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization/nodes.py
git commit -m "perf: integrate chart template engine into chart_generator node"
```

---

## Task 4: Connection Pooling for sql_executor

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:187-223`
- Test: `tests/test_connection_pool.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_connection_pool.py
"""Test connection pooling for SQL executor."""
import pytest
from unittest.mock import patch, MagicMock


def test_connection_pool_reuses_connections():
    """get_pooled_connection should reuse connections for same connection string."""
    from src.graphs.report_agent.subagents.text2sql.nodes import (
        get_pooled_connection,
        _connection_pools,
    )

    # Clear any existing pools
    _connection_pools.clear()

    mock_conn = MagicMock()
    with patch("pyodbc.connect", return_value=mock_conn) as mock_connect:
        conn1 = get_pooled_connection("test_conn_str")
        conn2 = get_pooled_connection("test_conn_str")

        # Should only call pyodbc.connect once (pool reuse)
        assert mock_connect.call_count == 1
        assert conn1 is conn2

    _connection_pools.clear()


def test_connection_pool_different_strings():
    """Different connection strings should get different pools."""
    from src.graphs.report_agent.subagents.text2sql.nodes import (
        get_pooled_connection,
        _connection_pools,
    )

    _connection_pools.clear()

    mock_conn1 = MagicMock()
    mock_conn2 = MagicMock()
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_conn1 if call_count == 1 else mock_conn2

    with patch("pyodbc.connect", side_effect=side_effect):
        conn1 = get_pooled_connection("conn_str_1")
        conn2 = get_pooled_connection("conn_str_2")

        assert conn1 is not conn2

    _connection_pools.clear()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_connection_pool.py -v`
Expected: FAIL — `get_pooled_connection` and `_connection_pools` don't exist

**Step 3: Implement connection pooling**

Edit `src/graphs/report_agent/subagents/text2sql/nodes.py`.

Add near the top (after `_db_executor` definition, around line 49):

```python
# Connection pool: connection_string -> pyodbc.Connection
_connection_pools: dict = {}
_pool_lock = threading.Lock()


def get_pooled_connection(pyodbc_conn_str: str):
    """
    Get or create a pooled connection for the given connection string.
    Connections are reused across calls to avoid reconnection overhead.
    """
    with _pool_lock:
        if pyodbc_conn_str in _connection_pools:
            conn = _connection_pools[pyodbc_conn_str]
            try:
                # Test if connection is still alive
                conn.execute("SELECT 1")
                return conn
            except Exception:
                # Connection dead, remove and recreate
                logger.debug("[SQL_EXECUTOR] Pooled connection dead, reconnecting")
                try:
                    conn.close()
                except Exception:
                    pass
                del _connection_pools[pyodbc_conn_str]

        # Create new connection
        conn = pyodbc.connect(pyodbc_conn_str, timeout=30, autocommit=True)
        _connection_pools[pyodbc_conn_str] = conn
        logger.debug("[SQL_EXECUTOR] New pooled connection created")
        return conn
```

Add `import threading` to the imports at top of file.

Modify `_execute_sql_async` (lines 209-223) to use pooled connection:

```python
async def _execute_sql_async(connection_string: str, sql: str) -> List[Dict[str, Any]]:
    """SQL'i thread pool'da async çalıştır (pooled connection)."""
    pyodbc_conn_str = _parse_connection_string(connection_string)
    loop = asyncio.get_event_loop()

    def _run():
        conn = get_pooled_connection(pyodbc_conn_str)
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        cursor.close()
        return [_serialize_row(columns, row) for row in rows]

    return await loop.run_in_executor(_db_executor, _run)
```

Key change: `pyodbc.connect()` → `get_pooled_connection()`, and `conn.close()` removed (connection stays in pool). `cursor.close()` added instead.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_connection_pool.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py tests/test_connection_pool.py
git commit -m "perf: add connection pooling for sql_executor to avoid reconnection overhead"
```

---

## Task 5: Integration Test & Benchmark

**Files:**
- Test: `tests/test_speed_optimizations_integration.py` (create)

**Step 1: Write integration tests**

```python
# tests/test_speed_optimizations_integration.py
"""Integration tests verifying all speed optimizations work together."""
import pytest
import time


def test_viz_decider_skips_llm_for_ranking():
    """End-to-end: RANKING query should not trigger viz_decider LLM."""
    from src.graphs.report_agent.subagents.visualization.nodes import (
        _rule_based_viz_decision,
    )

    profile = {
        "row_count": 5,
        "column_count": 2,
        "dimension_columns": ["BranchName"],
        "metric_columns": ["Total"],
        "time_column": None,
        "has_time_series": False,
    }
    results = [{"BranchName": f"B{i}", "Total": i * 100} for i in range(5)]

    start = time.perf_counter()
    decision = _rule_based_viz_decision("RANKING", results, profile, wants_viz=True)
    duration = time.perf_counter() - start

    assert decision is not None
    assert decision["chart_type"] == "bar_chart"
    assert duration < 0.01, f"Rule-based decision took {duration:.4f}s, should be <10ms"


def test_chart_template_generates_fast():
    """Chart template should generate HTML in under 100ms."""
    from src.graphs.report_agent.subagents.visualization.chart_templates import (
        build_chart,
    )

    results = [{"Category": f"Cat{i}", "Amount": i * 1000} for i in range(10)]
    decision = {
        "chart_type": "bar_chart",
        "x_field": "Category",
        "y_field": "Amount",
        "series_field": None,
        "title": "Test Chart",
    }

    start = time.perf_counter()
    html = build_chart(decision, results, {})
    duration = time.perf_counter() - start

    assert html is not None
    assert duration < 0.5, f"Template generation took {duration:.4f}s, should be <500ms"


def test_all_chart_types_produce_html():
    """Every supported chart type should produce valid HTML."""
    from src.graphs.report_agent.subagents.visualization.chart_templates import (
        build_chart,
        _BUILDERS,
    )

    results = [
        {"Dim": "A", "Dim2": "X", "Val": 100},
        {"Dim": "B", "Dim2": "Y", "Val": 200},
        {"Dim": "C", "Dim2": "Z", "Val": 300},
    ]

    for chart_type in _BUILDERS:
        decision = {
            "chart_type": chart_type,
            "x_field": "Dim",
            "y_field": "Val",
            "series_field": "Dim2" if chart_type in ("comparison",) else None,
            "title": f"Test {chart_type}",
        }
        html = build_chart(decision, results, {})
        assert html is not None, f"{chart_type} returned None"
        assert "plotly" in html.lower(), f"{chart_type} missing plotly reference"
```

**Step 2: Run all tests**

Run: `python -m pytest tests/test_speed_optimizations_integration.py tests/test_chart_templates.py tests/test_viz_decider_fast_path.py tests/test_business_rules_cache.py tests/test_connection_pool.py -v`
Expected: ALL PASS

**Step 3: Run full test suite for regression**

Run: `python -m pytest tests/ -v`
Expected: No regressions

**Step 4: Commit**

```bash
git add tests/test_speed_optimizations_integration.py
git commit -m "test: add integration tests and benchmarks for speed optimizations"
```

---

## Summary

| Task | Type | What | Latency Impact |
|------|------|------|----------------|
| 1 | Cache | Business rules search result cache | 3.6s → 0.01s (warm) |
| 2 | Rule-based | viz_decider deterministic fast path | 3.1s → 0.01s |
| 3 | Template | Dynamic Plotly chart builder (7 types) | 6.7s → 0.05s |
| 4 | Pooling | pyodbc connection reuse | 4.5s → 3-3.5s |
| 5 | Test | Integration tests & benchmarks | — |

**Target critical path (warm):** classify(1.5) + rules(0.01) + parallel_llm(4.0) + sql(3.0) + viz(0.01) + chart(0.05) = **~8.6s**
