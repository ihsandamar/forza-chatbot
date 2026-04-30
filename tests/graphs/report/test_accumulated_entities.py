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
