# Chart Title Generation & Thinking-Step Transparency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synthesize descriptive chart titles when none is set, and surface a step-by-step "thinking trace" panel to users explaining how each report was built.

**Architecture:** Title synthesis added to `spec_validator_node` (pure Python, no LLM). Transparency module (`transparency.py`) builds a structured step list from existing state fields (`auto_rules`, `active_sql`, `visualization_output`, etc.) and is wired into `create_build_response_node` via `additional_kwargs["transparency"]`.

**Tech Stack:** Python 3.11, LangGraph, `re` (stdlib only — no new dependencies)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/graphs/report_agent/transparency.py` | Step builders + `build_transparency_payload()` |
| Create | `tests/graphs/report/test_transparency.py` | Unit tests for transparency module |
| Modify | `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Add `_synthesize_title` + call in `spec_validator_node` |
| Modify | `src/graphs/report_agent/nodes.py` | Import transparency, pass `column_metadata` to factory, add `"transparency"` key to `additional_kwargs` |
| Modify | `src/graphs/report_agent/graph.py` | Pass `column_metadata` to `create_build_response_node` |

---

## Task 1: Chart Title Synthesis in spec_validator_node

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py`
- Test: `tests/graphs/report/test_transparency.py` (new file, start here)

- [ ] **Step 1: Write failing tests for `_synthesize_title`**

Create `tests/graphs/report/test_transparency.py`:

```python
"""Unit tests for transparency module and title synthesis."""
import pytest


# ---------------------------------------------------------------------------
# _synthesize_title (from viz nodes)
# ---------------------------------------------------------------------------

def test_synthesize_title_x_and_y_with_metadata():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _synthesize_title
    meta = {"BranchName": "Şube", "RowAmount": "Satış Tutarı"}
    spec = {"x_field": "BranchName", "y_field": "RowAmount"}
    assert _synthesize_title("", spec, meta) == "Şube Bazında Satış Tutarı"


def test_synthesize_title_x_only():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _synthesize_title
    meta = {"CategoryName": "Kategori"}
    spec = {"x_field": "CategoryName", "y_field": None}
    assert _synthesize_title("", spec, meta) == "Kategori Analizi"


def test_synthesize_title_no_fields_uses_query():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _synthesize_title
    spec = {"x_field": None, "y_field": None}
    assert _synthesize_title("En çok satan ürünler", spec, {}) == "En çok satan ürünler"


def test_synthesize_title_long_query_truncated():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _synthesize_title
    spec = {}
    long_query = "a" * 100
    result = _synthesize_title(long_query, spec, {})
    assert len(result) <= 60


def test_synthesize_title_no_fields_no_query_returns_rapor():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _synthesize_title
    assert _synthesize_title("", {}, {}) == "Rapor"


def test_synthesize_title_dict_metadata_uses_description():
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _synthesize_title
    meta = {"BranchName": {"description": "Şube Adı", "type": "string"}}
    spec = {"x_field": "BranchName", "y_field": None}
    assert _synthesize_title("", spec, meta) == "Şube Adı Analizi"
```

- [ ] **Step 2: Run tests — verify they fail**

```
pytest tests/graphs/report/test_transparency.py::test_synthesize_title_x_and_y_with_metadata -v
```
Expected: `ImportError` — `_synthesize_title` does not exist yet.

- [ ] **Step 3: Add `_synthesize_title` to `visualization_v2/nodes.py`**

Add after the existing `_build_column_info` function (around line 290), before `create_viz_decider_node`:

```python
def _synthesize_title(user_query: str, spec: dict, column_metadata: dict) -> str:
    def _lbl(field):
        if not field:
            return ""
        meta = column_metadata.get(field, "")
        if isinstance(meta, dict):
            return meta.get("description", field)
        return meta if isinstance(meta, str) and meta else field

    x_label = _lbl(spec.get("x_field"))
    y_label = _lbl(spec.get("y_field"))
    if x_label and y_label:
        return f"{x_label} Bazında {y_label}"
    if x_label:
        return f"{x_label} Analizi"
    return (user_query or "Rapor")[:60].rstrip()
