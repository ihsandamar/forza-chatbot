"""
Visualization V2 — Chart Renderer (Deterministic)

CIZIM KATMANI: Pure Plotly API cagrilari, LLM yok, exec() yok.
Girdi: Validated ChartSpec dict + DataFrame
Cikti: HTML snippet veya None
"""
import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

MAX_TRACES = 50


def render_chart(
    spec: dict,
    results: List[Dict[str, Any]],
    column_metadata: Dict[str, Any],
) -> Optional[str]:
    """
    Render a Plotly chart from validated ChartSpec.

    Args:
        spec: Validated ChartSpec dict
        results: SQL query results
        column_metadata: Column name -> description mapping

    Returns:
        HTML snippet string or None if unsupported/empty
    """
    spec = dict(spec)  # defensive copy — composite time mutates x_field
    chart_type = spec.get("chart_type")
    if chart_type not in _BUILDERS:
        logger.warning(f"[RENDERER] Unsupported chart_type '{chart_type}'")
        return None

    if not results:
        return None

    try:
        df = pd.DataFrame(results)
        df = _apply_preprocessing(df, spec)
        df = _apply_composite_time(df, spec)

        if chart_type == "line_chart":
            return _render_line_pyechart(df, spec, column_metadata)

        fig = _BUILDERS[chart_type](df, spec)
        if fig is None:
            return None
        fig = _apply_labels(fig, spec, column_metadata)
        fig = _apply_number_format(fig, df, spec)
        fig = _apply_layout(fig, spec)

        if len(fig.data) > MAX_TRACES:
            fig.data = fig.data[:MAX_TRACES]

        return fig.to_html(include_plotlyjs="cdn", full_html=False)

    except Exception as e:
        logger.error(f"[RENDERER] Failed: {e}")
        return None


def render_chart_summary(
    spec: dict,
    results: List[Dict[str, Any]],
    column_metadata: Dict[str, Any],
) -> Optional[str]:
    """
    Render a compact sparkline-style summary chart for inline chat display.

    Currently only line_chart is supported; returns None for other types.
    """
    if not results:
        return None
    spec = dict(spec)
    chart_type = spec.get("chart_type")
    if chart_type != "line_chart":
        return None
    try:
        df = pd.DataFrame(results)
        df = _apply_preprocessing(df, spec)
        df = _apply_composite_time(df, spec)
        return _render_line_summary(df, spec, column_metadata)
    except Exception as e:
        logger.error(f"[RENDERER:SUMMARY] Failed: {e}")
        return None


def _summary_series(y_raw: list, color: str, *, with_area: bool, show_label: bool = False) -> dict:
    """Build a single ECharts series dict for the compact summary chart."""
    data = []
    for i, v in enumerate(y_raw):
        is_last = (i == len(y_raw) - 1)
        if is_last:
            entry: dict = {
                "value": v,
                "symbol": "circle",
                "symbolSize": 7,
                "itemStyle": {"color": color, "borderColor": "#fff", "borderWidth": 2},
            }
            if show_label and v is not None:
                entry["label"] = {
                    "show": True, "position": "top",
                    "formatter": _fmt_value(v),
                    "color": color, "fontWeight": "bold", "fontSize": 11,
                }
            data.append(entry)
        else:
            data.append(v)

    s: dict = {
        "type": "line", "data": data,
        "smooth": True, "symbol": "none",
        "lineStyle": {"width": 2, "color": color},
    }
    if with_area:
        s["areaStyle"] = {"color": "__AREA_GRAD__"}
    return s


def _fmt_value(v: float) -> str:
    """Format a numeric value to K/M shorthand."""
    try:
        lv = float(v)
        if lv >= 1_000_000:
            return f"{lv / 1_000_000:.1f}M"
        if lv >= 1_000:
            return f"{lv / 1_000:.1f}K"
        return str(int(lv)) if lv == int(lv) else f"{lv:.1f}"
    except (TypeError, ValueError):
        return str(v)


