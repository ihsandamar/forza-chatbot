import pytest

import src.graphs.report_agent.subagents.export_v1.exporters.markdown  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_markdown_export_has_title():
    exporter = ExporterRegistry.get("md")
    spec = ExportSpec(format="md", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    content = buf.read().decode("utf-8")
    assert "# Rapor — 2026-06-18" in content


def test_markdown_export_has_table():
    exporter = ExporterRegistry.get("md")
    spec = ExportSpec(format="md", title="Rapor")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    content = buf.read().decode("utf-8")
    assert "| BranchName |" in content
    assert "| Istanbul |" in content
    assert "---" in content


def test_markdown_export_empty():
    exporter = ExporterRegistry.get("md")
    spec = ExportSpec(format="md", title="Rapor")
    buf = exporter.export([], spec)
    content = buf.read().decode("utf-8")
    assert "Veri bulunamadı" in content
