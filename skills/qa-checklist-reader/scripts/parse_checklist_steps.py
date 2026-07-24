#!/usr/bin/env python3
"""
parse_checklist_steps.py

Turn a `## QA Checklist` section authored on an Optimus ticket into the
structured `test_plan_steps[]` records the agentic UI executor
(qa-ui-executor) consumes.

v0.4 contract: the checklist is human-authored inside the Optimus ticket
description, under a stable `## QA Checklist` heading. `extract_checklist_block.py`
isolates that section; this parser lifts each numbered step into:

    {
      "n": 2,
      "step_id": "step-2",
      "priority": "P0",
      "action": "Click Download CSV template on the Imports page.",
      "expected": "A CSV file downloads; opening it shows clean UTF-8 punctuation."
    }

plus the tester persona ("Tester role: coordinator" -> "coordinator") and the
branch under test, so the executor knows who to log in as.

Design notes
------------
* We reuse the same step/priority regexes as parse_checklist_counts.py so the
  two stay in lockstep. (Counts and steps must never disagree.)
* A step's priority is the explicit [P0]/[P1]/[P2] tag if present; otherwise it
  inherits the priority of the most recent tagged step, else defaults to "P1"
  (treated as verdict-affecting — we do not silently demote untagged work).
* "Expected:" / "Expect:" continuation lines (and any indented follow-on prose
  before the next step) are folded into the step's `expected` field.
* The parser is intentionally forgiving about formatting drift. When in doubt
  it keeps the raw line text rather than dropping a step.
* History: in v0.3 the input came from an external sk-manual-qa generator's
  .txt output. v0.4 retargets the parser to read the human-authored checklist
  block out of the Optimus description directly. The shape of a step line is
  identical — only the source changed.

This module is pure-Python with no side effects beyond reading the input,
so it is fully unit-testable with no network and no browser. Accepts either
a file path (positional arg) or text on stdin (`--stdin`).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PRIORITY_TAGS = ("P0", "P1", "P2")
TAG_RE = re.compile(r"\[\s*(P[012])\s*\]", re.IGNORECASE)

# A numbered step line: '1.' or '1)' at the start of the line.
NUMBERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)\s*$")

# Bulleted step line (used in some checklist sections): '-' or '*'.
BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")

# Persona / role line. sk-manual-qa writes "Tester role: coordinator" or
# similar; we also accept "Login as", "Persona", "Role".
PERSONA_RE = re.compile(
    r"(?i)^\s*(?:tester\s+role|login\s+as|persona|role)\s*[:\-]\s*([A-Za-z_][A-Za-z0-9_ \-]*)\s*$"
)

# Branch line: "Branch under test: feat/..." or "Branch: feat/...".
BRANCH_RE = re.compile(r"(?i)^\s*branch(?:\s+under\s+test)?\s*[:\-]\s*(\S+)\s*$")

# Expected-result continuation line.
EXPECTED_RE = re.compile(r"(?i)^\s*(?:expected|expect|result)\s*[:\-]\s*(.*\S)\s*$")

# Lines that are section dividers / table rules, never steps.
DIVIDER_RE = re.compile(r"^\s*[-=|+\s]+\s*$")


def _known_persona(value: str) -> str:
    """Normalize a free-text role into a persona key. Conservative — we only
    map obvious synonyms; anything else is lowercased + underscored and passed
    through for the executor's persona file to resolve (or fail loudly)."""
    v = value.strip().lower()
    synonyms = {
        "program director": "pd",
        "program_director": "pd",
        "resident": "trainee",
        "student": "trainee",
        "attending physician": "attending",
        "administrator": "admin",
        "tenant admin": "admin",
        "external": "external_evaluator",
        "external evaluator": "external_evaluator",
    }
    if v in synonyms:
        return synonyms[v]
    return re.sub(r"\s+", "_", v)


def _strip_tag(text: str) -> tuple[str | None, str]:
    """Pull a leading/embedded [P0] tag out of a step's text. Returns
    (priority_or_None, text_without_tag)."""
    m = TAG_RE.search(text)
    if not m:
        return None, text.strip()
    pr = m.group(1).upper()
    cleaned = (text[: m.start()] + text[m.end():]).strip()
    return pr, cleaned


def parse(text: str) -> dict:
    lines = text.splitlines()

    persona: str | None = None
    branch: str | None = None
    steps: list[dict] = []
    last_priority = "P1"   # inheritance anchor for untagged steps

    i = 0
    n_steps = 0
    while i < len(lines):
        line = lines[i]

        if persona is None:
            pm = PERSONA_RE.match(line)
            if pm:
                persona = _known_persona(pm.group(1))
                i += 1
                continue

        if branch is None:
            bm = BRANCH_RE.match(line)
            if bm:
                branch = bm.group(1).strip()
                i += 1
                continue

        # Identify a step line (numbered preferred; bulleted accepted only when
        # it carries a priority tag, to avoid swallowing prose bullet lists).
        nm = NUMBERED_RE.match(line)
        step_text: str | None = None
        if nm:
            step_text = nm.group(2)
        else:
            bm2 = BULLET_RE.match(line)
            if bm2 and TAG_RE.search(bm2.group(1)):
                step_text = bm2.group(1)

        if step_text is None or DIVIDER_RE.match(line):
            i += 1
            continue

        priority, action = _strip_tag(step_text)
        if priority is None:
            priority = last_priority
        else:
            last_priority = priority

        # Gather expected / continuation lines beneath this step.
        expected_parts: list[str] = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if NUMBERED_RE.match(nxt):
                break
            if not nxt.strip():
                # one blank line tolerated inside a step block; stop on it to be
                # safe (sk-manual-qa separates steps with blanks).
                break
            em = EXPECTED_RE.match(nxt)
            if em:
                expected_parts.append(em.group(1).strip())
            elif nxt.startswith((" ", "\t")):
                # indented continuation prose
                expected_parts.append(nxt.strip())
            else:
                break
            j += 1

        n_steps += 1
        steps.append({
            "n": n_steps,
            "step_id": f"step-{n_steps}",
            "priority": priority,
            "action": action,
            "expected": " ".join(expected_parts).strip(),
        })
        i = j

    return {
        "branch": branch,
        "persona": persona,
        "step_count": len(steps),
        "priority_counts": {
            p: sum(1 for s in steps if s["priority"] == p) for p in PRIORITY_TAGS
        },
        "steps": steps,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path, nargs="?",
                   help="Path to a checklist text file. Omit when using --stdin.")
    p.add_argument("--stdin", action="store_true",
                   help="Read the checklist text from stdin instead of a file.")
    args = p.parse_args()

    if args.stdin:
        text = sys.stdin.read()
    else:
        if args.path is None or not args.path.exists():
            print(json.dumps({"error": "checklist_not_found",
                              "path": str(args.path) if args.path else None}),
                  file=sys.stderr)
            return 2
        text = args.path.read_text(encoding="utf-8", errors="replace")

    print(json.dumps(parse(text), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