def _render_line_summary(
    df: pd.DataFrame, spec: dict, column_metadata: dict
) -> Optional[str]:
    """
    Compact A+B hybrid sparkline — handles single, multi-metric and series_field.

    Single series: gradient area + last-point value label.
    Multi-series (series_field / y_fields): palette-colored lines, last-point
    circle marker per series, no area fill (avoids visual clutter).
    No datazoom, no tooltip, no legend, no title. Height: 130px.
    """
    import json

    x_field = spec.get("x_field")
    y_field = spec.get("y_field")
    y_fields = spec.get("y_fields")
    series_field = spec.get("series_field")

    if not x_field or x_field not in df.columns:
        return None

    df_sorted = df.sort_values(x_field)

    _PALETTE = ["#2563eb", "#0891b2", "#059669", "#d97706", "#dc2626", "#7c3aed"]

    # ---------- build x_data and series_list ----------
    series_list: list = []

    if y_fields and len(y_fields) > 1:
        # Multi-metric: one line per metric, shared x axis
        x_vals = df_sorted[x_field].tolist()
        x_data = [str(v) for v in x_vals]
        for i, metric in enumerate(y_fields):
            if metric not in df_sorted.columns:
                continue
            y_raw = df_sorted[metric].tolist()
            c = _PALETTE[i % len(_PALETTE)]
            series_list.append(_summary_series(y_raw, c, with_area=(i == 0)))

    elif series_field and series_field in df.columns and y_field and y_field in df.columns:
        # Series field: one line per category, unified x axis
        x_vals = df_sorted[x_field].unique().tolist()
        x_data = [str(v) for v in x_vals]
        for i, sv in enumerate(df_sorted[series_field].unique().tolist()):
            group = df_sorted[df_sorted[series_field] == sv].sort_values(x_field)
            val_map = dict(zip([str(v) for v in group[x_field]], group[y_field]))
            y_raw = [val_map.get(x) for x in x_data]
            c = _PALETTE[i % len(_PALETTE)]
            series_list.append(_summary_series(y_raw, c, with_area=(i == 0)))

    elif y_field and y_field in df.columns:
        # Single line — gradient area + last-point label
        x_vals = df_sorted[x_field].tolist()
        x_data = [str(v) for v in x_vals]
        y_raw = df_sorted[y_field].tolist()
        series_list.append(_summary_series(y_raw, "#2563eb", with_area=True, show_label=True))

    else:
        return None

    if not series_list:
        return None

    n = len(x_data)
    XLBL_FMT = f"function(v,i){{return i===0||i==={n - 1}?v:''}}"
    NUM_FMT = "function(v){return v>=1e6?(v/1e6).toFixed(1)+'M':v>=1000?(v/1000).toFixed(0)+'K':v}"
    AREA_GRAD = (
        "new echarts.graphic.LinearGradient(0,0,0,1,"
        "[{offset:0,color:'rgba(37,99,235,0.14)'},{offset:1,color:'rgba(37,99,235,0.01)'}])"
    )

    option = {
        "backgroundColor": "#ffffff",
        "animation": False,
        "grid": {"top": 20, "right": 14, "bottom": 30, "left": 46},
        "xAxis": {
            "type": "category", "data": x_data,
            "axisLabel": {"color": "#bbb", "fontSize": 10, "formatter": "__XLBL_FMT__"},
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "min": "dataMin",
            "axisLabel": {"color": "#bbb", "fontSize": 10, "formatter": "__NUM_FMT__"},
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {"lineStyle": {"color": "#f5f5f5", "type": "dashed"}},
        },
        "tooltip": {"show": False},
        "series": series_list,
    }

    opt_json = (
        json.dumps(option, ensure_ascii=False)
        .replace('"__XLBL_FMT__"', XLBL_FMT)
        .replace('"__NUM_FMT__"', NUM_FMT)
        .replace('"__AREA_GRAD__"', AREA_GRAD)
    )

    return (
        "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
        "<script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>"
        "<style>html,body{margin:0;padding:0;width:100%;height:100%;background:#fff}"
        "#c{width:100%;height:100%;min-height:120px}</style></head>"
        "<body><div id='c'></div><script>"
        "var ec=echarts.init(document.getElementById('c'));"
        f"ec.setOption({opt_json});"
        "window.addEventListener('resize',function(){{ec.resize();}});"
        "</script></body></html>"
    )


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def _apply_preprocessing(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """Apply top_n and sort before chart building."""
    y = spec.get("y_field")
    top_n = spec.get("top_n")
    sort_by = spec.get("sort_by")
    sort_order = spec.get("sort_order", "desc")

    if top_n and y and y in df.columns and len(df) > top_n:
        df = df.nlargest(top_n, y)

    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=(sort_order == "asc"))

    return df


