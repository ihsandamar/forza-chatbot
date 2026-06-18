import csv
from io import BytesIO, StringIO
from typing import Any, Dict, List

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec


@ExporterRegistry.register
class CsvExporter(BaseExporter):
    FORMAT = "csv"

    @property
    def content_type(self) -> str:
        return "text/csv; charset=utf-8"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        if not results:
            buf = BytesIO()
            buf.write("Veri bulunamadı\n".encode("utf-8-sig"))
            buf.seek(0)
            return buf
        si = StringIO()
        writer = csv.DictWriter(si, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
        buf = BytesIO()
        buf.write(si.getvalue().encode("utf-8-sig"))
        buf.seek(0)
        return buf
