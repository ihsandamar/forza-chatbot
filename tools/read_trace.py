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
