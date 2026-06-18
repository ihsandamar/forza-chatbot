import pytest
from io import BytesIO

import src.graphs.report_agent.subagents.export_v1.exporters.pdf  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_pdf_produces_pdf_bytes():
    exporter = ExporterRegistry.get("pdf")
    spec = ExportSpec(format="pdf", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    buf.seek(0)
    header = buf.read(4)
    assert header == b"%PDF", f"Expected PDF header, got {header!r}"


def test_pdf_empty_results_still_produces_pdf():
    exporter = ExporterRegistry.get("pdf")
    spec = ExportSpec(format="pdf", title="Rapor")
    buf = exporter.export([], spec)
    buf.seek(0)
    assert buf.read(4) == b"%PDF"


def test_pdf_with_chart_figure():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    ax.bar(["A", "B"], [1, 2])
    exporter = ExporterRegistry.get("pdf")
    spec = ExportSpec(format="pdf", title="Rapor", include_chart=True)
    buf = exporter.export(SAMPLE_RESULTS, spec, chart_figure=fig)
    buf.seek(0)
    assert buf.read(4) == b"%PDF"
    plt.close("all")


def test_pdf_content_type():
    exporter = ExporterRegistry.get("pdf")
    assert exporter.content_type == "application/pdf"
