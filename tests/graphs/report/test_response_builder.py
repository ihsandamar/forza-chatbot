"""Unit tests for response_builder — isolated from nodes/graph."""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# _insight_python
# ---------------------------------------------------------------------------

def test_insight_python_finds_top_entry():
    from src.graphs.report_agent.response_builder import _insight_python
    results = [
        {"City": "Ankara", "Amount": 2400000},
        {"City": "Istanbul", "Amount": 1800000},
        {"City": "Izmir", "Amount": 900000},
    ]
    viz = {"x_field": "City", "y_field": "Amount", "title": "Sehir Satislari"}
    result = _insight_python(results, viz)
    assert "Ankara" in result
    assert "2,400,000" in result
    assert "3 kayıt" in result


def test_insight_python_no_xy_fields():
    from src.graphs.report_agent.response_builder import _insight_python
    results = [{"A": 1}, {"A": 2}]
    result = _insight_python(results, {})
    assert "2 kayıt" in result


def test_insight_python_handles_non_numeric_y():
    from src.graphs.report_agent.response_builder import _insight_python
    results = [{"City": "X", "Amount": "not_a_number"}]
    viz = {"x_field": "City", "y_field": "Amount", "title": ""}
    result = _insight_python(results, viz)
    assert "1 kayıt" in result


def test_insight_python_includes_title_prefix():
    from src.graphs.report_agent.response_builder import _insight_python
    results = [{"Cat": "A", "Val": 10}]
    viz = {"x_field": "Cat", "y_field": "Val", "title": "Kategori Analizi"}
    result = _insight_python(results, viz)
    assert result.startswith("Kategori Analizi:")


# ---------------------------------------------------------------------------
# _metadata_section
# ---------------------------------------------------------------------------

def test_metadata_section_known_chart_type():
    from src.graphs.report_agent.response_builder import _metadata_section
    result = _metadata_section({"chart_type": "sunburst"}, 64)
    assert "Sunburst" in result
    assert "64 kayıt" in result


def test_metadata_section_bar_chart_label():
    from src.graphs.report_agent.response_builder import _metadata_section
    result = _metadata_section({"chart_type": "bar_chart"}, 10)
    assert "Cubuk Grafik" in result or "ubuk" in result


def test_metadata_section_unknown_type_uses_fallback():
    from src.graphs.report_agent.response_builder import _metadata_section
    result = _metadata_section({"chart_type": "unknown_type"}, 5)
    assert "5 kayıt" in result


# ---------------------------------------------------------------------------
# build_chart_response — python mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_chart_response_python_includes_insight_and_metadata():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"City": "A", "Amount": 100}, {"City": "B", "Amount": 50}]
    viz = {"x_field": "City", "y_field": "Amount", "title": "Test", "chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="python", show_metadata=True)
    result = await build_chart_response(results, viz, "satis?", config)
    assert "A" in result          # top entry
    assert "kayıt" in result      # row count appears


@pytest.mark.asyncio
async def test_build_chart_response_metadata_off():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"City": "A", "Amount": 100}]
    viz = {"x_field": "City", "y_field": "Amount", "title": "", "chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="python", show_metadata=False)
    result = await build_chart_response(results, viz, "", config)
    # metadata separator not present
    assert "·" not in result


@pytest.mark.asyncio
async def test_build_chart_response_off_mode_returns_count():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"A": 1}, {"A": 2}]
    viz = {"chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="off", show_metadata=False)
    result = await build_chart_response(results, viz, "", config)
    assert "2 kayıt" in result


# ---------------------------------------------------------------------------
# build_chart_response — llm mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_chart_response_llm_calls_llm_and_returns_content():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"City": "Ankara", "Amount": 500}]
    viz = {"x_field": "City", "y_field": "Amount", "title": "T", "chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="llm", show_metadata=True)
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Ankara one cikiyor."
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    result = await build_chart_response(results, viz, "satis?", config, llm=mock_llm)
    assert "Ankara one cikiyor." in result
    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_build_chart_response_llm_falls_back_on_error():
    from src.graphs.report_agent.response_builder import ResponseConfig, build_chart_response
    results = [{"City": "B", "Amount": 500}]
    viz = {"x_field": "City", "y_field": "Amount", "title": "T", "chart_type": "bar_chart"}
    config = ResponseConfig(insight_mode="llm", show_metadata=False)
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM down"))
    result = await build_chart_response(results, viz, "", config, llm=mock_llm)
    assert "B" in result   # python fallback used