```

- [ ] **Step 4: Update `spec_validator_node` to call `_synthesize_title`**

In `spec_validator_node` (around line 401), replace the current return:

```python
# BEFORE (last 4 lines of spec_validator_node):
    validated = validate_spec(viz_decision, results, profile)
    logger.info(
        f"[V2:VALIDATOR] {validated.get('chart_type')}, "
        f"x={validated.get('x_field')}, y={validated.get('y_field')}"
    )
    return {"viz_decision": validated}
```

```python
# AFTER:
    validated = validate_spec(viz_decision, results, profile)

    if not validated.get("title"):
        column_metadata = _get_configurable(config, "column_metadata", {})
        if isinstance(column_metadata, str):
            try:
                column_metadata = json.loads(column_metadata)
            except (json.JSONDecodeError, TypeError):
                column_metadata = {}
        user_query = state.get("user_query", "")
        validated = {**validated, "title": _synthesize_title(user_query, validated, column_metadata)}

    logger.info(
        f"[V2:VALIDATOR] {validated.get('chart_type')}, "
        f"x={validated.get('x_field')}, y={validated.get('y_field')}, "
        f"title={validated.get('title', '')[:40]}"
    )
    return {"viz_decision": validated}
```

`json` is already imported at the top of the file. `_get_configurable` is already defined in the same file.

- [ ] **Step 5: Run title synthesis tests — verify they pass**

```
pytest tests/graphs/report/test_transparency.py -k "synthesize_title" -v
```
Expected: 6 PASSED.

- [ ] **Step 6: Run existing viz tests to check for regressions**

```
pytest tests/test_visualization_v2/ -v
```
Expected: all PASSED.

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py tests/graphs/report/test_transparency.py
git commit -m "feat(viz): synthesize chart title in spec_validator_node when title is None"
```

---

## Task 2: Transparency Module — Helper Functions

**Files:**
- Create: `src/graphs/report_agent/transparency.py`
- Test: `tests/graphs/report/test_transparency.py` (extend)

- [ ] **Step 1: Write failing tests for helper functions**

Append to `tests/graphs/report/test_transparency.py`:

```python
# ---------------------------------------------------------------------------
# _fmt_date
# ---------------------------------------------------------------------------

def test_fmt_date_formats_correctly():
    from src.graphs.report_agent.transparency import _fmt_date
    assert _fmt_date("2026-01-01") == "1 Ocak 2026"
    assert _fmt_date("2026-04-29") == "29 Nisan 2026"
    assert _fmt_date("2025-12-31") == "31 Aralık 2025"


def test_fmt_date_invalid_returns_original():
    from src.graphs.report_agent.transparency import _fmt_date
    assert _fmt_date("not-a-date") == "not-a-date"


# ---------------------------------------------------------------------------
# _extract_period
# ---------------------------------------------------------------------------

def test_extract_period_between_pattern():
    from src.graphs.report_agent.transparency import _extract_period
    sql = "WHERE DocumentDate BETWEEN '2026-01-01' AND '2026-04-29'"
    result = _extract_period(sql)
    assert result == "1 Ocak 2026 – 29 Nisan 2026"


def test_extract_period_gte_lte_pattern():
    from src.graphs.report_agent.transparency import _extract_period
    sql = "WHERE DocumentDate >= '2026-01-01' AND DocumentDate <= '2026-03-31'"
    result = _extract_period(sql)
    assert result == "1 Ocak 2026 – 31 Mart 2026"


def test_extract_period_year_pattern():
    from src.graphs.report_agent.transparency import _extract_period
    sql = "WHERE YEAR(DocumentDate) = 2025"
    result = _extract_period(sql)
    assert result == "2025 yılı"


def test_extract_period_no_date_returns_none():
    from src.graphs.report_agent.transparency import _extract_period
    sql = "SELECT BranchName, SUM(RowAmount) FROM MasterReportDocumentTable"
    assert _extract_period(sql) is None


def test_extract_period_none_sql_returns_none():
    from src.graphs.report_agent.transparency import _extract_period
    assert _extract_period(None) is None


# ---------------------------------------------------------------------------
# _detect_aggregation
# ---------------------------------------------------------------------------

def test_detect_aggregation_sum():
    from src.graphs.report_agent.transparency import _detect_aggregation
    sql = "SELECT BranchName, SUM(RowAmount) AS Tutar FROM ..."
    assert _detect_aggregation(sql, "RowAmount") == "toplamı"


def test_detect_aggregation_count():
    from src.graphs.report_agent.transparency import _detect_aggregation
    sql = "SELECT CategoryName, COUNT(Quantity) AS Adet FROM ..."
    assert _detect_aggregation(sql, "Quantity") == "adedi"


def test_detect_aggregation_avg():
    from src.graphs.report_agent.transparency import _detect_aggregation
    sql = "SELECT ProductName, AVG(RowAmount) AS Ort FROM ..."
    assert _detect_aggregation(sql, "RowAmount") == "ortalaması"


def test_detect_aggregation_bracketed_column():
    from src.graphs.report_agent.transparency import _detect_aggregation
    sql = "SELECT BranchName, SUM([RowAmount]) AS Tutar FROM ..."
    assert _detect_aggregation(sql, "RowAmount") == "toplamı"


def test_detect_aggregation_no_match_returns_degeri():
    from src.graphs.report_agent.transparency import _detect_aggregation
    assert _detect_aggregation("SELECT *", "RowAmount") == "değeri"


def test_detect_aggregation_none_sql_returns_degeri():
    from src.graphs.report_agent.transparency import _detect_aggregation
    assert _detect_aggregation(None, "RowAmount") == "değeri"
```

