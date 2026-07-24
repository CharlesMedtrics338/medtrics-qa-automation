#!/usr/bin/env python3
"""
gitlab_find_mr_attachment.py — locate a checklist attachment in an MR's threads.

Walks the discussions on a merge request, extracts every project-upload
reference in every note body, and picks the best match against a filename
pattern. Returns the upload's secret + filename so the caller can hand them
to `gitlab_download_upload.py`.

Filename matching policy (in priority order):

  1. Exact match against the **branch-derived name**:
        branch_to_filename_slug(branch_name) + "-manual-qa-checklist.txt"
     e.g. `fix/m1-1190/block-schedule-foo` → `fix-m1-1190-block-schedule-foo-manual-qa-checklist.txt`

  2. Glob-style suffix match: anything ending in `-manual-qa-checklist.txt`.

  3. Any `.txt` attachment whose filename contains the ticket id (e.g.
     "m1-1190" anywhere in the name).

The script returns the **most recent** match (latest note `created_at`) when
the priority ties — so a re-uploaded checklist supersedes earlier copies in
the same thread.

Usage:
    python3 gitlab_find_mr_attachment.py \\
        --iid 6865 \\
        --branch fix/m1-1190/block-schedule-manage-blocks-form \\
        [--ticket M1-1190] \\
        [--pattern '*-manual-qa-checklist.txt']

Output (stdout):
    {
      "ok": true,
      "match": {
        "secret": "0e2a605a3146a2db9ae2b6d78761114d",
        "filename": "fix-m1-1190-...-manual-qa-checklist.txt",
        "alt": "fix-m1-1190-…-manual-qa-checklist.txt",
        "url": "/uploads/0e2a.../fix-m1-1190-...-manual-qa-checklist.txt",
        "note_id": 12345,
        "discussion_id": "abc...",
        "author": "CharlesMedtrics",
        "created_at": "2026-06-03T13:57:36.312Z",
        "match_kind": "exact_branch_slug" | "suffix" | "ticket_id"
      }
    }

Exit codes:
    0 — match found
    1 — env / input error
    3 — no matching attachment found in any discussion
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from gitlab_client import (  # noqa: E402
    load_env, get_mr_discussions, extract_upload_refs, log,
)

DEFAULT_PATTERN = "*-manual-qa-checklist.txt"


def branch_to_filename_slug(branch: str) -> str:
    """Convert a git branch into the filename slug used by the manual-qa
    checklist convention.

    Replaces both '/' and '\\' (Windows-style) with '-' so the resulting
    slug is a single flat filename component. Collapses consecutive
    separators. Lowercase. Does NOT add the '-manual-qa-checklist.txt'
    suffix — the caller composes the full name.

    Examples:
        fix/m1-1190/block-schedule-foo  →  fix-m1-1190-block-schedule-foo
        feat/M1-1234/CSV-Encoding       →  feat-m1-1234-csv-encoding
    """
    if not branch:
        return ""
    s = branch.strip().lower()
    for sep in ("\\", "/"):
        s = s.replace(sep, "-")
    # collapse runs of '-'
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")


def expected_filename(branch: str, suffix: str = "-manual-qa-checklist.txt") -> str:
    """Compose the canonical filename for a given branch."""
    return branch_to_filename_slug(branch) + suffix


def _gather_attachment_candidates(discussions: list, branch: str | None, ticket: str | None,
                                  pattern: str) -> list[dict]:
    """Return every upload ref across every note, annotated with author /
    created_at / match_kind."""
    canonical = expected_filename(branch) if branch else None
    ticket_lc = ticket.lower() if ticket else None

    candidates: list[dict] = []
    for d in discussions or []:
        for note in d.get("notes") or []:
            body = note.get("body") or ""
            for ref in extract_upload_refs(body):
                fn = ref["filename"]
                fn_lc = fn.lower()
                kind = None
                if canonical and fn_lc == canonical.lower():
                    kind = "exact_branch_slug"
                elif fnmatch.fnmatchcase(fn_lc, pattern.lower()):
                    kind = "suffix"
                elif ticket_lc and ticket_lc in fn_lc and fn_lc.endswith(".txt"):
                    kind = "ticket_id"
                else:
                    continue
                candidates.append({
                    "secret":         ref["secret"],
                    "filename":       fn,
                    "alt":            ref["alt"],
                    "url":            ref["url"],
                    "note_id":        note.get("id"),
                    "discussion_id":  d.get("id"),
                    "author":         (note.get("author") or {}).get("username"),
                    "created_at":     note.get("created_at"),
                    "match_kind":     kind,
                })
    return candidates


# Priority order — lower index wins ties on created_at.
_MATCH_KIND_PRIORITY = ("exact_branch_slug", "suffix", "ticket_id")


def pick_best(candidates: list[dict]) -> dict | None:
    """Pick the best match: highest-priority match_kind, then most recent."""
    if not candidates:
        return None
    def sort_key(c):
        pri = _MATCH_KIND_PRIORITY.index(c["match_kind"]) \
              if c["match_kind"] in _MATCH_KIND_PRIORITY else 99
        # negate created_at by string sort (ISO 8601 sorts lexicographically)
        # Newer is "larger" string; we want it first, so use a negated tuple.
        return (pri, -ord("Z") if not c.get("created_at") else 0, -hash(c.get("created_at") or ""))
    # Simpler: stable sort by priority asc, then created_at desc.
    candidates_sorted = sorted(
        candidates,
        key=lambda c: (
            _MATCH_KIND_PRIORITY.index(c["match_kind"]) if c["match_kind"] in _MATCH_KIND_PRIORITY else 99,
            -(int(_iso_to_sortable(c.get("created_at") or "")))
        ),
    )
    return candidates_sorted[0]


def _iso_to_sortable(iso: str) -> int:
    """Convert an ISO 8601 string to an int (UNIX-ish) for sort order; 0 on parse fail."""
    if not iso:
        return 0
    try:
        import datetime as dt
        s = iso.rstrip("Z")
        # tolerate fractional seconds
        return int(dt.datetime.fromisoformat(s).timestamp())
    except (ValueError, OverflowError):
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--iid", required=True, help="MR internal ID (e.g. 6865).")
    p.add_argument("--branch", help="Branch under test (used for exact-name matching).")
    p.add_argument("--ticket", help="Optimus ticket id (e.g. M1-1190) — used as a fallback "
                                    "match against the filename.")
    p.add_argument("--pattern", default=DEFAULT_PATTERN,
                   help=f"Glob fallback pattern (default {DEFAULT_PATTERN!r}).")
    p.add_argument("--project-id", help="Override env GITLAB_PROJECT_ID.")
    p.add_argument("--env-file", help="Explicit .env path.")
    args = p.parse_args()

    env = load_env(args.env_file)
    discussions = get_mr_discussions(env, args.iid, project_id=args.project_id)
    if not discussions:
        log(f"No discussions on MR {args.iid} (or fetch failed).")
        print(json.dumps({"ok": False, "reason": "no_discussions"}))
        return 3

    candidates = _gather_attachment_candidates(
        discussions, branch=args.branch, ticket=args.ticket, pattern=args.pattern,
    )
    if not candidates:
        print(json.dumps({"ok": False, "reason": "no_matching_attachment",
                          "expected_filename": expected_filename(args.branch) if args.branch else None,
                          "pattern": args.pattern}))
        return 3

    best = pick_best(candidates)
    print(json.dumps({"ok": True, "match": best,
                      "all_candidates": len(candidates)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