# ---------------------------------------------------------------------------
# Composite Time Axis
# ---------------------------------------------------------------------------

_YEAR_PATTERNS = {"yil", "year"}
_PERIOD_COMPOSITE = {
    "hafta": "W{period:02d}",
    "week": "W{period:02d}",
    "ay": "{period:02d}",
    "month": "{period:02d}",
}


def _apply_composite_time(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """
    Combine Yil + Hafta/Ay into a sortable composite x-axis label.
    Example: Yil=2025, Hafta=40 → "2025-W40"
    """
    x = spec.get("x_field")
    if not x:
        return df

    x_lower = x.lower()

    # Check if x_field is a period column that needs a year companion
    fmt_template = None
    for pattern, template in _PERIOD_COMPOSITE.items():
        if pattern in x_lower:
            fmt_template = template
            break

    if fmt_template is None:
        return df

    # Find year column in the dataframe
    year_col = None
    for col in df.columns:
        if col.lower() in _YEAR_PATTERNS and col != x:
            year_col = col
            break

    if year_col is None or year_col not in df.columns:
        return df

    # Create composite column
    composite_col = f"_{x}_composite"
    try:
        df = df.copy()
        df[composite_col] = df.apply(
            lambda row: f"{int(row[year_col])}-{fmt_template.format(period=int(row[x]))}",
            axis=1,
        )
        # Sort by year then period (numeric sort, not string sort)
        df = df.sort_values([year_col, x])
        # Replace x_field with composite column
        spec["x_field"] = composite_col
    except (ValueError, TypeError, KeyError):
        pass  # Fallback: keep original x_field

    return df


# ---------------------------------------------------------------------------
# Chart Builders
# ---------------------------------------------------------------------------

def _build_bar(df: pd.DataFrame, spec: dict) -> go.Figure:
    x = spec.get("x_field")
    y = spec.get("y_field")
    y_fields = spec.get("y_fields")
    series = spec.get("series_field")
    title = spec.get("title") or ""
    orientation = spec.get("orientation")

    # Multi-metric bar
    if y_fields and len(y_fields) > 1:
        fig = go.Figure()
        for metric in y_fields:
            fig.add_trace(go.Bar(x=df[x], y=df[metric], name=metric))
        fig.update_layout(barmode="group", title=title)
        return fig

    # Horizontal bar
    if orientation == "h" or (orientation is None and len(df) > 15):
        if not spec.get("sort_by"):
            df = df.sort_values(y, ascending=True)
        return px.bar(df, x=y, y=x, orientation="h", color=series, title=title)

    # Grouped bar with series
    if series:
        return px.bar(df, x=x, y=y, color=series, barmode="group", title=title)

    # Simple bar
    if not spec.get("sort_by"):
        df = df.sort_values(y, ascending=False)
    return px.bar(df, x=x, y=y, title=title)


def _build_line(df: pd.DataFrame, spec: dict) -> go.Figure:
    x = spec.get("x_field")
    y = spec.get("y_field")
    y_fields = spec.get("y_fields")
    series = spec.get("series_field")
    title = spec.get("title") or ""

    # Multi-metric line
    if y_fields and len(y_fields) > 1:
        fig = go.Figure()
        df_sorted = df.sort_values(x)
        for metric in y_fields:
            fig.add_trace(go.Scatter(
                x=df_sorted[x], y=df_sorted[metric],
                mode="lines+markers", name=metric,
            ))
        fig.update_layout(title=title)
        return fig

    df_sorted = df.sort_values(x)
    return px.line(df_sorted, x=x, y=y, color=series, title=title, markers=True)


def _render_line_pyechart(
    df: pd.DataFrame, spec: dict, column_metadata: dict
) -> Optional[str]:
    """Render line chart as standalone ECharts HTML — Clean & Minimal corporate style.

    Generates HTML directly for full control over legend (right-side panel),
    grid margins, formatters, and gradient fills without PyECharts rendering quirks.
    """
    import json

    x_field = spec.get("x_field")
    y_field = spec.get("y_field")
    y_fields = spec.get("y_fields")
    series_field = spec.get("series_field")
    title = spec.get("title") or ""

    if not x_field or x_field not in df.columns:
        return None

    df_sorted = df.sort_values(x_field)
    x_label = _get_label(x_field, column_metadata)
    y_label = _get_label(y_field, column_metadata) if y_field else ""

    if series_field and series_field in df.columns:
        x_vals = df_sorted[x_field].unique().tolist()
    else:
        x_vals = df_sorted[x_field].tolist()
    x_data = [str(v) for v in x_vals]

    _PALETTE = ["#2563eb", "#0891b2", "#059669", "#d97706", "#dc2626", "#7c3aed"]

    # Build series list
    series_list: list = []
    multi_series = False

    if y_fields and len(y_fields) > 1:
        multi_series = True
        for i, metric in enumerate(y_fields):
            if metric not in df_sorted.columns:
                continue
            c = _PALETTE[i % len(_PALETTE)]
            series_list.append({
                "name": _get_label(metric, column_metadata) or metric,
                "type": "line", "data": df_sorted[metric].tolist(),
                "smooth": True, "symbol": "circle", "symbolSize": 6,
                "lineStyle": {"width": 2.5, "color": c},
                "itemStyle": {"color": c, "borderColor": "#fff", "borderWidth": 2},
                "label": {"show": False},
            })

    elif series_field and series_field in df.columns and y_field and y_field in df.columns:
        multi_series = True
        for i, sv in enumerate(df_sorted[series_field].unique().tolist()):
            group = df_sorted[df_sorted[series_field] == sv].sort_values(x_field)
            val_map = dict(zip([str(v) for v in group[x_field]], group[y_field]))
            c = _PALETTE[i % len(_PALETTE)]
            series_list.append({
                "name": str(sv),
                "type": "line", "data": [val_map.get(x) for x in x_data],
                "smooth": True, "symbol": "circle", "symbolSize": 6,
                "lineStyle": {"width": 2.5, "color": c},
                "itemStyle": {"color": c, "borderColor": "#fff", "borderWidth": 2},
                "label": {"show": False},
            })

    elif y_field and y_field in df_sorted.columns:
        series_list.append({
            "name": y_label or y_field,
            "type": "line", "data": df_sorted[y_field].tolist(),
            "smooth": True, "symbol": "circle", "symbolSize": 6,
            "lineStyle": {"width": 2.5, "color": "#2563eb"},
            "itemStyle": {"color": "#2563eb", "borderColor": "#fff", "borderWidth": 2},
            "label": {"show": False},
            "areaStyle": {"color": "__AREA_GRAD__"},
        })

    else:
        return None

    grid_right = 155 if multi_series else 20

    option = {
        "backgroundColor": "#ffffff",
        "title": {
            "text": title, "left": "center",
            "textStyle": {"fontSize": 15, "fontWeight": "bold", "color": "#1d1d1f"},
        },
        "tooltip": {
            "trigger": "axis",
            "backgroundColor": "#ffffff",
            "borderColor": "#e8e8e8", "borderWidth": 1,
            "textStyle": {"color": "#333333", "fontSize": 13},
            "formatter": "__TIP_FMT__",
        },
        "legend": {
            "show": multi_series,
            "orient": "vertical", "right": 10, "top": "middle",
            "textStyle": {"color": "#333333", "fontSize": 12},
            "itemWidth": 16, "itemHeight": 4, "itemGap": 14,
            "icon": "roundRect",
        },
        "grid": {"top": 56, "right": grid_right, "bottom": 64, "left": 60},
        "xAxis": {
            "type": "category", "data": x_data,
            "name": x_label, "nameLocation": "middle", "nameGap": 32,
            "nameTextStyle": {"color": "#888888", "fontSize": 11},
            "axisLabel": {"color": "#888888", "fontSize": 11, "rotate": 30},
            "axisLine": {"lineStyle": {"color": "#e0e0e0"}},
            "axisTick": {"show": False}, "splitLine": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "name": y_label, "nameLocation": "middle", "nameGap": 50,
            "nameTextStyle": {"color": "#888888", "fontSize": 11},
            "axisLabel": {"color": "#888888", "fontSize": 11, "formatter": "__NUM_FMT__"},
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "splitLine": {"lineStyle": {"color": "#f0f0f0", "type": "dashed"}},
        },
        "dataZoom": [{"type": "slider", "start": 0, "end": 100, "height": 18, "bottom": 10}],
        "series": series_list,
    }

    NUM_FMT = "function(v){return v>=1e6?(v/1e6).toFixed(1)+'M':v>=1000?(v/1000).toFixed(0)+'K':v}"
    TIP_FMT = (
        "function(p){"
        "var s='<div style=\"font-weight:700;margin-bottom:4px;color:#1d1d1f\">'+p[0].axisValue+'</div>';"
        "p.forEach(function(x){"
        "var v=x.value==null?'-':x.value;"
        "var f=typeof v==='number'?"
        "(v>=1e6?(v/1e6).toFixed(2)+'M':v>=1000?(v/1000).toFixed(1)+'K':v.toLocaleString('tr')):v;"
        "s+=x.marker+' <span style=\"color:#555\">'+x.seriesName+'</span>: <b>'+f+'</b><br/>';});"
        "return s;}"
    )
    AREA_GRAD = (
        "new echarts.graphic.LinearGradient(0,0,0,1,"
        "[{offset:0,color:'rgba(37,99,235,0.18)'},{offset:1,color:'rgba(37,99,235,0.01)'}])"
    )

    opt_json = (
        json.dumps(option, ensure_ascii=False)
        .replace('"__NUM_FMT__"', NUM_FMT)
        .replace('"__TIP_FMT__"', TIP_FMT)
        .replace('"__AREA_GRAD__"', AREA_GRAD)
    )

    return (
        "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
        "<script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>"
        "<style>html,body{margin:0;padding:0;width:100%;height:100%;background:#fff}"
        "#c{width:100%;height:100%;min-height:420px}</style></head>"
        "<body><div id='c'></div><script>"
        "var ec=echarts.init(document.getElementById('c'));"
        f"ec.setOption({opt_json});"
        "window.addEventListener('resize',function(){ec.resize();});"
        "</script></body></html>"
    )


def _build_pie(df: pd.DataFrame, spec: dict) -> go.Figure:
    x = spec.get("x_field")
    y = spec.get("y_field")
    title = spec.get("title") or ""

    # top_n already applied in preprocessing, but if >10 rows still remain, group
    if len(df) > 10 and not spec.get("top_n"):
        top = df.nlargest(9, y)
        other_sum = df[~df.index.isin(top.index)][y].sum()
        other_row = pd.DataFrame([{x: "Diger", y: other_sum}])
        df = pd.concat([top, other_row], ignore_index=True)

    return px.pie(df, names=x, values=y, title=title)


def _build_scatter(df: pd.DataFrame, spec: dict) -> go.Figure:
    return px.scatter(
        df, x=spec.get("x_field"), y=spec.get("y_field"),
        color=spec.get("series_field"), title=spec.get("title") or "",
    )


def _build_sunburst(df: pd.DataFrame, spec: dict) -> go.Figure:
    path = spec.get("hierarchy_fields")
    if not path:
        x = spec.get("x_field")
        s = spec.get("series_field")
        y = spec.get("y_field")
        # x_field is outer level, series_field is inner — deduplicate to prevent
        # plotly DuplicateError when LLM sets both to the same column
        seen: set = set()
        path = [p for p in [x, s] if p and p not in seen and not seen.add(p)]  # type: ignore[func-returns-value]
        if not path:
            path = [c for c in df.columns if c != y][:3]
    if not path:
        return None
    # Drop rows with None/NaN in path columns — Plotly raises
    # "None entries cannot have not-None children" on NULL hierarchy values
    valid_path_cols = [c for c in path if c in df.columns]
    if valid_path_cols:
        df = df.dropna(subset=valid_path_cols)
    if df.empty:
        return None
    # Sabit kök düğüm — treemap ile aynı nedenle gerekli (boş root label)
    df = df.copy()
    df["__root__"] = "Toplam"
    path = ["__root__"] + path
    return px.sunburst(df, path=path, values=spec.get("y_field"), title=spec.get("title") or "")


def _build_treemap(df: pd.DataFrame, spec: dict) -> go.Figure:
    path = spec.get("hierarchy_fields")
    if not path:
        s = spec.get("series_field")
        x = spec.get("x_field")
        path = [p for p in [s, x] if p]
    # Guard: keep only path columns that actually exist in the DataFrame
    path = [c for c in path if c in df.columns]
    if not path:
        return None
    # Drop rows with None/NaN in path columns — Plotly raises
    # "None entries cannot have not-None children" on NULL hierarchy values
    df = df.dropna(subset=path)
    if df.empty:
        return None
    # Sabit kök düğüm ekle: px.treemap'in otomatik kök düğümü boş label üretir
    # ("" label'lı root → grand total görünmez). "Toplam" kolonu ile düzeltiriz.
    df = df.copy()
    df["__root__"] = "Toplam"
    full_path = ["__root__"] + path
    return px.treemap(df, path=full_path, values=spec.get("y_field"), title=spec.get("title") or "")


def _build_comparison(df: pd.DataFrame, spec: dict) -> go.Figure:
    return px.bar(
        df, x=spec.get("x_field"), y=spec.get("y_field"),
        color=spec.get("series_field"), barmode="group",
        title=spec.get("title") or "",
    )


def _build_heatmap(df: pd.DataFrame, spec: dict) -> go.Figure:
    """
    Build a heatmap from flat rows by pivoting.

    Expects:
        x_field: period/category column (becomes x-axis)
        series_field: entity column (becomes y-axis rows)
        y_field: metric column (becomes cell color values)
    """
    x = spec.get("x_field")
    y_metric = spec.get("y_field")
    entity = spec.get("series_field")
    title = spec.get("title") or ""

    if not entity or not x or not y_metric:
        return None

    try:
        pivot = df.pivot_table(
            index=entity,
            columns=x,
            values=y_metric,
            aggfunc="sum",
        ).fillna(0)
    except (KeyError, ValueError):
        return None

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=[str(c) for c in pivot.columns],
        y=[str(r) for r in pivot.index],
        colorscale="YlOrRd",
        hoverongaps=False,
        hovertemplate="%{y}<br>%{x}<br>Deger: %{z:,.0f}<extra></extra>",
    ))
    fig.update_layout(title=title)
    return fig


