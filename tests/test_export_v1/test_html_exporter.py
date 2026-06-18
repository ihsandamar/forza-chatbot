import pytest

import src.graphs.report_agent.subagents.export_v1.exporters.html  # noqa: F401
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


def test_html_produces_valid_html():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor — 2026-06-18")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    content = buf.read().decode("utf-8")
    assert "<!DOCTYPE html>" in content
    assert "<title>Rapor" in content


def test_html_contains_table_data():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor")
    buf = exporter.export(SAMPLE_RESULTS, spec)
    content = buf.read().decode("utf-8")
    assert "Istanbul" in content
    assert "BranchName" in content
    assert "<table" in content


def test_html_embeds_echarts_snippet_when_provided():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor", include_chart=True)
    echarts_snippet = '<div id="chart">ECharts HTML</div>'
    buf = exporter.export(SAMPLE_RESULTS, spec, chart_figure=echarts_snippet)
    content = buf.read().decode("utf-8")
    assert "ECharts HTML" in content


def test_html_no_chart_when_figure_is_none():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor")
    buf = exporter.export(SAMPLE_RESULTS, spec, chart_figure=None)
    content = buf.read().decode("utf-8")
    assert "chart-container" not in content


def test_html_empty_results():
    exporter = ExporterRegistry.get("html")
    spec = ExportSpec(format="html", title="Rapor")
    buf = exporter.export([], spec)
    content = buf.read().decode("utf-8")
    assert "Veri bulunamadı" in content
