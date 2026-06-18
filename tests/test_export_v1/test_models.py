import pytest
from src.graphs.report_agent.subagents.export_v1.models import ExportSpec


def test_export_spec_defaults():
    spec = ExportSpec(format="xlsx", title="Rapor — 2026-06-18")
    assert spec.include_chart is False
    assert spec.include_insight is False
    assert spec.sheet_name == "Veri"


def test_export_spec_full():
    spec = ExportSpec(
        format="pdf",
        include_chart=True,
        include_insight=True,
        title="Rapor — 2026-06-18",
        sheet_name="Satışlar",
    )
    assert spec.format == "pdf"
    assert spec.include_chart is True
    assert spec.sheet_name == "Satışlar"


def test_export_spec_invalid_missing_format():
    with pytest.raises(Exception):
        ExportSpec(title="Rapor")
