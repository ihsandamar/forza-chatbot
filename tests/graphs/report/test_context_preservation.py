import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import HumanMessage

from src.graphs.report_agent.prompts import IntentClassificationResult


def _make_llm_mock(intent_type: str, query_type: str = "RANKING", wants_viz: bool = False) -> MagicMock:
    result = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=0.95,
        wants_visualization=wants_viz,
        visualization_explicitly_set=False,
    )
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result)
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


@pytest.mark.asyncio
async def test_active_filters_preserved_on_modify_query():
    """MODIFY_QUERY'de active_filters state'den taşınmalı."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("MODIFY_QUERY")
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Ankara'yı ekle")],
        "active_sql": "SELECT * FROM T",
        "active_results": [{"BranchName": "Ankara", "RowAmount": 100}],
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["active_filters"] == [{"field": "CategoryName", "value": "Dürüm"}]


@pytest.mark.asyncio
async def test_active_filters_cleared_on_new_query():
    """NEW_QUERY'de active_filters temizlenmeli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("NEW_QUERY")
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Tüm şubeleri listele")],
        "active_sql": "SELECT * FROM T WHERE CategoryName='Dürüm'",
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["active_filters"] is None


@pytest.mark.asyncio
async def test_active_filters_none_when_state_empty():
    """State'de active_filters yoksa MODIFY_QUERY'de de None gelmeli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("MODIFY_QUERY")
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Limit'i 20 yap")],
        "active_sql": "SELECT * FROM T",
        "active_filters": None,
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["active_filters"] is None


# ---------------------------------------------------------------------------
# Task 2 — visualization inheritance tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wants_visualization_inherited_on_modify_when_not_addressed():
    """MODIFY_QUERY'de kullanıcı grafikten bahsetmemişse önceki wants_visualization korunmalı."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    # LLM: kullanıcı grafikten bahsetmedi → False (default), chart_type=None
    llm = _make_llm_mock("MODIFY_QUERY", wants_viz=False)
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Ankara'yı ekle")],
        "active_sql": "SELECT * FROM T",
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "wants_visualization": True,
        "requested_chart_type": "bar_chart",
        "chart_x_hint": "BranchName",
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["wants_visualization"] is True
    assert result["requested_chart_type"] == "bar_chart"
    assert result["chart_x_hint"] == "BranchName"


@pytest.mark.asyncio
async def test_wants_visualization_updated_when_explicitly_set():
    """MODIFY_QUERY'de kullanıcı açıkça grafik istedi → güncellenmeli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    result_obj = IntentClassificationResult(
        intent_type="MODIFY_QUERY",
        query_type="RANKING",
        confidence=0.95,
        wants_visualization=True,
        chart_type="pie_chart",
        visualization_explicitly_set=True,
    )
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result_obj)
    llm.with_structured_output = MagicMock(return_value=structured)
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Pasta grafik olarak göster")],
        "active_sql": "SELECT * FROM T",
        "active_filters": [],
        "wants_visualization": True,
        "requested_chart_type": "bar_chart",
        "chart_x_hint": None,
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["wants_visualization"] is True
    assert result["requested_chart_type"] == "pie_chart"


@pytest.mark.asyncio
async def test_wants_visualization_explicitly_removed():
    """MODIFY_QUERY'de kullanıcı açıkça grafiği kaldırdı → False olmalı."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    result_obj = IntentClassificationResult(
        intent_type="MODIFY_QUERY",
        query_type="RANKING",
        confidence=0.95,
        wants_visualization=False,
        visualization_explicitly_set=True,
    )
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result_obj)
    llm.with_structured_output = MagicMock(return_value=structured)
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Grafiği kaldır")],
        "active_sql": "SELECT * FROM T",
        "active_filters": [],
        "wants_visualization": True,
        "requested_chart_type": "bar_chart",
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["wants_visualization"] is False


@pytest.mark.asyncio
async def test_wants_visualization_not_inherited_on_new_query():
    """NEW_QUERY'de visualization state inherit edilmemeli — LLM kararı geçerli."""
    from src.graphs.report_agent.nodes import create_classify_intent_node

    llm = _make_llm_mock("NEW_QUERY", wants_viz=False)
    node = create_classify_intent_node(llm)

    state = {
        "messages": [HumanMessage(content="Tüm şubeleri listele")],
        "active_sql": None,
        "active_filters": None,
        "wants_visualization": True,
        "requested_chart_type": "bar_chart",
        "accumulated_entities": None,
    }

    result = await node(state)
    assert result["wants_visualization"] is False


# ---------------------------------------------------------------------------
# Task 3 — modify_sql_node filter delta propagation tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_modify_sql_propagates_updated_filters():
    """modify_sql_node SqlDelta'yı uygularken active_filters güncellenmeli."""
    from src.graphs.report_agent.nodes import create_modify_sql_node
    from src.graphs.report_agent.prompts import SqlDelta, FilterDelta

    delta = SqlDelta(
        add_filters=[FilterDelta(column="BranchName", operator="=", value="'Ankara'")],
        remove_filter_columns=[],
        explanation="Ankara filtresi eklendi",
        confidence=0.95,
    )

    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=delta)
    llm.with_structured_output = MagicMock(return_value=structured)

    node = create_modify_sql_node(llm, {})

    state = {
        "active_sql": "SELECT TOP 10 [BranchName], SUM([RowAmount]) FROM T GROUP BY [BranchName]",
        "active_filters": [{"field": "CategoryName", "value": "Dürüm"}],
        "active_results": [],
        "accumulated_entities": None,
        "user_query": "Ankara şubesini ekle",
    }

    result = await node(state)

    assert "active_filters" in result
    fields = {f["field"] for f in result["active_filters"]}
    assert "CategoryName" in fields
    assert "BranchName" in fields


@pytest.mark.asyncio
async def test_modify_sql_removes_filters_from_active():
    """modify_sql_node remove_filter_columns'daki filtreleri active_filters'dan çıkarmalı."""
    from src.graphs.report_agent.nodes import create_modify_sql_node
    from src.graphs.report_agent.prompts import SqlDelta, FilterDelta

    delta = SqlDelta(
        add_filters=[],
        remove_filter_columns=["CategoryName"],
        explanation="Kategori filtresi kaldırıldı",
        confidence=0.95,
    )

    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=delta)
    llm.with_structured_output = MagicMock(return_value=structured)

    node = create_modify_sql_node(llm, {})

    state = {
        "active_sql": "SELECT * FROM T WHERE CategoryName='Dürüm'",
        "active_filters": [
            {"field": "CategoryName", "value": "Dürüm"},
            {"field": "BranchName", "value": "Ankara"},
        ],
        "active_results": [],
        "accumulated_entities": None,
        "user_query": "Kategori filtresini kaldır",
    }

    result = await node(state)

    assert "active_filters" in result
    fields = [f["field"] for f in result["active_filters"]]
    assert "CategoryName" not in fields
    assert "BranchName" in fields
