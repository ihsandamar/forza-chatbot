# Local Debug Tracer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Her LangGraph node'unun giriş/çıkış state'ini `logs/debug/<session_id>.jsonl` dosyasına yazan, `DEBUG_TRACE=1` ile aktive edilen, `@debug_node` decorator tabanlı local debug sistemi.

**Architecture:** `src/services/debug_tracer.py` tek dosya olarak tüm mantığı barındırır (decorator, serializer, writer, retention). `@debug_node("node_name")` decorator'ı her node factory'nin iç async fonksiyonuna eklenir. `contextvars.ContextVar` ile `session_id` subgraph node'larına aktarılır (çünkü Text2SQLState ve VisualizationState'te `session_id` field'ı yoktur).

**Tech Stack:** Python stdlib (`json`, `pathlib`, `contextvars`, `asyncio`, `functools`), `langchain_core.messages.BaseMessage`, `pytest`, `pytest-asyncio`

---

## File Map

| Eylem | Dosya |
|-------|-------|
| Oluştur | `src/services/debug_tracer.py` |
| Oluştur | `tests/unit/test_debug_tracer.py` |
| Değiştir | `src/graphs/report_agent/nodes.py` |
| Değiştir | `src/graphs/report_agent/subagents/text2sql/nodes.py` |
| Değiştir | `src/graphs/report_agent/subagents/visualization_v2/nodes.py` |
| Oluştur | `tools/read_trace.py` |

---

## Task 1: `debug_tracer.py` — Core Module

**Files:**
- Create: `src/services/debug_tracer.py`
- Create: `tests/unit/test_debug_tracer.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_debug_tracer.py -v
```

Expected: ImportError — `src.services.debug_tracer` not found.

- [ ] **Step 3: Implement `src/services/debug_tracer.py`**

```python
# src/services/debug_tracer.py
from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage

_ENABLED: bool = os.getenv("DEBUG_TRACE", "0") == "1"
_LOG_DIR: Path = Path(os.getenv("DEBUG_TRACE_DIR", "logs/debug"))
_MAX_SESSIONS: int = 10

_current_session: contextvars.ContextVar[str] = contextvars.ContextVar(
    "debug_session_id", default="unknown"
)


def _safe_default(obj: Any) -> Any:
    if isinstance(obj, BaseMessage):
        return {"type": obj.__class__.__name__, "content": str(obj.content)[:500]}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _serialize_state(state: Any) -> Any:
    if isinstance(state, dict):
        return {k: _serialize_state(v) for k, v in state.items()}
    if isinstance(state, list):
        return [_serialize_state(i) for i in state]
    try:
        json.dumps(state)
        return state
    except (TypeError, ValueError):
        return _safe_default(state)


def _get_turn(state: dict) -> int:
    from langchain_core.messages import HumanMessage
    return sum(1 for m in state.get("messages", []) if isinstance(m, HumanMessage))


def _enforce_retention(log_dir: Path, max_sessions: int = _MAX_SESSIONS) -> None:
    files = sorted(log_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
    for old in files[:-max_sessions]:
        old.unlink(missing_ok=True)


def _write_event(session_id: str, node_name: str, event: str, state: Any) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _LOG_DIR / f"{session_id}.jsonl"

    if not log_file.exists():
        _enforce_retention(_LOG_DIR)

    turn = _get_turn(state) if isinstance(state, dict) else 0
    record = {
        "ts": datetime.utcnow().isoformat(timespec="microseconds"),
        "node": node_name,
        "event": event,
        "turn": turn,
        "state": _serialize_state(state),
    }
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=_safe_default) + "\n")


def debug_node(node_name: str):
    """Decorator: node giriş/çıkış state'ini JSONL'e yazar. DEBUG_TRACE=0 ise no-op."""

    def decorator(fn):
        if not _ENABLED:
            return fn

        @functools.wraps(fn)
        async def async_wrapper(state: dict, **kwargs) -> dict:
            sid = state.get("session_id") or _current_session.get()
            if state.get("session_id"):
                _current_session.set(state["session_id"])
            _write_event(sid, node_name, "enter", state)
            result = await fn(state, **kwargs)
            _write_event(sid, node_name, "exit", result or {})
            return result

        @functools.wraps(fn)
        def sync_wrapper(state: dict, **kwargs) -> dict:
            sid = state.get("session_id") or _current_session.get()
            if state.get("session_id"):
                _current_session.set(state["session_id"])
            _write_event(sid, node_name, "enter", state)
            result = fn(state, **kwargs)
            _write_event(sid, node_name, "exit", result or {})
            return result

        return async_wrapper if asyncio.iscoroutinefunction(fn) else sync_wrapper

    return decorator
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_debug_tracer.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/debug_tracer.py tests/unit/test_debug_tracer.py
git commit -m "feat(debug): add debug_tracer module with decorator, serializer, retention"
```

