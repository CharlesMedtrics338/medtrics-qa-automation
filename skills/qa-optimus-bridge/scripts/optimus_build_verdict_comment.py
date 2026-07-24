#!/usr/bin/env python3
"""
optimus_build_verdict_comment.py — compose the verdict summary appended to
the Optimus task description alongside the verdict pointer block.

Pure-Python. No MCP calls. Reads a run-log JSON, emits a short markdown
comment the calling SKILL.md splices into update_task(description=...).

The comment is concise on purpose — it's a footer line under the pointer
block, not a replacement for the full Mem run-log. Three states:

  pass    → "Moved to qa2. P0 100% · P1 100%. Run log: mem://..."
  fail    → "Moved to needs_changes. GitLab fail-thread: <url>. P0 N% · P1 N%."
  partial → "Sent to needs_review. <n> step(s) flagged needs_human. Run log: ..."

Usage:
    python3 optimus_build_verdict_comment.py \\
        --run-log run_log.json \\
        --target-lane qa2 \\
        [--gitlab-thread-url https://gitlab.com/...]

Output:
    Markdown text on stdout.

Exit codes:
    0 — comment composed
    1 — input error (missing run-log)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _fmt_rate(rate) -> str:
    if rate is None:
        return "—"
    try:
        return f"{float(rate) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def build_comment(run_log: dict, target_lane: str, gitlab_thread_url: str | None = None) -> str:
    verdict = run_log.get("verdict") or "unknown"
    lane = run_log.get("lane") or "unknown"
    p0 = _fmt_rate(run_log.get("p0_pass_rate"))
    p1 = _fmt_rate(run_log.get("p1_pass_rate"))
    ticket = run_log.get("ticket") or "(no ticket id)"

    failed_items = run_log.get("failed_items") or []
    failed_count = len(failed_items)
    trace = run_log.get("execution_trace") or []
    needs_human_count = sum(1 for e in trace if (e or {}).get("verdict") == "needs_human")

    mem_ref = f"mem://QA Run Logs/{ticket}"

    if verdict == "pass":
        line = (
            f"**Automated QA1 → moved to `{target_lane}`.** "
            f"P0 {p0} · P1 {p1} · lane `{lane}`. "
            f"Run log: {mem_ref}."
        )
    elif verdict == "fail":
        thread = f" GitLab fail-thread: {gitlab_thread_url}." if gitlab_thread_url else ""
        line = (
            f"**Automated QA1 → moved to `{target_lane}`.** "
            f"Verdict `fail` — P0 {p0} · P1 {p1} · {failed_count} failing step(s).{thread} "
            f"Run log: {mem_ref}."
        )
    elif verdict == "partial":
        line = (
            f"**Automated QA1 → sent to `{target_lane}` for human review.** "
            f"{needs_human_count} step(s) flagged `needs_human` — couldn't reduce the "
            f"expected outcome to a structured assertion. P0 {p0} · P1 {p1}. "
            f"Run log: {mem_ref}."
        )
    elif verdict == "blocked":
        line = (
            f"**Automated QA1 blocked — stayed in `qa1`.** "
            f"Reason: `{run_log.get('blocked_reason') or 'unknown'}`. "
            f"Run log: {mem_ref}."
        )
    else:
        line = (
            f"**Automated QA1 outcome:** `{verdict}` → `{target_lane}`. "
            f"P0 {p0} · P1 {p1}. Run log: {mem_ref}."
        )
    return line


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-log", required=True, type=Path,
                   help="Path to the Mem run-log JSON.")
    p.add_argument("--target-lane", required=True,
                   help="Resolved target lane (from optimus_move_task.py output).")
    p.add_argument("--gitlab-thread-url", default=None,
                   help="URL of the posted GitLab fail-thread (when verdict=fail).")
    args = p.parse_args()

    if not args.run_log.exists():
        print(json.dumps({"ok": False, "error": "run_log_not_found",
                          "path": str(args.run_log)}), file=sys.stderr)
        return 1

    try:
        run_log = json.loads(args.run_log.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "run_log_invalid_json",
                          "detail": str(e)}), file=sys.stderr)
        return 1

    sys.stdout.write(build_comment(run_log, args.target_lane, args.gitlab_thread_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
