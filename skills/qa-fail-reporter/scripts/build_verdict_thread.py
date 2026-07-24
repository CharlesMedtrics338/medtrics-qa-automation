#!/usr/bin/env python3
"""
build_verdict_thread.py

Render the GitLab verdict-thread body for ANY verdict (pass / partial / fail /
blocked). Posts per-step evidence (screenshot + console excerpt + network
excerpt) inside collapsible <details> blocks so the comment stays scannable.

Successor to build_fail_thread.py. Backwards-compatible run_log shape — extends
the same execution_trace shape with optional `evidence.dom_snapshot_ref` and
`evidence.gif_ref` fields surfaced by qa-screenshot-capture.

Pure-Python. No GitLab calls. No MCP calls. Input is JSON, output is markdown
on stdout (or a file via --out).

Attachments index shape (matches what qa-gitlab-bridge produces after each
upload):

    {
      "attachments": [
        {"step_n": 3, "label": "screenshot",
         "path": "outputs/qa/M1-1206/.../step-3.gif",
         "gitlab_markdown": "![step-3](/uploads/abc/step-3.gif)",
         "kind": "image"},
        {"step_n": 3, "label": "console",
         "path": "outputs/qa/M1-1206/.../step-3.console.log",
         "gitlab_markdown": "[step-3.console.log](/uploads/abc/step-3.console.log)",
         "kind": "log"},
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "verdict-thread.md"
DEFAULT_PLUGIN_VERSION = "0.11.1"

# Caps for the plain-English summary section. Long checklists collapse to a
# truncated list with a "… N more" suffix.
NARRATIVE_TEST_SUMMARY_MAX_ITEMS = 15
NARRATIVE_ACTION_MAX_CHARS = 110
NARRATIVE_GAP_NOTE_MAX_CHARS = 140

# Maps the partial_cause vocabulary to plain-English explanations the narrative
# can splice in. Keeps the prose stable across runs.
PARTIAL_CAUSE_PLAIN_ENGLISH = {
    "missing_test_data": (
        "The dev tenant did not have the seeded test data the fix specifically "
        "targets, so the affected behavior could not be reproduced end-to-end."
    ),
    "blocked_by_seed_data": (
        "The dev tenant was missing seed data the run needed to exercise the fix."
    ),
    "no_seed_data": (
        "No seed data was available on the dev tenant for the affected feature."
    ),
    "environment_not_seeded": (
        "The environment was not seeded for the scenario the fix targets."
    ),
    "checklist_unstructured": (
        "Some checklist steps could not be reduced to a structured assertion "
        "the automation could judge by code."
    ),
}

VERDICT_EMOJI = {
    "pass":    "✅",
    "fail":    "❌",
    "partial": "🟡",
    "blocked": "⚠️",
}
VERDICT_TITLE = {
    "pass":    "Passed",
    "fail":    "Failed",
    "partial": "Partial (needs review)",
    "blocked": "Blocked",
}
STEP_VERDICT_EMOJI = {
    "pass":         "✅",
    "fail":         "❌",
    "needs_human":  "👤",
    "blocked":      "⚠️",
    "not_run":      "⏭️",
    "skipped":      "⏭️",
}

# Console / network inline-block size caps. Above these, we link the upload
# instead of inlining the content. Keeps the thread body under GitLab's
# ~1 MB markdown cap.
CONSOLE_INLINE_LINE_CAP = 60
CONSOLE_INLINE_CHAR_CAP = 4000
NETWORK_INLINE_ROW_CAP = 30


def _fmt_rate(rate):
    if rate is None:
        return "—"
    try:
        return f"{float(rate) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _step_attachments(step_n: int, attachments: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for a in attachments:
        if a.get("step_n") != step_n:
            continue
        label = a.get("label", "")
        out[label] = a
    return out


def _attachment_markdown(a: dict | None) -> str:
    if not a:
        return ""
    md = a.get("gitlab_markdown")
    if md:
        return md
    return f"_(attachment at `{a.get('path')}` — upload pending)_"


def _escape_fence(text: str) -> str:
    return (text or "").replace("```", "ʼ``")


def _format_console_inline(messages: list[dict]) -> str:
    if not messages:
        return ""
    lines = []
    for m in messages:
        level = (m.get("level") or "log").upper()
        text = _escape_fence(m.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{level}] {text}")
        if len(lines) >= CONSOLE_INLINE_LINE_CAP:
            lines.append(f"… ({len(messages) - len(lines) + 1} more truncated)")
            break
    body = "\n".join(lines)
    if len(body) > CONSOLE_INLINE_CHAR_CAP:
        body = body[:CONSOLE_INLINE_CHAR_CAP] + "\n… (truncated)"
    return body


def _format_network_inline(requests: list[dict]) -> str:
    if not requests:
        return ""
    rows = ["| Method | URL | Status |", "|---|---|---|"]
    for r in requests[:NETWORK_INLINE_ROW_CAP]:
        method = r.get("method", "GET")
        url = r.get("url", "")
        status = r.get("status", "")
        rows.append(f"| {method} | `{url}` | {status} |")
    if len(requests) > NETWORK_INLINE_ROW_CAP:
        rows.append(f"| _… {len(requests) - NETWORK_INLINE_ROW_CAP} more_ | | |")
    return "\n".join(rows)


def _format_step_evidence_block(step: dict, attachments: list[dict]) -> str:
    """One collapsible <details> block per step with its evidence."""
    ev = step.get("evidence") or {}
    sa = _step_attachments(step.get("n"), attachments)
    v = step.get("verdict") or "not_run"
    v_emoji = STEP_VERDICT_EMOJI.get(v, "·")

    summary = (
        f"<summary>{v_emoji} <b>Step {step.get('n')}</b> · "
        f"[{step.get('priority', 'P?')}] · {v} — "
        f"{(step.get('action_taken') or step.get('action') or '').strip()[:120]}"
        f"</summary>"
    )

    body: list[str] = []

    expected = (step.get("expected") or "").strip()
    observed = (step.get("observed") or step.get("note") or "").strip()
    if expected:
        body.append(f"**Expected:** {expected}")
    if observed:
        body.append(f"**Observed:** {observed}")

    # Inline screenshot (gif or png) — the headline visual evidence.
    screenshot_md = _attachment_markdown(sa.get("screenshot"))
    if screenshot_md:
        body += ["", screenshot_md, ""]

    # Console excerpt — inline if small, linked if large.
    console_inline = _format_console_inline(ev.get("console") or ev.get("console_errors") or [])
    console_attachment = _attachment_markdown(sa.get("console"))
    if console_inline:
        body += [
            "<details><summary>Console output</summary>",
            "",
            "```text",
            console_inline,
            "```",
            "</details>",
            "",
        ]
    elif console_attachment:
        body += [f"📋 Console log: {console_attachment}", ""]

    # Network excerpt — inline if small, linked if large.
    network_inline = _format_network_inline(ev.get("network") or ev.get("network_errors") or [])
    network_attachment = _attachment_markdown(sa.get("network"))
    if network_inline:
        body += [
            "<details><summary>Network activity</summary>",
            "",
            network_inline,
            "</details>",
            "",
        ]
    elif network_attachment:
        body += [f"🌐 Network capture: {network_attachment}", ""]

    # DOM snapshot link (never inline — always a download).
    dom_attachment = _attachment_markdown(sa.get("dom"))
    if dom_attachment:
        body += [f"🧱 DOM snapshot: {dom_attachment}", ""]

    body_text = "\n".join(body).rstrip()
    return f"<details>\n{summary}\n\n{body_text}\n</details>\n"


def _format_ui_observations(obs: list[dict]) -> str:
    if not obs:
        return ""
    lines = ["### UI/UX observations (advisory — do not affect verdict)", ""]
    for o in obs:
        kind = o.get("kind", "observation")
        step_id = o.get("step_id", "")
        ev = (o.get("evidence") or "").strip()
        if len(ev) > 240:
            ev = ev[:237] + "…"
        anchor = f" on `{step_id}`" if step_id else ""
        lines.append(f"- **{kind}**{anchor}: {ev}")
    return "\n".join(lines) + "\n"


def _format_partial_cause(run_log: dict) -> str:
    cause = run_log.get("partial_cause")
    lane_decision = run_log.get("lane_decision") or {}
    if not cause and not lane_decision:
        return ""
    lines = []
    if cause:
        lines.append(f"> **Partial cause:** `{cause}`")
    intended = lane_decision.get("intended_lane")
    effective = lane_decision.get("effective_lane")
    reason = lane_decision.get("reason")
    if intended and effective and intended != effective:
        lines.append(f"> **Lane decision:** intended `{intended}` → effective `{effective}` — {reason or ''}")
    elif effective:
        lines.append(f"> **Routed to lane:** `{effective}`")
    return "\n".join(lines) + "\n" if lines else ""


def _count_step_verdicts(trace: list[dict]) -> dict[str, int]:
    counts = {"pass": 0, "fail": 0, "needs_human": 0, "blocked": 0, "not_run": 0, "skipped": 0}
    for s in trace:
        v = s.get("verdict") or "not_run"
        if v in counts:
            counts[v] += 1
    return counts


# ----- Plain-English narrative renderers (v0.11.1) -----

_STEP_PREFIX_RE = re.compile(r"^\s*(?:Step\s+\d+\s*[\.:\-—]?\s*|\d+[\.\)]\s+|-\s+)")


def _clean_action(text: str, *, max_chars: int = NARRATIVE_ACTION_MAX_CHARS) -> str:
    """Strip checklist-prefix noise and truncate an action sentence."""
    if not text:
        return "(no action recorded)"
    out = _STEP_PREFIX_RE.sub("", text).strip()
    # Collapse repeated whitespace.
    out = re.sub(r"\s+", " ", out)
    if len(out) > max_chars:
        out = out[: max_chars - 1].rstrip() + "…"
    return out


def _format_test_summary_narrative(trace: list[dict]) -> str:
    """One line per step: 'Step N — action (emoji verdict)'.

    Caps at NARRATIVE_TEST_SUMMARY_MAX_ITEMS with a truncation suffix.
    """
    if not trace:
        return "_(no steps were executed)_"
    lines: list[str] = []
    for step in trace[:NARRATIVE_TEST_SUMMARY_MAX_ITEMS]:
        n = step.get("n", "?")
        verdict = step.get("verdict") or "not_run"
        emoji = STEP_VERDICT_EMOJI.get(verdict, "·")
        priority = step.get("priority")
        priority_marker = f" `{priority}`" if priority else ""
        action = _clean_action(step.get("action_taken") or step.get("action") or "")
        lines.append(f"- **Step {n}**{priority_marker} — {action} {emoji}")
    if len(trace) > NARRATIVE_TEST_SUMMARY_MAX_ITEMS:
        remaining = len(trace) - NARRATIVE_TEST_SUMMARY_MAX_ITEMS
        lines.append(f"- _(… {remaining} more step(s) — full list in the per-step evidence below)_")
    return "\n".join(lines)


def _format_outcomes_narrative(run_log: dict) -> str:
    """Verdict-aware one-paragraph summary of what happened."""
    verdict = run_log.get("verdict") or "fail"
    trace = run_log.get("execution_trace") or []
    counts = _count_step_verdicts(trace)
    total_executable = counts["pass"] + counts["fail"] + counts["needs_human"]

    sentences: list[str] = []

    if verdict == "pass":
        if counts["pass"] == total_executable and total_executable > 0:
            sentences.append(f"All {counts['pass']} executable step(s) passed end-to-end.")
        else:
            sentences.append(f"{counts['pass']} step(s) passed, {counts['fail']} failed, {counts['needs_human']} need human review.")
        if counts["needs_human"]:
            sentences.append(
                f"{counts['needs_human']} step(s) could not be judged automatically and need a human eye — see the gaps section."
            )

    elif verdict == "fail":
        sentences.append(
            f"{counts['fail']} of {total_executable} executable steps failed."
        )
        # Pull the action of the first failed step for a quick anchor.
        first_fail = next((s for s in trace if s.get("verdict") == "fail"), None)
        if first_fail:
            sentences.append(
                f"The first failure was on Step {first_fail.get('n')}: {_clean_action(first_fail.get('action_taken') or first_fail.get('action') or '', max_chars=140)}"
            )

    elif verdict == "partial":
        cause = run_log.get("partial_cause")
        plain = PARTIAL_CAUSE_PLAIN_ENGLISH.get(cause)
        if plain:
            sentences.append(plain)
        elif cause:
            sentences.append(f"The run could only partially exercise the change. Cause: `{cause}`.")
        else:
            sentences.append("Some steps could not be fully evaluated by the automation.")
        if counts["pass"] or counts["needs_human"]:
            sentences.append(
                f"{counts['pass']} step(s) passed by automation; {counts['needs_human']} need human review."
            )

    elif verdict == "blocked":
        reason = run_log.get("blocked_reason") or "an unrecoverable error"
        sentences.append(
            f"The automated run was blocked before completing all steps. Reason: `{reason}`."
        )

    else:
        sentences.append("Run completed with no clear verdict — see the per-step evidence below.")

    return " ".join(s for s in sentences if s).strip() or "_(no outcome recorded)_"


def _format_gaps_narrative(trace: list[dict]) -> str:
    """List the steps automation did NOT complete (needs_human / skipped / not_run)."""
    label_by_verdict = {
        "needs_human": "Needs human",
        "skipped":     "Skipped",
        "not_run":     "Not run",
        "blocked":     "Blocked",
    }
    gap_steps = [s for s in trace if s.get("verdict") in label_by_verdict]
    if not gap_steps:
        return "_(none — every step was completed by automation)_"

    lines: list[str] = []
    for step in gap_steps:
        n = step.get("n", "?")
        v = step.get("verdict") or "not_run"
        label = label_by_verdict.get(v, v)
        action = _clean_action(step.get("action_taken") or step.get("action") or "")
        note = (step.get("note") or step.get("observed") or "").strip()
        note = re.sub(r"\s+", " ", note)
        if note and len(note) > NARRATIVE_GAP_NOTE_MAX_CHARS:
            note = note[: NARRATIVE_GAP_NOTE_MAX_CHARS - 1].rstrip() + "…"
        if note:
            lines.append(f"- **Step {n}** ({label}) — {action}  ·  _why_: {note}")
        else:
            lines.append(f"- **Step {n}** ({label}) — {action}")
    return "\n".join(lines)


def render(run_log: dict, attachments_idx: dict, template_path: Path,
           *, plugin_version: str = DEFAULT_PLUGIN_VERSION,
           dashboard_url: str = "_(not configured)_",
           optimus_url_pattern: str = "https://optimus.medtricslab.com/tasks/{ticket}",
           mem_url_pattern: str = "mem://QA Run Logs/{ticket}") -> str:
    template = template_path.read_text(encoding="utf-8")

    verdict = run_log.get("verdict") or "fail"
    trace = run_log.get("execution_trace") or []
    attachments = attachments_idx.get("attachments") or []
    counts = _count_step_verdicts(trace)

    step_blocks = "\n".join(_format_step_evidence_block(s, attachments) for s in trace)
    if not step_blocks.strip():
        step_blocks = "_(no per-step evidence captured)_"

    ui_section = _format_ui_observations(run_log.get("ui_observations") or [])
    partial_block = _format_partial_cause(run_log)

    narrative_test_summary = _format_test_summary_narrative(trace)
    narrative_outcomes = _format_outcomes_narrative(run_log)
    narrative_gaps = _format_gaps_narrative(trace)

    truncated_notice = ""
    if attachments_idx.get("truncated"):
        trunc_n = attachments_idx.get("truncated_count", 0)
        total = attachments_idx.get("total_count", len(trace))
        kept = total - trunc_n
        truncated_notice = (
            f"\n> ⚠️ Showing evidence for the first **{kept}** of "
            f"**{total}** steps. Full set in the Mem run log.\n"
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
        passed_count=counts["pass"],
        failed_count=counts["fail"],
        needs_human_count=counts["needs_human"],
        total_steps=((run_log.get("checklist") or {}).get("step_count") or len(trace)),
        run_id=run_log.get("run_id", ""),
        partial_cause_block=partial_block,
        truncation_notice=truncated_notice,
        narrative_test_summary=narrative_test_summary,
        narrative_outcomes=narrative_outcomes,
        narrative_gaps=narrative_gaps,
        step_evidence_blocks=step_blocks,
        ui_observations_section=ui_section,
        mem_url=mem_url_pattern.format(ticket=run_log.get("ticket", "")),
        dashboard_url=dashboard_url,
        plugin_version=plugin_version,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-log", type=Path, required=True)
    p.add_argument("--attachments", type=Path,
                   help="Path to attachments index. If omitted, no evidence is rendered.")
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
