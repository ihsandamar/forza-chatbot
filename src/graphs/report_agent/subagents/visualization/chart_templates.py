"""
Dynamic Chart Template Engine
==============================

Generates Plotly charts from viz_decision parameters without LLM.
Adapts to data shape, column metadata, and chart type.

Returns HTML snippet or None if chart_type is unsupported (LLM fallback).
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

MAX_TRACES = 50


def build_chart(
    viz_decision: dict,
    results: List[Dict[str, Any]],
    column_metadata: Dict[str, Any],
) -> Optional[str]:
    chart_type = viz_decision.get("chart_type")
    if chart_type not in _BUILDERS:
        logger.info(f"[CHART_TEMPLATE] Unsupported chart_type '{chart_type}', falling back to LLM")
        return None

    if not results:
        return None

    try:
        df = pd.DataFrame(results)
        x = viz_decision.get("x_field")
        y = viz_decision.get("y_field")
        series = viz_decision.get("series_field")
        title = viz_decision.get("title") or ""

        for field in [x, y, series]:
            if field and field not in df.columns:
                logger.warning(f"[CHART_TEMPLATE] Field '{field}' not in columns {list(df.columns)}, LLM fallback")
                return None

        x_label = _get_label(x, column_metadata)
        y_label = _get_label(y, column_metadata)
        y_format = _detect_number_format(df, y) if y else None

        fig = _BUILDERS[chart_type](df, x, y, series, title)

        # Detect if horizontal bar (labels need swapping)
        is_horizontal = (
            len(fig.data) > 0
            and hasattr(fig.data[0], 'orientation')
            and fig.data[0].orientation == 'h'
        )

        if is_horizontal:
            fig = _apply_labels(fig, y_label, x_label)  # swap labels
            fig = _apply_number_format(fig, y_format, axis="x")  # format on x-axis
        else:
            fig = _apply_labels(fig, x_label, y_label)
            fig = _apply_number_format(fig, y_format)
        fig = _apply_layout(fig, title)

        if len(fig.data) > MAX_TRACES:
            fig.data = fig.data[:MAX_TRACES]

        return fig.to_html(include_plotlyjs="cdn", full_html=False)

    except Exception as e:
        logger.warning(f"[CHART_TEMPLATE] Template failed: {e}, falling back to LLM")
        return None


def _build_bar(df, x, y, series, title):
    if len(df) > 15:
        df_sorted = df.sort_values(y, ascending=True)
        fig = px.bar(df_sorted, x=y, y=x, orientation="h", color=series, title=title)
    elif series:
        fig = px.bar(df, x=x, y=y, color=series, barmode="group", title=title)
    else:
        df_sorted = df.sort_values(y, ascending=False)
        fig = px.bar(df_sorted, x=x, y=y, title=title)
    return fig


def _build_line(df, x, y, series, title):
    df_sorted = df.sort_values(x)
    fig = px.line(df_sorted, x=x, y=y, color=series, title=title, markers=True)
    return fig


def _build_pie(df, x, y, series, title):
    if len(df) > 10:
        top = df.nlargest(9, y)
        other_sum = df[~df.index.isin(top.index)][y].sum()
        other_row = pd.DataFrame([{x: "Diğer", y: other_sum}])
        df = pd.concat([top, other_row], ignore_index=True)
    fig = px.pie(df, names=x, values=y, title=title)
    return fig


def _build_scatter(df, x, y, series, title):
    fig = px.scatter(df, x=x, y=y, color=series, title=title)
    return fig


def _build_treemap(df, x, y, series, title):
    path_cols = [series, x] if series else [x]
    fig = px.treemap(df, path=path_cols, values=y, title=title)
    return fig


def _build_sunburst(df, x, y, series, title):
    path_cols = [series, x] if series else [x]
    fig = px.sunburst(df, path=path_cols, values=y, title=title)
    return fig


def _build_comparison(df, x, y, series, title):
    fig = px.bar(df, x=x, y=y, color=series, barmode="group", title=title)
    return fig


_BUILDERS = {
    "bar_chart": _build_bar,
    "line_chart": _build_line,
    "pie_chart": _build_pie,
    "scatter_chart": _build_scatter,
    "scatter": _build_scatter,
    "treemap": _build_treemap,
    "sunburst": _build_sunburst,
    "comparison": _build_comparison,
}


def _get_label(field: Optional[str], column_metadata: dict) -> str:
    if not field:
        return ""
    meta = column_metadata.get(field, {})
    if isinstance(meta, dict):
        return meta.get("description", field)
    return field


def _detect_number_format(df, col: str) -> Optional[str]:
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


def _apply_labels(fig, x_label: str, y_label: str):
    update = {}
    if x_label:
        update["xaxis_title"] = x_label
    if y_label:
        update["yaxis_title"] = y_label
    if update:
        fig.update_layout(**update)
    return fig


def _apply_number_format(fig, fmt: Optional[str], axis: str = "y"):
    if fmt == "currency":
        fig.update_layout(**{f"{axis}axis_tickformat": ","})
    elif fmt == "percentage":
        fig.update_layout(**{f"{axis}axis_tickformat": ".0%"})
    return fig


def _apply_layout(fig, title: str):
    fig.update_layout(
        autosize=True,
        margin=dict(l=40, r=40, t=60, b=40),
        template="plotly_white",
    )
    return fig
