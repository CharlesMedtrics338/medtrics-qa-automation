"""Unit tests for qa-gitlab-bridge/scripts/gitlab_find_mr_attachment.py.

Covers the branch → filename slug conversion, the upload-ref regex
extraction, and the match-priority / tiebreak logic. Pure-Python; no
network.

    pytest skills/qa-gitlab-bridge/tests/test_find_mr_attachment.py
"""
import gitlab_find_mr_attachment as F


# ---- branch_to_filename_slug ----

def test_slug_replaces_slashes():
    assert F.branch_to_filename_slug("fix/m1-1190/block-schedule-foo") \
        == "fix-m1-1190-block-schedule-foo"


def test_slug_lowercases():
    assert F.branch_to_filename_slug("Feat/M1-1234/CSV-Encoding") \
        == "feat-m1-1234-csv-encoding"


def test_slug_collapses_double_dashes():
    assert F.branch_to_filename_slug("fix//m1-1190//foo") == "fix-m1-1190-foo"


def test_slug_strips_leading_trailing_dashes():
    assert F.branch_to_filename_slug("/fix/m1-1190/") == "fix-m1-1190"


def test_slug_empty_input():
    assert F.branch_to_filename_slug("") == ""
    assert F.branch_to_filename_slug(None) == ""


def test_expected_filename_appends_suffix():
    assert F.expected_filename("fix/m1-1190/block-schedule-foo") \
        == "fix-m1-1190-block-schedule-foo-manual-qa-checklist.txt"


# ---- upload-ref extraction (exercised via the gitlab_client helper) ----

def test_finder_extracts_canonical_upload_markdown():
    # We use the lib's helper directly here; it's the regex layer the finder
    # consumes.
    from gitlab_client import extract_upload_refs
    body = (
        "checklist attached: "
        "[fix-m1-1190-block-schedule-foo-manual-qa-checklist.txt]"
        "(/uploads/0e2a605a3146a2db9ae2b6d78761114d/fix-m1-1190-block-schedule-foo-manual-qa-checklist.txt)"
    )
    refs = extract_upload_refs(body)
    assert len(refs) == 1
    assert refs[0]["secret"] == "0e2a605a3146a2db9ae2b6d78761114d"
    assert refs[0]["filename"].endswith("-manual-qa-checklist.txt")


def test_finder_ignores_short_or_malformed_uploads():
    from gitlab_client import extract_upload_refs
    # secrets shorter than 8 hex chars are filtered (defensive — real GitLab
    # uploads use 32+).
    body = "see [bad.txt](/uploads/abc/bad.txt) and [also-bad](/random/thing/x.txt)"
    refs = extract_upload_refs(body)
    assert refs == []


# ---- match priority ----

def _discussion(notes):
    return {"id": "d1", "notes": notes}


def _note(body, *, note_id=1, created_at="2026-06-03T13:57:36.312Z", author="cnorris"):
    return {"id": note_id, "body": body, "created_at": created_at,
            "author": {"username": author}}


def test_priority_prefers_exact_branch_slug_over_suffix_match():
    branch = "fix/m1-1190/block-schedule-foo"
    canonical = F.expected_filename(branch)
    other_name = "some-random-thing-manual-qa-checklist.txt"
    discussions = [_discussion([
        _note(f"[{other_name}](/uploads/aaaa11112222333344445555666677aa/{other_name})",
              note_id=1, created_at="2026-06-03T14:00:00Z"),
        _note(f"[{canonical}](/uploads/bbbb11112222333344445555666677bb/{canonical})",
              note_id=2, created_at="2026-06-03T13:00:00Z"),  # older!
    ])]
    cands = F._gather_attachment_candidates(discussions, branch=branch, ticket=None,
                                            pattern=F.DEFAULT_PATTERN)
    best = F.pick_best(cands)
    # exact_branch_slug should win even though it was uploaded earlier
    assert best["match_kind"] == "exact_branch_slug"
    assert best["filename"] == canonical


def test_priority_suffix_match_beats_ticket_id_match():
    discussions = [_discussion([
        _note("[m1-1190-misc.txt](/uploads/aaaa11112222333344445555666677aa/m1-1190-misc.txt)",
              note_id=1),
        _note("[anything-manual-qa-checklist.txt](/uploads/bbbb11112222333344445555666677bb/anything-manual-qa-checklist.txt)",
              note_id=2),
    ])]
    cands = F._gather_attachment_candidates(discussions, branch=None, ticket="M1-1190",
                                            pattern=F.DEFAULT_PATTERN)
    best = F.pick_best(cands)
    assert best["match_kind"] == "suffix"
    assert best["filename"].endswith("-manual-qa-checklist.txt")


def test_ticket_id_match_when_no_suffix_or_branch_match():
    discussions = [_discussion([
        _note("[m1-1190-stuff.txt](/uploads/aaaa11112222333344445555666677aa/m1-1190-stuff.txt)",
              note_id=1),
    ])]
    cands = F._gather_attachment_candidates(discussions, branch=None, ticket="M1-1190",
                                            pattern="*.never-matches-anything*")
    best = F.pick_best(cands)
    assert best["match_kind"] == "ticket_id"


def test_most_recent_wins_among_same_priority():
    branch = "fix/m1-1190/block-schedule-foo"
    canonical = F.expected_filename(branch)
    discussions = [_discussion([
        _note(f"[{canonical}](/uploads/aaaa11112222333344445555666677aa/{canonical})",
              note_id=1, created_at="2026-06-02T13:00:00Z"),
        _note(f"[{canonical}](/uploads/bbbb11112222333344445555666677bb/{canonical})",
              note_id=2, created_at="2026-06-03T13:00:00Z"),  # newer
    ])]
    cands = F._gather_attachment_candidates(discussions, branch=branch, ticket=None,
                                            pattern=F.DEFAULT_PATTERN)
    best = F.pick_best(cands)
    assert best["note_id"] == 2  # newer wins


def test_no_candidates_returns_none():
    discussions = [_discussion([
        _note("just a regular comment, no uploads here", note_id=1),
    ])]
    cands = F._gather_attachment_candidates(discussions, branch=None, ticket=None,
                                            pattern=F.DEFAULT_PATTERN)
    assert cands == []
    assert F.pick_best(cands) is None


def test_pick_best_empty_list():
    assert F.pick_best([]) is None
