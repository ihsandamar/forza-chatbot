def test_mcp_server_has_read_trace_tool():
    from tools.mcp_debug_tracer import read_trace
    assert callable(read_trace)


def test_mcp_read_trace_returns_expected_structure(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBUG_TRACE_DIR", str(tmp_path))
    from tools.mcp_debug_tracer import read_trace
    result = read_trace("definitely-nonexistent-session-xyz-abc")
    assert isinstance(result, dict)
    assert "summary" in result
    assert "events" in result
    assert "event_count" in result
    assert "session_id" in result
    assert result["event_count"] == 0
    assert result["session_id"] == "definitely-nonexistent-session-xyz-abc"
