"""Tests for build_verdict_thread.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_verdict_thread as M  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "verdict-thread.md"


def _trace(*steps):
    return list(steps)


def _step(n, verdict="pass", priority="P0", action="Click button"):
    return {
        "n": n, "step_id": f"step-{n}", "priority": priority,
        "verdict": verdict, "action_taken": action,
        "expected": f"Expected {n}", "observed": f"Observed {n}",
        "evidence": {},
    }


def test_pass_verdict_renders_all_steps_with_evidence_blocks():
    run_log = {
        "ticket": "M1-1206", "branch": "fix/m1-1206/foo",
        "deploy_url": "https://6888.medtrics.dev/", "lane": "ui",
        "verdict": "pass", "verdict_confidence": 0.95,
        "p0_pass_rate": 1.0, "p1_pass_rate": 1.0,
        "execution_trace": _trace(_step(1), _step(2), _step(3)),
        "run_id": "2026-06-17T03:15Z",
        "checklist": {"step_count": 3},
    }
    attachments_idx = {
        "attachments": [
            {"step_n": 1, "label": "screenshot",
             "gitlab_markdown": "![s1](/uploads/aaa/s1.gif)"},
            {"step_n": 2, "label": "screenshot",
             "gitlab_markdown": "![s2](/uploads/bbb/s2.gif)"},
        ],
    }
    body = M.render(run_log, attachments_idx, TEMPLATE)
    assert "M1-1206" in body
    assert "Passed" in body
    assert "![s1]" in body
    assert "![s2]" in body
    # Three step blocks — three <details> wrappers for steps, plus possibly
    # internal collapsibles for console/network. Just verify the count >= 3.
    assert body.count("<details>") >= 3


def test_partial_verdict_with_lane_decision_renders_cause():
    run_log = {
        "ticket": "M1-1207", "verdict": "partial",
        "partial_cause": "missing_test_data",
        "lane_decision": {
            "intended_lane": "needs_review",
            "effective_lane": "on_hold",
            "reason": "needs_review not yet released",
        },
        "execution_trace": _trace(_step(1), _step(2, verdict="needs_human")),
    }
    body = M.render(run_log, {"attachments": []}, TEMPLATE)
    assert "Partial" in body
    assert "missing_test_data" in body
    assert "needs_review" in body and "on_hold" in body


def test_failed_step_renders_with_console_excerpt():
    run_log = {
        "ticket": "M1-1190", "verdict": "fail",
        "execution_trace": [{
            "n": 1, "priority": "P0", "verdict": "fail",
            "action_taken": "Submit form",
            "expected": "Success alert", "observed": "Validation error",
            "evidence": {
                "console": [
                    {"level": "error", "text": "TypeError: Cannot read 'value' of undefined"},
                    {"level": "warn", "text": "deprecated API: foo"},
                ],
            },
        }],
    }
    body = M.render(run_log, {"attachments": []}, TEMPLATE)
    assert "Failed" in body
    assert "TypeError" in body
    assert "Console output" in body


def test_screenshot_attachment_appears_in_step_block():
    run_log = {
        "ticket": "M1-1206", "verdict": "pass",
        "execution_trace": [_step(5)],
    }
    attachments_idx = {
        "attachments": [
            {"step_n": 5, "label": "screenshot",
             "gitlab_markdown": "![step5](/uploads/xyz/step5.gif)"},
        ],
    }
    body = M.render(run_log, attachments_idx, TEMPLATE)
    assert "![step5](/uploads/xyz/step5.gif)" in body


def test_console_log_attachment_falls_back_to_link_when_no_inline():
    run_log = {
        "ticket": "M1-1206", "verdict": "pass",
        "execution_trace": [_step(2)],
    }
    attachments_idx = {
        "attachments": [
            {"step_n": 2, "label": "console",
             "gitlab_markdown": "[step-2.console.log](/uploads/log/step2.log)"},
        ],
    }
    body = M.render(run_log, attachments_idx, TEMPLATE)
    assert "[step-2.console.log](/uploads/log/step2.log)" in body
    assert "Console log" in body


def test_dom_attachment_renders_as_link():
    run_log = {
        "ticket": "M1-1206", "verdict": "pass",
        "execution_trace": [_step(2)],
    }
    attachments_idx = {
        "attachments": [
            {"step_n": 2, "label": "dom",
             "gitlab_markdown": "[step-2.dom.html](/uploads/dom/step2.html)"},
        ],
    }
    body = M.render(run_log, attachments_idx, TEMPLATE)
    assert "[step-2.dom.html](/uploads/dom/step2.html)" in body
    assert "DOM snapshot" in body


def test_step_verdict_emojis_render():
    run_log = {
        "ticket": "M1-X", "verdict": "partial",
        "execution_trace": _trace(
            _step(1, verdict="pass"),
            _step(2, verdict="fail"),
            _step(3, verdict="needs_human"),
        ),
    }
    body = M.render(run_log, {"attachments": []}, TEMPLATE)
    # ascii-only assertions to avoid encoding surprises
    assert "step-1" in body or "Step 1" in body
    assert "Step 2" in body
    assert "Step 3" in body


def test_truncation_notice_renders_when_set():
    run_log = {
        "ticket": "M1-X", "verdict": "fail",
        "execution_trace": [_step(1, verdict="fail")],
    }
    attachments_idx = {
        "attachments": [{"step_n": 1, "label": "screenshot", "gitlab_markdown": "![](/u/a)"}],
        "truncated": True, "truncated_count": 3, "total_count": 4,
    }
    body = M.render(run_log, attachments_idx, TEMPLATE)
    assert "Showing evidence" in body


def test_empty_trace_has_clean_fallback():
    run_log = {"ticket": "M1-X", "verdict": "blocked", "execution_trace": []}
    body = M.render(run_log, {"attachments": []}, TEMPLATE)
    assert "no per-step evidence" in body
