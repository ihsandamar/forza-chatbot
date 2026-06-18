import pytest
from io import BytesIO
from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter
from src.graphs.report_agent.subagents.export_v1.exporters.registry import ExporterRegistry
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec


def test_register_and_get():
    @ExporterRegistry.register
    class FakeExporter(BaseExporter):
        FORMAT = "fake"

        @property
        def content_type(self):
            return "application/fake"

        def export(self, results, spec, chart_figure=None, insight_text="") -> BytesIO:
            return BytesIO(b"fake")

    exporter = ExporterRegistry.get("fake")
    assert isinstance(exporter, FakeExporter)
    spec = ExportSpec(format="fake", title="Test")
    result = exporter.export([], spec)
    assert result.getvalue() == b"fake"


def test_get_unsupported_raises():
    with pytest.raises(ValueError, match="Unsupported export format"):
        ExporterRegistry.get("nonexistent_xyz")


def test_supported_formats_includes_registered():
    @ExporterRegistry.register
    class AnotherFake(BaseExporter):
        FORMAT = "anotherfake"

        @property
        def content_type(self):
            return "application/anotherfake"

        def export(self, results, spec, chart_figure=None, insight_text="") -> BytesIO:
            return BytesIO()

    assert "anotherfake" in ExporterRegistry.supported_formats()
