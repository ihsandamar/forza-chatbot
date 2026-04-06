# Aggregate Period Granularity Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `hour_of_day`, `day_of_week`, `day_of_month` aggregate granularity types that GROUP BY only the period dimension (not date), producing distribution-style results (24 rows, 7 rows, 31 rows respectively).

**Architecture:** Extend the existing `time_granularity` Literal in QuerySchema with 3 new values. Update `_TIME_GRAN_MAP` to map them to single SQL expressions (no date component). Update prompts to teach the LLM the distinction between time-series granularity (trend over time) vs aggregate-period granularity (distribution across a period). Update visualization to prefer bar charts for aggregate periods. Add clarification mechanism when intent is ambiguous.

**Tech Stack:** Python, Pydantic, LangGraph, T-SQL, Vega-Lite (via visualization_v2)

---

## Terminology

| Term | Meaning | Example Query | GROUP BY | Rows |
|------|---------|---------------|----------|------|
| **Time-series hourly** | Trend over time at hourly intervals | "saatlik satış trendi" | date + hour | ~2000 |
| **Aggregate hour_of_day** | Distribution by hour of day | "saate göre ciro" | only hour | 24 |
| **Time-series daily** | Trend over days | "günlük satışlar" | date | ~90 |
| **Aggregate day_of_week** | Distribution by weekday | "haftanın günlerine göre" | only DayOfWeek | 7 |
| **Aggregate day_of_month** | Distribution by day-of-month | "ayın günlerine göre" | only day(date) | 31 |

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/graphs/report_agent/subagents/text2sql/prompts.py` | Modify | QuerySchema Literal + LLM prompt rules |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | Modify | `_TIME_GRAN_MAP` + keyword fallback + `_TIME_ADJACENT_COLS_UPPER` |
| `src/graphs/report_agent/subagents/text2sql/sql_builder.py` | Modify | `_EXPR_ALIAS_MAP` + ORDER BY detection |
| `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Modify | Chart type rule for aggregate periods |
| `src/graphs/report_agent/subagents/visualization_v2/prompts.py` | Modify | Field mapping guidance for aggregate periods |
| `src/graphs/report_agent/prompts.py` | Modify | Intent classification guidance |
| `tests/unit/test_aggregate_period_granularity.py` | Create | Unit tests for all changes |

---

## Chunk 1: SQL Generation Layer

### Task 1: Extend QuerySchema and `_TIME_GRAN_MAP`

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py:97` (QuerySchema.time_granularity Literal)
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:115-121` (`_TIME_GRAN_MAP`)
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:136-147` (`_ALL_TIME_EXPRS_UPPER` — manually maintained, NOT auto-derived)
- Test: `tests/unit/test_aggregate_period_granularity.py`

- [ ] **Step 1: Write failing test for new granularity mappings**

```python
# tests/unit/test_aggregate_period_granularity.py
"""Tests for aggregate period granularity (hour_of_day, day_of_week, day_of_month)."""
import pytest


