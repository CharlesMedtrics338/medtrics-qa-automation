"""Tests for the plain-English narrative renderers in build_verdict_thread.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_verdict_thread as M  # noqa: E402


def _step(n, verdict="pass", action="Click button X", priority="P0", note=""):
    s = {
        "n": n, "verdict": verdict, "priority": priority,
        "action_taken": action,
    }
    if note:
        s["note"] = note
    return s


# ----- _clean_action -----

def test_clean_action_strips_step_prefix():
    assert M._clean_action("Step 3 — Open the dialog") == "Open the dialog"
    assert M._clean_action("3. Click submit") == "Click submit"
    assert M._clean_action("- Inspect the row") == "Inspect the row"
    assert M._clean_action("4) Save the form") == "Save the form"


def test_clean_action_collapses_whitespace():
    assert M._clean_action("Step 1 —  Click   the  button  ") == "Click the button"


def test_clean_action_handles_empty():
    assert M._clean_action("") == "(no action recorded)"
    assert M._clean_action(None) == "(no action recorded)"


def test_clean_action_truncates_long_text():
    long_action = "A" * 200
    out = M._clean_action(long_action, max_chars=50)
    assert len(out) == 50
    assert out.endswith("…")


# ----- _format_test_summary_narrative -----

def test_test_summary_lists_each_step():
    trace = [
        _step(1, "pass", "Step 1 — Log in as admin"),
        _step(2, "pass", "Click Edit"),
        _step(3, "fail", "Save the form"),
    ]
    out = M._format_test_summary_narrative(trace)
    assert "**Step 1**" in out and "Log in as admin" in out
    assert "**Step 2**" in out and "Click Edit" in out
    assert "**Step 3**" in out and "Save the form" in out


def test_test_summary_includes_priority_when_present():
    trace = [_step(1, "pass", "Click button", priority="P0")]
    assert "`P0`" in M._format_test_summary_narrative(trace)


def test_test_summary_truncates_with_suffix():
    trace = [_step(i, "pass", f"Step {i} action") for i in range(1, 20)]  # 19 steps
    out = M._format_test_summary_narrative(trace)
    assert "**Step 15**" in out
    assert "**Step 16**" not in out
    assert "more step" in out


def test_test_summary_empty_trace():
    assert "no steps" in M._format_test_summary_narrative([]).lower()


# ----- _format_outcomes_narrative -----

def test_outcomes_pass_all_steps():
    run_log = {
        "verdict": "pass",
        "execution_trace": [_step(1, "pass"), _step(2, "pass"), _step(3, "pass")],
    }
    out = M._format_outcomes_narrative(run_log)
    assert "All 3" in out and "passed" in out


def test_outcomes_pass_with_needs_human():
    run_log = {
        "verdict": "pass",
        "execution_trace": [_step(1, "pass"), _step(2, "needs_human")],
    }
    out = M._format_outcomes_narrative(run_log)
    assert "need" in out.lower() and "human" in out.lower()


def test_outcomes_fail_anchors_first_failure():
    run_log = {
        "verdict": "fail",
        "execution_trace": [
            _step(1, "pass", "Click login"),
            _step(2, "fail", "Submit form with empty field"),
            _step(3, "pass", "Reload page"),
        ],
    }
    out = M._format_outcomes_narrative(run_log)
    assert "1 of 3" in out or "1 of" in out
    assert "Step 2" in out
    assert "Submit form with empty field" in out


def test_outcomes_partial_with_missing_test_data_plain_english():
    run_log = {
        "verdict": "partial",
        "partial_cause": "missing_test_data",
        "execution_trace": [_step(1, "pass"), _step(2, "needs_human")],
    }
    out = M._format_outcomes_narrative(run_log)
    # Should use the plain-English mapping, not just echo the cause name.
    assert "missing_test_data" not in out
    assert "seeded" in out or "seed" in out.lower()


def test_outcomes_partial_unknown_cause_falls_back_to_cause_string():
    run_log = {
        "verdict": "partial",
        "partial_cause": "some_new_cause_we_havent_mapped",
        "execution_trace": [_step(1, "pass")],
    }
    out = M._format_outcomes_narrative(run_log)
    assert "some_new_cause_we_havent_mapped" in out


def test_outcomes_blocked_uses_reason():
    run_log = {
        "verdict": "blocked",
        "blocked_reason": "checklist_missing",
        "execution_trace": [],
    }
    out = M._format_outcomes_narrative(run_log)
    assert "blocked" in out.lower()
    assert "checklist_missing" in out


# ----- _format_gaps_narrative -----

def test_gaps_lists_needs_human_steps():
    trace = [
        _step(1, "pass"),
        _step(2, "needs_human", "Verify responsive layout at narrow width",
              note="resize tool can't shrink viewport"),
        _step(3, "pass"),
        _step(4, "skipped", "Optional fallback create"),
        _step(5, "not_run", "Cross-browser regression"),
    ]
    out = M._format_gaps_narrative(trace)
    assert "Step 2" in out and "Needs human" in out
    assert "Step 4" in out and "Skipped" in out
    assert "Step 5" in out and "Not run" in out
    assert "Step 1" not in out
    assert "Step 3" not in out


def test_gaps_includes_why_when_note_present():
    trace = [
        _step(2, "needs_human", "Inspect the modal", note="modal didn't open"),
    ]
    out = M._format_gaps_narrative(trace)
    assert "why" in out.lower()
    assert "modal didn't open" in out


def test_gaps_omits_why_when_no_note():
    trace = [
        _step(2, "skipped", "Optional fallback create"),
    ]
    out = M._format_gaps_narrative(trace)
    assert "why" not in out.lower()


def test_gaps_truncates_long_notes():
    trace = [
        _step(2, "needs_human", "Inspect modal", note="X" * 300),
    ]
    out = M._format_gaps_narrative(trace)
    # Long note must be truncated to a reasonable length
    assert "X" * 300 not in out
    assert "…" in out


def test_gaps_empty_when_all_steps_completed():
    trace = [_step(1, "pass"), _step(2, "fail")]
    out = M._format_gaps_narrative(trace)
    assert "every step" in out.lower() or "none" in out.lower()


# ----- render() integration -----

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "verdict-thread.md"


def test_render_includes_narrative_sections():
    run_log = {
        "ticket": "M1-1206", "verdict": "pass",
        "execution_trace": [
            _step(1, "pass", "Log in as admin"),
            _step(2, "needs_human", "Inspect responsive layout"),
        ],
    }
    body = M.render(run_log, {"attachments": []}, TEMPLATE)
    assert "Plain-English summary" in body
    assert "What was tested" in body
    assert "What we observed" in body
    assert "What we did NOT cover" in body
    # Step actions appear in the narrative
    assert "Log in as admin" in body
    # Gap step is called out
    assert "Step 2" in body
    assert "Needs human" in body


def test_render_partial_with_lane_decision_shows_plain_english_cause():
    run_log = {
        "ticket": "M1-1207", "verdict": "partial",
        "partial_cause": "missing_test_data",
        "lane_decision": {
            "intended_lane": "needs_review",
            "effective_lane": "on_hold",
            "reason": "needs_review not yet released",
        },
        "execution_trace": [_step(1, "pass"), _step(2, "needs_human")],
    }
    body = M.render(run_log, {"attachments": []}, TEMPLATE)
    # Plain-English cause appears in the outcomes paragraph
    assert "seed" in body.lower()
    # Lane decision still shown in the technical block
    assert "needs_review" in body
