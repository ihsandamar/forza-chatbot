# Design: Plotly Chart Embeddable via srcdoc

**Date:** 2026-04-29  
**Status:** Approved

## Problem

Backend generates Plotly charts wrapped in `<iframe src="data:text/html;base64,...">`. Vue frontend renders this via `v-html`. The iframe has `height: 100vh` hardcoded, causing the chart to overflow its container and appear broken when embedded in a page element.

## Solution

Replace the base64 + `src` approach with `srcdoc` + fixed height. Only `nodes.py: build_response_node` changes — no frontend, no other backend files.

## Design

### What changes

**File:** `src/graphs/report_agent/nodes.py`  
**Function:** `build_response_node` (lines ~552–565)

**Before:**
```python
import base64
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

**After:**
```python
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

### Key decisions

- **`srcdoc` vs base64**: `srcdoc` is native HTML — no encoding overhead, browser parses it directly.
- **HTML entity escaping**: `&` → `&amp;`, `"` → `&quot;` so the attribute value is valid. `<`/`>` do not need escaping inside a double-quoted attribute.
- **Height**: `480px` for all charts; `600px` for `turkey_map` (choropleth needs more vertical space).
- **Inner CSS**: `.plotly-graph-div` forced to `100% × 100%` so the chart fills the iframe instead of using Plotly's default fixed pixel size.
- **`import base64` removal**: The import is inside the function block and can be removed.

### What does NOT change

- `chart_renderer.py`: `fig.to_html(include_plotlyjs="cdn", full_html=False)` stays as-is.
- `chat_service.py`: still extracts `chart_html` from `additional_kwargs` as before.
- `visualization_v2/nodes.py`: no changes.
- Frontend: no changes.

## Scope

Single function edit, ~10 lines. No new files, no schema changes, no test changes needed (existing tests mock `visualization_output`, not the iframe string).
