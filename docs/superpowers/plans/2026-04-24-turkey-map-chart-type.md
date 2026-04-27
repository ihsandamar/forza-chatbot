# Turkey Province Choropleth Map Chart Type — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `turkey_map` chart type that colors Turkish provinces on a map by metric value, auto-selected when the query result has exactly one city dimension, no time axis, and no explicit chart type requested by the user.

**Architecture:** The `turkey_map` type follows the existing Visualization V2 extension pattern — registered in `ChartSpec` and `IntentClassificationResult`, implemented as `_build_turkey_map` in `chart_renderer.py`, validated in `validator.py`, and auto-selected via a rule in `_rule_based_decision`. City column detection is isolated in a new `turkey_geo.py` utility module. Rendering uses `plotly.express.choropleth` with a bundled Turkey provinces GeoJSON file loaded at render time.

**Tech Stack:** Plotly Express (choropleth), Python pathlib, unicodedata (stdlib), pytest, unittest.mock

---

## File Map

| File | Action | What Changes |
|------|--------|--------------|
| `src/graphs/report_agent/subagents/visualization_v2/models.py` | Modify | Add `"turkey_map"` to `ChartSpec.chart_type` Literal |
| `src/graphs/report_agent/prompts.py` | Modify | Add `"turkey_map"` to `IntentClassificationResult.chart_type` Literal |
| `src/graphs/report_agent/subagents/visualization_v2/turkey_geo.py` | **Create** | `detect_city_column()`, `load_turkey_geojson()`, `normalize_city_name()` |
| `src/graphs/report_agent/subagents/visualization_v2/assets/turkey_provinces.geojson` | **Create** | Downloaded Turkey province boundaries — `properties.name` = province name |
| `src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py` | Modify | Add `_build_turkey_map()` + register in `_BUILDERS` |
| `src/graphs/report_agent/subagents/visualization_v2/validator.py` | Modify | Add Rule 3 case for `turkey_map` |
| `src/graphs/report_agent/subagents/visualization_v2/nodes.py` | Modify | Add turkey_map rule in `_rule_based_decision` |
| `src/graphs/report_agent/subagents/visualization_v2/prompts.py` | Modify | Add `turkey_map` to chart_type selection guidance |
| `tests/test_visualization_v2/test_turkey_geo.py` | **Create** | Tests for `detect_city_column` and `normalize_city_name` |
| `tests/test_visualization_v2/test_chart_renderer.py` | Modify | Add `turkey_map` renderer test (mocks GeoJSON loader) |
| `tests/test_viz_decider_fast_path.py` | Modify | Add city-dimension auto-selection rule test |

---

## Task 1: Schema Registration + City Detection Utility

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/models.py:16-21`
- Modify: `src/graphs/report_agent/prompts.py:17-20`
- Create: `src/graphs/report_agent/subagents/visualization_v2/turkey_geo.py`
- Create: `tests/test_visualization_v2/test_turkey_geo.py`

---

- [ ] **Step 1: Write failing tests for `turkey_geo.py`**

Create `tests/test_visualization_v2/test_turkey_geo.py`:

```python
"""Tests for Turkey map utility functions."""


def test_detect_city_column_finds_branchcityname():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column(["BranchCityName", "RowAmount"]) == "BranchCityName"


def test_detect_city_column_finds_sehir():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column(["SehirAdi", "Tutar"]) == "SehirAdi"


def test_detect_city_column_finds_cityname():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column(["CityName", "Revenue"]) == "CityName"


def test_detect_city_column_returns_none_for_no_city():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column(["BranchName", "ProductName", "RowAmount"]) is None


def test_detect_city_column_returns_none_for_empty():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column([]) is None


def test_normalize_city_name_strips_turkish_diacritics():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import normalize_city_name
    assert normalize_city_name("İstanbul") == "istanbul"
    assert normalize_city_name("Şanlıurfa") == "sanliurfa"
    assert normalize_city_name("Muğla") == "mugla"


