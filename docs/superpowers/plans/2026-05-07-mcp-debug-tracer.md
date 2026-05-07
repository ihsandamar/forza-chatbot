# MCP Debug Tracer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose `read_trace` as a Claude MCP tool so Claude can call it directly during debug sessions without running a CLI command.

**Architecture:** `tools/read_trace.py` gets a reusable `_read_trace_data()` function extracted from its `main()`. A new `tools/mcp_debug_tracer.py` wraps it with FastMCP and exposes it as a single tool. A `.mcp.json` at project root registers the server with Claude Code.

**Tech Stack:** Python 3.12, `fastmcp>=2.0`, existing `tools/read_trace.py` logic

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `tools/read_trace.py` | Modify | Extract `_read_trace_data()` — reusable core logic |
| `tools/mcp_debug_tracer.py` | Create | FastMCP server, wraps `_read_trace_data` |
| `.mcp.json` | Create | Registers server with Claude Code |
| `requirements.txt` | Modify | Add `fastmcp>=2.0` |
| `tests/unit/test_read_trace.py` | Create | Tests for `_read_trace_data()` |
| `tests/unit/test_mcp_debug_tracer.py` | Create | Smoke test for MCP tool |

---

## Task 1: Install fastmcp

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Install the package**

```bash
pip install fastmcp
```

- [ ] **Step 2: Verify import works**

```bash
python -c "import fastmcp; print(fastmcp.__version__)"
```

Expected: version string printed (e.g. `2.x.x`), no errors.

- [ ] **Step 3: Add to requirements.txt**

Add this line after the `# API & Models` block in `requirements.txt`:

```
fastmcp>=2.0
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add fastmcp dependency for MCP debug tracer"
```

---

## Task 2: Extract `_read_trace_data()` from `read_trace.py`

**Files:**
- Modify: `tools/read_trace.py`
- Create: `tests/unit/test_read_trace.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_read_trace.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/unit/test_read_trace.py -v
```

Expected: FAIL — `ImportError: cannot import name '_read_trace_data' from 'tools.read_trace'`

- [ ] **Step 3: Replace `tools/read_trace.py` with this version**

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Local debug trace reader.

Usage:
    python tools/read_trace.py <session_id>
    python tools/read_trace.py <session_id> --node classify_intent
    python tools/read_trace.py <session_id> --turn 2
    python tools/read_trace.py <session_id> --turn 2 --node classify_intent --full
    python tools/read_trace.py --list
