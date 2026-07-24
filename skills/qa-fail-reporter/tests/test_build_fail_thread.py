"""Unit tests for qa-fail-reporter/scripts/build_fail_thread.py and
select_attachments.py. Pure-Python, no GitLab calls.

    pytest tests/test_build_fail_thread.py
"""
from pathlib import Path

import build_fail_thread as B
import select_attachments as S

# Skill root is one level up from tests/ — sibling to scripts/ and templates/.
SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL_ROOT / "templates" / "fail-thread.md"


def _run_log(verdict="fail", failures=None):
    return {
        "ticket": "M1-1190",
        "branch": "feat/x",
        "deploy_url": "https://mr-1.medtrics.dev",
        "lane": "ui",
        "run_id": "2026-06-02T18-00-00Z",
        "verdict": verdict,
        "verdict_confidence": 0.92,
        "p0_pass_rate": 0.5,
        "p1_pass_rate": 1.0,
        "p2_pass_rate": 1.0,
        "mr_url": "https://gitlab.com/x/-/merge_requests/1",
        "mr_id": "1",
        "checklist": {"step_count": len(failures) + 1 if failures else 1},
        "execution_trace": failures or [],
        "ui_observations": [],
    }


def _fail_step(n, console_err=None, net_err=None, screenshot=True):
    ev = {"url": f"/p{n}", "assertions": [{"kind": "text_present", "passed": False}]}
    if screenshot:
        ev["screenshot_ref"] = f"step-{n}.png"
    if console_err:
        ev["console_errors"] = [{"level": "error", "text": console_err}]
    if net_err:
        ev["network_errors"] = [{"method": "GET", "url": net_err, "status": 500}]
    return {
        "n": n, "step_id": f"step-{n}", "priority": "P0",
        "action_taken": f"Did thing {n}",
        "observed": f"Saw something wrong on step {n}",
        "expected": f"Expected something else on step {n}",
        "verdict": "fail",
        "evidence": ev,
    }


# ---------- select_attachments ----------

def test_select_picks_before_and_at_failure_pair(tmp_path):
    rl = _run_log(failures=[
        {"n": 1, "step_id": "step-1", "priority": "P0", "verdict": "pass",
         "evidence": {"screenshot_ref": "step-1.png"}},
        _fail_step(2),
    ])
    (tmp_path / "step-1.png").write_bytes(b"x")
    (tmp_path / "step-2.png").write_bytes(b"x")
    out = S.select(rl, tmp_path)
    labels = [a["label"] for a in out["attachments"]]
    assert labels == ["before", "at_failure"]
    assert all(a["exists"] for a in out["attachments"])


def test_select_skips_before_when_failure_is_first_step(tmp_path):
    rl = _run_log(failures=[_fail_step(1)])
    (tmp_path / "step-1.png").write_bytes(b"x")
    out = S.select(rl, tmp_path)
    labels = [a["label"] for a in out["attachments"]]
    assert labels == ["at_failure"]


def test_select_truncates_when_too_many_failures(tmp_path):
    fails = [_fail_step(n) for n in range(1, 11)]  # 10 failures
    rl = _run_log(failures=fails)
    for n in range(1, 11):
        (tmp_path / f"step-{n}.png").write_bytes(b"x")
    out = S.select(rl, tmp_path, max_attachments=8)
    assert out["truncated"] is True
    assert out["truncated_count"] > 0
    assert len(out["attachments"]) <= 8


def test_select_handles_missing_screenshots(tmp_path):
    rl = _run_log(failures=[_fail_step(1, screenshot=False)])
    out = S.select(rl, tmp_path)
    assert out["attachments"] == []  # no screenshot_ref → no attachments


# ---------- build_fail_thread ----------

def test_thread_renders_with_all_sections():
    rl = _run_log(failures=[_fail_step(
        2,
        console_err="TypeError: bad bad bad",
        net_err="/api/v2/foo",
    )])
    rl["ui_observations"] = [
        {"kind": "broken_image", "step_id": "step-2",
         "evidence": "img.x naturalWidth=0"}
    ]
    atts = {"attachments": [
        {"step_n": 2, "step_id": "step-2", "label": "at_failure",
         "path": "step-2.png",
         "gitlab_markdown": "![at_failure.png](/uploads/abc/step-2.png)"}
    ], "truncated": False, "truncated_count": 0}
    body = B.render(rl, atts, TEMPLATE, dashboard_url="cowork://x")
    assert "M1-1190" in body
    assert "Failed" in body
    assert "Did thing 2" in body
    assert "Saw something wrong" in body
    assert "TypeError: bad bad bad" in body
    assert "/api/v2/foo" in body
    assert "500" in body
    assert "/uploads/abc/step-2.png" in body
    assert "broken_image" in body
    assert "img.x naturalWidth=0" in body


def test_thread_handles_missing_attachments_gracefully():
    rl = _run_log(failures=[_fail_step(2)])
    atts = {"attachments": [], "truncated": False, "truncated_count": 0}
    body = B.render(rl, atts, TEMPLATE)
    assert "M1-1190" in body
    assert "Step 2" in body


def test_thread_emits_truncation_notice_when_many_failures():
    rl = _run_log(failures=[_fail_step(n) for n in range(1, 11)])
    atts = {"attachments": [], "truncated": True, "truncated_count": 7,
            "total_failures": 10}
    body = B.render(rl, atts, TEMPLATE)
    assert "Showing screenshots" in body
    assert "10" in body


def test_pass_rates_format_as_percent():
    rl = _run_log(failures=[_fail_step(2)])
    body = B.render(rl, {"attachments": [], "truncated": False,
                         "truncated_count": 0}, TEMPLATE)
    assert "**50%**" in body  # p0_pass_rate=0.5
    assert "**100%**" in body  # p1_pass_rate=1.0


def test_ui_observations_section_omitted_when_empty():
    rl = _run_log(failures=[_fail_step(2)])
    rl["ui_observations"] = []
    body = B.render(rl, {"attachments": [], "truncated": False,
                         "truncated_count": 0}, TEMPLATE)
    assert "UI/UX observations" not in body


def test_partial_verdict_renders_with_partial_title():
    rl = _run_log(verdict="partial", failures=[_fail_step(2)])
    body = B.render(rl, {"attachments": [], "truncated": False,
                         "truncated_count": 0}, TEMPLATE)
    assert "Partial" in body
