import pytest
from src.api.models.responses.chat import StreamEvent


def test_stream_event_progress():
    e = StreamEvent(
        event_type="progress",
        step="sql_executor",
        message="Veriler çekiliyor...",
        index=9,
        total=13,
    )
    assert e.event_type == "progress"
    assert e.step == "sql_executor"
    assert e.index == 9
    assert e.total == 13
    assert e.text is None  # result fields are absent


def test_stream_event_result_report():
    e = StreamEvent(
        event_type="result",
        text="Grafik hazır",
        type="report",
        confidence=0.85,
        action={"type": "chart", "target": "<iframe>", "params": {}},
    )
    assert e.event_type == "result"
    assert e.type == "report"
    assert e.step is None  # progress fields are absent
    assert e.action == {"type": "chart", "target": "<iframe>", "params": {}}
    assert e.confidence == 0.85


def test_stream_event_error():
    e = StreamEvent(event_type="error", message="Hata oluştu")
    assert e.event_type == "error"
    assert e.message == "Hata oluştu"
    assert e.text is None
    assert e.step is None