---

## Task 2: Report Agent Nodes Integration

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`

7 node: `classify_intent`, `modify_sql`, `extract_entity`, `compute_results`, `report_chat`, `build_response`, `hitl_check`

- [ ] **Step 1: Add import at top of file**

`src/graphs/report_agent/nodes.py` dosyasının import bloğuna ekle (diğer `from src.` importlarının yanına):

```python
from src.services.debug_tracer import debug_node
```

- [ ] **Step 2: Decorate inner functions**

Her factory'nin iç `async def` satırının üstüne `@debug_node(...)` ekle.

`create_classify_intent_node` içinde:
```python
        @debug_node("classify_intent")
        async def classify_intent_node(state: dict) -> dict:
```

`create_modify_sql_node` içinde (`async def modify_sql_node` satırı):
```python
        @debug_node("modify_sql")
        async def modify_sql_node(state: dict) -> dict:
```

`create_extract_entity_node` içinde:
```python
        @debug_node("extract_entity")
        async def extract_entity_node(state: dict) -> dict:
```

`create_compute_results_node` içinde (fonksiyon adını grep ile bul):
```python
        @debug_node("compute_results")
        async def compute_results_node(state: dict) -> dict:
```

`create_report_chat_node` içinde:
```python
        @debug_node("report_chat")
        async def report_chat_node(state: dict) -> dict:
```

`create_build_response_node` içinde:
```python
        @debug_node("build_response")
        async def build_response_node(state: dict) -> dict:
```

`hitl_check_node` — factory yok, standalone:
```python
@debug_node("hitl_check")
async def hitl_check_node(state: dict) -> dict:
```

- [ ] **Step 3: Run existing tests to verify no regressions**

```
pytest tests/ -x -q --ignore=tests/integration
```

Expected: All tests PASS (decorator is no-op since `DEBUG_TRACE` env var is not set in test env).

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/nodes.py
git commit -m "feat(debug): add @debug_node to report_agent nodes (7 nodes)"
```

---

## Task 3: Text2SQL Nodes Integration

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

10 node: `create_table`, `business_rules`, `semantic_extractor`, `term_resolver`, `term_validator`, `schema_builder`, `value_resolver`, `sql_generator`, `sql_executor`, `cleanup_table`

- [ ] **Step 1: Add import**

`src/graphs/report_agent/subagents/text2sql/nodes.py` dosyasına import ekle:

```python
from src.services.debug_tracer import debug_node
```

- [ ] **Step 2: Decorate `create_create_table_node` iç fonksiyonu**

```python
        @debug_node("create_table")
        async def create_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
```

- [ ] **Step 3: Decorate `create_business_rules_node` iç fonksiyonu**

```python
        @debug_node("business_rules")
        async def business_rules_node(state: dict) -> dict:
```

- [ ] **Step 4: Decorate `create_semantic_extractor_node` iç fonksiyonu**

`create_semantic_extractor_node` factory'sini bul (line ~1382), içindeki async fonksiyona ekle:

```python
        @debug_node("semantic_extractor")
        async def semantic_extractor_node(state: dict) -> dict:
```

