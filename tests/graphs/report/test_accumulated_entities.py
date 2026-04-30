"""Tests for accumulated_entities cross-turn context mechanism."""
from src.graphs.report_agent.state import create_initial_state


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