def _build_turkey_map(df: pd.DataFrame, spec: dict) -> go.Figure:
    """
    Render a Turkey province choropleth map.

    All 81 provinces are shown. Provinces with data are colored (Blues scale);
    provinces with no data appear in light grey.

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

    # Build lookup: normalized GeoJSON province name -> original GeoJSON name
    name_lookup: dict = {}
    all_province_names: list = []
    for feature in geojson.get("features", []):
        original = feature.get("properties", {}).get("name", "")
        if original:
            name_lookup[normalize_city_name(original)] = original
            all_province_names.append(original)

    df = df.copy()
    df["_geo_loc"] = df[x].apply(
        lambda v: name_lookup.get(normalize_city_name(str(v).strip())) if v else None
    )
    df_mapped = df.dropna(subset=["_geo_loc"]).copy()
    df_mapped[y] = pd.to_numeric(df_mapped[y], errors="coerce")
    df_mapped = df_mapped.dropna(subset=[y])

    if df_mapped.empty:
        return None

    z_min = float(df_mapped[y].min())
    z_max = float(df_mapped[y].max())
    if z_min == z_max:
        z_max = z_min + 1

    fig = go.Figure()

    # Trace 1: all 81 provinces in light grey (background for provinces with no data)
    fig.add_trace(go.Choropleth(
        geojson=geojson,
        locations=all_province_names,
        z=[0] * len(all_province_names),
        featureidkey="properties.name",
        colorscale=[[0, "#d4d4d4"], [1, "#d4d4d4"]],
        showscale=False,
        marker_line_color="white",
        marker_line_width=0.5,
        text=all_province_names,
        hovertemplate="%{text}: Veri yok<extra></extra>",
        name="",
    ))

    # Trace 2: provinces with data, colored in Blues scale
    fig.add_trace(go.Choropleth(
        geojson=geojson,
        locations=df_mapped["_geo_loc"].tolist(),
        z=df_mapped[y].tolist(),
        featureidkey="properties.name",
        colorscale="Blues",
        zmin=z_min,
        zmax=z_max,
        colorbar=dict(title=y),
        marker_line_color="white",
        marker_line_width=0.5,
        text=df_mapped[x].tolist(),
        hovertemplate="%{text}: %{z:,.0f}<extra></extra>",
        name="",
    ))

    fig.update_layout(title=title, showlegend=False)
    fig.update_geos(fitbounds="locations", visible=False)
    return fig


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


# ---------------------------------------------------------------------------
# Layout & Formatting
# ---------------------------------------------------------------------------

def _get_label(field: Optional[str], column_metadata: dict) -> str:
    if not field:
        return ""
    meta = column_metadata.get(field, "")
    if isinstance(meta, dict):
        return meta.get("description", field)
    if isinstance(meta, str) and meta:
        return meta
    return field


def _apply_labels(fig: go.Figure, spec: dict, column_metadata: dict) -> go.Figure:
    x = spec.get("x_field")
    y = spec.get("y_field")
    x_label = _get_label(x, column_metadata)
    y_label = _get_label(y, column_metadata)

    orientation = spec.get("orientation")
    is_horizontal = orientation == "h" or (
        len(fig.data) > 0
        and hasattr(fig.data[0], "orientation")
        and fig.data[0].orientation == "h"
    )

    update = {}
    if is_horizontal:
        if y_label:
            update["xaxis_title"] = y_label
        if x_label:
            update["yaxis_title"] = x_label
    else:
        if x_label:
            update["xaxis_title"] = x_label
        if y_label:
            update["yaxis_title"] = y_label

    if update:
        fig.update_layout(**update)
    return fig


def _detect_number_format(df: pd.DataFrame, col: str) -> Optional[str]:
    if col not in df.columns:
        return None
    try:
        sample = df[col].dropna()
        if sample.empty:
            return None
        max_val = sample.max()
        if max_val > 1000:
            return "currency"
        if 0 <= sample.min() and max_val <= 1 and pd.api.types.is_float_dtype(df[col]):
            return "percentage"
    except (TypeError, ValueError):
        pass
    return None


def _apply_number_format(fig: go.Figure, df: pd.DataFrame, spec: dict) -> go.Figure:
    y = spec.get("y_field")
    if not y:
        return fig
    fmt = _detect_number_format(df, y)

    is_horizontal = (
        len(fig.data) > 0
        and hasattr(fig.data[0], "orientation")
        and fig.data[0].orientation == "h"
    )
    axis = "x" if is_horizontal else "y"

    if fmt == "currency":
        fig.update_layout(**{f"{axis}axis_tickformat": ","})
    elif fmt == "percentage":
        fig.update_layout(**{f"{axis}axis_tickformat": ".0%"})
    return fig


def _apply_layout(fig: go.Figure, spec: dict) -> go.Figure:
    fig.update_layout(
        autosize=True,
        margin=dict(l=40, r=40, t=60, b=40),
        template="plotly_white",
    )
    return fig
