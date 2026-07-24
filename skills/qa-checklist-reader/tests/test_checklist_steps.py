"""Unit tests for parse_checklist_steps.py (Optimus '## QA Checklist' section
or any compatible text -> structured steps).

Pure-Python, no network. Run with:
    pytest tests/test_checklist_steps.py
"""
from pathlib import Path

import parse_checklist_steps as P

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-ui-checklist.txt"


def parsed():
    return P.parse(FIXTURE.read_text(encoding="utf-8"))


def test_persona_and_branch_extracted():
    out = parsed()
    assert out["persona"] == "coordinator"
    assert out["branch"] == "fix/m1-1190/block-schedule-date-off-by-one"


def test_step_count_and_numbering():
    out = parsed()
    assert out["step_count"] == 5
    assert [s["n"] for s in out["steps"]] == [1, 2, 3, 4, 5]
    assert [s["step_id"] for s in out["steps"]] == [f"step-{i}" for i in range(1, 6)]


def test_priorities_and_inheritance():
    out = parsed()
    pr = [s["priority"] for s in out["steps"]]
    # Steps 1,2 = P0; 3 = P1; 4 untagged -> inherits previous (P1); 5 = P2.
    assert pr == ["P0", "P0", "P1", "P1", "P2"]
    assert out["priority_counts"] == {"P0": 2, "P1": 2, "P2": 1}


def test_action_text_has_tag_stripped():
    out = parsed()
    s2 = out["steps"][1]
    assert s2["action"].startswith("Create a block starting 2026-05-12")
    assert "[P0]" not in s2["action"]


def test_expected_captured():
    out = parsed()
    s2 = out["steps"][1]
    assert "2026-05-12" in s2["expected"]
    assert "2026-05-11" in s2["expected"]  # the bug condition is described
    s5 = out["steps"][4]
    assert s5["expected"] == "Looks correct."  # vague -> executor will mark needs_human


def test_persona_synonym_mapping():
    txt = "Branch: feat/x\nTester role: Program Director\n1. [P0] do thing\n   Expected: ok"
    out = P.parse(txt)
    assert out["persona"] == "pd"


def test_handles_missing_persona_gracefully():
    txt = "Branch: feat/y\n1. [P0] do thing\n   Expected: shows \"Done\""
    out = P.parse(txt)
    assert out["persona"] is None
    assert out["step_count"] == 1
