# build_response_node Simplification

## Date: 2026-03-06

## Problem
`build_response_node` doesn't return actual query results to the user. It either returns a count string ("{N} sonuç bulundu") or the raw plotly HTML snippet.

## Design

### Behavior Matrix

| Condition | Response |
|-----------|----------|
| `use_result_type == "compute"` + `final_response` exists | Use existing `final_response` (no change) |
| `error` exists | `"Sorgu hatası: {error}"` (no change) |
| No results | `"Bu sorgu için sonuç bulunamadı."` (no change) |
| Graph generated (`viz.needs_graph` + `plotly_html_snippet`) | `"Grafiğiniz oluşturuldu."` |
| Results exist (no graph) | Markdown table of results (max 50 rows) |

### Markdown Table Format
- Headers from `results[0].keys()`
- Rows from result values
- Truncated at 50 rows with note: `*...ve {N} satır daha*`

### Files Changed
- `src/graphs/report_agent/nodes.py` — `build_response_node` function only

### Implementation
1. Add `_results_to_markdown_table(results, max_rows=50)` helper
2. Update `build_response_node` logic:
   - Graph case: return `"Grafiğiniz oluşturuldu."`
   - Results case: return markdown table
