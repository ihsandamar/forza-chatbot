import json
import pytest
from pathlib import Path


def test_read_trace_data_missing_directory(tmp_path):
    from tools.read_trace import _read_trace_data
    result = _read_trace_data("any-session", log_dir=str(tmp_path / "nonexistent"))
    assert result["event_count"] == 0
    assert "No trace directory" in result["summary"]
    assert result["events"] == []
    assert result["session_id"] == "any-session"


def test_read_trace_data_missing_session(tmp_path):
    from tools.read_trace import _read_trace_data
    result = _read_trace_data("missing-session", log_dir=str(tmp_path))
    assert result["event_count"] == 0
    assert "Session not found" in result["summary"]
    assert result["events"] == []


def test_read_trace_data_returns_events(tmp_path):
    from tools.read_trace import _read_trace_data
    log_file = tmp_path / "test-session.jsonl"
    events = [
        {"ts": "2026-05-07T10:00:00.000000+00:00", "node": "classify_intent", "event": "enter", "turn": 1, "state": {"user_query": "hello"}},
        {"ts": "2026-05-07T10:00:01.000000+00:00", "node": "classify_intent", "event": "exit",  "turn": 0, "state": {"intent_type": "NEW_QUERY"}},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    result = _read_trace_data("test-session", log_dir=str(tmp_path))
    assert result["event_count"] == 2
    assert result["session_id"] == "test-session"
    assert len(result["events"]) == 2
    assert "classify_intent" in result["summary"]


def test_read_trace_data_filters_by_node(tmp_path):
    from tools.read_trace import _read_trace_data
    log_file = tmp_path / "test-session.jsonl"
    events = [
        {"ts": "2026-05-07T10:00:00.000000+00:00", "node": "classify_intent", "event": "enter", "turn": 1, "state": {}},
        {"ts": "2026-05-07T10:00:01.000000+00:00", "node": "sql_generator",    "event": "enter", "turn": 1, "state": {}},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    result = _read_trace_data("test-session", node="classify_intent", log_dir=str(tmp_path))
    assert result["event_count"] == 1
    assert result["events"][0]["node"] == "classify_intent"


def test_read_trace_data_filters_by_turn(tmp_path):
    from tools.read_trace import _read_trace_data
    log_file = tmp_path / "test-session.jsonl"
    events = [
        {"ts": "2026-05-07T10:00:00.000000+00:00", "node": "classify_intent", "event": "enter", "turn": 1, "state": {}},
        {"ts": "2026-05-07T10:00:01.000000+00:00", "node": "classify_intent", "event": "enter", "turn": 2, "state": {}},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    result = _read_trace_data("test-session", turn=1, log_dir=str(tmp_path))
    assert result["event_count"] == 1
    assert result["events"][0]["turn"] == 1


def test_read_trace_data_skips_malformed_lines(tmp_path):
    from tools.read_trace import _read_trace_data
    log_file = tmp_path / "test-session.jsonl"
    log_file.write_text(
        '{"ts": "2026-05-07T10:00:00.000000+00:00", "node": "a", "event": "enter", "turn": 1, "state": {}}\n'
        'not valid json\n'
        '{"ts": "2026-05-07T10:00:01.000000+00:00", "node": "b", "event": "exit",  "turn": 1, "state": {}}\n',
        encoding="utf-8",
    )
    result = _read_trace_data("test-session", log_dir=str(tmp_path))
    assert result["event_count"] == 2


def test_read_trace_data_returns_summary_and_events_keys(tmp_path):
    from tools.read_trace import _read_trace_data
    log_file = tmp_path / "sess.jsonl"
    log_file.write_text(
        json.dumps({"ts": "2026-05-07T10:00:00.000000+00:00", "node": "n", "event": "enter", "turn": 1, "state": {"k": "v"}}),
        encoding="utf-8",
    )
    result = _read_trace_data("sess", log_dir=str(tmp_path))
    assert isinstance(result["summary"], str)
    assert isinstance(result["events"], list)
    assert isinstance(result["event_count"], int)
    assert isinstance(result["session_id"], str)
