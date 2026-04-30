"""Tests for accumulated_entities cross-turn context mechanism."""
from src.graphs.report_agent.state import create_initial_state
from src.graphs.report_agent.context_builder import build_query_context_summary


def test_initial_state_has_accumulated_entities_none():
    """accumulated_entities başlangıçta None olmalı."""
    state = create_initial_state()
    assert "accumulated_entities" in state
    assert state["accumulated_entities"] is None


def test_accumulated_entities_field_in_report_state():
    """ReportState TypedDict'inde accumulated_entities field'ı tanımlı olmalı."""
    from src.graphs.report_agent.state import ReportState
    # TypedDict annotation'larını kontrol et
    annotations = ReportState.__annotations__
    assert "accumulated_entities" in annotations


def test_text2sql_state_has_accumulated_entities():
    """Text2SQLState'de de overlapping field olarak tanımlı olmalı."""
    from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
    annotations = Text2SQLState.__annotations__
    assert "accumulated_entities" in annotations


def test_context_builder_includes_accumulated_entities():
    """Accumulated entities LLM context'inde görünmeli."""
    accumulated = [
        {"column": "ProductName", "value": "LAS VEGAS UC PEYNIRLI BAGEL"},
        {"column": "ProductName", "value": "LATTE"},
    ]
    result = build_query_context_summary(
        active_results=None,
        active_filters=None,
        accumulated_entities=accumulated,
    )
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in result
    assert "LATTE" in result
    assert "ProductName" in result


def test_context_builder_without_accumulated_unchanged():
    """accumulated_entities=None olduğunda eski davranış korunmalı."""
    active_results = [{"BranchName": "Ankara", "ToplamCiro": 1000.0}]
    result = build_query_context_summary(
        active_results=active_results,
        active_filters=None,
        accumulated_entities=None,
    )
    assert "Ankara" in result
    assert "Konuşmada geçen" not in result


def test_context_builder_accumulated_grouped_by_column():
    """Farklı kolonlardan entity'ler ayrı satırlarda gruplu görünmeli."""
    accumulated = [
        {"column": "ProductName", "value": "LATTE"},
        {"column": "BranchName", "value": "Ankara"},
        {"column": "ProductName", "value": "FINCAN CAY"},
    ]
    result = build_query_context_summary(
        active_results=None,
        active_filters=None,
        accumulated_entities=accumulated,
    )
    assert "ProductName" in result
    assert "BranchName" in result
    assert "LATTE" in result
    assert "Ankara" in result


def test_context_builder_no_duplicate_in_accumulated():
    """Aynı değer accumulated'da iki kez var olsa bile context'te tek görünmeli."""
    accumulated = [
        {"column": "ProductName", "value": "LATTE"},
        {"column": "ProductName", "value": "LATTE"},  # duplicate
    ]
    result = build_query_context_summary(
        active_results=None,
        active_filters=None,
        accumulated_entities=accumulated,
    )
    # LATTE sadece bir kez görünmeli
    assert result.count("LATTE") == 1


import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_core.messages import HumanMessage
from src.graphs.report_agent.nodes import create_classify_intent_node
from src.graphs.report_agent.prompts import IntentClassificationResult
from src.graphs.report_agent.subagents.text2sql.nodes import (
    create_sql_executor_node,
    _merge_accumulated_entities,
)


def _make_classify_node(intent_type: str, query_type: str = "RANKING"):
    """Test helper: intent_type ve query_type ile classify node oluştur."""
    mock_llm = MagicMock()
    result = IntentClassificationResult(
        intent_type=intent_type,
        query_type=query_type,
        confidence=0.95,
        wants_visualization=False,
        time_breakdown=False,
    )
    mock_structured = MagicMock()
    mock_structured.ainvoke = AsyncMock(return_value=result)
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
    return create_classify_intent_node(mock_llm)


def test_classify_intent_resets_accumulated_entities_on_new_query():
    """NEW_QUERY'de accumulated_entities sıfırlanmalı."""
    node = _make_classify_node("NEW_QUERY")
    state = {
        "messages": [HumanMessage(content="farklı bir soru")],
        "active_sql": None,
        "active_results": [],
        "accumulated_entities": [{"column": "ProductName", "value": "LATTE"}],
        "_clarification_count": 0,
        "_skip_vague_check": False,
    }
    result = asyncio.run(node(state))
    assert result["accumulated_entities"] is None


