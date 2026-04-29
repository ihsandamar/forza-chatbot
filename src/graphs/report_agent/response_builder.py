"""
Chart Response Builder

Section-based, strategy-selectable response text for chart responses.
Consumed by create_build_response_node in nodes.py.

Sections (order preserved):
  1. insight  — natural language summary (llm | python | off)
  2. metadata — compact chart info line (on | off)

Adding a new section: add a function + a field to ResponseConfig.
build_chart_response calls it conditionally. No other files change.
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class ResponseConfig:
    insight_mode: Literal["llm", "python", "off"] = "python"
    show_metadata: bool = True


DEFAULT_CONFIG = ResponseConfig(
    insight_mode=os.getenv("CHART_INSIGHT_MODE", "python"),  # type: ignore[arg-type]
    show_metadata=os.getenv("CHART_SHOW_METADATA", "true").lower() != "false",
)

_CHART_TYPE_LABELS = {
    "bar_chart":     "Çubuk Grafik",
    "line_chart":    "Çizgi Grafik",
    "pie_chart":     "Pasta Grafik",
    "scatter_chart": "Dağılım Grafik",
    "scatter":       "Dağılım Grafik",
    "sunburst":      "Sunburst",
    "treemap":       "Treemap",
    "comparison":    "Karşılaştırma",
    "heatmap":       "Isı Haritası",
    "turkey_map":    "Türkiye Haritası",
}


def _insight_python(results: list, viz: dict) -> str:
    x = viz.get("x_field")
    y = viz.get("y_field")
    title = viz.get("title") or ""
    n = len(results)
    prefix = f"{title}: " if title else ""

    if x and y:
        try:
            top = max(results, key=lambda r: float(r.get(y) or 0))
            top_label = top.get(x, "?")
            top_val = float(top.get(y) or 0)
            return f"{prefix}{top_label} en yüksek değerde ({top_val:,.0f}). {n} kayıt analiz edildi."
        except (TypeError, ValueError, KeyError):
            pass
    return f"{prefix}{n} kayıt analiz edildi."


async def _insight_llm(results: list, viz: dict, user_query: str, llm) -> str:
    title = viz.get("title") or ""
    sample = results[:10]
    prompt = (
        f"Kullanıcı sorusu: {user_query}\n"
        f"Grafik başlığı: {title}\n"
        f"Veri ({len(sample)} kayıt): {json.dumps(sample, ensure_ascii=False, default=str)}\n\n"
        "Yukarıdaki verilere dayanarak 1-2 cümlelik Türkçe bir içgörü yaz. "
        "Sadece içgörü cümlesini yaz, başlık veya ek açıklama ekleme."
    )
    try:
        response = await llm.ainvoke(prompt)
        return response.content.strip()
    except Exception as e:
        logger.warning(f"[RESPONSE_BUILDER] LLM insight failed, falling back to python: {e}")
        return _insight_python(results, viz)


def _metadata_section(viz: dict, row_count: int) -> str:
    chart_type = viz.get("chart_type", "")
    label = _CHART_TYPE_LABELS.get(
        chart_type,
        chart_type.replace("_", " ").title() if chart_type else "Grafik",
    )
    return f"{label} · {row_count} kayıt"


async def build_chart_response(
    results: list,
    viz: dict,
    user_query: str,
    config: ResponseConfig,
    llm=None,
) -> str:
    """Assemble chart response text from enabled sections."""
    parts: list[str] = []

    if config.insight_mode == "llm" and llm is not None:
        insight = await _insight_llm(results, viz, user_query, llm)
    elif config.insight_mode == "llm" and llm is None:
        logger.warning("[RESPONSE_BUILDER] insight_mode='llm' but no llm provided, falling back to python")
        insight = _insight_python(results, viz)
    elif config.insight_mode == "python":
        insight = _insight_python(results, viz)
    else:
        insight = None

    if insight:
        parts.append(insight)

    if config.show_metadata:
        parts.append(_metadata_section(viz, len(results)))

    return "\n".join(parts) if parts else f"{len(results)} kayıt analiz edildi."