- [ ] **Step 2: Run — verify they fail**

```
pytest tests/graphs/report/test_transparency.py -k "fmt_date or extract_period or detect_aggregation" -v
```
Expected: `ImportError` — `transparency` module not found.

- [ ] **Step 3: Create `src/graphs/report_agent/transparency.py` with helpers**

```python
"""
Chart Transparency Module

Builds a thinking-step payload for additional_kwargs["transparency"].
Each step translates a state field into plain Turkish for business users.
Frontend renders steps ①②③... with a "Tümünü Gör" summary.

No LLM, no I/O — pure dict assembly from existing state fields.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_QUERY_TYPE_LABELS = {
    "SINGLE":                "Tek değer sorgusu",
    "RANKING":               "Sıralama raporu",
    "COMPARISON":            "Karşılaştırma raporu",
    "TIME_SERIES":           "Zaman serisi raporu",
    "TIME_SERIES_COMPARISON": "Çok boyutlu zaman serisi",
}

_CHART_TYPE_LABELS = {
    "bar_chart":     "Çubuk grafik",
    "line_chart":    "Çizgi grafik",
    "pie_chart":     "Pasta grafik",
    "sunburst":      "Sunburst grafik",
    "treemap":       "Treemap grafik",
    "heatmap":       "Isı haritası",
    "turkey_map":    "Türkiye haritası",
    "scatter_chart": "Dağılım grafik",
    "comparison":    "Karşılaştırma grafiği",
    "single_value":  "Tek değer",
    "table":         "Tablo",
}

_AGG_LABELS = {
    "SUM":   "toplamı",
    "COUNT": "adedi",
    "AVG":   "ortalaması",
    "MIN":   "minimumu",
    "MAX":   "maksimumu",
}

_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


def _fmt_date(date_str: str) -> str:
    """'2026-01-01' → '1 Ocak 2026'. Returns original string on parse failure."""
    try:
        parts = date_str.split("-")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{day} {_MONTHS[month - 1]} {year}"
    except (ValueError, IndexError, AttributeError):
        return date_str


def _extract_period(sql: Optional[str]) -> Optional[str]:
    """Extract human-readable date range from SQL WHERE clause. Returns None if not found."""
    if not sql:
        return None
    # BETWEEN '...' AND '...'
    m = re.search(
        r"BETWEEN\s+'(\d{4}-\d{2}-\d{2})'\s+AND\s+'(\d{4}-\d{2}-\d{2})'",
        sql, re.IGNORECASE,
    )
    if m:
        return f"{_fmt_date(m.group(1))} – {_fmt_date(m.group(2))}"
    # >= 'date' AND <= 'date'
    m1 = re.search(r">= ?'(\d{4}-\d{2}-\d{2})'", sql, re.IGNORECASE)
    m2 = re.search(r"<= ?'(\d{4}-\d{2}-\d{2})'", sql, re.IGNORECASE)
    if m1 and m2:
        return f"{_fmt_date(m1.group(1))} – {_fmt_date(m2.group(1))}"
    # YEAR(col) = YYYY
    m = re.search(r"YEAR\s*\(\s*\w+\s*\)\s*=\s*(\d{4})", sql, re.IGNORECASE)
    if m:
        return f"{m.group(1)} yılı"
    # >= 'date' only (open-ended)
    if m1:
        return f"{_fmt_date(m1.group(1))} ve sonrası"
    return None


def _detect_aggregation(sql: Optional[str], y_field: Optional[str]) -> str:
    """Detect SUM/COUNT/AVG/MIN/MAX applied to y_field in SQL. Returns 'değeri' if not found."""
    if not sql or not y_field:
        return "değeri"
    pattern = rf'(SUM|COUNT|AVG|MIN|MAX)\s*\(\s*\[?{re.escape(y_field)}\]?\s*\)'
    m = re.search(pattern, sql, re.IGNORECASE)
    return _AGG_LABELS.get(m.group(1).upper(), "değeri") if m else "değeri"


def _get_col_label(field: Optional[str], column_metadata: dict) -> str:
    """Resolve a DB column name to its human-readable label via column_metadata."""
    if not field:
        return ""
    meta = column_metadata.get(field, "")
    if isinstance(meta, dict):
        return meta.get("description", field)
    return meta if isinstance(meta, str) and meta else field
```