def test_normalize_city_name_lowercases():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import normalize_city_name
    assert normalize_city_name("ANKARA") == "ankara"
    assert normalize_city_name("Ankara") == "ankara"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_visualization_v2/test_turkey_geo.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `turkey_geo` does not exist yet.

- [ ] **Step 3: Create `turkey_geo.py`**

Create `src/graphs/report_agent/subagents/visualization_v2/turkey_geo.py`:

```python
"""
Turkey province map utilities.

Provides city column detection and GeoJSON asset loading for
the turkey_map chart type.
"""
import pathlib
import unicodedata
from typing import List, Optional

_ASSET_DIR = pathlib.Path(__file__).parent / "assets"
TURKEY_GEOJSON_PATH = _ASSET_DIR / "turkey_provinces.geojson"

# Column name fragments (lowercased, stripped of _ and space) that indicate a city dimension
_CITY_HINTS = frozenset({
    "city", "cityname", "sehir", "sehiradi",
    "branchcity", "branchcityname", "iladi", "il",
})


def detect_city_column(dim_cols: List[str]) -> Optional[str]:
    """
    Return the first column in dim_cols that looks like a Turkish city dimension.
    Returns None if no match.
    """
    for col in dim_cols:
        normalized = col.lower().replace("_", "").replace(" ", "")
        if normalized in _CITY_HINTS or "city" in normalized or "sehir" in normalized:
            return col
    return None


def normalize_city_name(name: str) -> str:
    """
    Lowercase + strip Turkish/Latin diacritics for fuzzy name matching.
    Example: 'İstanbul' → 'istanbul', 'Şanlıurfa' → 'sanliurfa'
    """
    nfkd = unicodedata.normalize("NFKD", name.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def load_turkey_geojson() -> Optional[dict]:
    """
    Load Turkey provinces GeoJSON from the bundled asset file.
    Returns None if the asset file does not exist (renderer falls back gracefully).
    """
    if not TURKEY_GEOJSON_PATH.exists():
        return None
    import json
    with open(TURKEY_GEOJSON_PATH, encoding="utf-8") as f:
        return json.load(f)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_visualization_v2/test_turkey_geo.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 5: Add `"turkey_map"` to `ChartSpec` Literal**

Read `src/graphs/report_agent/subagents/visualization_v2/models.py` first, then edit lines 16-21:

```python
    chart_type: Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "single_value", "simple_list", "table",
        "comparison", "sunburst", "treemap",
        "heatmap", "turkey_map",
    ]
```

- [ ] **Step 6: Add `"turkey_map"` to `IntentClassificationResult.chart_type` Literal**

Read `src/graphs/report_agent/prompts.py` first, then edit lines 17-20:

```python
    chart_type: Optional[Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "heatmap", "sunburst", "treemap", "comparison", "turkey_map",
    ]] = None
```

- [ ] **Step 7: Commit Task 1**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/turkey_geo.py \
        src/graphs/report_agent/subagents/visualization_v2/models.py \
        src/graphs/report_agent/prompts.py \
        tests/test_visualization_v2/test_turkey_geo.py
git commit -m "feat(viz): add turkey_map type + turkey_geo utility module"
```

---

## Task 2: GeoJSON Asset + Renderer + Validator Rule

**Files:**
- Create: `src/graphs/report_agent/subagents/visualization_v2/assets/turkey_provinces.geojson`
- Modify: `src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py` (after line 306, before line 309)
- Modify: `src/graphs/report_agent/subagents/visualization_v2/validator.py` (after line 162)
- Modify: `tests/test_visualization_v2/test_chart_renderer.py` (append)

---

- [ ] **Step 1: Write failing renderer test**

Read `tests/test_visualization_v2/test_chart_renderer.py` to find the end of the file, then append:

