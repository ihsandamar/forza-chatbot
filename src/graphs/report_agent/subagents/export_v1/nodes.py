import logging
from datetime import date
from typing import Any, Dict

from src.graphs.report_agent.subagents.export_v1.chart_bridge import build_chart_figure
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

logger = logging.getLogger(__name__)

_HTML_FORMATS = {"html"}
_NO_CHART_FORMATS = {"csv", "md"}


async def export_decider_node(state: Dict[str, Any]) -> dict:
    if not state.get("wants_export"):
        return {}

    results = state.get("results") or state.get("active_results") or []
    if not results:
        logger.warning("[EXPORT] No results available for export")
        return {"error": "Export için veri bulunamadı. Önce bir sorgu çalıştırın."}

    export_format = state.get("export_format") or "xlsx"
    viz_out = state.get("visualization_output") or {}
    has_chart = bool(viz_out.get("needs_graph") and export_format not in _NO_CHART_FORMATS)
    has_insight = bool(state.get("insight_output") and export_format in ("pdf", "docx", "html"))

    spec = ExportSpec(
        format=export_format,
        include_chart=has_chart,
        include_insight=has_insight,
        title=f"Rapor — {date.today().isoformat()}",
    )
    logger.info(f"[EXPORT] spec: format={export_format}, chart={has_chart}, insight={has_insight}")
    return {"export_spec": spec.model_dump(), "results": results}


async def format_renderer_node(state: Dict[str, Any]) -> dict:
    from src.api.services import export_store

    raw_spec = state.get("export_spec")
    if not raw_spec:
        return {}

    spec = ExportSpec(**raw_spec)
    results = state.get("results") or []
    viz_out = state.get("visualization_output") or {}
    session_id = state.get("session_id") or "unknown"

    chart_figure = None
    if spec.include_chart:
        if spec.format in _HTML_FORMATS:
            chart_figure = viz_out.get("plotly_html_snippet") or ""
        else:
            chart_figure = build_chart_figure(viz_out, results)

    insight_text = state.get("insight_output") or ""

    try:
        exporter = ExporterRegistry.get(spec.format)
        buffer = exporter.export(results, spec, chart_figure=chart_figure, insight_text=insight_text)
        filename = f"rapor_{date.today().isoformat()}.{spec.format}"
        export_store.put(session_id, buffer, filename, exporter.content_type)
    except Exception as exc:
        logger.error(f"[EXPORT] Renderer failed: {exc}")
        return {"error": f"Export oluşturulamadı: {exc}"}

    logger.info(f"[EXPORT] format={spec.format}, session={session_id}")
    return {
        "export_output": {
            "format": spec.format,
            "download_url": f"/api/export/{session_id}",
            "filename": filename,
            "has_chart": chart_figure is not None and chart_figure != "",
        }
    }


async def export_response_builder_node(state: Dict[str, Any]) -> dict:
    out = state.get("export_output")
    if not out:
        return {}
    fmt = out.get("format", "").upper()
    url = out.get("download_url", "")
    summary = f"{fmt} raporu hazır. [İndir]({url})"
    return {"export_output": {**out, "summary": summary}}
