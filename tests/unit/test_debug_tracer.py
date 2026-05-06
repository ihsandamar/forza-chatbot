# tests/unit/test_debug_tracer.py
import json
import os
import asyncio
import pytest
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def test_safe_default_base_message():
    from langchain_core.messages import HumanMessage
    from src.services.debug_tracer import _safe_default
    msg = HumanMessage(content="hello world")
    result = _safe_default(msg)
    assert result == {"type": "HumanMessage", "content": "hello world"}


def test_safe_default_truncates_long_content():
    from langchain_core.messages import HumanMessage
    from src.services.debug_tracer import _safe_default
    msg = HumanMessage(content="x" * 600)
    result = _safe_default(msg)
    assert len(result["content"]) == 500


def test_safe_default_decimal():
    from src.services.debug_tracer import _safe_default
    assert _safe_default(Decimal("3.14")) == 3.14


def test_safe_default_datetime():
    from src.services.debug_tracer import _safe_default
    dt = datetime(2026, 5, 6, 9, 0, 0)
    assert _safe_default(dt) == "2026-05-06T09:00:00"


def test_safe_default_unknown_type():
    from src.services.debug_tracer import _safe_default
    class Weird:
        def __str__(self): return "weird"
    assert _safe_default(Weird()) == "weird"


def test_enforce_retention_deletes_oldest(tmp_path):
    import time
    from src.services.debug_tracer import _enforce_retention
    files = []
    for i in range(12):
        f = tmp_path / f"session_{i:02d}.jsonl"
        f.write_text("{}")
        time.sleep(0.02)
        files.append(f)

    _enforce_retention(tmp_path, max_sessions=10)

    remaining = list(tmp_path.glob("*.jsonl"))
    assert len(remaining) == 10
    assert not files[0].exists()
    assert not files[1].exists()
    assert files[11].exists()


def test_enforce_retention_noop_under_limit(tmp_path):
    from src.services.debug_tracer import _enforce_retention
    for i in range(5):
        (tmp_path / f"s{i}.jsonl").write_text("{}")
    _enforce_retention(tmp_path, max_sessions=10)
    assert len(list(tmp_path.glob("*.jsonl"))) == 5


def test_write_event_creates_jsonl(tmp_path):
    from src.services.debug_tracer import _write_event
    with patch("src.services.debug_tracer._LOG_DIR", tmp_path):
        _write_event("sess123", "classify_intent", "enter", {"user_query": "test"})

    log_file = tmp_path / "sess123.jsonl"
    assert log_file.exists()
    line = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert line["node"] == "classify_intent"
    assert line["event"] == "enter"
    assert line["state"]["user_query"] == "test"
    assert "ts" in line
    assert "turn" in line


def test_write_event_appends_multiple(tmp_path):
    from src.services.debug_tracer import _write_event
    with patch("src.services.debug_tracer._LOG_DIR", tmp_path):
        _write_event("sess1", "node_a", "enter", {})
        _write_event("sess1", "node_a", "exit", {"result": "ok"})

    lines = (tmp_path / "sess1.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "enter"
    assert json.loads(lines[1])["event"] == "exit"


def test_debug_node_noop_when_disabled():
    import src.services.debug_tracer as dt
    original = dt._ENABLED
    dt._ENABLED = False
    try:
        from src.services.debug_tracer import debug_node
        async def my_node(state): return {"out": 1}
        wrapped = debug_node("test")(my_node)
        assert wrapped is my_node
    finally:
        dt._ENABLED = original


@pytest.mark.asyncio
async def test_debug_node_writes_enter_and_exit_when_enabled(tmp_path):
    import src.services.debug_tracer as dt
    original = dt._ENABLED
    dt._ENABLED = True
    try:
        written = []
        with patch("src.services.debug_tracer._write_event", side_effect=lambda *a: written.append(a)):
            from src.services.debug_tracer import debug_node
            @debug_node("test_node")
            async def my_node(state): return {"out": 1}
            await my_node({"session_id": "sess_abc"})
        assert len(written) == 2
        assert written[0][1] == "test_node"
        assert written[0][2] == "enter"
        assert written[1][2] == "exit"
    finally:
        dt._ENABLED = original


@pytest.mark.asyncio
async def test_debug_node_passes_kwargs_through(tmp_path):
    import src.services.debug_tracer as dt
    original = dt._ENABLED
    dt._ENABLED = True
    try:
        received_kwargs = {}
        with patch("src.services.debug_tracer._write_event"):
            from src.services.debug_tracer import debug_node
            @debug_node("test_node")
            async def my_node(state, **kwargs):
                received_kwargs.update(kwargs)
                return {}
            await my_node({"session_id": "s"}, config={"key": "val"})
        assert received_kwargs == {"config": {"key": "val"}}
    finally:
        dt._ENABLED = original


def test_safe_default_date():
    from datetime import date
    from src.services.debug_tracer import _safe_default
    d = date(2026, 5, 6)
    assert _safe_default(d) == "2026-05-06"


def test_debug_node_sync_writes_enter_and_exit_when_enabled():
    import src.services.debug_tracer as dt
    original = dt._ENABLED
    dt._ENABLED = True
    try:
        written = []
        with patch("src.services.debug_tracer._write_event", side_effect=lambda *a: written.append(a)):
            from src.services.debug_tracer import debug_node
            @debug_node("sync_node")
            def my_sync_node(state): return {"out": 1}
            my_sync_node({"session_id": "sess_sync"})
        assert len(written) == 2
        assert written[0][2] == "enter"
        assert written[1][2] == "exit"
    finally:
        dt._ENABLED = original


def test_write_event_does_not_raise_on_bad_dir():
    from src.services.debug_tracer import _write_event
    from pathlib import Path
    # A path that cannot be created/written to
    with patch("src.services.debug_tracer._LOG_DIR", Path("/this/path/cannot/exist/on/any/os/xyz123")):
        # Should not raise, even with invalid directory
        try:
            _write_event("sess", "node", "enter", {})
        except Exception as e:
            pytest.fail(f"_write_event raised unexpectedly: {e}")
