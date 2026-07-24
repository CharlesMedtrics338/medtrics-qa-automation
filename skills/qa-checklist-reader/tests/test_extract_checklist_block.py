"""Unit tests for extract_checklist_block.py — pulls the '## QA Checklist'
section out of an Optimus task description. Pure-Python, no network.

Run with: pytest tests/test_extract_checklist_block.py
"""
import extract_checklist_block as E


def test_present_with_surrounding_prose():
    desc = (
        "Some intro prose.\n\n"
        "## Context\n"
        "Context here.\n\n"
        "## QA Checklist\n"
        "\n"
        "Tester role: coordinator\n"
        "Branch: feat/x\n\n"
        "1. [P0] Do thing\n"
        "   Expected: ok\n\n"
        "## Notes\n"
        "closing.\n"
    )
    out = E.extract(desc)
    assert out["present"] is True
    assert out["reason"] is None
    assert "Tester role: coordinator" in out["checklist"]
    assert "[P0] Do thing" in out["checklist"]
    assert "## Notes" not in out["checklist"]
    assert "closing" not in out["checklist"]


def test_missing_returns_blocked_reason():
    out = E.extract("just some prose, no heading anywhere")
    assert out["present"] is False
    assert out["reason"] == "checklist_missing"
    assert out["checklist"] == ""


def test_pointer_block_is_stripped():
    desc = (
        "## QA Checklist\n\n"
        "Tester role: pd\n\n"
        "1. [P0] step\n"
        "   Expected: ok\n\n"
        "<!-- qa-automation:pointer:start -->\n"
        "verdict: pass\n"
        "<!-- qa-automation:pointer:end -->\n\n"
        "## Other\n"
    )
    out = E.extract(desc)
    assert out["present"] is True
    assert "verdict: pass" not in out["checklist"]
    assert "qa-automation:pointer" not in out["checklist"]
    assert "[P0] step" in out["checklist"]


def test_section_at_end_of_description():
    desc = "## Background\nfoo\n\n## QA Checklist\n\nTester role: trainee\n\n1. [P0] x\n   Expected: y\n"
    out = E.extract(desc)
    assert out["present"] is True
    assert "Tester role: trainee" in out["checklist"]


def test_heading_must_be_exact():
    # "## qa checklist" lower-case should NOT match (case-sensitive on the heading text).
    desc = "## qa checklist\n\nTester role: coordinator\n\n1. [P0] x\n   Expected: y\n"
    out = E.extract(desc)
    assert out["present"] is False


def test_extract_then_parse_pipeline_smoke():
    """Verify the v0.4 pipeline (extract → parse) handoff produces structured steps."""
    import parse_checklist_steps as P  # noqa: E402
    desc = (
        "Bug report follows.\n\n"
        "## QA Checklist\n\n"
        "Tester role: coordinator\n"
        "Branch: feat/m1-1234/csv-fix\n\n"
        "1. [P0] Navigate to /curriculum/imports and click \"Download CSV template\"\n"
        "   Expected: A CSV file downloads; UTF-8 punctuation, no mojibake.\n\n"
        "2. [P1] Upload courses-good.csv\n"
        "   Expected: 8 rows imported, no console errors.\n"
    )
    block = E.extract(desc)
    assert block["present"]
    parsed = P.parse(block["checklist"])
    assert parsed["persona"] == "coordinator"
    assert parsed["branch"] == "feat/m1-1234/csv-fix"
    assert parsed["step_count"] == 2
    assert parsed["priority_counts"]["P0"] == 1
    assert parsed["priority_counts"]["P1"] == 1
