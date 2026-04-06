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
    chart_type=None,
    chart_llm_raises=None,
):
    """Mock LLM for parallel chart type detection tests.

    with_structured_output is called twice:
      1st call → IntentClassificationResult chain
      2nd call → ChartTypeResult chain
    """
    from src.graphs.report_agent.prompts import IntentClassificationResult, ChartTypeResult

    mock_intent = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=confidence,
        wants_visualization=wants_visualization,
        use_result_type=use_result_type,
    )
    mock_chart = ChartTypeResult(chart_type=chart_type)

    intent_chain = MagicMock()
    intent_chain.ainvoke = AsyncMock(return_value=mock_intent)

    chart_chain = MagicMock()
    if chart_llm_raises:
        chart_chain.ainvoke = AsyncMock(side_effect=chart_llm_raises)
    else:
        chart_chain.ainvoke = AsyncMock(return_value=mock_chart)

    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(
        side_effect=[intent_chain, chart_chain]
    )
    return mock_llm


@pytest.mark.asyncio
async def test_fallback_sets_sunburst_when_llm_returns_none():
    """Root cause: LLM None döndüğünde 'sunbrust' fallback ile sunburst olmalı."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=True, chart_type=None)
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="son 3 aydaki satışları sunbrust grafik ile göster")]}
    result = await node(state)
    assert result["requested_chart_type"] == "sunburst"


@pytest.mark.asyncio
async def test_fallback_does_not_override_when_llm_returns_value():
    """LLM zaten bir değer döndürdüyse fallback override etmemeli."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=True, chart_type="bar_chart")
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="sunburst grafik ver")]}
    result = await node(state)
    assert result["requested_chart_type"] == "bar_chart"


@pytest.mark.asyncio
async def test_fallback_inactive_when_no_visualization():
    """wants_visualization=False, use_result_type=None ve chart keyword yok → None beklenir."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=False, use_result_type=None, chart_type=None)
    node = create_classify_intent_node(llm)
    # Sorguda chart keyword YOK — explicit_chart=None → wants_viz=False → chart_type=None
    state = {"messages": [HumanMessage(content="son 3 aydaki satışları karşılaştır")]}
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
        chart_type=None,
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

    llm = _make_mock_llm(wants_visualization=True, chart_type=None)
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="son 3 aydaki satışları karşılaştır")]}
    result = await node(state)
    assert result["requested_chart_type"] is None


@pytest.mark.asyncio
async def test_chart_llm_exception_falls_back_to_keyword_detection():
    """chart_llm Exception fırlatırsa keyword fallback devreye girmeli, node çökmemeli."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(
        wants_visualization=True,
        chart_llm_raises=RuntimeError("OpenAI rate limit"),
    )
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="sunburst grafik ver")]}
    result = await node(state)
    assert result["requested_chart_type"] == "sunburst"


@pytest.mark.asyncio
async def test_parallel_chart_llm_value_used_when_wants_viz():
    """chart LLM sonucu doğrudan kullanılmalı."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=True, chart_type="treemap")
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="kategorilerin alt kırılımını göster")]}
    result = await node(state)
    assert result["requested_chart_type"] == "treemap"


@pytest.mark.asyncio
async def test_chart_type_none_when_no_viz_requested():
    """wants_visualization=False olduğunda chart LLM sonucu kullanılmamalı."""
    from langchain_core.messages import HumanMessage
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_mock_llm(wants_visualization=False, chart_type="sunburst")
    node = create_classify_intent_node(llm)
    state = {"messages": [HumanMessage(content="son 3 aydaki satışlar")]}
    result = await node(state)
    assert result["requested_chart_type"] is None