```python
def test_turkey_map_renders_with_mock_geojson(monkeypatch):
    """turkey_map renders choropleth HTML when GeoJSON is available."""
    from unittest.mock import patch
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    _MINIMAL_GEOJSON = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[28.0, 41.0], [29.0, 41.0], [29.0, 42.0], [28.0, 42.0], [28.0, 41.0]]]
                },
                "properties": {"name": "İstanbul"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[32.0, 39.0], [33.0, 39.0], [33.0, 40.0], [32.0, 40.0], [32.0, 39.0]]]
                },
                "properties": {"name": "Ankara"},
            },
        ],
    }

    results = [
        {"BranchCityName": "Istanbul", "TotalSales": 50000},
        {"BranchCityName": "Ankara", "TotalSales": 35000},
    ]
    spec = {
        "chart_type": "turkey_map",
        "x_field": "BranchCityName",
        "y_field": "TotalSales",
        "title": "İl Bazında Satışlar",
    }

    with patch(
        "src.graphs.report_agent.subagents.visualization_v2.turkey_geo.load_turkey_geojson",
        return_value=_MINIMAL_GEOJSON,
    ):
        html = render_chart(spec, results, {})

    assert html is not None
    assert "plotly" in html.lower()


def test_turkey_map_returns_none_when_no_geojson(monkeypatch):
    """turkey_map returns None gracefully when GeoJSON asset is missing."""
    from unittest.mock import patch
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    results = [{"BranchCityName": "Istanbul", "TotalSales": 50000}]
    spec = {
        "chart_type": "turkey_map",
        "x_field": "BranchCityName",
        "y_field": "TotalSales",
    }

    with patch(
        "src.graphs.report_agent.subagents.visualization_v2.turkey_geo.load_turkey_geojson",
        return_value=None,
    ):
        html = render_chart(spec, results, {})

    assert html is None


def test_turkey_map_returns_none_when_x_field_missing():
    """turkey_map returns None when spec has no x_field."""
    from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart

    results = [{"BranchCityName": "Istanbul", "TotalSales": 50000}]
    spec = {"chart_type": "turkey_map", "x_field": None, "y_field": "TotalSales"}
    html = render_chart(spec, results, {})
    assert html is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_visualization_v2/test_chart_renderer.py::test_turkey_map_renders_with_mock_geojson tests/test_visualization_v2/test_chart_renderer.py::test_turkey_map_returns_none_when_no_geojson tests/test_visualization_v2/test_chart_renderer.py::test_turkey_map_returns_none_when_x_field_missing -v
```

Expected: FAIL — `turkey_map` not in `_BUILDERS`.

- [ ] **Step 3: Download Turkey provinces GeoJSON asset**

Create the assets directory and download the GeoJSON:

```bash
mkdir -p src/graphs/report_agent/subagents/visualization_v2/assets
curl -L "https://raw.githubusercontent.com/cihadturhan/tr-geojson/master/geo/tr-cities-utf8.json" \
     -o "src/graphs/report_agent/subagents/visualization_v2/assets/turkey_provinces.geojson"
```

Verify the file downloaded correctly and has a `properties.name` key:

```bash
python -c "
import json
with open('src/graphs/report_agent/subagents/visualization_v2/assets/turkey_provinces.geojson') as f:
    gj = json.load(f)
print('Features:', len(gj['features']))
print('First name:', gj['features'][0]['properties'].get('name'))
"
```

Expected output: `Features: 81` and a Turkish province name.

> **Note:** If the download fails or the `name` property key differs, check the GeoJSON structure and update `featureidkey="properties.name"` in `_build_turkey_map` to match the actual key.

- [ ] **Step 4: Implement `_build_turkey_map` in `chart_renderer.py`**

Read `src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py` first. Then insert the following function after `_build_heatmap` (currently ending at line 306) and before the `_BUILDERS` dict (currently line 309):

