#!/usr/bin/env python3
"""
Parse a human-authored QA Checklist (markdown or plain text) and count items by
priority tag.

In v0.4 the input is the `## QA Checklist` section on the Optimus ticket
(extracted by extract_checklist_block.py). The expected shape is:

    Branch under test: feat/...
    Scope Summary
    - ...

    High-Level Findings
    - [P0] something critical
    - [P1] high-traffic thing
    - [P2] long-tail thing

    Direct Actions
    - ...

    Numbered test steps
    1. [P0] Do the thing
       Expected: ...
    2. [P1] Do the other thing
       Expected: ...
    3. Untagged step
       Expected: ...

We count occurrences of [P0], [P1], [P2] tags, plus an "untagged" bucket for
step lines that look like checklist items but carry no priority marker.

Section titles (e.g., "Scope Summary", "Direct Actions") are also recorded
in the returned shape so the caller can sanity-check the structure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Priority-tag patterns, allowing for optional surrounding whitespace / case.
PRIORITY_TAGS = ("P0", "P1", "P2")
TAG_RE = re.compile(r"\[\s*(P[012])\s*\]", re.IGNORECASE)

# A "checklist step line" is a numbered or bulleted line that looks like a test step.
STEP_LINE_RE = re.compile(
    r"""(?ix)
    ^\s*                # leading whitespace
    (?:                 # one of:
        \d+\.           #   '1.'
      | \d+\)           #   '1)'
      | [-*]            #   '-' or '*'
      | \|              #   '|' (markdown table row — sk-manual-qa uses tables)
    )
    \s+\S               # then whitespace then non-whitespace
    """
)

# Section title heuristic — lines that are short, end with no period, and the
# next line is blank or a dash. Used purely for diagnostics.
SECTION_TITLE_RE = re.compile(
    r"""(?ix)
    ^\#{0,4}\s*         # optional markdown heading marker
    ([A-Z][A-Za-z0-9 \-/]{2,60})  # the title text
    \s*\#*\s*$
    """
)


def count_priorities(text: str) -> dict[str, int]:
    counts = {t: 0 for t in PRIORITY_TAGS}
    for m in TAG_RE.finditer(text):
        tag = m.group(1).upper()
        counts[tag] += 1
    return counts


def count_untagged_steps(lines: list[str]) -> int:
    """Count step-shaped lines that carry no priority tag."""
    n = 0
    for line in lines:
        if not STEP_LINE_RE.match(line):
            continue
        if TAG_RE.search(line):
            continue
        # Skip section dividers like '---' and '| ---'
        if set(line.strip()) <= set("-| "):
            continue
        n += 1
    return n


def extract_sections(lines: list[str]) -> list[str]:
    """Pull out short title-like lines for diagnostics. Heuristic only."""
    titles: list[str] = []
    for i, line in enumerate(lines):
        m = SECTION_TITLE_RE.match(line)
        if not m:
            continue
        # Has to look like a heading — surrounding context check:
        prev_blank = i == 0 or not lines[i - 1].strip()
        next_blank = i + 1 >= len(lines) or not lines[i + 1].strip() or lines[i + 1].startswith("-")
        if prev_blank or next_blank:
            t = m.group(1).strip()
            if t and t not in titles and len(t) < 60:
                titles.append(t)
    return titles[:20]  # cap


def parse(text: str) -> dict:
    lines = text.splitlines()
    counts = count_priorities(text)
    untagged = count_untagged_steps(lines)
    sections = extract_sections(lines)
    total = counts["P0"] + counts["P1"] + counts["P2"] + untagged

    return {
        "total": total,
        "p0": counts["P0"],
        "p1": counts["P1"],
        "p2": counts["P2"],
        "untagged": untagged,
        "sections": sections,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path, help="Path to a QA checklist text file (extracted by extract_checklist_block.py, or any compatible markdown/.txt).")
    p.add_argument("--json", action="store_true", help="Emit JSON (default).")
    args = p.parse_args()

    if not args.path.exists():
        print(json.dumps({"error": "checklist_not_found", "path": str(args.path)}), file=sys.stderr)
        return 2

    text = args.path.read_text(encoding="utf-8", errors="replace")
    result = parse(text)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