def test_classify_intent_preserves_accumulated_entities_on_modify_query():
    """MODIFY_QUERY'de accumulated_entities korunmalı."""
    node = _make_classify_node("MODIFY_QUERY")
    accumulated = [{"column": "ProductName", "value": "LATTE"}]
    state = {
        "messages": [HumanMessage(content="filtrele")],
        "active_sql": "SELECT * FROM T",
        "active_results": [],
        "accumulated_entities": accumulated,
        "_clarification_count": 0,
        "_skip_vague_check": False,
    }
    result = asyncio.run(node(state))
    assert result["accumulated_entities"] == accumulated


def test_classify_intent_preserves_accumulated_entities_on_use_result():
    """USE_RESULT'da accumulated_entities korunmalı."""
    mock_llm = MagicMock()
    llm_result = IntentClassificationResult(
        intent_type="USE_RESULT",
        query_type="SINGLE",
        confidence=0.95,
        wants_visualization=False,
        use_result_type="compute",
        time_breakdown=False,
    )
    mock_structured = MagicMock()
    mock_structured.ainvoke = AsyncMock(return_value=llm_result)
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
    node = create_classify_intent_node(mock_llm)

    accumulated = [{"column": "BranchName", "value": "Ankara"}]
    state = {
        "messages": [HumanMessage(content="toplamı nedir")],
        "active_sql": "SELECT * FROM T",
        "active_results": [{"ToplamCiro": 1000.0}],
        "accumulated_entities": accumulated,
        "_clarification_count": 0,
        "_skip_vague_check": False,
    }
    result = asyncio.run(node(state))
    assert result["accumulated_entities"] == accumulated


def test_classify_intent_preserves_accumulated_entities_on_vague_query():
    """VAGUE_QUERY'de accumulated_entities korunmalı."""
    node = _make_classify_node("VAGUE_QUERY")
    accumulated = [{"column": "CategoryName", "value": "KAHVELER"}]
    state = {
        "messages": [HumanMessage(content="detaylar")],
        "active_sql": None,
        "active_results": [],
        "accumulated_entities": accumulated,
        "_clarification_count": 0,
        "_skip_vague_check": False,
    }
    result = asyncio.run(node(state))
    assert result["accumulated_entities"] == accumulated


def test_merge_accumulated_entities_adds_new_string_values():
    existing = [{"column": "ProductName", "value": "LATTE"}]
    results = [
        {"ProductName": "FINCAN CAY", "ToplamCiro": 1000.0},
        {"ProductName": "LATTE", "ToplamCiro": 500.0},
    ]
    merged = _merge_accumulated_entities(existing, results)
    values = [e["value"] for e in merged if e["column"] == "ProductName"]
    assert "LATTE" in values
    assert "FINCAN CAY" in values
    assert values.count("LATTE") == 1


def test_merge_accumulated_entities_caps_at_max():
    existing = [{"column": "ProductName", "value": f"P{i}"} for i in range(95)]
    results = [{"ProductName": f"Q{i}", "ToplamCiro": float(i)} for i in range(20)]
    merged = _merge_accumulated_entities(existing, results)
    assert len(merged) <= 100


def test_merge_accumulated_entities_skips_non_string():
    results = [{"ProductName": "LATTE", "ToplamCiro": 45000.0, "Quantity": 100}]
    merged = _merge_accumulated_entities(None, results)
    cols = [e["column"] for e in merged]
    assert "ToplamCiro" not in cols
    assert "Quantity" not in cols
    assert "ProductName" in cols


def test_sql_executor_node_updates_accumulated_entities():
    existing = [{"column": "ProductName", "value": "LAS VEGAS UC PEYNIRLI BAGEL"}]
    results = [{"ProductName": "LATTE", "ToplamCiro": 45000.0}]
    state = {
        "sql_queries": ["SELECT * FROM T"],
        "retry_count": 0,
        "query_schema": {},
        "accumulated_entities": existing,
    }

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql_async",
        new=AsyncMock(return_value=results),
    ):
        node = create_sql_executor_node("mssql+pyodbc://dummy")
        output = asyncio.run(node(state))

    acc = output["accumulated_entities"]
    values = [e["value"] for e in acc]
    assert "LAS VEGAS UC PEYNIRLI BAGEL" in values
    assert "LATTE" in values
