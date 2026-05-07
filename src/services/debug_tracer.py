# src/services/debug_tracer.py
from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage

# Load .env before reading env vars — debug_tracer is imported before ConfigLoader runs load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=False)

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
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = _LOG_DIR / f"{session_id}.jsonl"

        if not log_file.exists():
            _enforce_retention(_LOG_DIR)

        turn = _get_turn(state) if isinstance(state, dict) else 0
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "node": node_name,
            "event": event,
            "turn": turn,
            "state": _serialize_state(state),
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=_safe_default) + "\n")
    except Exception:
        pass  # Tracer must never crash graph execution


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