- [ ] **Step 4: Run helper tests — verify they pass**

```
pytest tests/graphs/report/test_transparency.py -k "fmt_date or extract_period or detect_aggregation" -v
```
Expected: 11 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/transparency.py tests/graphs/report/test_transparency.py
git commit -m "feat(transparency): add helper functions — date extraction, agg detection, label resolver"
```

---

## Task 3: Transparency Module — Step Builders & Main Function

**Files:**
- Modify: `src/graphs/report_agent/transparency.py` (extend)
- Test: `tests/graphs/report/test_transparency.py` (extend)

- [ ] **Step 1: Write failing tests for step builders and `build_transparency_payload`**

Append to `tests/graphs/report/test_transparency.py`:

```python
# ---------------------------------------------------------------------------
# Step builders
# ---------------------------------------------------------------------------

def test_step_intent_includes_query_and_type():
    from src.graphs.report_agent.transparency import _step_intent
    state = {"user_query": "Şubelere göre satışlar", "query_type": "RANKING"}
    step = _step_intent(state)
    assert step["title"] == "Sorunuzu anladım"
    assert "Şubelere göre satışlar" in step["detail"]
    assert "Sıralama raporu" in step["detail"]


def test_step_period_present_when_sql_has_date():
    from src.graphs.report_agent.transparency import _step_period
    state = {"active_sql": "WHERE DocumentDate BETWEEN '2026-01-01' AND '2026-04-29'"}
    step = _step_period(state)
    assert step is not None
    assert step["title"] == "Dönem belirlendi"
    assert "Ocak" in step["detail"]


def test_step_period_none_when_no_date_in_sql():
    from src.graphs.report_agent.transparency import _step_period
    state = {"active_sql": "SELECT BranchName, SUM(RowAmount) FROM MasterTable"}
    assert _step_period(state) is None


def test_step_rules_present_when_auto_rules_exist():
    from src.graphs.report_agent.transparency import _step_rules
    state = {"auto_rules": [
        {"description": "İptal siparişler dışlandı", "is_default": True},
        {"description": "Sıfır miktarlar hariç", "is_default": True},
    ]}
    step = _step_rules(state)
    assert step is not None
    assert step["title"] == "İş kuralları uygulandı"
    assert len(step["rules"]) == 2
    assert "İptal siparişler dışlandı" in step["rules"]


def test_step_rules_none_when_no_auto_rules():
    from src.graphs.report_agent.transparency import _step_rules
    assert _step_rules({"auto_rules": []}) is None
    assert _step_rules({}) is None


