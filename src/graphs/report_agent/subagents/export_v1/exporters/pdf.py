import logging
import os
import tempfile
from io import BytesIO
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

logger = logging.getLogger(__name__)

_HEADER_HEX = colors.HexColor("#1F4E79")
_ALT_ROW_HEX = colors.HexColor("#EBF5FB")


@ExporterRegistry.register
class PdfExporter(BaseExporter):
    FORMAT = "pdf"

    @property
    def content_type(self) -> str:
        return "application/pdf"

    def export(
        self,
        results: List[Dict[str, Any]],
        spec: ExportSpec,
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO:
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ExportTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=12
        )

        story = [Paragraph(spec.title, title_style), Spacer(1, 0.4 * cm)]

        if spec.include_insight and insight_text:
            story.append(Paragraph(insight_text, styles["Normal"]))
            story.append(Spacer(1, 0.4 * cm))

        # Keep track of any temp file so it can be cleaned up AFTER doc.build()
        # (ReportLab reads image files lazily during build, not during append)
        _tmp_chart_path = None
        if chart_figure is not None:
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    _tmp_chart_path = tmp.name
                chart_figure.savefig(_tmp_chart_path, dpi=150, bbox_inches="tight")
                story.append(RLImage(_tmp_chart_path, width=15 * cm, height=9 * cm))
                story.append(Spacer(1, 0.4 * cm))
            except Exception as exc:
                logger.warning(f"[PDF] Chart save failed: {exc}")
                if _tmp_chart_path and os.path.exists(_tmp_chart_path):
                    os.unlink(_tmp_chart_path)
                _tmp_chart_path = None

        if results:
            headers = list(results[0].keys())
            table_data = [headers] + [
                [str(row.get(h, "")) for h in headers] for row in results
            ]
            col_width = 15 * cm / max(len(headers), 1)
            tbl = Table(table_data, colWidths=[col_width] * len(headers), repeatRows=1)
            tbl.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_HEX),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ALT_ROW_HEX]),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("PADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(tbl)
        else:
            story.append(Paragraph("Veri bulunamadı.", styles["Normal"]))

        try:
            doc.build(story)
        finally:
            if _tmp_chart_path and os.path.exists(_tmp_chart_path):
                os.unlink(_tmp_chart_path)

        return buf
