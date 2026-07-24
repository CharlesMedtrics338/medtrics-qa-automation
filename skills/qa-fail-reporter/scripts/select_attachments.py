#!/usr/bin/env python3
"""
select_attachments.py

Pick the before/after screenshot pair for each failing step in a QA1 run.

For every step in `execution_trace[]` with `verdict == "fail"`, this script
returns up to two attachment records:

  1. The screenshot from the step IMMEDIATELY BEFORE — "state going in".
     Skipped if the failing step is step 1.
  2. The screenshot from the failing step itself — "state at failure".
     Skipped if the trace entry has no `evidence.screenshot_ref`.

The output is an ordered list capped at MAX_ATTACHMENTS (default 8). When the
true total exceeds the cap, the script:
  - keeps the first ceil(cap/2) failure pairs in execution order
  - emits `truncated: true` plus `truncated_count` so the caller can surface a
    "showing first N of M failures" notice in the thread body.

The script is pure. It does no GitLab uploads — that's qa-gitlab-bridge's job.
Input is the Mem run log JSON; output is JSON describing attachment candidates.

Usage:
    python3 select_attachments.py --run-log run_log.json --screenshot-dir outputs/qa/<ticket>/
    python3 select_attachments.py --run-log run_log.json --max 4

Output schema:
    {
      "attachments": [
        {
          "step_id": "step-3",
          "step_n": 3,
          "priority": "P0",
          "label": "before" | "at_failure",
          "path": "outputs/qa/M1-1190/step-2.png",
          "exists": true
        },
        ...
      ],
      "truncated": bool,
      "truncated_count": int,
      "total_failures": int
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_ATTACHMENTS_DEFAULT = 8


def select(run_log: dict, screenshot_dir: Path, max_attachments: int = MAX_ATTACHMENTS_DEFAULT) -> dict:
    trace = run_log.get("execution_trace") or []

    failing = [(i, e) for i, e in enumerate(trace) if e.get("verdict") == "fail"]
    total_failures = len(failing)

    pairs_to_keep = max(1, max_attachments // 2)
    kept = failing[:pairs_to_keep]
    truncated = total_failures > len(kept)

    attachments: list[dict] = []

    for idx, entry in kept:
        # "before" screenshot — the previous step's screenshot, if any.
        if idx > 0:
            prev = trace[idx - 1]
            ref = (prev.get("evidence") or {}).get("screenshot_ref")
            if ref:
                p = _resolve(ref, screenshot_dir)
                attachments.append({
                    "step_id": entry.get("step_id"),
                    "step_n": entry.get("n"),
                    "priority": entry.get("priority"),
                    "label": "before",
                    "path": str(p),
                    "exists": p.exists() if isinstance(p, Path) else False,
                })

        # "at_failure" screenshot.
        ref = (entry.get("evidence") or {}).get("screenshot_ref")
        if ref:
            p = _resolve(ref, screenshot_dir)
            attachments.append({
                "step_id": entry.get("step_id"),
                "step_n": entry.get("n"),
                "priority": entry.get("priority"),
                "label": "at_failure",
                "path": str(p),
                "exists": p.exists() if isinstance(p, Path) else False,
            })

    # Hard-cap on attachment count (in case a single failure produced both
    # before + after and we still overshot).
    if len(attachments) > max_attachments:
        attachments = attachments[:max_attachments]
        truncated = True

    return {
        "attachments": attachments,
        "truncated": truncated,
        "truncated_count": max(0, total_failures - len(kept)),
        "total_failures": total_failures,
    }


def _resolve(ref: str, screenshot_dir: Path) -> Path:
    """Resolve a screenshot_ref to a Path. Refs may be absolute, or relative
    to the screenshot_dir, or relative to the project root."""
    p = Path(ref)
    if p.is_absolute():
        return p
    cand = screenshot_dir / p.name
    if cand.exists():
        return cand
    return p  # fall back to ref as-given; exists==False will surface


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-log", type=Path, required=True,
                   help="Path to the Mem run log JSON (or stdin with --stdin).")
    p.add_argument("--screenshot-dir", type=Path,
                   default=Path("outputs/qa"),
                   help="Directory containing the step PNGs.")
    p.add_argument("--max", type=int, default=MAX_ATTACHMENTS_DEFAULT,
                   help=f"Maximum attachments to return (default {MAX_ATTACHMENTS_DEFAULT}).")
    p.add_argument("--stdin", action="store_true",
                   help="Read the run log JSON from stdin instead of a file.")
    args = p.parse_args()

    if args.stdin:
        run_log = json.loads(sys.stdin.read())
    else:
        if not args.run_log.exists():
            print(json.dumps({"error": "run_log_not_found", "path": str(args.run_log)}),
                  file=sys.stderr)
            return 2
        run_log = json.loads(args.run_log.read_text(encoding="utf-8"))

    result = select(run_log, args.screenshot_dir, args.max)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