def test_step_computation_uses_labels_and_agg():
    from src.graphs.report_agent.transparency import _step_computation
    state = {
        "visualization_output": {"x_field": "BranchName", "y_field": "RowAmount"},
        "results": [{"BranchName": "A", "RowAmount": 1}] * 64,
        "active_sql": "SELECT BranchName, SUM(RowAmount) AS Tutar FROM ...",
    }
    meta = {"BranchName": "Şube", "RowAmount": "Satış Tutarı"}
    step = _step_computation(state, meta)
    assert step["title"] == "Hesaplama yapıldı"
    assert "Şube" in step["detail"]
    assert "toplamı" in step["detail"]
    assert "64 kayıt" in step["detail"]


def test_step_visualization_uses_chart_label():
    from src.graphs.report_agent.transparency import _step_visualization
    state = {"visualization_output": {"chart_type": "sunburst"}}
    step = _step_visualization(state)
    assert step["title"] == "Görselleştirildi"
    assert "Sunburst grafik" in step["detail"]


# ---------------------------------------------------------------------------
# build_transparency_payload
# ---------------------------------------------------------------------------

def test_build_transparency_payload_full_state():
    from src.graphs.report_agent.transparency import build_transparency_payload
    state = {
        "user_query": "Kategoriye göre satışlar",
        "query_type": "RANKING",
        "active_sql": "SELECT CategoryName, SUM(RowAmount) AS Tutar FROM MasterTable WHERE DocumentDate BETWEEN '2026-01-01' AND '2026-04-29' AND DocumentStatus != 'İptal'",
        "auto_rules": [{"description": "İptal siparişler dışlandı", "is_default": True}],
        "visualization_output": {
            "chart_type": "bar_chart",
            "x_field": "CategoryName",
            "y_field": "RowAmount",
        },
        "results": [{"CategoryName": "Elektronik", "RowAmount": 5000}] * 42,
    }
    meta = {"CategoryName": "Kategori", "RowAmount": "Satış Tutarı"}
    result = build_transparency_payload(state, meta)

    assert "steps" in result
    assert "summary" in result
    steps = result["steps"]
    # Steps should be numbered 1..N
    assert steps[0]["n"] == 1
    assert all(s["n"] == i + 1 for i, s in enumerate(steps))
    # Step titles present
    titles = [s["title"] for s in steps]
    assert "Sorunuzu anladım" in titles
    assert "Dönem belirlendi" in titles
    assert "İş kuralları uygulandı" in titles
    assert "Hesaplama yapıldı" in titles
    assert "Görselleştirildi" in titles
    # Summary is a non-empty string
    assert isinstance(result["summary"], str)
    assert len(result["summary"]) > 0


def test_build_transparency_payload_empty_state_no_exception():
    from src.graphs.report_agent.transparency import build_transparency_payload
    result = build_transparency_payload({})
    assert "steps" in result
    assert "summary" in result
    assert isinstance(result["steps"], list)


def test_build_transparency_payload_no_rules_step_absent():
    from src.graphs.report_agent.transparency import build_transparency_payload
    state = {
        "user_query": "Satışlar",
        "query_type": "SINGLE",
        "auto_rules": [],
        "active_sql": "SELECT SUM(RowAmount) FROM MasterTable",
        "visualization_output": {"chart_type": "single_value"},
        "results": [{"Total": 1000}],
    }
    result = build_transparency_payload(state)
    titles = [s["title"] for s in result["steps"]]
    assert "İş kuralları uygulandı" not in titles


def test_build_transparency_payload_no_date_step_absent():
    from src.graphs.report_agent.transparency import build_transparency_payload
    state = {
        "user_query": "Tüm satışlar",
        "active_sql": "SELECT BranchName, SUM(RowAmount) FROM MasterTable GROUP BY BranchName",
        "visualization_output": {"chart_type": "bar_chart"},
        "results": [],
    }
    result = build_transparency_payload(state)
    titles = [s["title"] for s in result["steps"]]
    assert "Dönem belirlendi" not in titles


def test_build_transparency_payload_steps_renumbered_correctly():
    from src.graphs.report_agent.transparency import build_transparency_payload
    # No rules, no date → only 3 steps: intent, computation, visualization
    state = {
        "user_query": "Satışlar",
        "auto_rules": [],
        "active_sql": "SELECT BranchName, SUM(RowAmount) FROM MasterTable",
        "visualization_output": {"chart_type": "bar_chart", "x_field": "BranchName", "y_field": "RowAmount"},
        "results": [{"BranchName": "A", "RowAmount": 1}],
    }
    result = build_transparency_payload(state)
    for i, step in enumerate(result["steps"], 1):
        assert step["n"] == i