- [ ] **Step 5: Decorate `create_term_resolver_node` iç fonksiyonu**

`create_term_resolver_node` factory'sini bul (line ~421), içindeki async fonksiyona ekle:

```python
        @debug_node("term_resolver")
        async def term_resolver_node(state: dict) -> dict:
```

- [ ] **Step 6: Decorate `create_term_validator_node` iç fonksiyonu**

`create_term_validator_node` factory'sini bul (line ~626), içindeki async fonksiyona ekle:

```python
        @debug_node("term_validator")
        async def term_validator_node(state: dict) -> dict:
```

- [ ] **Step 7: Decorate `create_schema_builder_node` iç fonksiyonu**

`create_schema_builder_node` factory'sini bul (line ~1448), içindeki async fonksiyona ekle:

```python
        @debug_node("schema_builder")
        async def schema_builder_node(state: dict) -> dict:
```

- [ ] **Step 8: Decorate `create_value_resolver_node` iç fonksiyonu**

`create_value_resolver_node` factory'sini bul (line ~695), içindeki async fonksiyona ekle:

```python
        @debug_node("value_resolver")
        async def value_resolver_node(state: dict) -> dict:
```

- [ ] **Step 9: Decorate `create_sql_generator_node` iç fonksiyonu**

`create_sql_generator_node` factory'sini bul (line ~1047), içindeki async fonksiyona ekle:

```python
        @debug_node("sql_generator")
        async def sql_generator_node(state: dict, *, config: RunnableConfig = None) -> dict:
```

- [ ] **Step 10: Decorate `create_sql_executor_node` iç fonksiyonu**

`create_sql_executor_node` factory'sini bul (line ~1306), içindeki async fonksiyona ekle:

```python
        @debug_node("sql_executor")
        async def sql_executor_node(state: dict) -> dict:
```

- [ ] **Step 11: Decorate `create_cleanup_table_node` iç fonksiyonu**

`create_cleanup_table_node` factory'sini bul (line ~1651), içindeki async fonksiyona ekle:

```python
        @debug_node("cleanup_table")
        async def cleanup_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
```

- [ ] **Step 12: Run existing tests**

```
pytest tests/ -x -q --ignore=tests/integration
```

Expected: All tests PASS.

- [ ] **Step 13: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(debug): add @debug_node to text2sql nodes (10 nodes)"
```

---

## Task 4: Visualization Nodes Integration

**Files:**
- Modify: `src/graphs/report_agent/subagents/visualization_v2/nodes.py`

5 node: `data_analyzer`, `viz_decider`, `spec_validator`, `template_renderer`, `response_builder`

- [ ] **Step 1: Add import**

```python
from src.services.debug_tracer import debug_node
```

- [ ] **Step 2: Decorate standalone node'ları**

`data_analyzer_node` (line ~104) — standalone:
```python
@debug_node("data_analyzer")
async def data_analyzer_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
```

`spec_validator_node` (line ~401) — standalone:
```python
@debug_node("spec_validator")
async def spec_validator_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
```

`template_renderer_node` (line ~421) — standalone:
```python
@debug_node("template_renderer")
async def template_renderer_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
```

`response_builder_node` (line ~452) — standalone:
```python
@debug_node("response_builder")
async def response_builder_node(state: dict) -> dict:
```

- [ ] **Step 3: Decorate `create_viz_decider_node` iç fonksiyonu**

`create_viz_decider_node` factory (line ~293), içindeki async fonksiyona:
```python
        @debug_node("viz_decider")
        async def viz_decider_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