```python
def _build_turkey_map(df: pd.DataFrame, spec: dict) -> go.Figure:
    """
    Render a Turkey province choropleth map.

    Expects:
        x_field: city/province column (dimension)
        y_field: metric column (color intensity)
    """
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import (
        load_turkey_geojson,
        normalize_city_name,
    )

    x = spec.get("x_field")
    y = spec.get("y_field")
    title = spec.get("title") or ""

    if not x or not y or x not in df.columns or y not in df.columns:
        return None

    geojson = load_turkey_geojson()
    if geojson is None:
        return None

    # Build lookup: normalized GeoJSON province name → original GeoJSON name
    name_lookup: dict = {}
    for feature in geojson.get("features", []):
        original = feature.get("properties", {}).get("name", "")
        if original:
            name_lookup[normalize_city_name(original)] = original

    df = df.copy()
    df["_geo_loc"] = df[x].apply(
        lambda v: name_lookup.get(normalize_city_name(str(v))) if v else None
    )
    df_mapped = df.dropna(subset=["_geo_loc"])

    if df_mapped.empty:
        return None

    fig = px.choropleth(
        df_mapped,
        geojson=geojson,
        locations="_geo_loc",
        featureidkey="properties.name",
        color=y,
        hover_name=x,
        color_continuous_scale="Blues",
        title=title,
    )
    fig.update_geos(fitbounds="locations", visible=False)
    return fig
```

Then add `"turkey_map": _build_turkey_map` to the `_BUILDERS` dict (currently lines 309-319):

```python
_BUILDERS = {
    "bar_chart": _build_bar,
    "line_chart": _build_line,
    "pie_chart": _build_pie,
    "scatter_chart": _build_scatter,
    "scatter": _build_scatter,
    "sunburst": _build_sunburst,
    "treemap": _build_treemap,
    "comparison": _build_comparison,
    "heatmap": _build_heatmap,
    "turkey_map": _build_turkey_map,
}
```

- [ ] **Step 5: Run renderer tests to verify they pass**

```
pytest tests/test_visualization_v2/test_chart_renderer.py -v
```

Expected: All tests PASS including the 3 new turkey_map tests.

- [ ] **Step 6: Add validator Rule 3 case for `turkey_map`**

Read `src/graphs/report_agent/subagents/visualization_v2/validator.py` first. Then insert after line 162 (after the `heatmap` Rule 3 block), before `# Rule 5`:

```python
    if chart_type == "turkey_map":
        if not spec.get("x_field") or not spec.get("y_field"):
            spec["chart_type"] = "bar_chart"
            logger.info("[VALIDATOR] Rule 3: turkey_map missing x/y field -> bar_chart")
```

- [ ] **Step 7: Commit Task 2**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/chart_renderer.py \
        src/graphs/report_agent/subagents/visualization_v2/validator.py \
        src/graphs/report_agent/subagents/visualization_v2/assets/turkey_provinces.geojson \
        tests/test_visualization_v2/test_chart_renderer.py
git commit -m "feat(viz): add turkey_map renderer with choropleth + validator rule"
```

---

## Task 3: Auto-Selection Rule + Prompt Update

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py` (inside `_rule_based_decision`, after line 215)
- Modify: `src/graphs/report_agent/subagents/visualization_v2/prompts.py` (after line 72)
- Modify: `tests/test_viz_decider_fast_path.py` (append)

**Auto-selection condition:**
- Only city dimension in data (no other dim columns)
- No time column in data
- No time granularity set
- At least one metric column
- `wants_viz=True`

---

- [ ] **Step 1: Write failing rule-based selection test**

Read `tests/test_viz_decider_fast_path.py` to see current structure, then append:

