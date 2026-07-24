#!/usr/bin/env python3
r"""
extract_checklist_block.py

Isolate the `## QA Checklist` section from an Optimus task description so
`parse_checklist_steps.py` can lift it into structured `test_plan_steps[]`.

v0.4 contract: the QA checklist is human-authored inside the Optimus task
description, under a stable `## QA Checklist` heading. Author writes prose
and other markdown freely above and below it; this script extracts only the
relevant section.

Boundaries:
- Section starts at the line matching `^##\s+QA Checklist\s*$` (case-sensitive
  on "QA Checklist"; the heading text is exact, the trailing whitespace is
  tolerated).
- Section ends at the next `^##\s` heading at the same level, or end-of-text.
- Optional `<!-- qa-automation:pointer:start -->` / `:end` markers (the verdict
  pointer block written by qa-checklist-reader on a prior run) are stripped
  before returning the block, so the parser only sees the author's content.

This script is pure — no network, no MCP calls. The orchestrating SKILL.md
fetches the Optimus task description via the Optimus MCP and pipes it here.

Usage:
    # from a file:
    python3 extract_checklist_block.py path/to/description.md
    # from stdin:
    cat description.md | python3 extract_checklist_block.py --stdin
    # JSON output instead of raw markdown:
    python3 extract_checklist_block.py --stdin --json < description.md

Output:
    Default: the raw markdown of the checklist section (without the heading).
    --json:  {"present": bool, "checklist": str, "start_line": int|null,
              "end_line": int|null, "reason": str|null}

Exit codes:
    0 — checklist section present and extracted
    3 — no `## QA Checklist` heading found (caller should mark
        blocked_reason=checklist_missing)
    2 — input file not found / unreadable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^##\s+QA Checklist\s*$")
ANY_H2_RE = re.compile(r"^##\s+\S")

POINTER_START = "<!-- qa-automation:pointer:start -->"
POINTER_END = "<!-- qa-automation:pointer:end -->"


def extract(description: str) -> dict:
    """Return a dict describing the QA Checklist section in `description`.

    Schema:
        {
          "present":   bool,
          "checklist": str,         # markdown body without the heading; "" if absent
          "start_line": int|None,   # 0-indexed line of the heading
          "end_line":   int|None,   # 0-indexed line of the line AFTER the section
          "reason":     str|None,   # populated when present=False
        }
    """
    lines = description.splitlines()
    start: int | None = None
    end: int | None = None

    for idx, line in enumerate(lines):
        if HEADING_RE.match(line):
            start = idx
            break

    if start is None:
        return {
            "present": False,
            "checklist": "",
            "start_line": None,
            "end_line": None,
            "reason": "checklist_missing",
        }

    # Walk forward from start+1 looking for the next H2.
    for idx in range(start + 1, len(lines)):
        if ANY_H2_RE.match(lines[idx]):
            end = idx
            break
    if end is None:
        end = len(lines)

    section = lines[start + 1:end]

    # Strip the pointer block (verdict marker written on a prior run) if present.
    cleaned: list[str] = []
    skipping = False
    for line in section:
        if POINTER_START in line:
            skipping = True
            continue
        if POINTER_END in line:
            skipping = False
            continue
        if skipping:
            continue
        cleaned.append(line)

    # Strip leading/trailing blank lines for cleaner downstream parsing.
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    return {
        "present": True,
        "checklist": "\n".join(cleaned),
        "start_line": start,
        "end_line": end,
        "reason": None,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path, nargs="?",
                   help="Path to the Optimus task description (markdown).")
    p.add_argument("--stdin", action="store_true",
                   help="Read the description from stdin.")
    p.add_argument("--json", action="store_true",
                   help="Emit the full extraction record as JSON.")
    args = p.parse_args()

    if args.stdin:
        text = sys.stdin.read()
    else:
        if args.path is None or not args.path.exists():
            print(json.dumps({"error": "description_not_found",
                              "path": str(args.path) if args.path else None}),
                  file=sys.stderr)
            return 2
        text = args.path.read_text(encoding="utf-8", errors="replace")

    result = extract(text)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if not result["present"]:
            print(json.dumps({"reason": result["reason"]}), file=sys.stderr)
            return 3
        print(result["checklist"])

    return 0 if result["present"] else 3


if __name__ == "__main__":
    sys.exit(main())