```

- [ ] **Step 4: Run existing tests**

```
pytest tests/ -x -q --ignore=tests/integration
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization_v2/nodes.py
git commit -m "feat(debug): add @debug_node to visualization nodes (5 nodes)"
```

---

## Task 5: Developer CLI Tool

**Files:**
- Create: `tools/read_trace.py`

- [ ] **Step 1: Create `tools/read_trace.py`**

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
            lines = sum(1 for _ in f.open(encoding="utf-8"))
            print(f"  {f.stem}  ({lines} events, {size_kb}KB)")
        return

    log_file = log_dir / f"{args.session_id}.jsonl"
    if not log_file.exists():
        print(f"[ERROR] No trace file: {log_file}")
        files = sorted(log_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        if files:
            print("Available sessions:")
            for f in files:
                print(f"  {f.stem}")
        return

    events = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if args.turn is not None:
        events = [e for e in events if e.get("turn") == args.turn]
    if args.node:
        events = [e for e in events if e.get("node") == args.node]

    print(f"[SESSION] {args.session_id}  ({len(events)} events)")
    print("=" * 72)

    for evt in events:
        ts = evt.get("ts", "")
        ts_short = ts[11:26] if len(ts) > 19 else ts  # HH:MM:SS.ffffff
        node = evt.get("node", "?")
        event = evt.get("event", "?")
        turn = evt.get("turn", 0)
        state = evt.get("state", {})

        arrow = "→" if event == "enter" else "←"
        print(f"\n[T{turn}] {ts_short}  {arrow} {node}")

        if args.full:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        elif isinstance(state, dict):
            for k, v in state.items():
                if v is None or v == [] or v == {} or v == "":
                    continue
                print(f"  {k}: {_summary_line(v)}")
        else:
            print(f"  {_summary_line(state)}")

    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test CLI manually**

`DEBUG_TRACE=1` aktif değilken:
```
python tools/read_trace.py --list
```
Expected: "No trace files in logs/debug" veya mevcut session listesi.

`.env` dosyasına `DEBUG_TRACE=1` ekle, uygulamayı bir kez çalıştır, sonra:
```
python tools/read_trace.py --list
python tools/read_trace.py <session_id>
python tools/read_trace.py <session_id> --turn 1
python tools/read_trace.py <session_id> --node classify_intent --full
```

Expected: Turn ve node bilgileri, state field'ları listelenir.

- [ ] **Step 3: Commit**

```bash
git add tools/read_trace.py
git commit -m "feat(debug): add read_trace.py CLI for local JSONL trace inspection"
```

---

## Task 6: Environment Variable

**Files:**
- Modify: `.env.example` (varsa)
- Modify: `.env`

- [ ] **Step 1: `.env`'e `DEBUG_TRACE` ekle (kapalı)**

`.env` dosyasına ekle:
```env
DEBUG_TRACE=0
DEBUG_TRACE_DIR=logs/debug
```

- [ ] **Step 2: `.gitignore`'a `logs/debug/` ekle**

```
logs/debug/
```

- [ ] **Step 3: Commit**

```bash
git add .env .gitignore
git commit -m "chore: add DEBUG_TRACE env var and gitignore logs/debug"
```

---

## Self-Review

**Spec coverage check:**

| Spec gereksinimi | Task |
|-----------------|------|
| `@debug_node` decorator | Task 1 |
| `DEBUG_TRACE=1` kontrol | Task 1 (\_ENABLED) |
| JSONL format — ts/node/event/turn/state | Task 1 (\_write\_event) |
| session\_id via contextvars | Task 1 (\_current\_session) |
| JSON serialization — BaseMessage, datetime, Decimal | Task 1 (\_safe\_default) |
| Retention — 10 session | Task 1 (\_enforce\_retention) |
| report\_agent nodes (7) | Task 2 |
| text2sql nodes (10) | Task 3 |
| visualization nodes (5) | Task 4 |
| `tools/read_trace.py` | Task 5 |
| `.env` + `.gitignore` | Task 6 |
| config kwargs pass-through | Task 1 (async\_wrapper **kwargs) |

**Placeholder scan:** Tüm code blokları tam içeriklidir, TBD/TODO yok.

**Type consistency:** `debug_node` Task 1'de tanımlanıyor, Task 2-4'te aynı isimle import edilip kullanılıyor. `_write_event` signature Task 1'de sabit, tüm referanslar eşleşiyor.