```python
def test_city_dimension_no_time_gets_turkey_map():
    """Single city dimension + no time + no granularity → turkey_map auto-selected."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

    profile = {
        "row_count": 10,
        "dimension_columns": ["BranchCityName"],
        "metric_columns": ["TotalSales"],
        "time_column": None,
    }
    decision = _rule_based_decision(
        "RANKING", wants_viz=True, profile=profile,
        time_granularity=None, comparison_dimension=None,
    )
    assert decision is not None
    assert decision["chart_type"] == "turkey_map"
    assert decision["x_field"] == "BranchCityName"
    assert decision["needs_graph"] is True


def test_city_dimension_with_time_does_not_get_turkey_map():
    """City dimension + time column → does NOT auto-select turkey_map (falls through to line_chart)."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

    profile = {
        "row_count": 10,
        "dimension_columns": ["BranchCityName"],
        "metric_columns": ["TotalSales"],
        "time_column": "DocumentDate",
    }
    decision = _rule_based_decision(
        "TIME_SERIES_COMPARISON", wants_viz=True, profile=profile,
        time_granularity=None, comparison_dimension="BranchCityName",
    )
    assert decision is None or decision["chart_type"] != "turkey_map"


def test_city_dimension_with_other_dims_does_not_get_turkey_map():
    """City + other dimension → does NOT auto-select turkey_map (multiple dims = sunburst/bar)."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

    profile = {
        "row_count": 10,
        "dimension_columns": ["BranchCityName", "CategoryName"],
        "metric_columns": ["TotalSales"],
        "time_column": None,
    }
    decision = _rule_based_decision(
        "RANKING", wants_viz=True, profile=profile,
        time_granularity=None, comparison_dimension=None,
    )
    assert decision is None or decision["chart_type"] != "turkey_map"


def test_non_city_single_dimension_does_not_get_turkey_map():
    """BranchName alone (no city hints) → does NOT get turkey_map."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision

    profile = {
        "row_count": 5,
        "dimension_columns": ["BranchName"],
        "metric_columns": ["TotalSales"],
        "time_column": None,
    }
    decision = _rule_based_decision(
        "RANKING", wants_viz=True, profile=profile,
        time_granularity=None, comparison_dimension=None,
    )
    assert decision is not None
    assert decision["chart_type"] != "turkey_map"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_viz_decider_fast_path.py::test_city_dimension_no_time_gets_turkey_map tests/test_viz_decider_fast_path.py::test_city_dimension_with_time_does_not_get_turkey_map tests/test_viz_decider_fast_path.py::test_city_dimension_with_other_dims_does_not_get_turkey_map tests/test_viz_decider_fast_path.py::test_non_city_single_dimension_does_not_get_turkey_map -v
```

Expected: `test_city_dimension_no_time_gets_turkey_map` FAILS (returns bar_chart), others may pass.

- [ ] **Step 3: Add `detect_city_column` import to `nodes.py`**

Read `src/graphs/report_agent/subagents/visualization_v2/nodes.py` first. Add to the existing import block at the top (after the existing `from src.graphs.report_agent.subagents...` imports):

```python
from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
```

- [ ] **Step 4: Add Turkey map rule to `_rule_based_decision`**

In `_rule_based_decision`, insert after the `TIME_SERIES` block (currently ending around line 215, which returns `line_chart`) and before the `COMPARISON / RANKING with multiple dimensions -> sunburst` block (currently around line 217):

```python
    # --- TURKEY MAP: single city dimension, no time axis, no time granularity ---
    _city_col = detect_city_column(dim_cols)
    if (
        _city_col
        and not time_col
        and not time_granularity
        and len(dim_cols) == 1
        and metric_cols
    ):
        return {
            "needs_graph": True,
            "chart_type": "turkey_map",
            "x_field": _city_col,
            "y_field": None,  # validator Rule 4 fills from metric_cols[0]
            "series_field": None,
            "reason": f"City dimension ({_city_col}) + no time axis -> Turkey province map",
        }
```

- [ ] **Step 5: Run rule-based selection tests**

```
pytest tests/test_viz_decider_fast_path.py -v
```

Expected: All tests PASS including the 4 new turkey_map tests.

- [ ] **Step 6: Update viz decider LLM prompt**

Read `src/graphs/report_agent/subagents/visualization_v2/prompts.py` first. Add to the `chart_type SECIMI` section, after the heatmap line (currently line 72):

```
- İl/şehir boyutu + metrik + zaman yok → turkey_map
```

And add to the user keyword mappings section (after `"heatmap/ısı haritası" → heatmap` line):

