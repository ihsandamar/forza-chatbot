import csv
import io
import pytest

# Trigger registration
import src.graphs.report_agent.subagents.export_v1.exporters.csv  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_csv_export_produces_valid_csv():
    exporter = ExporterRegistry.get("csv")
    spec = ExportSpec(format="csv", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    buf.seek(0)
    content = buf.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["BranchName"] == "Istanbul"
    assert rows[0]["RowAmount"] == "50000"


def test_csv_export_empty_results():
    exporter = ExporterRegistry.get("csv")
    spec = ExportSpec(format="csv", title="Rapor")
    buf = exporter.export([], spec)
    assert buf.getvalue() != b""


def test_csv_content_type():
    exporter = ExporterRegistry.get("csv")
    assert "text/csv" in exporter.content_type
