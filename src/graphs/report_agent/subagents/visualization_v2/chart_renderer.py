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
    return px.sunburst(df, path=path, values=spec.get("y_field"), title=spec.get("title") or "")


def _build_treemap(df: pd.DataFrame, spec: dict) -> go.Figure:
    path = spec.get("hierarchy_fields")
    if not path:
        s = spec.get("series_field")
        x = spec.get("x_field")
        path = [p for p in [s, x] if p]
    return px.treemap(df, path=path, values=spec.get("y_field"), title=spec.get("title") or "")


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