```
- "türkiye haritası", "il haritası", "şehir haritası", "il bazında harita" → turkey_map
```

And add a new section for turkey_map rules after the heatmap section (after line 93):

```
### 🗺️ TÜRKİYE İL HARİTASI KURALLARI
- turkey_map = Türkiye illerini metrik değere göre renklendiren choropleth harita
- KOŞULLAR: x_field = il/şehir kolonu (ör. BranchCityName), y_field = metrik
- Zaman ekseni OLMAMALI (zamanla değişen şehir verisinde line_chart daha uygun)
- Kullanıcı "harita", "il bazında", "şehirlere göre", "türkiye haritası" derse → turkey_map
```

- [ ] **Step 7: Run full test suite**

```
pytest tests/test_visualization_v2/ tests/test_viz_decider_fast_path.py tests/test_viz_validator.py -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py \
        src/graphs/report_agent/subagents/visualization_v2/prompts.py \
        tests/test_viz_decider_fast_path.py
git commit -m "feat(viz): auto-select turkey_map for city dimension + update LLM prompt"
```

---

## Complete Data Flow After Implementation

```
Kullanıcı: "şehirlere göre satışları göster"
    ↓
[classify_intent_node]
    wants_visualization = True
    chart_type = None  (kullanıcı belirtmedi)
    ↓
[viz_decider_node]
    requested_chart_type = None → fast-return atlanır
    _rule_based_decision(query_type="RANKING", dim_cols=["BranchCityName"], time_col=None)
        _city_col = "BranchCityName"    ← detect_city_column buldu
        → returns chart_type="turkey_map", x_field="BranchCityName"
    ↓
[spec_validator_node]
    Rule 4: y_field = "TotalSales"  (metric_cols[0])
    Rule 3: turkey_map + x_field + y_field OK → pass
    ↓
[template_renderer_node]
    _build_turkey_map(df, spec)
        load_turkey_geojson() → 81 il feature
        normalize + map → "BranchCityName" values → GeoJSON province names
        px.choropleth(...) → Plotly HTML
    ↓
Plotly HTML — Türkiye haritası, iller metriğe göre renklendirilmiş
```

```
Kullanıcı: "türkiye haritası olarak göster"  (explicit)
    ↓
[classify_intent_node]
    chart_type = "turkey_map"
    ↓
[viz_decider_node]
    requested_chart_type = "turkey_map" → fast-return fires
    x_field = chart_x_hint (None → validator fills)
    ↓ same as above
```

---

## Self-Review

### Spec Coverage

| Requirement | Task | Status |
|-------------|------|--------|
| Yeni chart type eklendi | Task 1 (models.py, prompts.py) | ✓ |
| Şehirler renklendiriliyor | Task 2 (px.choropleth) | ✓ |
| İl geldiğinde otomatik seçim | Task 3 (_rule_based_decision) | ✓ |
| Zaman yok koşulu | Task 3 (not time_col and not time_granularity) | ✓ |
| Chart tipi belirtilmedi koşulu | Task 3 (rule-based, not fast-return path) | ✓ |
| Kullanıcı açıkça turkey_map isteyebilir | Task 1 (Literal) + Task 2 (renderer) | ✓ |
| GeoJSON yoksa graceful fallback | Task 2 (load returns None → renderer returns None → table) | ✓ |

### Placeholder Scan

Yok. Tüm adımlarda tam kod verilmiştir.

### Type Consistency

- `detect_city_column` returns `Optional[str]` — used as `_city_col` in `_rule_based_decision` → checked with `if _city_col` ✓
- `load_turkey_geojson` returns `Optional[dict]` — `_build_turkey_map` checks `if geojson is None` ✓
- `ChartSpec.chart_type` and `IntentClassificationResult.chart_type` both have `"turkey_map"` in Literal ✓
- `_build_turkey_map` signature matches all other builders: `(df: pd.DataFrame, spec: dict) -> go.Figure` ✓