```

- [ ] **Step 2: Run — verify they fail**

```
pytest tests/graphs/report/test_transparency.py -k "step_ or build_transparency" -v
```
Expected: `ImportError` — step builders not yet defined.

- [ ] **Step 3: Add step builders and `build_transparency_payload` to `transparency.py`**

Append to `src/graphs/report_agent/transparency.py`:

```python
# ---------------------------------------------------------------------------
# Step builders — each returns a dict or None
# ---------------------------------------------------------------------------

def _step_intent(state: dict) -> dict:
    user_query = (state.get("user_query") or "")[:80]
    query_type = state.get("query_type") or ""
    type_label = _QUERY_TYPE_LABELS.get(query_type, "")
    detail = f'"{user_query}"'
    if type_label:
        detail += f" → {type_label}"
    return {"n": 0, "title": "Sorunuzu anladım", "detail": detail}


def _step_period(state: dict) -> Optional[dict]:
    period = _extract_period(state.get("active_sql"))
    if not period:
        return None
    return {"n": 0, "title": "Dönem belirlendi", "detail": period}


def _step_rules(state: dict) -> Optional[dict]:
    auto_rules = state.get("auto_rules") or []
    descriptions = [r.get("description", "") for r in auto_rules if r.get("description")]
    if not descriptions:
        return None
    return {"n": 0, "title": "İş kuralları uygulandı", "rules": descriptions}


def _step_computation(state: dict, column_metadata: dict) -> dict:
    viz = state.get("visualization_output") or {}
    results = state.get("results") or []
    sql = state.get("active_sql") or ""
    x_field = viz.get("x_field")
    y_field = viz.get("y_field")
    x_label = _get_col_label(x_field, column_metadata) or x_field or ""
    y_label = _get_col_label(y_field, column_metadata) or y_field or ""
    agg = _detect_aggregation(sql, y_field) if y_field else "değeri"
    row_count = len(results)
    parts = []
    if x_label:
        parts.append(f"{x_label} bazında gruplandı")
    if y_label:
        parts.append(f"{y_label} {agg} alındı")
    computation = ", ".join(parts) if parts else "Veri hesaplandı"
    return {"n": 0, "title": "Hesaplama yapıldı", "detail": f"{computation} → {row_count} kayıt"}


def _step_visualization(state: dict) -> dict:
    viz = state.get("visualization_output") or {}
    chart_type = viz.get("chart_type") or ""
    label = _CHART_TYPE_LABELS.get(
        chart_type,
        chart_type.replace("_", " ").title() if chart_type else "Grafik",
    )
    return {"n": 0, "title": "Görselleştirildi", "detail": f"{label} seçildi"}


def _build_summary(state: dict, column_metadata: dict) -> str:
    viz = state.get("visualization_output") or {}
    results = state.get("results") or []
    auto_rules = state.get("auto_rules") or []
    sql = state.get("active_sql") or ""
    x_field = viz.get("x_field")
    y_field = viz.get("y_field")
    x_label = _get_col_label(x_field, column_metadata) or x_field or ""
    y_label = _get_col_label(y_field, column_metadata) or y_field or ""
    agg = _detect_aggregation(sql, y_field) if y_field else ""
    period = _extract_period(sql) or "Tüm dönem"
    row_count = len(results)
    chart_type = viz.get("chart_type") or ""
    chart_label = _CHART_TYPE_LABELS.get(chart_type, chart_type or "Grafik")
    parts = []
    if x_label and y_label:
        parts.append(f"{x_label} & {y_label} {agg}".strip())
    elif x_label:
        parts.append(x_label)
    parts.append(period)
    if auto_rules:
        parts.append(f"{len(auto_rules)} filtre")
    parts.append(f"{row_count} kayıt")
    parts.append(chart_label)
    return " · ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_transparency_payload(state: dict, column_metadata: dict = None) -> dict:
    """
    Build thinking-step transparency payload for additional_kwargs['transparency'].
    Steps translate state fields to plain Turkish for business users.
    Returns {"steps": [...], "summary": "..."} — always safe, never raises.
    """
    meta = column_metadata or {}
    try:
        steps = [_step_intent(state)]
        period_step = _step_period(state)
        if period_step:
            steps.append(period_step)
        rules_step = _step_rules(state)
        if rules_step:
            steps.append(rules_step)
        steps.append(_step_computation(state, meta))
        steps.append(_step_visualization(state))
        for i, step in enumerate(steps, 1):
            step["n"] = i
        return {"steps": steps, "summary": _build_summary(state, meta)}
    except Exception as e:
        logger.warning(f"[TRANSPARENCY] Failed to build payload: {e}")
        return {"steps": [], "summary": ""}
