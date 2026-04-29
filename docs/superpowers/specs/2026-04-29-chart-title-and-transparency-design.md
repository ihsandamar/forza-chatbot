# Design: Chart Title Generation & Two-Layer Transparency System

**Date:** 2026-04-29
**Status:** Approved

## Problem

Two related gaps in the current chart response pipeline:

1. **Missing chart titles:** Rule-based and user-override paths in `viz_decider_node` return `ChartSpec` dicts without a `title` field. Most charts render with an empty title string. The `_insight_python` prefix in `response_builder.py` is also empty as a result.

2. **No transparency:** Users cannot see which business rule filters were automatically applied, what SQL was generated, or why a result looks unexpected — without reading backend logs. There is no developer-accessible debug surface either.

## Solution Overview

Two independent sub-features sharing one new module:

- **Sub-feature 1:** Synthesize a descriptive title at `spec_validator_node` when `title` is None.
- **Sub-feature 2:** New `transparency.py` module produces a structured `additional_kwargs["transparency"]` payload with `user` and `debug` sub-sections. Both layers are button-triggered on the frontend — neither pollutes `AIMessage.content`.

## Architecture

### Sub-feature 1: Title Synthesis

**Location:** `spec_validator_node` in `subagents/visualization_v2/nodes.py`

After validation completes, if `validated["title"]` is None or empty:

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

`_get_label` is the existing helper in `chart_renderer.py` — import or duplicate in nodes.py. `column_metadata` is already accessible via `config` in `spec_validator_node`. Title propagates to Plotly chart and to `visualization_output["title"]`, which means `_insight_python` in `response_builder.py` gets a non-empty prefix automatically.

### Sub-feature 2: Transparency Module

**New file:** `src/graphs/report_agent/transparency.py`

Single public function:

```python
def build_transparency_payload(state: dict) -> dict:
    """Build structured transparency payload for additional_kwargs["transparency"]."""
    applied_rules = state.get("applied_business_rules") or []
    results = state.get("results") or []
    row_count = len(results)

    user_section = {
        "applied_rules": [
            {
                "description": r.get("description", ""),
                "is_default": r.get("is_default", False),
            }
            for r in applied_rules
        ],
        "row_count": row_count,
    }

    debug_section = {
        "sql": state.get("active_sql"),
        "intent_type": state.get("intent_type"),
        "query_type": state.get("query_type"),
        "applied_rules": applied_rules,
        "row_count": row_count,
        "error": state.get("error"),
    }

    return {"user": user_section, "debug": debug_section}
```

No LLM, no I/O — pure dict assembly from state.

### State Change (`state.py`)

Add one field:

```python
applied_business_rules: Optional[List[Dict]]
# Populated by: sql_generator_node
# Reset by: classify_intent_node (same pattern as pre_built_sql)
# Each dict: {id, description, is_default, sql_filter}
```

### `sql_generator_node` change (`subagents/text2sql/nodes.py`)

After business rules are fetched and merged, write to state:

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
return {
    ...,
    "applied_business_rules": applied_rules,
}
```

### `create_build_response_node` change (`nodes.py`)

```python
from src.graphs.report_agent.transparency import build_transparency_payload

async def build_response_node(state: dict) -> dict:
    ...
    summary_text = await build_chart_response(results, viz, user_query, DEFAULT_CONFIG, llm)
    transparency = build_transparency_payload(state)
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

### `response_builder.py` — no structural change

`build_chart_response` signature stays the same (no `applied_rules` param added). The `show_user_transparency` field is NOT added to `ResponseConfig` — transparency is always computed by `transparency.py`, and `AIMessage.content` stays clean.

## Data Flow

```
sql_generator_node
  → fetches business rules via BusinessRulesStore
  → state["applied_business_rules"] = [{id, description, is_default, sql_filter}, ...]

classify_intent_node (each turn)
  → state["applied_business_rules"] = None   (reset)

spec_validator_node
  → validates ChartSpec
  → if title is None → _synthesize_title(user_query, spec, column_metadata)
  → state["viz_decision"]["title"] = synthesized_title

create_build_response_node
  → build_chart_response(...)          → AIMessage.content (insight + metadata, unchanged)
  → build_transparency_payload(state)  → AIMessage.additional_kwargs["transparency"]
                                           .user  { applied_rules[], row_count }
                                           .debug { sql, intent_type, query_type, applied_rules[], row_count, error }
```

## Output Example

**`AIMessage.content`** (unchanged structure):
```
Şube Bazında Satış Tutarı: Ankara en yüksek değerde (2,400,000). 64 kayıt analiz edildi.
Çubuk Grafik · 64 kayıt
```

**`AIMessage.additional_kwargs["transparency"]`**:
```json
{
  "user": {
    "applied_rules": [
      {"description": "İptal satışlar dışlandı", "is_default": true},
      {"description": "Sıfır miktarlar hariç", "is_default": true}
    ],
    "row_count": 64
  },
  "debug": {
    "sql": "SELECT BranchName, SUM(RowAmount) FROM MasterReportDocumentTable WHERE ...",
    "intent_type": "NEW_QUERY",
    "query_type": "RANKING",
    "applied_rules": [...],
    "row_count": 64,
    "error": null
  }
}
```

Frontend renders a single transparency button per message when `transparency` key exists. Button reveals a panel with two tabs/sections (user-friendly + developer detail). Backend has no responsibility for rendering.

## Error Handling

| Scenario | Behavior |
|---|---|
| `applied_business_rules` is None | `build_transparency_payload` uses `[]`, user section shows empty rules list |
| `sql_generator_node` fails to fetch rules | `applied_business_rules: []` written, silently no rules shown |
| `_synthesize_title` — column_metadata missing | Falls back to `user_query[:60]` |
| `_synthesize_title` — both fields None, no query | Returns `"Rapor"` |
| `build_transparency_payload` — any state field missing | `dict.get()` returns None, payload is partial, no exception |

## Scope

**Create:**
- `src/graphs/report_agent/transparency.py`

**Modify:**
- `src/graphs/report_agent/state.py` — add `applied_business_rules`
- `src/graphs/report_agent/nodes.py` — import transparency, add payload to `additional_kwargs`
- `src/graphs/report_agent/subagents/text2sql/nodes.py` — populate `applied_business_rules`
- `src/graphs/report_agent/subagents/visualization_v2/nodes.py` — title synthesis in `spec_validator_node`

**No change:**
- `response_builder.py` — signature and `ResponseConfig` unchanged
- `chart_renderer.py` — already uses `spec.get("title") or ""`
- Frontend, API layer, other subgraphs

## Testing

**`transparency.py` unit tests:**
- `build_transparency_payload(state_with_rules)` → correct structure, correct rule count
- `build_transparency_payload({})` → no exception, null fields tolerated
- `build_transparency_payload(state_no_rules)` → `user.applied_rules == []`

**`spec_validator_node` title synthesis:**
- `x_field + y_field + column_metadata` → `"Şube Bazında Tutar"`
- `x_field` only → `"Şube Analizi"`
- Neither field, query present → `user_query[:60]`
- Title already set → not overwritten

**`create_build_response_node` integration:**
- `AIMessage.additional_kwargs` has `"transparency"` key
- `AIMessage.additional_kwargs["transparency"]["user"]` has `applied_rules` and `row_count`
- `AIMessage.additional_kwargs["transparency"]["debug"]` has `sql` and `intent_type`
- `AIMessage.content` does NOT contain transparency text (clean separation)