"""
import argparse
import json
import os
from pathlib import Path


def _summary_line(v) -> str:
    s = str(v)
    return s[:120].replace("\n", " ")


def _read_trace_data(
    session_id: str,
    node: str | None = None,
    turn: int | None = None,
    full: bool = False,
    log_dir: str | None = None,
) -> dict:
    """Read trace events for a session. Returns structured data + summary text."""
    dir_path = Path(log_dir or os.getenv("DEBUG_TRACE_DIR", "logs/debug"))

    if not dir_path.exists():
        return {
            "session_id": session_id,
            "event_count": 0,
            "summary": f"No trace directory: {dir_path}",
            "events": [],
        }

    log_file = dir_path / f"{session_id}.jsonl"
    if not log_file.exists():
        return {
            "session_id": session_id,
            "event_count": 0,
            "summary": f"Session not found: {session_id}",
            "events": [],
        }

    events = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if turn is not None:
        events = [e for e in events if e.get("turn") == turn]
    if node is not None:
        events = [e for e in events if e.get("node") == node]

    summary_lines = [f"[SESSION] {session_id}  ({len(events)} events)", "=" * 72]
    for evt in events:
        ts = evt.get("ts", "")
        ts_short = ts[11:26] if len(ts) > 19 else ts
        node_name = evt.get("node", "?")
        event = evt.get("event", "?")
        turn_num = evt.get("turn", 0)
        state = evt.get("state", {})

        arrow = "→" if event == "enter" else "←"
        summary_lines.append(f"\n[T{turn_num}] {ts_short}  {arrow} {node_name}")

        if full:
            summary_lines.append(json.dumps(state, ensure_ascii=False, indent=2))
        elif isinstance(state, dict):
            for k, v in state.items():
                if v is None or v == [] or v == {} or v == "":
                    continue
                summary_lines.append(f"  {k}: {_summary_line(v)}")
        else:
            summary_lines.append(f"  {_summary_line(state)}")

    summary_lines.append("\n" + "=" * 72)

    return {
        "session_id": session_id,
        "event_count": len(events),
        "summary": "\n".join(summary_lines),
        "events": events,
    }


def main():
    parser = argparse.ArgumentParser(description="Read local debug trace JSONL")
    parser.add_argument("session_id", nargs="?", help="Session ID (filename without .jsonl)")
    parser.add_argument("--node", help="Filter by node name")
    parser.add_argument("--turn", type=int, help="Filter by turn number")
    parser.add_argument("--full", action="store_true", help="Show full state JSON")
    parser.add_argument(
        "--dir",
        default=os.getenv("DEBUG_TRACE_DIR", "logs/debug"),
        help="Trace directory",
    )
    parser.add_argument("--list", action="store_true", help="List available sessions")
    args = parser.parse_args()

    log_dir = Path(args.dir)

    if args.list or not args.session_id:
        files = sorted(log_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            print(f"[INFO] No trace files in {log_dir}")
            return
        print(f"Available sessions in {log_dir}:")
        for f in files:
            size_kb = f.stat().st_size // 1024
            try:
                lines = sum(1 for _ in f.open(encoding="utf-8"))
            except OSError:
                lines = -1
            print(f"  {f.stem}  ({lines} events, {size_kb}KB)")
        return

    result = _read_trace_data(
        args.session_id,
        node=args.node,
        turn=args.turn,
        full=args.full,
        log_dir=args.dir,
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/unit/test_read_trace.py -v
```

Expected: 7 tests PASS

- [ ] **Step 5: Verify CLI still works**

```bash
python tools/read_trace.py --list
```

Expected: list of sessions printed (or "No trace files" message), no error.

- [ ] **Step 6: Commit**

```bash
git add tools/read_trace.py tests/unit/test_read_trace.py
git commit -m "refactor(debug): extract _read_trace_data() from read_trace CLI for reuse"
```

---

## Task 3: Create `tools/mcp_debug_tracer.py`

**Files:**
- Create: `tools/mcp_debug_tracer.py`
- Create: `tests/unit/test_mcp_debug_tracer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_mcp_debug_tracer.py`:

```python
def test_mcp_server_has_read_trace_tool():
    from tools.mcp_debug_tracer import read_trace
    assert callable(read_trace)


def test_mcp_read_trace_returns_expected_structure():
    from tools.mcp_debug_tracer import read_trace
    result = read_trace("definitely-nonexistent-session-xyz-abc")
    assert isinstance(result, dict)
    assert "summary" in result
    assert "events" in result
    assert "event_count" in result
    assert "session_id" in result
    assert result["event_count"] == 0
    assert result["session_id"] == "definitely-nonexistent-session-xyz-abc"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/unit/test_mcp_debug_tracer.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'tools.mcp_debug_tracer'`

- [ ] **Step 3: Create `tools/mcp_debug_tracer.py`**

```python
#!/usr/bin/env python
"""MCP server: exposes read_trace as a Claude tool."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastmcp import FastMCP
from tools.read_trace import _read_trace_data

mcp = FastMCP("forza-debug-tracer")


@mcp.tool()
def read_trace(
    session_id: str,
    node: str | None = None,
    turn: int | None = None,
    full: bool = False,
) -> dict:
    """Read a local debug trace JSONL file.

    Returns events list and human-readable summary.
    Use node/turn to filter. Set full=True for complete state JSON.
    """
    return _read_trace_data(session_id, node=node, turn=turn, full=full)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/unit/test_mcp_debug_tracer.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Smoke-test the server starts**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python tools/mcp_debug_tracer.py
```

Expected: JSON response containing `"name": "read_trace"`.

- [ ] **Step 6: Commit**

```bash
git add tools/mcp_debug_tracer.py tests/unit/test_mcp_debug_tracer.py
git commit -m "feat(debug): add MCP server exposing read_trace as a Claude tool"
```

---

## Task 4: Create `.mcp.json` and verify

**Files:**
- Create: `.mcp.json`

- [ ] **Step 1: Create `.mcp.json` at project root**

```json
{
  "mcpServers": {
    "forza-debug-tracer": {
      "type": "stdio",
      "command": "python",
      "args": ["tools/mcp_debug_tracer.py"],
      "env": {
        "DEBUG_TRACE_DIR": "logs/debug"
      }
    }
  }
}
```

- [ ] **Step 2: Run the full test suite to check no regressions**

```bash
python -m pytest tests/unit/ -v
```

Expected: All tests pass (including the 7 new `test_read_trace` and 2 new `test_mcp_debug_tracer`).

- [ ] **Step 3: Commit**

```bash
git add .mcp.json
git commit -m "feat(debug): add .mcp.json to register forza-debug-tracer MCP server with Claude Code"
```

- [ ] **Step 4: Reload Claude Code**

Restart Claude Code (or run `/mcp` to reload MCP servers). The `forza-debug-tracer` server should appear as connected with the `read_trace` tool available.
