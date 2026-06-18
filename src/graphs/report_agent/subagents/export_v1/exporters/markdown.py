from io import BytesIO
from typing import Any, Dict, List

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec


@ExporterRegistry.register
class MarkdownExporter(BaseExporter):
    FORMAT = "md"

    @property
    def content_type(self) -> str:
        return "text/markdown; charset=utf-8"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        lines = [f"# {spec.title}", ""]
        if not results:
            lines.append("Veri bulunamadı.")
            buf = BytesIO()
            buf.write("\n".join(lines).encode("utf-8"))
            buf.seek(0)
            return buf

        headers = list(results[0].keys())
        lines.append("| " + " | ".join(str(h) for h in headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in results:
            lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")

        buf = BytesIO()
        buf.write("\n".join(lines).encode("utf-8"))
        buf.seek(0)
        return buf
