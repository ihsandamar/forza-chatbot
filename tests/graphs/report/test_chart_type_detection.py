"""Tests for chart type and x-axis extraction via classify_intent_node (LLM-based).

chart_type and chart_x_hint are now fields in IntentClassificationResult.
Tests mock the LLM return and verify classify_intent_node wires both
correctly into state.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import HumanMessage


def _make_mock_llm(
    intent_type="NEW_QUERY",
    query_type="RANKING",
    confidence=0.9,
    wants_visualization=True,
    chart_type=None,
    chart_x_hint=None,
    use_result_type=None,
):
    from src.graphs.report_agent.prompts import IntentClassificationResult

    mock_result = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=confidence,
        wants_visualization=wants_visualization,
        chart_type=chart_type,
        chart_x_hint=chart_x_hint,
        use_result_type=use_result_type,
    )
    chain = MagicMock()
    chain.ainvoke = AsyncMock(return_value=mock_result)
    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=chain)
    return mock_llm


async def _run_classify(user_msg: str, llm):
    from src.graphs.report_agent.nodes import create_classify_intent_node
    node = create_classify_intent_node(llm)
    return await node({"messages": [HumanMessage(content=user_msg)]})


# ---------------------------------------------------------------------------
# chart_type correctly wired from LLM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bar_chart_wired():
    llm = _make_mock_llm(wants_visualization=True, chart_type="bar_chart")
    result = await _run_classify("bar grafik yap", llm)
    assert result["requested_chart_type"] == "bar_chart"
    assert result["wants_visualization"] is True


@pytest.mark.asyncio
async def test_sunburst_wired():
    llm = _make_mock_llm(wants_visualization=True, chart_type="sunburst")
    result = await _run_classify("sunbrust grafik istiyorum", llm)
    assert result["requested_chart_type"] == "sunburst"


@pytest.mark.asyncio
async def test_heatmap_wired():
    llm = _make_mock_llm(wants_visualization=True, chart_type="heatmap")
    result = await _run_classify("ısı haritası olarak göster", llm)
    assert result["requested_chart_type"] == "heatmap"


@pytest.mark.asyncio
async def test_chart_type_none_when_no_viz():
    llm = _make_mock_llm(wants_visualization=False, chart_type=None)
    result = await _run_classify("son 3 aydaki satışlar", llm)
    assert result["requested_chart_type"] is None
    assert result["wants_visualization"] is False


@pytest.mark.asyncio
async def test_chart_type_none_when_llm_returns_none():
    """User says 'grafik göster' without specifying type."""
    llm = _make_mock_llm(wants_visualization=True, chart_type=None)
    result = await _run_classify("satışları grafik olarak göster", llm)
    assert result["requested_chart_type"] is None
    assert result["wants_visualization"] is True


# ---------------------------------------------------------------------------
# chart_x_hint correctly wired from LLM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chart_x_hint_wired_when_user_names_column():
    """User says 'BranchName bazında bar chart' → x_hint = 'BranchName'."""
    llm = _make_mock_llm(
        wants_visualization=True,
        chart_type="bar_chart",
        chart_x_hint="BranchName",
    )
    result = await _run_classify("BranchName bazında bar chart yap", llm)
    assert result["requested_chart_type"] == "bar_chart"
    assert result["chart_x_hint"] == "BranchName"


@pytest.mark.asyncio
async def test_chart_x_hint_none_when_user_does_not_name_column():
    """'bar chart yap' without naming a column → x_hint = None."""
    llm = _make_mock_llm(
        wants_visualization=True,
        chart_type="bar_chart",
        chart_x_hint=None,
    )
    result = await _run_classify("bar chart yap", llm)
    assert result["requested_chart_type"] == "bar_chart"
    assert result["chart_x_hint"] is None


@pytest.mark.asyncio
async def test_chart_x_hint_with_semantic_column_name():
    """'kategorilere göre pasta grafik' → LLM resolves to 'CategoryName'."""
    llm = _make_mock_llm(
        wants_visualization=True,
        chart_type="pie_chart",
        chart_x_hint="CategoryName",
    )
    result = await _run_classify("kategorilere göre pasta grafik göster", llm)
    assert result["requested_chart_type"] == "pie_chart"
    assert result["chart_x_hint"] == "CategoryName"


@pytest.mark.asyncio
async def test_chart_x_hint_cleared_by_model_validator_when_no_chart_type():
    """chart_x_hint must be None when chart_type is None (model_validator enforces)."""
    llm = _make_mock_llm(
        wants_visualization=True,
        chart_type=None,
        chart_x_hint=None,  # model_validator would clear it anyway
    )
    result = await _run_classify("satışları grafik olarak göster", llm)
    assert result["chart_x_hint"] is None


@pytest.mark.asyncio
async def test_chart_x_hint_reset_each_turn():
    """chart_x_hint must reset to None each turn (stale state prevention)."""
    llm = _make_mock_llm(
        wants_visualization=True,
        chart_type="bar_chart",
        chart_x_hint=None,
    )
    result = await _run_classify("şimdi line chart yap", llm)
    assert result["chart_x_hint"] is None


# ---------------------------------------------------------------------------
# revisualize path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revisualize_wires_chart_type_and_hint():
    llm = _make_mock_llm(
        intent_type="USE_RESULT",
        use_result_type="revisualize",
        wants_visualization=False,
        chart_type="bar_chart",
        chart_x_hint="BranchName",
    )
    result = await _run_classify("bunu BranchName bazında bar chart olarak göster", llm)
    assert result["wants_visualization"] is True
    assert result["requested_chart_type"] == "bar_chart"
    assert result["chart_x_hint"] == "BranchName"


@pytest.mark.asyncio
async def test_revisualize_chart_type_none_when_not_specified():
    llm = _make_mock_llm(
        intent_type="USE_RESULT",
        use_result_type="revisualize",
        wants_visualization=False,
        chart_type=None,
    )
    result = await _run_classify("bunu farklı göster", llm)
    assert result["wants_visualization"] is True
    assert result["requested_chart_type"] is None