```

- [ ] **Step 4: Run all transparency tests — verify they pass**

```
pytest tests/graphs/report/test_transparency.py -v
```
Expected: all PASSED (title synthesis + helpers + step builders + payload).

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/transparency.py tests/graphs/report/test_transparency.py
git commit -m "feat(transparency): add step builders and build_transparency_payload"
```

---

## Task 4: Wire Transparency into build_response_node

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`
- Modify: `src/graphs/report_agent/graph.py`
- Test: `tests/graphs/report/test_build_response_node.py` (extend)

- [ ] **Step 1: Read existing build_response_node tests to understand pattern**

```
pytest tests/graphs/report/test_build_response_node.py -v
```
Note which tests check `additional_kwargs`.

- [ ] **Step 2: Write failing test**

Append to `tests/graphs/report/test_build_response_node.py`:

```python
@pytest.mark.asyncio
async def test_build_response_node_adds_transparency_to_additional_kwargs():
    from src.graphs.report_agent.nodes import create_build_response_node
    node = create_build_response_node(llm=None, column_metadata={"BranchName": "Şube"})
    results = [{"BranchName": "Ankara", "RowAmount": 1000}]
    state = {
        "error": None,
        "use_result_type": None,
        "final_response": None,
        "user_query": "Şube satışları",
        "query_type": "RANKING",
        "auto_rules": [{"description": "İptal siparişler dışlandı", "is_default": True}],
        "active_sql": "SELECT BranchName, SUM([RowAmount]) FROM MasterTable GROUP BY BranchName",
        "results": results,
        "visualization_output": {
            "needs_graph": True,
            "chart_type": "bar_chart",
            "plotly_html_snippet": "<div>chart</div>",
            "x_field": "BranchName",
            "y_field": "RowAmount",
            "title": "Şube Bazında Satış Tutarı",
        },
    }
    output = await node(state)
    messages = output.get("messages", [])
    assert len(messages) == 1
    msg = messages[0]
    assert "transparency" in msg.additional_kwargs
    transparency = msg.additional_kwargs["transparency"]
    assert "steps" in transparency
    assert "summary" in transparency
    assert isinstance(transparency["steps"], list)
    assert len(transparency["steps"]) >= 1


@pytest.mark.asyncio
async def test_build_response_node_transparency_steps_numbered():
    from src.graphs.report_agent.nodes import create_build_response_node
    node = create_build_response_node(llm=None, column_metadata={})
    state = {
        "error": None,
        "use_result_type": None,
        "final_response": None,
        "user_query": "Satışlar",
        "auto_rules": [],
        "active_sql": "SELECT SUM(RowAmount) FROM MasterTable",
        "results": [{"Total": 5000}],
        "visualization_output": {
            "needs_graph": True,
            "chart_type": "bar_chart",
            "plotly_html_snippet": "<div>x</div>",
            "x_field": None,
            "y_field": None,
            "title": "Rapor",
        },
    }
    output = await node(state)
    steps = output["messages"][0].additional_kwargs["transparency"]["steps"]
    for i, step in enumerate(steps, 1):
        assert step["n"] == i
```

- [ ] **Step 3: Run — verify they fail**

```
pytest tests/graphs/report/test_build_response_node.py::test_build_response_node_adds_transparency_to_additional_kwargs -v
```
Expected: `TypeError` — `create_build_response_node()` does not accept `column_metadata`.

- [ ] **Step 4: Update `create_build_response_node` in `nodes.py`**

At line 532 in `src/graphs/report_agent/nodes.py`:

Add import at the top of the imports section:
```python
from src.graphs.report_agent.transparency import build_transparency_payload
```

Change the factory signature and add transparency call:

```python
# BEFORE:
def create_build_response_node(llm=None):
    """Factory: returns build_response_node with optional LLM for insight generation."""
    async def build_response_node(state: dict) -> dict:
