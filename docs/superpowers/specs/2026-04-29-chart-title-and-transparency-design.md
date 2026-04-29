# Design: Chart Title Generation & Thinking-Step Transparency

**Date:** 2026-04-29
**Status:** Approved

## Problem

Two related gaps in the current chart response pipeline:

1. **Missing chart titles:** Rule-based and user-override paths in `viz_decider_node` return `ChartSpec` dicts without a `title` field. Most charts render with an empty title string. The `_insight_python` prefix in `response_builder.py` is also empty as a result.

2. **No transparency:** Users cannot see how a report was built — which filters were automatically applied, what period was covered, how data was aggregated — without reading backend logs. This prevents users from comparing chatbot-generated reports against static Excel/paper reports.

## Solution Overview

Two independent sub-features:

- **Sub-feature 1:** Synthesize a descriptive chart title in `spec_validator_node` when `title` is None.
- **Sub-feature 2:** New `transparency.py` module produces a structured `additional_kwargs["transparency"]` payload as a **step-by-step thinking trace** — each step translates a state field into plain business Turkish. Frontend renders steps sequentially with a "Tümünü Gör" summary at the end. Button-triggered, not in `AIMessage.content`.

## Sub-feature 1: Chart Title Synthesis

**Location:** `spec_validator_node` in `subagents/visualization_v2/nodes.py`

After validation, if `validated["title"]` is None or empty, synthesize deterministically:

```python
def _synthesize_title(user_query: str, spec: dict, column_metadata: dict) -> str:
    x_label = _get_label(spec.get("x_field"), column_metadata)
    y_label = _get_label(spec.get("y_field"), column_metadata)
    if x_label and y_label:
        return f"{x_label} Bazında {y_label}"
    if x_label:
        return f"{x_label} Analizi"
    return (user_query or "Rapor")[:60].rstrip()
```

`column_metadata` is already accessible via `config`. `_get_label` is imported from `chart_renderer.py`. Title propagates to the Plotly chart and to `visualization_output["title"]`, so `_insight_python` gets a non-empty prefix automatically.

## Sub-feature 2: Thinking-Step Transparency

### Output format

`AIMessage.additional_kwargs["transparency"]` contains:

```json
{
  "steps": [
    {
      "n": 1,
      "title": "Sorunuzu anladım",
      "detail": "Çok boyutlu sıralama raporu"
    },
    {
      "n": 2,
      "title": "Dönem belirlendi",
      "detail": "1 Ocak – 29 Nisan 2026"
    },
    {
      "n": 3,
      "title": "İş kuralları uygulandı",
      "rules": [
        "İptal ve iade siparişler dışlandı",
        "Sıfır tutarlı satırlar hariç tutuldu"
      ]
    },
    {
      "n": 4,
      "title": "Hesaplama yapıldı",
      "detail": "Kategori ve şubeye göre gruplandı, satış tutarı toplamı (ciro) alındı → 128 kayıt"
    },
    {
      "n": 5,
      "title": "Görselleştirildi",
      "detail": "Sunburst grafik seçildi"
    }
  ],
  "summary": "Kategori & şube bazında, 1 Oca – 29 Nis 2026, iptal/sıfır hariç, 128 kayıt, ciro toplamı → Sunburst"
}
```

Frontend renders steps ①②③④⑤ sequentially. "Tümünü Gör" expands to show `summary` (all details combined in one line). No developer layer — LangGraph trace handles that.

### User-facing rendering example

```
① Sorunuzu anladım
   "Kategoriye ve şubeye göre bu yılki satışları göster"
   → Çok boyutlu sıralama raporu

② Dönem belirlendi
   1 Ocak – 29 Nisan 2026

③ İş kuralları uygulandı
   ✓ İptal ve iade siparişler dışlandı
   ✓ Sıfır tutarlı satırlar hariç tutuldu

④ Hesaplama yapıldı
   Kategori ve şubeye göre gruplandı
   Satış tutarı toplamı (ciro) alındı → 128 kayıt

⑤ Görselleştirildi
   Sunburst grafik seçildi

─────────────────────────
Tümünü Gör: Kategori & şube, 1 Oca–29 Nis 2026, iptal/sıfır hariç, 128 kayıt, ciro → Sunburst
```

### Step-to-state mapping

| Step | State source | Fallback |
|------|-------------|----------|
| ① intent | `user_query` + `intent_type` + `query_type` | `"Sorgu analiz edildi"` |
| ② period | `active_sql` date regex / `semantic_intent` | `"Tüm dönem"` |
| ③ rules | `applied_business_rules` (new field) | step omitted if empty |
| ④ computation | `x_field` + `y_field` + `column_metadata` + `active_sql` agg regex | field labels only |
| ⑤ visualization | `viz_decision["chart_type"]` + human label | chart type label only |

### New state field (`state.py`)

```python
applied_business_rules: Optional[List[Dict]]
# Populated by: sql_generator_node
# Reset by: classify_intent_node (same pattern as pre_built_sql: None each turn)
# Each dict: {id, description, is_default, sql_filter}
```

### `sql_generator_node` change

After fetching rules from `BusinessRulesStore`, write to state:

```python
applied_rules = [
    {
        "id": r["id"],
        "description": r["metadata"].get("description", ""),
        "is_default": r.get("is_default", False),
        "sql_filter": r["metadata"].get("sql_filter") or None,
    }
    for r in rules_result.get("individual_rules", [])
]
return {..., "applied_business_rules": applied_rules}
```

### `transparency.py` — new module

