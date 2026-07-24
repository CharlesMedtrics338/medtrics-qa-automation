"""Unit tests for qa-optimus-bridge/scripts/optimus_build_verdict_comment.py.

    pytest skills/qa-optimus-bridge/tests/test_optimus_build_verdict_comment.py
"""
import optimus_build_verdict_comment as C


def _log(verdict, **extra):
    base = {
        "ticket": "M1-1190",
        "verdict": verdict,
        "lane": "ui",
        "p0_pass_rate": 1.0,
        "p1_pass_rate": 1.0,
        "failed_items": [],
        "execution_trace": [],
    }
    base.update(extra)
    return base


def test_pass_comment_names_target_lane_and_pass_rates():
    out = C.build_comment(_log("pass"), target_lane="qa2")
    assert "moved to `qa2`" in out
    assert "P0 100%" in out
    assert "P1 100%" in out
    assert "mem://QA Run Logs/M1-1190" in out
    # No GitLab URL for pass
    assert "GitLab" not in out


def test_fail_comment_includes_gitlab_thread_url_when_provided():
    log = _log("fail", p0_pass_rate=0.5, failed_items=["step-2", "step-4"])
    url = "https://gitlab.com/medtrics/x/-/merge_requests/6865#note_42"
    out = C.build_comment(log, target_lane="needs_changes", gitlab_thread_url=url)
    assert "moved to `needs_changes`" in out
    assert "Verdict `fail`" in out
    assert "P0 50%" in out
    assert "2 failing step" in out
    assert url in out


def test_fail_comment_omits_thread_line_when_no_url():
    out = C.build_comment(_log("fail"), target_lane="needs_changes")
    assert "moved to `needs_changes`" in out
    assert "GitLab fail-thread" not in out


def test_partial_comment_counts_needs_human_steps():
    log = _log("partial", execution_trace=[
        {"verdict": "pass"}, {"verdict": "needs_human"}, {"verdict": "needs_human"},
        {"verdict": "pass"},
    ])
    out = C.build_comment(log, target_lane="needs_review")
    assert "sent to `needs_review`" in out
    assert "2 step(s) flagged `needs_human`" in out


def test_blocked_comment_includes_blocked_reason():
    log = _log("blocked", blocked_reason="checklist_missing")
    out = C.build_comment(log, target_lane="qa1")
    assert "stayed in `qa1`" in out
    assert "checklist_missing" in out


def test_unknown_verdict_falls_through_to_generic_line():
    out = C.build_comment(_log("weird"), target_lane="qa2")
    assert "weird" in out
    assert "→ `qa2`" in out


def test_rates_format_as_dashes_when_none():
    log = _log("pass", p0_pass_rate=None, p1_pass_rate=None)
    out = C.build_comment(log, target_lane="qa2")
    assert "P0 —" in out
    assert "P1 —" in out
