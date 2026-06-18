import logging
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)


def build_chart_figure(
    viz_decision: Optional[Dict[str, Any]],
    results: List[Dict[str, Any]],
) -> Optional[Figure]:
    """Convert a viz_decision dict + results list into a Matplotlib Figure.

    Returns None if:
    - results is empty or None
    - viz_decision is None
    - an exception is raised during rendering (logs warning, closes all figures)
    """
    if not results or not viz_decision:
        return None

    chart_type = viz_decision.get("chart_type", "bar_chart")
    x_field = viz_decision.get("x_field")
    y_field = viz_decision.get("y_field")
    series_field = viz_decision.get("series_field")
    title = viz_decision.get("title", "")

    # Infer fields from data columns if not provided
    if not x_field or not y_field:
        keys = list(results[0].keys())
        x_field = x_field or (keys[0] if keys else None)
        y_field = y_field or (keys[1] if len(keys) > 1 else (keys[0] if keys else None))

    if not x_field or not y_field:
        return None

    try:
        if chart_type == "pie_chart":
            fig, ax = plt.subplots(figsize=(8, 8))
            _draw_pie(ax, results, x_field, y_field)
        elif chart_type == "line_chart":
            fig, ax = plt.subplots(figsize=(10, 6))
            _draw_line(ax, results, x_field, y_field, series_field)
        else:
            # bar_chart is the default/fallback for all unrecognised types
            # (sunburst, turkey_map, heatmap, etc.)
            fig, ax = plt.subplots(figsize=(10, 6))
            _draw_bar(ax, results, x_field, y_field, series_field)

        if title:
            ax.set_title(title, fontsize=13, pad=10)
        fig.tight_layout()
        return fig
    except Exception as exc:
        logger.warning(f"[CHART_BRIDGE] Figure build failed: {exc}")
        plt.close("all")
        return None


def _draw_bar(ax, results, x_field, y_field, series_field):
    if series_field and results and series_field in results[0]:
        series_vals = list(dict.fromkeys(r.get(series_field) for r in results))
        x_vals = list(dict.fromkeys(r.get(x_field) for r in results))
        width = 0.8 / max(len(series_vals), 1)
        for i, sv in enumerate(series_vals):
            subset = [r for r in results if r.get(series_field) == sv]
            sub_x = [r.get(x_field) for r in subset]
            sub_y = [float(r.get(y_field) or 0) for r in subset]
            positions = [x_vals.index(x) + i * width for x in sub_x]
            ax.bar(positions, sub_y, width=width, label=str(sv))
        ax.set_xticks([i + (len(series_vals) - 1) * width / 2 for i in range(len(x_vals))])
        ax.set_xticklabels([str(x) for x in x_vals], rotation=45, ha="right")
        ax.legend(fontsize=9)
    else:
        x_vals = [str(r.get(x_field, "")) for r in results]
        y_vals = [float(r.get(y_field) or 0) for r in results]
        ax.bar(range(len(x_vals)), y_vals, color="#1F4E79")
        ax.set_xticks(range(len(x_vals)))
        ax.set_xticklabels(x_vals, rotation=45, ha="right")
    ax.set_xlabel(str(x_field), fontsize=10)
    ax.set_ylabel(str(y_field), fontsize=10)


def _draw_line(ax, results, x_field, y_field, series_field):
    if series_field and results and series_field in results[0]:
        series_vals = list(dict.fromkeys(r.get(series_field) for r in results))
        for sv in series_vals:
            subset = [r for r in results if r.get(series_field) == sv]
            x_vals = [str(r.get(x_field, "")) for r in subset]
            y_vals = [float(r.get(y_field) or 0) for r in subset]
            ax.plot(range(len(x_vals)), y_vals, marker="o", label=str(sv))
        ax.legend(fontsize=9)
        sample = [r for r in results if r.get(series_field) == series_vals[0]]
        all_x = [str(r.get(x_field, "")) for r in sample]
    else:
        all_x = [str(r.get(x_field, "")) for r in results]
        y_vals = [float(r.get(y_field) or 0) for r in results]
        ax.plot(range(len(all_x)), y_vals, marker="o", color="#1F4E79")

    step = max(1, len(all_x) // 10)
    ax.set_xticks(range(0, len(all_x), step))
    ax.set_xticklabels(all_x[::step], rotation=45, ha="right")
    ax.set_xlabel(str(x_field), fontsize=10)
    ax.set_ylabel(str(y_field), fontsize=10)


def _draw_pie(ax, results, x_field, y_field):
    labels = [str(r.get(x_field, "")) for r in results]
    values = [float(r.get(y_field) or 0) for r in results]
    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
    ax.axis("equal")