class TestTimeGranMap:
    """Verify _TIME_GRAN_MAP entries for aggregate period types."""

    def test_hour_of_day_has_no_date(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        cols = _TIME_GRAN_MAP["hour_of_day"]
        assert cols == ["DATEPART(HOUR, DocumentDate)"]
        assert not any("CAST(" in c for c in cols), "hour_of_day must NOT include date"

    def test_day_of_week_has_no_date(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        cols = _TIME_GRAN_MAP["day_of_week"]
        assert cols == ["DATEPART(DW, DocumentDate)"]
        assert not any("CAST(" in c for c in cols), "day_of_week must NOT include date"

    def test_day_of_month_has_no_date(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        cols = _TIME_GRAN_MAP["day_of_month"]
        assert cols == ["DATEPART(DAY, DocumentDate)"]
        assert not any("CAST(" in c for c in cols), "day_of_month must NOT include date"

    def test_existing_hourly_unchanged(self):
        """hourly (time-series) must still include date + hour."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        cols = _TIME_GRAN_MAP["hourly"]
        assert "CAST(DocumentDate AS DATE)" in cols
        assert "DATEPART(HOUR, DocumentDate)" in cols
```

- [ ] **Step 2: Run test — expect FAIL (KeyError for new keys)**

```bash
python -m pytest tests/unit/test_aggregate_period_granularity.py::TestTimeGranMap -v
```

- [ ] **Step 3: Add new entries to `_TIME_GRAN_MAP`**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, find `_TIME_GRAN_MAP` (line ~115) and add 3 entries:

```python
_TIME_GRAN_MAP: dict = {
    "hourly":       ["CAST(DocumentDate AS DATE)", "DATEPART(HOUR, DocumentDate)"],
    "daily":        ["CAST(DocumentDate AS DATE)"],
    "weekly":       ["CONCAT(YEAR(DocumentDate), '-W', RIGHT('0' + CAST(DATEPART(WEEK, DocumentDate) AS VARCHAR), 2))"],
    "monthly":      ["CONCAT(YEAR(DocumentDate), '-', RIGHT('0' + CAST(MONTH(DocumentDate) AS VARCHAR), 2))"],
    "yearly":       ["YEAR(DocumentDate)"],
    # --- Aggregate period types (distribution, NOT time-series) ---
    "hour_of_day":  ["DATEPART(HOUR, DocumentDate)"],
    "day_of_week":  ["DATEPART(DW, DocumentDate)"],
    "day_of_month": ["DATEPART(DAY, DocumentDate)"],
}
```

- [ ] **Step 4: Update `_ALL_TIME_EXPRS_UPPER` (MANUALLY maintained set)**

⚠️ `_ALL_TIME_EXPRS_UPPER` (lines 136-147) is **manually maintained** — it is NOT auto-derived from `_TIME_GRAN_MAP`. You MUST add the new DATEPART expressions here, otherwise the redundancy detection logic won't recognize them.

Add these entries to `_ALL_TIME_EXPRS_UPPER`:

```python
_ALL_TIME_EXPRS_UPPER = {
    "CAST(DOCUMENTDATE AS DATE)",
    "YEAR(DOCUMENTDATE)",
    "MONTH(DOCUMENTDATE)",
    "DATEPART(WEEK, DOCUMENTDATE)",
    "DATEPART(WEEKDAY, DOCUMENTDATE)",
    "DATEPART(HOUR, DOCUMENTDATE)",
    "DATEPART(DW, DOCUMENTDATE)",          # NEW — day_of_week
    "DATEPART(DAY, DOCUMENTDATE)",          # NEW — day_of_month
    "HOUR",
    "CONCAT(YEAR(DOCUMENTDATE), '-W', RIGHT('0' + CAST(DATEPART(WEEK, DOCUMENTDATE) AS VARCHAR), 2))",
    "CONCAT(YEAR(DOCUMENTDATE), '-', RIGHT('0' + CAST(MONTH(DOCUMENTDATE) AS VARCHAR), 2))",
}
```

**Note on `_TIME_ADJACENT_COLS_UPPER`** (~line 128): No change needed. It contains raw column names (`DAYOFWEEK`, `HOUR`), not DATEPART expressions. The DATEPART expressions go through `_ALL_TIME_EXPRS_UPPER` which is a separate check. Verify by reading nodes.py:128-147 before editing.

- [ ] **Step 5: Extend QuerySchema Literal type**

In `src/graphs/report_agent/subagents/text2sql/prompts.py`, find `time_granularity` field (~line 92):

```python
# BEFORE:
time_granularity: Optional[Literal["hourly", "daily", "weekly", "monthly", "yearly"]] = None

# AFTER:
time_granularity: Optional[Literal[
    "hourly", "daily", "weekly", "monthly", "yearly",
    "hour_of_day", "day_of_week", "day_of_month",
]] = None
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
python -m pytest tests/unit/test_aggregate_period_granularity.py::TestTimeGranMap -v
```

- [ ] **Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py \
        src/graphs/report_agent/subagents/text2sql/prompts.py \
        tests/unit/test_aggregate_period_granularity.py
git commit -m "feat: add hour_of_day, day_of_week, day_of_month to _TIME_GRAN_MAP and QuerySchema"
```

---

### Task 2: Update Expression Alias Map and ORDER BY

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/sql_builder.py:27-37` (`_EXPR_ALIAS_MAP`)
- Test: `tests/unit/test_aggregate_period_granularity.py`

- [ ] **Step 1: Write failing test for aliases**

```python
# Append to tests/unit/test_aggregate_period_granularity.py

class TestExprAliasMap:
    """Verify SELECT aliases for aggregate period expressions."""

    def test_hour_of_day_alias(self):
        from src.graphs.report_agent.subagents.text2sql.sql_builder import _EXPR_ALIAS_MAP
        assert _EXPR_ALIAS_MAP["DATEPART(HOUR, DocumentDate)"] == "Saat"

    def test_day_of_week_alias(self):
        from src.graphs.report_agent.subagents.text2sql.sql_builder import _EXPR_ALIAS_MAP
        assert _EXPR_ALIAS_MAP["DATEPART(DW, DocumentDate)"] == "HaftaGunu"

    def test_day_of_month_alias(self):
        from src.graphs.report_agent.subagents.text2sql.sql_builder import _EXPR_ALIAS_MAP
        assert _EXPR_ALIAS_MAP["DATEPART(DAY, DocumentDate)"] == "AyinGunu"
```

- [ ] **Step 2: Run test — expect FAIL for DW and DAY aliases**

```bash
python -m pytest tests/unit/test_aggregate_period_granularity.py::TestExprAliasMap -v
```

Note: `DATEPART(HOUR, DocumentDate)` → `"Saat"` likely already exists (line 33 of sql_builder.py).

- [ ] **Step 3: Add missing aliases to `_EXPR_ALIAS_MAP`**

In `src/graphs/report_agent/subagents/text2sql/sql_builder.py`, find `_EXPR_ALIAS_MAP` (~line 27) and add:

```python
_EXPR_ALIAS_MAP: dict[str, str] = {
    "YEAR(DocumentDate)": "Yil",
    "MONTH(DocumentDate)": "Ay",
    "CAST(DocumentDate AS DATE)": "Tarih",
    "DATEPART(WEEK, DocumentDate)": "Hafta",
    "DATEPART(QUARTER, DocumentDate)": "Ceyrek",
    "DATEPART(HOUR, DocumentDate)": "Saat",
    "DATEPART(DW, DocumentDate)": "HaftaGunu",       # NEW
    "DATEPART(DAY, DocumentDate)": "AyinGunu",        # NEW
    # Composite CONCAT expressions
    "CONCAT(YEAR(DocumentDate), '-W', RIGHT('0' + CAST(DATEPART(WEEK, DocumentDate) AS VARCHAR), 2))": "Hafta",
    "CONCAT(YEAR(DocumentDate), '-', RIGHT('0' + CAST(MONTH(DocumentDate) AS VARCHAR), 2))": "Ay",
}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/unit/test_aggregate_period_granularity.py::TestExprAliasMap -v
```

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/sql_builder.py \
        tests/unit/test_aggregate_period_granularity.py
git commit -m "feat: add DW and DAY expression aliases to sql_builder"
```

---

### Task 3: Update Keyword Fallback Detection

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:1073-1085` (keyword fallback)
- Test: `tests/unit/test_aggregate_period_granularity.py`

- [ ] **Step 1: Write failing test for keyword detection**

```python
# Append to tests/unit/test_aggregate_period_granularity.py

class TestKeywordFallback:
    """Verify Turkish keyword → granularity mapping for fallback detection."""

    @pytest.mark.parametrize("query,expected", [
        # hour_of_day patterns
        ("saate göre ciro ver", "hour_of_day"),
        ("günün saatlerine göre", "hour_of_day"),
        ("saat dağılımı", "hour_of_day"),
        ("saatlere göre satış", "hour_of_day"),
        # day_of_week patterns
        ("haftanın günlerine göre", "day_of_week"),
        ("güne göre dağılım", "day_of_week"),
        ("gün bazında", "daily"),  # "gün bazında" → maps to daily (existing keyword in time-series patterns)
        # day_of_month patterns
        ("ayın günlerine göre", "day_of_month"),
        # Existing patterns UNCHANGED
        ("saatlik satış trendi", "hourly"),
        ("günlük satışlar", "daily"),
        ("haftalık ciro", "weekly"),
        ("aylık karşılaştır", "monthly"),
    ])
    def test_keyword_to_granularity(self, query, expected):
        """Test that Turkish keywords resolve to correct granularity.

        NOTE: This tests the keyword fallback logic (Option B) extracted into
        a helper. The actual implementation may inline this in sql_generator_node.
        Test the helper function directly.
        """
        from src.graphs.report_agent.subagents.text2sql.nodes import _detect_time_granularity_from_query
        result = _detect_time_granularity_from_query(query)
        assert result == expected, f"Query '{query}' → expected {expected}, got {result}"
```

- [ ] **Step 2: Run test — expect FAIL (function doesn't exist yet)**

```bash
python -m pytest tests/unit/test_aggregate_period_granularity.py::TestKeywordFallback -v
```

- [ ] **Step 3: Extract keyword detection into a helper function and add new keywords**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, add a module-level helper function (before `sql_generator_node`):

```python
def _detect_time_granularity_from_query(user_query: str) -> Optional[str]:
    """Detect time_granularity from Turkish keywords in user query (Option B fallback).

    Returns granularity string or None if no match.
    Order matters: aggregate-period patterns are checked FIRST (more specific),
    then time-series patterns (more general).
    """
    q = user_query.lower()

    # --- Aggregate period patterns (check first — more specific) ---
    if any(k in q for k in ("saate göre", "saatlere göre", "günün saatlerine göre", "saat dağılımı")):
        return "hour_of_day"
    if any(k in q for k in ("haftanın günlerine göre", "haftanın günleri", "günlere göre dağılım")):
        return "day_of_week"
    if any(k in q for k in ("ayın günlerine göre", "ayın günleri")):
        return "day_of_month"

    # --- Time-series patterns (existing — more general) ---
    if any(k in q for k in ("saatlik", "her saat", "saat saat", "saat bazında")):
        return "hourly"
    if any(k in q for k in ("haftalık", "her hafta", "hafta hafta", "hafta bazında")):
        return "weekly"
    if any(k in q for k in ("aylık", "her ay", "ay ay", "ay bazında")):
        return "monthly"
    if any(k in q for k in ("yıllık", "her yıl", "yıl yıl", "yıl bazında")):
        return "yearly"
    if any(k in q for k in ("günlük", "her gün", "gün gün", "gün bazında")):
        return "daily"

    return None
```

Then update the TIME_SERIES_COMPARISON block (~line 1073) to use this helper:

```python
# --- Option B fallback: LLM alanları boş bıraktıysa query'den tespit ---
if not _time_gran:
    _time_gran = _detect_time_granularity_from_query(state.get("user_query", ""))
    if _time_gran:
        logger.warning(f"[SQL_GENERATOR] TIME_SERIES: time_granularity keyword fallback: {_time_gran}")
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/unit/test_aggregate_period_granularity.py::TestKeywordFallback -v
```

- [ ] **Step 5: Run ALL aggregate period tests**

```bash
python -m pytest tests/unit/test_aggregate_period_granularity.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py \
        tests/unit/test_aggregate_period_granularity.py
git commit -m "feat: extract keyword detection helper with aggregate period support"
```

---

### Task 4: Update LLM Prompts (KURAL 4.8 + KURAL 5)

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py:323-389` (KURAL 4.8 + KURAL 5)
- No test (prompt changes are validated by integration/manual testing)

- [ ] **Step 1: Update KURAL 4.8 — time_granularity section**

In `src/graphs/report_agent/subagents/text2sql/prompts.py`, find the `time_granularity` guidance block (~lines 326-331). Replace with:

```
**time_granularity** — Zaman granülaritesi (sadece bu değerlerden biri):

  ⏰ ZAMAN SERİSİ (trend/karşılaştırma — tarih + periyod):
  "saatlik trend", "saat saat değişim"   → "hourly"
  "günlük", "her gün", "gün bazında"    → "daily"
  "haftalık", "her hafta"                → "weekly"
  "aylık", "her ay", "ay bazında"       → "monthly"
  "yıllık", "her yıl", "yıl bazında"   → "yearly"

  📊 TOPLU DAĞILIM (aggregate — SADECE periyod, tarih YOK):
  "saate göre", "saatlere göre", "günün saatlerine göre"  → "hour_of_day"
  "haftanın günlerine göre", "güne göre dağılım"           → "day_of_week"
  "ayın günlerine göre", "ayın hangi günleri"              → "day_of_month"

  ⚠️ KRİTİK FARK:
  - "saatlik trend"      → "hourly"      (DATE + HOUR → her gün her saat ayrı satır)
  - "saate göre ciro"    → "hour_of_day" (SADECE HOUR → 24 satır, günler toplanır)
  - "günlük satışlar"    → "daily"       (her gün ayrı satır)
  - "haftanın günlerine göre" → "day_of_week" (7 satır: Pazartesi-Pazar, günler toplanır)
```

- [ ] **Step 2: Update KURAL 5 — Periyodik Gruplama examples**

Find KURAL 5 section (~lines 365-379). Add aggregate period examples:

```
### KURAL 5 — Periyodik Gruplama
"günlük satışlar"            → group_by: ["CAST(DocumentDate AS DATE)"]
"haftalık satışlar"          → group_by: ["YEAR(DocumentDate)", "DATEPART(WEEK, DocumentDate)"]
"aylık satışlar"             → group_by: ["YEAR(DocumentDate)", "MONTH(DocumentDate)"]
"yıllık satışlar"            → group_by: ["YEAR(DocumentDate)"]
"saatlik dağılım"            → group_by: ["CAST(DocumentDate AS DATE)", "DATEPART(HOUR, DocumentDate)"]

📊 TOPLU DAĞILIM (aggregate — tarih kolonu EKLEME):
"saate göre ciro"            → time_granularity: "hour_of_day"
                               group_by: ["DATEPART(HOUR, DocumentDate)"]  ← SADECE saat!
"haftanın günlerine göre"    → time_granularity: "day_of_week"
                               group_by: ["DATEPART(DW, DocumentDate)"]   ← SADECE gün!
"ayın günlerine göre"        → time_granularity: "day_of_month"
                               group_by: ["DATEPART(DAY, DocumentDate)"]  ← SADECE gün numarası!

⚠️ TOPLU DAĞILIM'da CAST(DocumentDate AS DATE) veya YEAR() KOYMA — tüm tarihler TOPLANMALI.
```

- [ ] **Step 3: Add KURAL 4.8 examples for new types**

After existing examples (~line 364), add:

```
ÖRNEK ✅ (aggregate — hour_of_day):
  "son 3 ayda espresso cirosu saate göre"
  → time_granularity: "hour_of_day"
  → comparison_dimension: null
  → filters: [CategoryName = "ESPRESSO"]
  → group_by: ["DATEPART(HOUR, DocumentDate)"]
  → Sonuç: 24 satır (0-23 saat, tüm günler toplanmış)

ÖRNEK ✅ (aggregate — day_of_week):
  "haftanın günlerine göre satış dağılımı"
  → time_granularity: "day_of_week"
  → comparison_dimension: null
  → group_by: ["DATEPART(DW, DocumentDate)"]
  → Sonuç: 7 satır (Pazartesi-Pazar)

ÖRNEK ✅ (aggregate — day_of_week + entity):
  "kategorilerin haftanın günlerine göre karşılaştırması"
  → time_granularity: "day_of_week"
  → comparison_dimension: "CategoryName"
  → group_by: ["CategoryName", "DATEPART(DW, DocumentDate)"]
```

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "feat: update LLM prompts with aggregate period granularity guidance"
```

---

## Chunk 2: Visualization and Intent Classification

### Task 5: Update Visualization V2 — Chart Type Rules

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py:129-194` (`_rule_based_decision`)
- Test: `tests/unit/test_aggregate_period_granularity.py`

The key insight: aggregate period granularities produce **distribution** data (24 hours, 7 days, 31 days). These are better shown as **bar charts**, not line charts. Time-series granularities (trend over time) keep using line charts.

- [ ] **Step 1: Write failing test for viz rule**

```python
# Append to tests/unit/test_aggregate_period_granularity.py

# Set of aggregate period granularities used across the codebase
AGGREGATE_PERIOD_GRANULARITIES = frozenset({"hour_of_day", "day_of_week", "day_of_month"})


class TestAggregateGranularitySet:
    """Verify the AGGREGATE_PERIOD_GRANULARITIES constant is accessible."""

    def test_set_exists_in_nodes(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import AGGREGATE_PERIOD_GRANULARITIES
        assert "hour_of_day" in AGGREGATE_PERIOD_GRANULARITIES
        assert "day_of_week" in AGGREGATE_PERIOD_GRANULARITIES
        assert "day_of_month" in AGGREGATE_PERIOD_GRANULARITIES
        # Time-series types should NOT be in this set
        assert "hourly" not in AGGREGATE_PERIOD_GRANULARITIES
        assert "daily" not in AGGREGATE_PERIOD_GRANULARITIES
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
python -m pytest tests/unit/test_aggregate_period_granularity.py::TestAggregateGranularitySet -v
```

- [ ] **Step 3: Add `AGGREGATE_PERIOD_GRANULARITIES` constant**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, after `_TIME_GRAN_MAP` definition (~line 122), add:

```python
# Aggregate period types: produce distribution data (bar chart), NOT time-series (line chart).
# Used by visualization layer to choose chart type.
AGGREGATE_PERIOD_GRANULARITIES: frozenset = frozenset({"hour_of_day", "day_of_week", "day_of_month"})
```

- [ ] **Step 4: Run test — PASS**

- [ ] **Step 5: Update `_rule_based_decision` in visualization_v2/nodes.py**

Read `src/graphs/report_agent/subagents/visualization_v2/nodes.py:129-194` to understand the current `_rule_based_decision` function. Then add a check: if `time_granularity` is in `AGGREGATE_PERIOD_GRANULARITIES`, prefer `bar_chart` instead of `line_chart`.

The function receives `profile` and `query_type` but likely NOT `time_granularity`. Check if `time_granularity` is available in the visualization state. If not, it needs to be threaded through.

**State threading check**: Read `src/graphs/report_agent/subagents/visualization_v2/state.py` and `src/graphs/report_agent/state.py` to see if `time_granularity` flows to the viz subgraph. If not, add it.

The approach: the simplest way is to check column names in the result data. If the x-axis column is `Saat` (from hour_of_day), `HaftaGunu` (from day_of_week), or `AyinGunu` (from day_of_month), and there's no `Tarih` column, this is an aggregate period result → bar chart.

**Alternative (preferred)**: Thread `time_granularity` through state to viz subgraph. This is more explicit and reliable than column name heuristics.

- [ ] **Step 6: Add `time_granularity` to ReportState**

In `src/graphs/report_agent/state.py`, add to ReportState (in the Text2SQL I/O section, after `pre_built_sql`):

```python
    time_granularity: Optional[str]      # text2sql → viz subgraph (hour_of_day, day_of_week, etc.)
```

Also add to `create_initial_state()`:
```python
    time_granularity=None,
```

- [ ] **Step 7: Add `time_granularity` to VisualizationState**

In `src/graphs/report_agent/subagents/visualization_v2/state.py`, add to VisualizationState (in the ReportState overlapping section):

```python
    time_granularity: Optional[str]       # from text2sql, for chart type decision
```

- [ ] **Step 8: Wire `time_granularity` from text2sql output**

In `src/graphs/report_agent/subagents/text2sql/nodes.py`, find where `sql_generator_node` returns its state dict. Add `time_granularity` to the return:

```python
# In sql_generator_node return dict, add:
"time_granularity": _time_gran,  # thread to viz layer
```

⚠️ The exact location depends on the node's return statement. Read the node to find the right place.

- [ ] **Step 9: Add aggregate period check to `viz_decider_node` (NOT `_rule_based_decision`)**

⚠️ `_rule_based_decision` signature is `(query_type: str, wants_viz: bool, profile: dict)` — it does NOT have access to state. Do NOT modify its signature. Instead, add the check in `viz_decider_node` BEFORE calling `_rule_based_decision`:

In `src/graphs/report_agent/subagents/visualization_v2/nodes.py`, in `viz_decider_node` (inside `create_viz_decider_node`), add BEFORE the `_rule_based_decision` call (~line 261):

```python
        # Aggregate period → bar chart (distribution, not trend)
        from src.graphs.report_agent.subagents.text2sql.nodes import AGGREGATE_PERIOD_GRANULARITIES
        _time_gran = state.get("time_granularity")
        if _time_gran and _time_gran in AGGREGATE_PERIOD_GRANULARITIES:
            logger.info(f"[V2:VIZ_DECIDER] Aggregate period: {_time_gran} → bar_chart")
            return {"viz_decision": {
                "needs_graph": True,
                "chart_type": "bar_chart",
                "x_field": None, "y_field": None, "series_field": None,
                "reason": f"Aggregate period distribution ({_time_gran})",
            }}
```

- [ ] **Step 10: Commit**

```bash
git add src/graphs/report_agent/state.py \
        src/graphs/report_agent/subagents/text2sql/nodes.py \
        src/graphs/report_agent/subagents/visualization_v2/nodes.py \
        src/graphs/report_agent/subagents/visualization_v2/state.py \
        tests/unit/test_aggregate_period_granularity.py
git commit -m "feat: thread time_granularity to viz layer, bar chart for aggregate periods"
```

---

### Task 6: Update Visualization V2 — Field Mapping Prompt

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/prompts.py:1-76` (VIZ_DECIDER_PROMPT)

- [ ] **Step 1: Add `{time_granularity}` format variable to VIZ_DECIDER_PROMPT**

First, add a new section to the prompt template between `## SORGU TIPI` and `## GRAFIK TALEBI`:

```
## ZAMAN GRANÜLARITESI
time_granularity: {time_granularity}
```

Then update the `viz_decider_node` in `nodes.py` to pass `time_granularity` when formatting the prompt:

```python
prompt = VIZ_DECIDER_PROMPT.format(
    user_query=effective_query,
    query_type=state.get("query_type", "SINGLE"),
    wants_visualization=wants_viz,
    time_granularity=state.get("time_granularity") or "N/A",  # NEW
    column_info=column_info,
    sample_rows=json.dumps(results[:3], ensure_ascii=False, indent=2),
    conversation_context=conversation_context,
)
```

- [ ] **Step 2: Add aggregate period field mapping guidance to VIZ_DECIDER_PROMPT**

In the field mapping section of the prompt, add:

```
📊 TOPLU DAĞILIM (Aggregate Period) Kuralları:
- time_granularity "hour_of_day" ise: x_field = "Saat", chart_type = "bar_chart"
- time_granularity "day_of_week" ise: x_field = "HaftaGunu", chart_type = "bar_chart"
- time_granularity "day_of_month" ise: x_field = "AyinGunu", chart_type = "bar_chart"
- Bu tiplerde Tarih kolonu OLMAZ — x ekseni periyod değeridir (0-23, 1-7, 1-31).
- Entity karşılaştırması varsa (CategoryName gibi) → series_field = entity kolon.
```

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/prompts.py \
        src/graphs/report_agent/subagents/visualization_v2/nodes.py
git commit -m "feat: add aggregate period field mapping guidance to viz prompt"
```

---

### Task 7: Update Intent Classification Prompt

**Files:**
- Modify: `src/graphs/report_agent/prompts.py` (intent classification rules)

- [ ] **Step 1: Read current intent classification prompt**

Read `src/graphs/report_agent/prompts.py` to find the query_type classification rules.

- [ ] **Step 2: Add aggregate period examples**

In the TIME_SERIES_COMPARISON section, add clarifying examples:

```
TIME_SERIES_COMPARISON ayrıca TOPLU DAĞILIM sorgularını da kapsar:
- "saate göre ciro dağılımı" → TIME_SERIES_COMPARISON (aggregate: hour_of_day)
- "haftanın günlerine göre satış" → TIME_SERIES_COMPARISON (aggregate: day_of_week)
- "ayın günlerine göre adet" → TIME_SERIES_COMPARISON (aggregate: day_of_month)

⚠️ FARK: "günlük satışlar" = TIME_SERIES (trend), "haftanın günlerine göre" = TIME_SERIES (dağılım)
  İkisi de TIME_SERIES_COMPARISON. Ayrım text2sql katmanında time_granularity ile yapılır.
```

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/prompts.py
git commit -m "feat: add aggregate period examples to intent classification prompt"
```

---

### Task 8: Clarification for Ambiguous Granularity

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py` (KURAL 4.8 ambiguity guidance)

This task adds LLM-level disambiguation guidance. The LLM should pick the most likely granularity based on context. True clarification (asking the user) is complex and deferred — instead, we make the LLM smarter about disambiguation.

- [ ] **Step 1: Add disambiguation rules to KURAL 4.8**

After the KRİTİK FARK section added in Task 4, add:

```
🔍 BELİRSİZLİK ÇÖZÜM KURALLARI:
Kullanıcı net belirtmezse, BAĞLAM'a göre karar ver:

1. "X göre" / "X'e göre" → TOPLU DAĞILIM (aggregate)
   - "saate göre" → hour_of_day
   - "güne göre" → day_of_week (haftanın günleri context'i varsa) veya daily
   - "aya göre" → monthly

2. "X'lik" / "X bazında" → ZAMAN SERİSİ (trend)
   - "saatlik" → hourly
   - "günlük" → daily
   - "haftalık" → weekly

3. "trend", "değişim", "seyir", "gelişim" kelimeleri varsa → ZAMAN SERİSİ
4. "dağılım", "oran", "yoğunluk", "yüzde" kelimeleri varsa → TOPLU DAĞILIM
5. Tarih aralığı kısa (1 gün) + "saate göre" → hour_of_day (kesin)
6. Tarih aralığı uzun (aylar) + "saate göre" → hour_of_day (günler toplanır)

VARSAYILAN: Belirsiz kalırsa, "X göre" → aggregate, "X'lik" → time-series
```

- [ ] **Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "feat: add disambiguation rules for aggregate vs time-series granularity"
```

---

## Chunk 3: Integration Testing and Verification

### Task 9: End-to-End Integration Test

**Files:**
- Create: `tests/integration/test_aggregate_period_e2e.py`

- [ ] **Step 1: Write integration test that simulates the full SQL generation pipeline**

```python
# tests/integration/test_aggregate_period_e2e.py
"""Integration tests for aggregate period granularity through sql_generator_node."""
import pytest


class TestAggregatePeriodSQLGeneration:
    """Test that aggregate period granularities produce correct SQL GROUP BY."""

    def _build_state(self, user_query: str, time_granularity: str, comparison_dimension=None):
        """Build minimal state dict for sql_generator_node testing."""
        raw_schema = {
            "description": "test",
            "select_columns": [],
            "filters": [],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": [],
            "time_granularity": time_granularity,
            "comparison_dimension": comparison_dimension,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        return {
            "query_type": "TIME_SERIES_COMPARISON",
            "user_query": user_query,
            "raw_schema": raw_schema,
            "term_filters": [],
            "auto_rules": [],
            "table_name": "MasterReportDocumentTable",
        }

    def test_hour_of_day_no_date_in_sql(self):
        """hour_of_day must produce SQL with only DATEPART(HOUR) in GROUP BY, no date."""
        from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        from datetime import date

        group_by = _TIME_GRAN_MAP["hour_of_day"]
        schema = {
            "select_columns": [],
            "filters": [{"column": "CategoryName", "operator": "=", "value": "ESPRESSO", "logical_operator": "AND"}],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": group_by,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        sql = generate_sql(schema, "MasterReportDocumentTable", [], date(2026, 3, 11))
        sql_upper = sql.upper()

        # MUST have DATEPART(HOUR
        assert "DATEPART(HOUR" in sql_upper
        # MUST NOT have CAST(DOCUMENTDATE AS DATE)
        assert "CAST(DOCUMENTDATE AS DATE)" not in sql_upper
        # MUST NOT have raw DocumentDate in GROUP BY
        assert "GROUP BY" in sql_upper

    def test_day_of_week_no_date_in_sql(self):
        """day_of_week must produce SQL with only DATEPART(DW) in GROUP BY."""
        from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        from datetime import date

        group_by = _TIME_GRAN_MAP["day_of_week"]
        schema = {
            "select_columns": [],
            "filters": [],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": group_by,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        sql = generate_sql(schema, "MasterReportDocumentTable", [], date(2026, 3, 11))
        sql_upper = sql.upper()

        assert "DATEPART(DW" in sql_upper
        assert "CAST(DOCUMENTDATE AS DATE)" not in sql_upper

    def test_day_of_month_no_date_in_sql(self):
        """day_of_month must produce SQL with only DATEPART(DAY) in GROUP BY."""
        from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        from datetime import date

        group_by = _TIME_GRAN_MAP["day_of_month"]
        schema = {
            "select_columns": [],
            "filters": [],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": group_by,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        sql = generate_sql(schema, "MasterReportDocumentTable", [], date(2026, 3, 11))
        sql_upper = sql.upper()

        assert "DATEPART(DAY" in sql_upper
        assert "CAST(DOCUMENTDATE AS DATE)" not in sql_upper
```

- [ ] **Step 2: Run integration tests**

```bash
python -m pytest tests/integration/test_aggregate_period_e2e.py -v
```

- [ ] **Step 3: Fix any failures, re-run**

- [ ] **Step 4: Run full test suite to verify no regressions**

```bash
python -m pytest tests/ -v --timeout=60
```

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_aggregate_period_e2e.py
git commit -m "test: add integration tests for aggregate period SQL generation"
```

---

### Task 10: Manual Verification with Original Query

- [ ] **Step 1: Verify the original failing query would now work**

The original query: `"son 3 ayda espresso kategorisindeki ciro oranlarını saate göre verir misin"`

Expected behavior after fix:
- Keyword detection: `"saate göre"` → `time_granularity = "hour_of_day"`
- `_TIME_GRAN_MAP["hour_of_day"]` → `["DATEPART(HOUR, DocumentDate)"]`
- GROUP BY: `DATEPART(HOUR, DocumentDate)` only (no date)
- Result: 24 rows (hours 0-23)
- Visualization: bar chart with Saat as x-axis

Expected SQL:
```sql
SELECT DATEPART(HOUR, DocumentDate) AS [Saat],
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [CategoryName] = 'ESPRESSO'
    AND [DocumentDate] >= DATEADD(MONTH, -3, '2026-03-11')
GROUP BY DATEPART(HOUR, DocumentDate)
ORDER BY DATEPART(HOUR, DocumentDate) ASC
```

- [ ] **Step 2: Verify existing hourly time-series still works**

Query: `"son 1 haftada saatlik satış trendi"`

Expected: `time_granularity = "hourly"` (NOT hour_of_day)
- GROUP BY: `CAST(DocumentDate AS DATE), DATEPART(HOUR, DocumentDate)`
- Chart: line chart (time series)

---

## Summary of Changes

| What | Where | Impact |
|------|-------|--------|
| 3 new granularity values | QuerySchema Literal | LLM can output new types |
| 3 new `_TIME_GRAN_MAP` entries | nodes.py:115 | SQL GROUP BY without date |
| 2 new `_EXPR_ALIAS_MAP` entries | sql_builder.py:27 | SELECT aliases: HaftaGunu, AyinGunu |
| Keyword detection helper | nodes.py (new function) | Fallback catches "saate göre" etc. |
| KURAL 4.8 + 5 prompt updates | prompts.py:323-389 | LLM learns the distinction |
| Disambiguation rules | prompts.py (KURAL 4.8) | LLM resolves ambiguity |
| `AGGREGATE_PERIOD_GRANULARITIES` set | nodes.py | Shared constant for viz layer |
| time_granularity in viz state | viz state + nodes | Bar chart for distributions |
| Viz field mapping guidance | viz prompts | Correct x_field for aggregate periods |
| Intent classification update | report_agent/prompts.py | Aggregate queries → TIME_SERIES_COMPARISON |
