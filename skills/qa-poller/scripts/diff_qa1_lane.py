#!/usr/bin/env python3
"""
Diff the current Optimus qa1 lane against the Mem QA1 Queue and report what
needs to be enqueued (or marked stale).

Inputs are two JSON files:

  --optimus-file  Output of mcp__...__list_lane_tasks(status="qa1", ...). Either
                  the full response shape ({"status": ..., "tasks": [...]}) or
                  just a list of task objects.

  --mem-file      Output of mcp__...__list_notes with include_note_content=true.
                  Either the full response shape ({"results": [...]}) or just
                  a list of notes. The script regex-extracts the ```json``` block
                  from each note's `content` field.

Output (JSON to stdout):

  {
    "to_enqueue":      [{ticket, title, type, priority, highRisk, statusChangedAt, ...}],
    "to_mark_stale":   [{ticket, current_state, reason}],
    "in_sync":         ["M1-1154", ...],
    "summary":         {optimus_count, mem_count, to_enqueue_count, to_mark_stale_count, in_sync_count}
  }

The script is pure — no MCP calls. The orchestrating SKILL.md does the I/O.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]*?)```")


def load_optimus(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    # Full list_lane_tasks response shape.
    return raw.get("tasks", []) or []


def load_mem(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    notes = raw if isinstance(raw, list) else (raw.get("results", []) or [])
    out: list[dict] = []
    for n in notes:
        content = n.get("content", "")
        m = JSON_BLOCK_RE.search(content)
        if not m:
            continue
        try:
            parsed = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        # Carry the Mem note ID alongside the parsed ticket state.
        parsed["_mem_note_id"] = n.get("id")
        out.append(parsed)
    return out


def diff(optimus: list[dict], mem: list[dict]) -> dict:
    by_optimus = {t["identifier"]: t for t in optimus if t.get("identifier")}
    by_mem = {t["ticket"]: t for t in mem if t.get("ticket")}

    optimus_ids = set(by_optimus.keys())
    mem_ids = set(by_mem.keys())

    new_ids = sorted(optimus_ids - mem_ids)
    stale_ids = sorted(mem_ids - optimus_ids)
    same_ids = sorted(optimus_ids & mem_ids)

    to_enqueue = []
    for tid in new_ids:
        t = by_optimus[tid]
        to_enqueue.append(
            {
                "ticket": tid,
                "title": t.get("title"),
                "type": t.get("type"),
                "priority": t.get("priority"),
                "highRisk": bool(t.get("highRisk")),
                "assignee": t.get("assignee"),
                "statusChangedAt": t.get("statusChangedAt"),
            }
        )

    to_mark_stale = []
    for tid in stale_ids:
        m = by_mem[tid]
        to_mark_stale.append(
            {
                "ticket": tid,
                "current_state": m.get("state"),
                "mem_note_id": m.get("_mem_note_id"),
                "reason": "not_in_optimus_qa1",
            }
        )

    return {
        "to_enqueue": to_enqueue,
        "to_mark_stale": to_mark_stale,
        "in_sync": same_ids,
        "summary": {
            "optimus_count": len(by_optimus),
            "mem_count": len(by_mem),
            "to_enqueue_count": len(to_enqueue),
            "to_mark_stale_count": len(to_mark_stale),
            "in_sync_count": len(same_ids),
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--optimus-file", required=True, type=Path)
    p.add_argument("--mem-file", required=True, type=Path)
    p.add_argument("--json", action="store_true", help="Emit JSON (default).")
    args = p.parse_args()

    optimus = load_optimus(args.optimus_file)
    mem = load_mem(args.mem_file)
    result = diff(optimus, mem)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
