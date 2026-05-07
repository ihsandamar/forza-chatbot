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
