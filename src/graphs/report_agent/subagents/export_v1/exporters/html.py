from html import escape
from io import BytesIO
from typing import Any, Dict, List

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

_CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:2rem;color:#1a1a2e}
h1{color:#1F4E79;border-bottom:2px solid #1F4E79;padding-bottom:.5rem}
.insight{background:#EBF5FB;border-left:4px solid #1F4E79;padding:.75rem 1rem;margin:1rem 0;border-radius:4px}
table{border-collapse:collapse;width:100%;margin-top:1.5rem;font-size:.9rem}
th{background:#1F4E79;color:#fff;padding:10px 14px;text-align:left}
td{padding:8px 14px;border-bottom:1px solid #e0e0e0}
tr:nth-child(even){background:#F2F8FF}
tr:hover{background:#D6EAF8}
"""


@ExporterRegistry.register
class HtmlExporter(BaseExporter):
    FORMAT = "html"

    @property
    def content_type(self) -> str:
        return "text/html; charset=utf-8"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        chart_html = chart_figure if isinstance(chart_figure, str) else ""
        insight_html = (
            f"<p class='insight'>{escape(insight_text)}</p>"
            if spec.include_insight and insight_text
            else ""
        )
        chart_block = (
            f"<div style='margin:1.5rem 0'>{chart_html}</div>" if chart_html else ""
        )
        table_html = _build_table(results)

        html = (
            "<!DOCTYPE html>\n"
            "<html lang='tr'>\n"
            "<head>\n"
            "<meta charset='UTF-8'>\n"
            "<meta name='viewport' content='width=device-width,initial-scale=1.0'>\n"
            f"<title>{escape(spec.title)}</title>\n"
            f"<style>{_CSS}</style>\n"
            "</head>\n"
            "<body>\n"
            f"<h1>{escape(spec.title)}</h1>\n"
            f"{insight_html}\n"
            f"{chart_block}\n"
            f"{table_html}\n"
            "</body>\n"
            "</html>"
        )
        buf = BytesIO()
        buf.write(html.encode("utf-8"))
        buf.seek(0)
        return buf


def _build_table(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "<p>Veri bulunamadı.</p>"
    headers = list(results[0].keys())
    header_row = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    body = ""
    for row in results:
        cells = "".join(f"<td>{escape(str(row.get(h, '')))}</td>" for h in headers)
        body += f"<tr>{cells}</tr>\n"
    return f"<table><thead><tr>{header_row}</tr></thead><tbody>{body}</tbody></table>"
