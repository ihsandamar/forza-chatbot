# Design: Section-Based Chart Response Builder

**Date:** 2026-04-29  
**Status:** Approved

## Problem

After a chart is generated, the chat message shown to the user (`AIMessage.content` / API `text` field) is a hardcoded technical metadata block:

```
📊 Rapor Sonucu:
• Görselleştirme Tipi: sunburst
• Grafik Gerekli: ✓ Evet
• Veri Noktası: 64
• 64 kayıt
📈 Grafik oluşturuldu.
```

This is robotic, uninformative, and bloats LLM context on subsequent turns. The user wants a meaningful, natural-language response that can optionally include a data insight (LLM-generated or deterministic) plus compact metadata.

## Solution

Extract response assembly into a dedicated `response_builder.py` module with a section-based architecture. Each section is independently togglable. The insight section supports two strategies (LLM or Python) controlled via an env var. `build_response_node` becomes a factory function to support optional LLM injection.

## Architecture

### New File: `src/graphs/report_agent/response_builder.py`

Single responsibility: assemble the chat message text for chart responses. No graph knowledge, no state management.

**`ResponseConfig` dataclass:**
```python
@dataclass
class ResponseConfig:
    insight_mode: Literal["llm", "python", "off"] = "python"
    show_metadata: bool = True
```

Loaded once at module level from env vars:
```python
DEFAULT_CONFIG = ResponseConfig(
    insight_mode=os.getenv("CHART_INSIGHT_MODE", "python"),
    show_metadata=os.getenv("CHART_SHOW_METADATA", "true").lower() != "false",
)
```

**`async def build_chart_response(results, viz, user_query, config, llm=None) → str`**  
Main entry point. Async because `_insight_llm` is async; in Python/off modes no I/O occurs. Assembles sections in order: insight (if enabled), metadata (if enabled). Returns a single string.

**`_insight_python(results, viz) → str`** — Pure Python, no I/O:
- Reads `viz["x_field"]`, `viz["y_field"]`, `viz.get("title", "")`
- Finds the top entry by y_field value (max)
- Formats: `"{title}: {top_label} en yüksek değerde ({top_val:,.0f}). {n} kayıt analiz edildi."`
- Falls back to `"{title} — {n} kayıt analiz edildi."` on any error

**`_insight_llm(results, viz, user_query, llm) → str`** — Async, requires LLM:
- Sends `results[:10]` (capped to avoid token bloat) + `user_query` + chart info to GPT-4.1-mini
- Prompt: Turkish, 1-2 sentence insight, no preamble
- Returns the LLM response string

**`_metadata_section(viz, row_count) → str`** — Pure Python:
- Returns compact one-liner: `"{chart_type} · {row_count} kayıt"`
- Uses human-readable chart type names (e.g. `"sunburst"` → `"Sunburst"`)

**Adding a new section in the future:** add a function + a field to `ResponseConfig`. `build_chart_response` calls it conditionally. No other files change.

### Modified: `src/graphs/report_agent/nodes.py`

**`build_response_node` → `create_build_response_node(llm=None)`**  

Follows the existing `create_compute_results_node(llm)` factory pattern already in the codebase.

```python
def create_build_response_node(llm=None):
    async def build_response_node(state: dict) -> dict:
        ...
        summary_text = await build_chart_response(
            results, viz, state.get("user_query", ""), DEFAULT_CONFIG, llm
        )
        ...
    return build_response_node
```

The hardcoded emoji `summary_text` block is deleted entirely.

The `llm` parameter is `None` when `insight_mode == "python"` or `"off"`. In LLM mode, the caller (graph assembly) passes the shared LLM instance.

### Modified: `src/graphs/report_agent/graph.py`

Line 22 import changes from `build_response_node` → `create_build_response_node`.  
Line 102 node registration changes from:
```python
graph.add_node("build_response", build_response_node)
```
to:
```python
graph.add_node("build_response", create_build_response_node(llm))
```

`llm` is the same instance already passed to all other factory nodes on lines 95–99. The env var `CHART_INSIGHT_MODE` controls which strategy actually runs at runtime — LLM injection is always done, the config flag decides if it's called.

## Data Flow

```
build_response_node(state)
  → build_chart_response(results, viz, user_query, config, llm)
      → _insight_python(results, viz)          # if mode == "python"
      → await _insight_llm(..., llm)           # if mode == "llm"
      → _metadata_section(viz, row_count)      # if show_metadata
  → AIMessage(content=summary_text, additional_kwargs={"chart_html": iframe})
```

## Example Output

**Python mode, metadata on:**
```
Kategori & Şube Dağılımı: Ankara en yüksek değerde (2,400,000). 64 kayıt analiz edildi.
sunburst · 64 kayıt
```

**LLM mode, metadata on:**
```
Ankara şubesi Elektronik kategorisinde öne çıkıyor. Batı bölgelerinde satışlar Doğu'ya kıyasla %34 daha yüksek.
sunburst · 64 kayıt
```

**Python mode, metadata off:**
```
Kategori & Şube Dağılımı: Ankara en yüksek değerde (2,400,000). 64 kayıt analiz edildi.
```

## Scope

- **Create:** `src/graphs/report_agent/response_builder.py`
- **Modify:** `src/graphs/report_agent/nodes.py` — replace hardcoded block, factory-ify `build_response_node`
- **Modify:** `src/graphs/report_agent/graph.py` — update import + node registration to `create_build_response_node(llm)`
- **No changes:** visualization_v2 subagraph, state definitions, frontend, API layer

## Error Handling

- LLM failure in insight → fall back to Python mode output silently (no exception propagates)
- Missing `x_field`/`y_field` in Python mode → fall back to `"{n} kayıt analiz edildi."`
- Empty results → `"Sonuç bulunamadı."` (unchanged from current behavior)

## Testing

- `response_builder.py` tested in isolation: each section function independently
- `build_chart_response` tested with both modes
- `create_build_response_node` tested: verifies `AIMessage.content` uses new format, not old hardcoded text