```python
# src/graphs/report_agent/transparency.py

def build_transparency_payload(state: dict, column_metadata: dict = None) -> dict:
    """Build thinking-step transparency payload for additional_kwargs['transparency']."""
    steps = []
    steps.append(_step_intent(state))
    period_step = _step_period(state)
    if period_step:
        steps.append(period_step)
    rules_step = _step_rules(state)
    if rules_step:
        steps.append(rules_step)
    steps.append(_step_computation(state, column_metadata or {}))
    steps.append(_step_visualization(state))

    # Renumber after optional steps removed
    for i, step in enumerate(steps, 1):
        step["n"] = i

    return {
        "steps": steps,
        "summary": _build_summary(state, column_metadata or {}),
    }
```

Helper functions (all pure Python, no I/O):

- `_step_intent(state)` → `query_type` label + `user_query` excerpt
- `_step_period(state)` → date range from `active_sql` regex; returns None if no date found
- `_step_rules(state)` → `applied_business_rules` descriptions; returns None if empty
- `_step_computation(state, column_metadata)` → dimension labels + agg type from `active_sql` + row count
- `_step_visualization(state)` → chart type human label from `viz_decision`
- `_build_summary(state, column_metadata)` → single-line combined summary string

**Aggregation detection** (used in step ④):
```python
import re

_AGG_LABELS = {"SUM": "toplamı", "COUNT": "adedi", "AVG": "ortalaması",
               "MIN": "minimumu", "MAX": "maksimumu"}

def _detect_aggregation(sql: str, y_field: str) -> str:
    if not sql or not y_field:
        return "değeri"
    pattern = rf'(SUM|COUNT|AVG|MIN|MAX)\s*\(\s*{re.escape(y_field)}\s*\)'
    m = re.search(pattern, sql, re.IGNORECASE)
    return _AGG_LABELS.get(m.group(1).upper(), "değeri") if m else "değeri"
```

**Date range detection** (used in step ②):
```python
def _extract_period(sql: str) -> Optional[str]:
    # BETWEEN pattern
    m = re.search(
        r"BETWEEN\s+'(\d{4}-\d{2}-\d{2})'\s+AND\s+'(\d{4}-\d{2}-\d{2})'",
        sql, re.IGNORECASE
    )
    if m:
        return f"{_fmt_date(m.group(1))} – {_fmt_date(m.group(2))}"
    # YEAR() = pattern
    m = re.search(r"YEAR\s*\(\s*\w+\s*\)\s*=\s*(\d{4})", sql, re.IGNORECASE)
    if m:
        return f"{m.group(1)} yılı"
    return None  # → step omitted, summary shows "Tüm dönem"
```

### `create_build_response_node` change (`nodes.py`)

```python
from src.graphs.report_agent.transparency import build_transparency_payload

async def build_response_node(state: dict) -> dict:
    ...
    column_metadata = _get_column_metadata(state)   # already available via config
    summary_text = await build_chart_response(results, viz, user_query, DEFAULT_CONFIG, llm)
    transparency = build_transparency_payload(state, column_metadata)

    return {
        "messages": [AIMessage(
            content=summary_text,
            additional_kwargs={
                "chart_html": iframe,
                "transparency": transparency,
            },
        )]
    }
```

## Data Flow

```
sql_generator_node
  → applies business rules
  → state["applied_business_rules"] = [...]

classify_intent_node (each turn)
  → state["applied_business_rules"] = None   (reset)

spec_validator_node
  → if title is None → _synthesize_title(user_query, spec, column_metadata)
  → state["viz_decision"]["title"] = synthesized_title

create_build_response_node
  → build_chart_response(...)                → AIMessage.content  (insight + metadata)
  → build_transparency_payload(state, meta)  → AIMessage.additional_kwargs["transparency"]
        .steps  [①②③④⑤ — optional steps omitted if no data]
        .summary  "one-line combined summary"
```

## Error Handling

| Scenario | Behavior |
|---|---|
| `applied_business_rules` is None | Step ③ omitted entirely |
| No date in `active_sql` | Step ② omitted; summary shows "Tüm dönem" |
| `active_sql` is None | Agg detection returns `"değeri"`, period step omitted |
| `_synthesize_title` — no fields, no query | Returns `"Rapor"` |
| Any step function raises | Wrapped in try/except, step shows fallback text |
| `build_transparency_payload` raises | `create_build_response_node` catches, sets `transparency: {}` |

## Scope

**Create:**
- `src/graphs/report_agent/transparency.py`

**Modify:**
- `src/graphs/report_agent/state.py` — add `applied_business_rules`
- `src/graphs/report_agent/nodes.py` — import transparency, add to `additional_kwargs`
- `src/graphs/report_agent/subagents/text2sql/nodes.py` — populate `applied_business_rules`
- `src/graphs/report_agent/subagents/visualization_v2/nodes.py` — title synthesis in `spec_validator_node`

**No change:**
- `response_builder.py` — unchanged
- `chart_renderer.py` — already uses `spec.get("title") or ""`
- Frontend, API layer, other subgraphs

## Testing

**`transparency.py` unit tests:**
- Full state → all 5 steps present, correct content
- No rules → step ③ absent, step numbers resequenced
- No date in SQL → step ② absent
- Empty state `{}` → no exception, minimal steps with fallbacks
- `_detect_aggregation` → SUM/COUNT/AVG patterns matched correctly
- `_extract_period` → BETWEEN and YEAR() patterns extracted correctly
- Summary string → single line combining all available info

**Title synthesis:**
- `x + y + metadata` → `"Şube Bazında Satış Tutarı"`
- `x` only → `"Şube Analizi"`
- Neither, query present → `user_query[:60]`
- Title already set → not overwritten

**`create_build_response_node` integration:**
- `additional_kwargs["transparency"]["steps"]` is a list
- `additional_kwargs["transparency"]["summary"]` is a string
- `AIMessage.content` contains no transparency text
