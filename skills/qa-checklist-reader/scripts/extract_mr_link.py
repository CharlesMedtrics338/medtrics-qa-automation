#!/usr/bin/env python3
"""
Extract MR resolution hints from an Optimus ticket's title + description.

This script is PURE. It does no network calls. It returns a structured
list of resolution candidates the qa-checklist-reader SKILL.md procedure
feeds into the qa-gitlab-bridge scripts (gitlab_get_mr.py etc.) in priority
order:

  1. explicit_mr_url   — a literal gitlab.com/.../merge_requests/NNNN URL
                         was found in the text.  Use this directly with
                         get_merge_request(merge_request_iid=NNNN).
  2. branch_exact      — a complete branch slug like
                         fix/m1-1129/bug-curriculum-a-import-encoded was
                         found.  Use get_merge_request(source_branch=slug).
  3. ticket_id_search  — a ticket id like M1-1129 was found in title or
                         description but no full branch slug.  Use
                         list_merge_requests(search=<ticket_id>) and pick
                         the open MR whose source_branch contains the id.

Why these three:
  - explicit URLs are unambiguous and rare.
  - branch slugs are how the medtrics-legacy team actually keys MRs to
    tickets; the GitLab auto-generated MR title is literally the slug with
    hyphens replaced by spaces.
  - the ticket id alone is the universal fallback — every Optimus ticket
    has one, and devs paste it into branch names by policy.

Output schema (JSON on stdout):

  {
    "ticket_ids":  ["M1-1129", ...],         # canonical-form, dedup'd
    "mr_urls":     [{"url": "...", "iid": "6848"}, ...],
    "branches":    ["fix/m1-1129/...", ...], # raw, lowercase, dedup'd
    "candidates":  [                         # ordered, highest confidence first
       {"strategy": "explicit_mr_url",   "value": {...}, "confidence": 1.0},
       {"strategy": "branch_exact",      "value": "...", "confidence": 0.9},
       {"strategy": "ticket_id_search",  "value": "M1-1129", "confidence": 0.6}
    ],
    "resolved":    bool                      # True iff candidates is non-empty
  }

Exit code is always 0 unless the inputs are malformed.  An empty candidate
list is a normal outcome ("no resolution hints" — the SKILL.md writes a
blocked Mem note and moves on).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
# Patterns
# --------------------------------------------------------------------------- #

# Explicit GitLab MR URL anywhere in the text.
# Examples that match:
#   https://gitlab.com/medtrics/medtrics/-/merge_requests/6848
#   https://gitlab.example.com/group/project/merge_requests/6848
GITLAB_MR_RE = re.compile(
    r"https?://[^\s)>\]]+?/-?/?merge_requests/(\d+)",
    re.IGNORECASE,
)

# Complete branch slugs starting with a known verb prefix. The Medtrics
# convention is `<verb>/<ticket-id>/<descriptor>`.
# Examples that match:
#   fix/m1-1129/bug-curriculum-a-import-encoded
#   feat/gen-21668/multi-tenant-rollover
#   chore/m1-1234/cleanup
BRANCH_SLUG_RE = re.compile(
    r"\b((?:feat|fix|chore|hotfix|refactor|test|docs|perf|style|build|ci|revert)"
    r"/[a-z][a-z0-9_\-/.]{2,})",
    re.IGNORECASE,
)

# Explicit "Branch:" line so we can ground confidence higher than a loose
# slug found elsewhere.
BRANCH_LINE_RE = re.compile(
    r"""(?ix)
    (?:^|\n)
    [\s\-*]*
    \**\s*branch\s*\**\s*:\s*
    `?([a-z][a-z0-9_\-/.]+)`?
    """
)

# Ticket-id patterns. The canonical form is <PREFIX>-<DIGITS>, with PREFIX
# being 2-5 alphanumeric characters (M1, GEN, M2, FE, BE — all real Medtrics
# prefixes are 2+ chars).  We accept hyphen, underscore, or whitespace as
# the separator because GitLab's auto-generated draft titles replace
# hyphens with spaces ("Fix/m1 1129/bug ..." vs the actual branch slug
# "fix/m1-1129/bug-...").
#
# Requiring 2+ chars in the prefix is what kills the "a-400" / "a-500"
# sentence-fragment false positives ("should return a 400", "not a 500").
TICKET_ID_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]{1,4})[\s\-_]+?(\d{2,6})\b"
)

# Stop-words that look like ticket ids but aren't.
TICKET_ID_BLOCKLIST = {
    "v1", "v2", "v3", "v4", "v5",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p0", "p1", "p2", "p3",   # priority labels
    "iso8601",                # common false-positive
    "rfc",                    # rfc 7234 etc
    "covid19",
    "win10", "win11",
    "py3", "py2",
}


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def find_mr_urls(text: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for m in GITLAB_MR_RE.finditer(text or ""):
        url, iid = m.group(0), m.group(1)
        if iid in seen:
            continue
        seen.add(iid)
        out.append({"url": url, "iid": iid})
    return out


def find_branches(text: str) -> tuple[list[str], list[str]]:
    """Returns (explicit_branches, loose_branches). Explicit ones came from
    a `Branch:` line; loose ones came from a free-text slug elsewhere."""
    text = text or ""
    explicit: list[str] = []
    for m in BRANCH_LINE_RE.finditer(text):
        explicit.append(m.group(1).lower())
    loose: list[str] = []
    for m in BRANCH_SLUG_RE.finditer(text):
        slug = m.group(1).lower()
        if slug not in explicit:
            loose.append(slug)
    return _dedup(explicit), _dedup(loose)


def find_ticket_ids(text: str) -> list[str]:
    """Return canonical-form ticket ids found anywhere in the text.

    The canonical form is uppercase prefix, hyphen, digits — e.g. M1-1129.
    The matcher tolerates space, underscore, and hyphen separators so the
    GitLab-auto-titled draft "Fix/m1 1129/bug ..." normalizes correctly.
    """
    text = text or ""
    seen: set[str] = set()
    out: list[str] = []
    for m in TICKET_ID_RE.finditer(text):
        prefix, digits = m.group(1).lower(), m.group(2)
        if prefix in TICKET_ID_BLOCKLIST:
            continue
        # Pure-digit prefixes don't fit our schema (e.g. "2026 05" date).
        if prefix.isdigit():
            continue
        # Require an alpha character in the prefix; we already start with
        # one but be explicit.
        if not any(c.isalpha() for c in prefix):
            continue
        canonical = f"{prefix.upper()}-{digits}"
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


def _dedup(xs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in xs:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


# --------------------------------------------------------------------------- #
# Candidate ordering
# --------------------------------------------------------------------------- #


def build_candidates(
    mr_urls: list[dict],
    explicit_branches: list[str],
    loose_branches: list[str],
    ticket_ids: list[str],
) -> list[dict]:
    """Order by confidence, highest first."""
    candidates: list[dict] = []

    # 1.0 — explicit MR URL: unambiguous
    for mr in mr_urls:
        candidates.append({
            "strategy": "explicit_mr_url",
            "value": mr,
            "confidence": 1.0,
        })

    # 0.9 — branch slug from an explicit "Branch:" line
    for b in explicit_branches:
        candidates.append({
            "strategy": "branch_exact",
            "value": b,
            "confidence": 0.9,
        })

    # 0.8 — branch slug found loosely in text
    for b in loose_branches:
        candidates.append({
            "strategy": "branch_exact",
            "value": b,
            "confidence": 0.8,
        })

    # 0.6 — ticket id alone; SKILL.md must search GitLab to resolve
    for tid in ticket_ids:
        candidates.append({
            "strategy": "ticket_id_search",
            "value": tid,
            "confidence": 0.6,
        })

    return candidates


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def extract(title: str, description: str) -> dict:
    """Combine title + description and emit all resolution hints."""
    combined = "\n".join(filter(None, [title or "", description or ""]))
    if not combined.strip():
        return {
            "ticket_ids": [],
            "mr_urls": [],
            "branches": [],
            "candidates": [],
            "resolved": False,
            "reason": "empty_input",
        }

    mr_urls = find_mr_urls(combined)
    explicit_branches, loose_branches = find_branches(combined)
    ticket_ids = find_ticket_ids(combined)

    candidates = build_candidates(
        mr_urls, explicit_branches, loose_branches, ticket_ids
    )

    return {
        "ticket_ids": ticket_ids,
        "mr_urls": mr_urls,
        "branches": _dedup(explicit_branches + loose_branches),
        "candidates": candidates,
        "resolved": len(candidates) > 0,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--title", default="", help="Optimus ticket title.")
    ap.add_argument("--description", default="", help="Inline description.")
    ap.add_argument(
        "--description-file",
        type=Path,
        help="Read the description from a file (overrides --description).",
    )
    ap.add_argument(
        "--title-file",
        type=Path,
        help="Read the title from a file (overrides --title).",
    )
    args = ap.parse_args(argv)

    title = (
        args.title_file.read_text(encoding="utf-8") if args.title_file
        else args.title
    )
    description = (
        args.description_file.read_text(encoding="utf-8") if args.description_file
        else args.description
    )

    print(json.dumps(extract(title, description), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
