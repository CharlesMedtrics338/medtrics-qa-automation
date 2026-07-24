#!/usr/bin/env python3
"""
build_fail_thread.py

Render the GitLab fail-thread body from a Mem run log + an attachments index.

Pure-Python. No GitLab calls. No MCP calls. Input is JSON, output is markdown
on stdout (or a file via --out).

Input run-log shape (the relevant subset):

    {
      "ticket": "M1-1190",
      "branch": "feat/...",
      "deploy_url": "https://...",
      "lane": "ui",
      "run_id": "...",
      "verdict": "fail" | "partial",
      "verdict_confidence": 0.0..1.0,
      "p0_pass_rate": 1.0,
      "p1_pass_rate": 0.9,
      "p2_pass_rate": 1.0,
      "mr_url": "...",
      "mr_id": "...",
      "checklist": {"step_count": int, ...},
      "execution_trace": [
        {
          "n": int,
          "step_id": "step-3",
          "priority": "P0" | "P1" | "P2",
          "started_at": "...",
          "action_taken": "...",
          "observed": "...",
          "verdict": "pass" | "fail" | "needs_human",
          "evidence": {
            "url": "/path/",
            "assertions": [{"kind": "...", "passed": bool, "args": {...}}],
            "screenshot_ref": "outputs/qa/<ticket>/step-3.png",
            "console_errors": [{"level": "error", "text": "..."}],
            "network_errors": [{"method": "GET", "url": "/static/foo.js", "status": 404}]
          }
        }, ...
      ],
      "ui_observations": [
        {"kind": "console_warning", "step_id": "step-2", "evidence": "..."},
        {"kind": "broken_image",    "step_id": "step-2", "evidence": "..."}, ...
      ]
    }

Attachments shape: the `select_attachments.py` output, augmented at upload
time by qa-gitlab-bridge with a `gitlab_markdown` field per entry:

    {
      "attachments": [
        {"step_id": "step-3", "step_n": 3, "label": "before",
         "path": "outputs/qa/...", "gitlab_markdown": "![step-3.png](/uploads/abc/step-3.png)"},
        ...
      ],
      "truncated": bool,
      "truncated_count": int
    }

If `gitlab_markdown` is absent (upload failed or dry-run), the renderer falls
back to a plain link to the local path so the thread is still informative.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "fail-thread.md"
DEFAULT_PLUGIN_VERSION = "0.5.0"

VERDICT_EMOJI = {
    "fail":    "❌",
    "partial": "🟡",
    "blocked": "⚠️",
}
VERDICT_TITLE = {
    "fail":    "Failed",
    "partial": "Partial (needs review)",
    "blocked": "Blocked",
}


def _fmt_rate(rate):
    if rate is None:
        return "—"
    try:
        return f"{float(rate) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _step_attachments(step_n: int, attachments: list[dict]) -> dict[str, dict]:
    out = {}
    for a in attachments:
        if a.get("step_n") != step_n:
            continue
        out[a.get("label", "")] = a
    return out


def _format_attachment(a: dict | None) -> str:
    if not a:
        return ""
    md = a.get("gitlab_markdown")
    if md:
        return md
    # Fallback when upload failed or dry-run — emit a plain reference.
    return f"_(screenshot at `{a.get('path')}` — upload pending)_"


def _format_console_errors(errs: list[dict]) -> str:
    if not errs:
        return ""
    lines = []
    for e in errs:
        level = (e.get("level") or "error").upper()
        text = (e.get("text") or "").strip().replace("```", "ʼ``")
        lines.append(f"[{level}] {text}")
    return "**Console errors during this step:**\n```\n" + "\n".join(lines) + "\n```\n"


def _format_network_errors(errs: list[dict]) -> str:
    if not errs:
        return ""
    rows = ["| Method | URL | Status |", "|---|---|---|"]
    for e in errs:
        method = e.get("method", "GET")
        url = e.get("url", "")
        status = e.get("status", "")
        rows.append(f"| {method} | `{url}` | {status} |")
    return "**Network errors during this step:**\n" + "\n".join(rows) + "\n"


def _format_failed_assertions(assertions: list[dict]) -> str:
    failed = [a.get("kind", "") for a in (assertions or []) if not a.get("passed", True)]
    return ", ".join(f"`{k}`" for k in failed) if failed else "_(none recorded)_"


def _format_step_block(step: dict, attachments: list[dict]) -> str:
    ev = step.get("evidence") or {}
    sa = _step_attachments(step.get("n"), attachments)
    before = _format_attachment(sa.get("before"))
    at_fail = _format_attachment(sa.get("at_failure"))

    parts = [
        f"#### Step {step.get('n')} · [{step.get('priority', 'P?')}] — {step.get('action_taken') or step.get('action', '')}",
        "",
        f"**Expected:** {step.get('expected', '_(not recorded)_')}",
        f"**Observed:** {step.get('observed', '_(not recorded)_')}",
        f"**Failed assertions:** {_format_failed_assertions(ev.get('assertions') or [])}",
        "",
    ]
    if before:
        parts += [before, "*State entering the step*", ""]
    if at_fail:
        parts += [at_fail, "*State at failure*", ""]

    ce = _format_console_errors(ev.get("console_errors") or [])
    if ce:
        parts += [ce]
    ne = _format_network_errors(ev.get("network_errors") or [])
    if ne:
        parts += [ne]

    return "\n".join(parts).rstrip() + "\n"


def _format_ui_observations(obs: list[dict]) -> str:
    if not obs:
        return ""
    lines = ["### UI/UX observations (advisory, do not affect verdict)", ""]
    for o in obs:
        kind = o.get("kind", "observation")
        step_id = o.get("step_id", "")
        ev = (o.get("evidence") or "").strip()
        if len(ev) > 240:
            ev = ev[:237] + "…"
        anchor = f" on `{step_id}`" if step_id else ""
        lines.append(f"- **{kind}**{anchor}: {ev}")
    return "\n".join(lines) + "\n"


def render(run_log: dict, attachments_idx: dict, template_path: Path,
           *, plugin_version: str = DEFAULT_PLUGIN_VERSION,
           dashboard_url: str = "_(not configured)_",
           optimus_url_pattern: str = "https://optimus.medtricslab.com/tasks/{ticket}",
           mem_url_pattern: str = "mem://QA Run Logs/{ticket}") -> str:
    template = template_path.read_text(encoding="utf-8")

    verdict = run_log.get("verdict") or "fail"
    trace = run_log.get("execution_trace") or []
    failing = [e for e in trace if e.get("verdict") == "fail"]
    attachments = attachments_idx.get("attachments") or []

    failing_blocks = "\n".join(_format_step_block(s, attachments) for s in failing)
    ui_section = _format_ui_observations(run_log.get("ui_observations") or [])

    truncated_notice = ""
    if attachments_idx.get("truncated"):
        trunc_n = attachments_idx.get("truncated_count", 0)
        total = attachments_idx.get("total_failures", len(failing))
        kept = total - trunc_n
        truncated_notice = (
            f"\n> ⚠️ Showing screenshots for the first **{kept}** of "
            f"**{total}** failures. Full evidence in the Mem run log.\n"
        )

    return template.format(
        ticket=run_log.get("ticket", ""),
        optimus_url=optimus_url_pattern.format(ticket=run_log.get("ticket", "")),
        branch=run_log.get("branch") or "_(unresolved)_",
        deploy_url=run_log.get("deploy_url") or "_(unresolved)_",
        lane=run_log.get("lane") or "_(unknown)_",
        verdict=verdict,
        verdict_emoji=VERDICT_EMOJI.get(verdict, "❌"),
        verdict_title=VERDICT_TITLE.get(verdict, verdict.title()),
        verdict_confidence=f"{run_log.get('verdict_confidence', 0):.2f}"
            if run_log.get("verdict_confidence") is not None else "—",
        p0_pass_rate=_fmt_rate(run_log.get("p0_pass_rate")),
        p1_pass_rate=_fmt_rate(run_log.get("p1_pass_rate")),
        p2_pass_rate=_fmt_rate(run_log.get("p2_pass_rate")),
        failed_count=len(failing),
        total_steps=((run_log.get("checklist") or {}).get("step_count") or len(trace)),
        run_id=run_log.get("run_id", ""),
        truncation_notice=truncated_notice,
        failing_steps_blocks=failing_blocks or "_(no failing steps recorded)_",
        ui_observations_section=ui_section,
        mem_url=mem_url_pattern.format(ticket=run_log.get("ticket", "")),
        dashboard_url=dashboard_url,
        plugin_version=plugin_version,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-log", type=Path, required=True)
    p.add_argument("--attachments", type=Path,
                   help="Path to the select_attachments.py output. If omitted, no screenshots are referenced.")
    p.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    p.add_argument("--plugin-version", default=DEFAULT_PLUGIN_VERSION)
    p.add_argument("--dashboard-url", default="_(not configured)_")
    p.add_argument("--out", type=Path, help="Write to this file instead of stdout.")
    args = p.parse_args()

    run_log = json.loads(args.run_log.read_text(encoding="utf-8"))
    attachments_idx = (
        json.loads(args.attachments.read_text(encoding="utf-8"))
        if args.attachments and args.attachments.exists()
        else {"attachments": [], "truncated": False, "truncated_count": 0}
    )

    body = render(
        run_log,
        attachments_idx,
        args.template,
        plugin_version=args.plugin_version,
        dashboard_url=args.dashboard_url,
    )

    if args.out:
        args.out.write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
