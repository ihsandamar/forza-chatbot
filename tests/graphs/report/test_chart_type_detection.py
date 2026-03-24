"""Unit tests for _detect_chart_type_from_query deterministic fallback.

Pure function tests — no LLM, no I/O, no async.
"""


def _fn(text):
    from src.graphs.report_agent.nodes import _detect_chart_type_from_query
    return _detect_chart_type_from_query(text)


# --- Exact keyword match ---
def test_sunburst_exact():
    assert _fn("sunburst grafik ver") == "sunburst"

def test_heatmap_exact():
    assert _fn("heatmap göster") == "heatmap"

def test_treemap_exact():
    assert _fn("treemap istiyorum") == "treemap"

def test_bar_chart_turkish():
    assert _fn("çubuk grafik") == "bar_chart"

def test_line_chart_turkish():
    assert _fn("çizgi grafik") == "line_chart"

def test_pie_chart_turkish():
    assert _fn("pasta grafik") == "pie_chart"

def test_scatter_chart_compound():
    assert _fn("scatter chart ver") == "scatter_chart"

def test_bar_chart_compound_english():
    assert _fn("bar chart istiyorum") == "bar_chart"

def test_line_chart_compound_english():
    assert _fn("line chart göster") == "line_chart"

def test_pie_chart_compound_english():
    assert _fn("pie chart ver") == "pie_chart"


# --- Typo tolerance (root cause case) ---
def test_sunbrust_typo():
    """Root cause: 'sunbrust' LLM tarafından resolve edilemiyor — bu test bunu yakalar."""
    assert _fn("sunbrust grafik ver") == "sunburst"

def test_sunbrust_uppercase():
    assert _fn("SUNBRUST GRAFİK") == "sunburst"

def test_sunbrust_in_full_query():
    """Actual failing query from the bug report."""
    q = ("Son 3 aydaki satışları karşılaştır ve bunlar içinde hangi kategoriler "
         "ne kadar satmış onu da gösteren sunbrust grafik ver")
    assert _fn(q) == "sunburst"


# --- Turkish heatmap ---
def test_isı_haritası():
    assert _fn("ısı haritası göster") == "heatmap"


# --- No false positives for bare English words in Turkish text ---
def test_no_false_positive_kabartma():
    """'kabartma' contains 'bar' as substring — must NOT trigger bar_chart."""
    assert _fn("kabartma tekniği") is None

def test_no_false_positive_line_in_turkish():
    """'oline' (as in online) must NOT trigger line_chart."""
    assert _fn("online rapor ver") is None


# --- No match cases ---
def test_no_chart_keyword_returns_none():
    assert _fn("son 3 aydaki satışları göster") is None

def test_empty_string_returns_none():
    assert _fn("") is None

def test_only_whitespace_returns_none():
    assert _fn("   ") is None


# ---------------------------------------------------------------------------
# Integration: classify_intent_node fallback path (LLM mock ile)
# Projedeki pattern: @pytest.mark.asyncio + async def (test_extract_entity_node.py)
# ---------------------------------------------------------------------------
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_mock_llm(
    intent_type="NEW_QUERY",
    query_type="COMPARISON",
    confidence=0.9,
    wants_visualization=True,
    use_result_type=None,
    requested_chart_type=None,
):
    """Structured LLM mock: ainvoke → IntentClassificationResult döner."""
    from src.graphs.report_agent.prompts import IntentClassificationResult

    mock_result = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=confidence,
        wants_visualization=wants_visualization,
        use_result_type=use_result_type,
        requested_chart_type=requested_chart_type,
    )
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=mock_result)
    mock_llm.with_structured_output = MagicMock(return_value=structured)
    return mock_llm


@pytest.mark.asyncio
async def test_fallback_sets_sunburst_when_llm_returns_none():
    """Root cause: LLM None döndüğünde 'sunbrust' fallback ile sunburst olmalı."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=True, requested_chart_type=None)
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="son 3 aydaki satışları sunbrust grafik ile göster")]}
    result = await node(state)
    assert result["requested_chart_type"] == "sunburst"


@pytest.mark.asyncio
async def test_fallback_does_not_override_when_llm_returns_value():
    """LLM zaten bir değer döndürdüyse fallback override etmemeli."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=True, requested_chart_type="bar_chart")
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="sunburst grafik ver")]}
    result = await node(state)
    assert result["requested_chart_type"] == "bar_chart"


@pytest.mark.asyncio
async def test_fallback_inactive_when_no_visualization():
    """wants_visualization=False ve use_result_type=None ise fallback çalışmamalı."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=False, use_result_type=None, requested_chart_type=None)
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="sunbrust grafik ver")]}
    result = await node(state)
    assert result["requested_chart_type"] is None


@pytest.mark.asyncio
async def test_fallback_active_on_revisualize_path():
    """use_result_type=revisualize + LLM None → fallback devreye girmeli."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(
        intent_type="USE_RESULT",
        wants_visualization=False,   # revisualize path'inde LLM bunu False bırakabilir
        use_result_type="revisualize",
        requested_chart_type=None,
    )
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="bunu sunbrust olarak göster")]}
    result = await node(state)
    assert result["requested_chart_type"] == "sunburst"


@pytest.mark.asyncio
async def test_fallback_returns_none_when_no_keyword():
    """Keyword yoksa fallback None bırakmalı."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=True, requested_chart_type=None)
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="son 3 aydaki satışları karşılaştır")]}
    result = await node(state)
    assert result["requested_chart_type"] is None