```

```python
# AFTER:
def create_build_response_node(llm=None, column_metadata=None):
    """Factory: returns build_response_node with optional LLM for insight generation."""
    _column_metadata = column_metadata or {}

    async def build_response_node(state: dict) -> dict:
```

Then in the chart branch (where `summary_text` is built, around line 573-588), add the transparency call:

```python
# BEFORE:
            summary_text = await build_chart_response(
                results, viz, state.get("user_query", ""), DEFAULT_CONFIG, llm
            )

            # Full response with iframe for user display
            full_response = summary_text + "\n\n" + iframe

            # Messages: short summary in content (LLM sees this)
            # chart_html in additional_kwargs (LLM does NOT see this, chat_service extracts it)
            return {
                "final_response": full_response,
                "messages": [AIMessage(
                    content=summary_text,
                    additional_kwargs={"chart_html": iframe},
                )],
            }
```

```python
# AFTER:
            summary_text = await build_chart_response(
                results, viz, state.get("user_query", ""), DEFAULT_CONFIG, llm
            )
            transparency = build_transparency_payload(state, _column_metadata)

            # Full response with iframe for user display
            full_response = summary_text + "\n\n" + iframe

            # Messages: short summary in content (LLM sees this)
            # chart_html and transparency in additional_kwargs (frontend-only)
            return {
                "final_response": full_response,
                "messages": [AIMessage(
                    content=summary_text,
                    additional_kwargs={"chart_html": iframe, "transparency": transparency},
                )],
            }
```

- [ ] **Step 5: Update `graph.py` to pass `column_metadata`**

In `src/graphs/report_agent/graph.py`, line 102:

```python
# BEFORE:
    graph.add_node("build_response", create_build_response_node(llm))
```

```python
# AFTER:
    graph.add_node("build_response", create_build_response_node(llm, column_metadata))
```

`column_metadata` is already a parameter of `build_report_agent_graph` (line 74).

- [ ] **Step 6: Run new tests — verify they pass**

```
pytest tests/graphs/report/test_build_response_node.py -v
```
Expected: all PASSED including the two new tests.

- [ ] **Step 7: Run full test suite**

```
pytest tests/ -v --ignore=tests/integration -x
```
Expected: all PASSED. Fix any failures before committing.

- [ ] **Step 8: Commit**

```bash
git add src/graphs/report_agent/nodes.py src/graphs/report_agent/graph.py tests/graphs/report/test_build_response_node.py
git commit -m "feat(transparency): wire build_transparency_payload into build_response_node"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Chart title synthesis in `spec_validator_node` → Task 1
- [x] `transparency.py` module with step builders → Tasks 2 + 3
- [x] `build_transparency_payload` public function → Task 3
- [x] `additional_kwargs["transparency"]` in AIMessage → Task 4
- [x] Step ① intent, ② period (optional), ③ rules (optional), ④ computation, ⑤ visualization → Task 3
- [x] Step numbers resequenced after optional steps removed → Task 3 tests
- [x] `summary` field → Task 3
- [x] `column_metadata` passed through factory to transparency → Task 4
- [x] `graph.py` updated to pass `column_metadata` → Task 4 Step 5
- [x] Empty state does not raise → Task 3 test `test_build_transparency_payload_empty_state_no_exception`
- [x] Title already set → not overwritten (checked by `if not validated.get("title"):`) → Task 1 Step 4

**No placeholders:** All steps have complete code.

**Type consistency:**
- `_synthesize_title(user_query: str, spec: dict, column_metadata: dict) -> str` — called same way in Task 1 Step 3 and Step 4
- `build_transparency_payload(state: dict, column_metadata: dict = None) -> dict` — called same way in Task 3 Step 3 and Task 4 Step 4
- `create_build_response_node(llm=None, column_metadata=None)` — signature in Task 4 Step 4 and Task 4 test both use `column_metadata` kwarg
