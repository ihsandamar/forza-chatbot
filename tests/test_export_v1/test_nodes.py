import pytest

# trigger all exporter registrations
import src.graphs.report_agent.subagents.export_v1.exporters.csv   # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.markdown  # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.xlsx  # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.pdf   # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.html  # noqa
import src.graphs.report_agent.subagents.export_v1.exporters.docx  # noqa

from src.graphs.report_agent.subagents.export_v1.nodes import (
    export_decider_node,
    format_renderer_node,
    export_response_builder_node,
)

SAMPLE_RESULTS = [
    {"BranchName": "Istanbul", "RowAmount": 50000},
    {"BranchName": "Ankara", "RowAmount": 35000},
]


@pytest.mark.asyncio
async def test_export_decider_produces_spec():
    state = {
        "results": SAMPLE_RESULTS,
        "export_format": "xlsx",
        "wants_export": True,
        "visualization_output": None,
        "insight_output": None,
    }
    result = await export_decider_node(state)
    assert "export_spec" in result
    assert result["export_spec"]["format"] == "xlsx"


@pytest.mark.asyncio
async def test_export_decider_falls_back_to_active_results():
    state = {
        "results": [],
        "active_results": SAMPLE_RESULTS,
        "export_format": "csv",
        "wants_export": True,
        "visualization_output": None,
    }
    result = await export_decider_node(state)
    assert "export_spec" in result
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_export_decider_sets_error_when_no_data():
    state = {"results": [], "active_results": [], "export_format": "xlsx", "wants_export": True}
    result = await export_decider_node(state)
    assert "error" in result


@pytest.mark.asyncio
async def test_format_renderer_produces_export_output(tmp_path, monkeypatch):
    from src.api.services import export_store

    captured = {}

    def fake_put(session_id, buffer, filename, content_type):
        captured[session_id] = buffer

    monkeypatch.setattr(export_store, "put", fake_put)

    from src.graphs.report_agent.subagents.export_v1.models import ExportSpec
    spec = ExportSpec(format="csv", title="Rapor — 2026-06-18")
    state = {
        "results": SAMPLE_RESULTS,
        "export_spec": spec.model_dump(),
        "visualization_output": None,
        "session_id": "test-session",
    }
    result = await format_renderer_node(state)
    assert "export_output" in result
    assert result["export_output"]["format"] == "csv"
    assert "/api/export/test-session" in result["export_output"]["download_url"]
    assert "test-session" in captured


@pytest.mark.asyncio
async def test_export_passthrough_when_wants_export_false():
    state = {"wants_export": False, "results": SAMPLE_RESULTS}
    result = await export_decider_node(state)
    assert result == {}
