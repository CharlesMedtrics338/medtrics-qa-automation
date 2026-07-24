#!/usr/bin/env python3
"""
Build the Automated QA1 verdict pointer block that gets appended to the
Optimus task description.

v0.4: the block is a *verdict marker* — it carries the lane, verdict, pass
rates, deploy URL, run log links — not a "checklist generated" announcement.
The checklist itself stays in the description above this block, under
`## QA Checklist`.

Inputs are kept simple — the template is loaded from disk and string-substituted.
Markers in the template (`<!-- qa-automation:pointer:start -->` and
`<!-- qa-automation:pointer:end -->`) are critical for idempotent replacement
by `find_pointer_block.py`.

The script does not write to Optimus. It prints the resulting markdown to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VERDICT_EMOJI = {
    "queued":      "🕓",
    "in_progress": "⏳",
    "passed":      "✅",
    "failed":      "❌",
    "blocked":     "⚠️",
    "needs_human": "🟡",
}

STATE_TITLE = {
    "queued":      "Queued",
    "in_progress": "Running",
    "passed":      "Passed",
    "failed":      "Failed",
    "blocked":     "Blocked",
    "needs_human": "Needs human review",
}


def _fmt_rate(rate):
    if rate is None:
        return "—"
    try:
        return f"{float(rate) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def render(
    template_path: Path,
    *,
    ticket: str,
    branch: str | None,
    run_id: str,
    counts: dict,
    mem_collection: str,
    cowork_dashboard_url: str | None,
    state: str = "queued",
    lane: str | None = None,
    deploy_url: str | None = None,
    verdict: str | None = None,
    verdict_confidence: float | None = None,
    p0_pass_rate: float | None = None,
    p1_pass_rate: float | None = None,
    p2_pass_rate: float | None = None,
    failed_items: list[str] | None = None,
    blocked_reason: str | None = None,
) -> str:
    template = template_path.read_text(encoding="utf-8")

    untagged = counts.get("untagged", 0)
    untagged_segment = f" · **{untagged}** untagged" if untagged > 0 else ""

    if state == "blocked" and blocked_reason:
        verdict_line = f"`blocked` — {blocked_reason}"
    elif verdict is None:
        verdict_line = "_(awaiting executor)_"
    else:
        conf_suffix = f" (confidence {verdict_confidence:.2f})" if verdict_confidence is not None else ""
        verdict_line = f"**{verdict}**{conf_suffix}"

    failed_items_line = (
        f"❗ **Failed steps**: {', '.join(failed_items)}"
        if failed_items
        else "_(no failed steps)_"
    )

    return template.format(
        ticket=ticket,
        branch=branch or "_(unresolved)_",
        run_id=run_id,
        total=counts.get("total", 0),
        p0=counts.get("p0", 0),
        p1=counts.get("p1", 0),
        p2=counts.get("p2", 0),
        untagged_segment=untagged_segment,
        state=state,
        state_title=STATE_TITLE.get(state, state.title()),
        verdict_emoji=VERDICT_EMOJI.get(state, "🔹"),
        lane=lane or "_(pending)_",
        deploy_url=deploy_url or "_(unresolved)_",
        verdict_line=verdict_line,
        p0_pass_rate=_fmt_rate(p0_pass_rate),
        p1_pass_rate=_fmt_rate(p1_pass_rate),
        p2_pass_rate=_fmt_rate(p2_pass_rate),
        failed_items_line=failed_items_line,
        mem_collection=mem_collection,
        cowork_dashboard_url=cowork_dashboard_url or "_(not configured)_",
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticket", required=True)
    p.add_argument("--branch")
    p.add_argument("--run-id", required=True)
    p.add_argument("--counts", required=True, type=Path,
                   help="Path to counts JSON ({total, p0, p1, p2, untagged}).")
    p.add_argument("--mem-collection", default="QA Run Logs")
    p.add_argument("--cowork-dashboard-url", default=None)
    p.add_argument("--state", default="queued",
                   choices=list(STATE_TITLE.keys()))
    p.add_argument("--lane", choices=["api", "ui"], default=None)
    p.add_argument("--deploy-url", default=None)
    p.add_argument("--verdict", choices=["pass", "fail", "partial"], default=None)
    p.add_argument("--verdict-confidence", type=float, default=None)
    p.add_argument("--p0-pass-rate", type=float, default=None)
    p.add_argument("--p1-pass-rate", type=float, default=None)
    p.add_argument("--p2-pass-rate", type=float, default=None)
    p.add_argument("--failed-items", default=None,
                   help="Comma-separated list of failed step IDs.")
    p.add_argument("--blocked-reason", default=None)
    p.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "templates" / "pointer-block.md",
    )
    args = p.parse_args()

    counts = json.loads(args.counts.read_text(encoding="utf-8"))
    failed = [s.strip() for s in args.failed_items.split(",")] if args.failed_items else None

    out = render(
        args.template,
        ticket=args.ticket,
        branch=args.branch,
        run_id=args.run_id,
        counts=counts,
        mem_collection=args.mem_collection,
        cowork_dashboard_url=args.cowork_dashboard_url,
        state=args.state,
        lane=args.lane,
        deploy_url=args.deploy_url,
        verdict=args.verdict,
        verdict_confidence=args.verdict_confidence,
        p0_pass_rate=args.p0_pass_rate,
        p1_pass_rate=args.p1_pass_rate,
        p2_pass_rate=args.p2_pass_rate,
        failed_items=failed,
        blocked_reason=args.blocked_reason,
    )
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
