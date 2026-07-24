#!/usr/bin/env python3
"""
Locate (and optionally replace) the qa-automation pointer block inside an
Optimus task description.

The block is delimited by two stable HTML-comment markers:
  <!-- qa-automation:pointer:start -->
  <!-- qa-automation:pointer:end -->

Modes:
  --find    Print JSON: {"present": bool, "start": int|null, "end": int|null}
  --strip   Print the description with the block (and one trailing blank line) removed.
  --upsert  Read a replacement block from --block-file and print the updated description.
            If no block exists yet, the replacement is appended to the description with
            a leading blank line.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

START_MARK = "<!-- qa-automation:pointer:start -->"
END_MARK = "<!-- qa-automation:pointer:end -->"


def locate(description: str) -> tuple[int | None, int | None]:
    start = description.find(START_MARK)
    if start < 0:
        return (None, None)
    end_start = description.find(END_MARK, start)
    if end_start < 0:
        return (start, None)
    return (start, end_start + len(END_MARK))


def strip(description: str) -> str:
    s, e = locate(description)
    if s is None or e is None:
        return description
    # Strip leading blank line(s) before the block too, so we don't leave a
    # dangling separator behind.
    head = description[:s].rstrip(" \t\n") + "\n"
    tail = description[e:].lstrip("\n")
    return (head + tail).strip() + "\n"


def upsert(description: str, replacement: str) -> str:
    s, _ = locate(description)
    if s is None:
        sep = "\n\n" if description.strip() else ""
        return description.rstrip() + sep + replacement.strip() + "\n"
    return strip(description).rstrip() + "\n\n" + replacement.strip() + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--find", action="store_true")
    g.add_argument("--strip", action="store_true")
    g.add_argument("--upsert", action="store_true")
    p.add_argument("--description-file", type=Path, required=True)
    p.add_argument("--block-file", type=Path, help="Required with --upsert: path to the replacement block.")
    p.add_argument("--json", action="store_true", help="Emit JSON (only meaningful with --find).")
    args = p.parse_args()

    description = args.description_file.read_text(encoding="utf-8")

    if args.find:
        s, e = locate(description)
        print(json.dumps({"present": s is not None and e is not None, "start": s, "end": e}, indent=2))
        return 0

    if args.strip:
        sys.stdout.write(strip(description))
        return 0

    if args.upsert:
        if not args.block_file:
            print("--upsert requires --block-file", file=sys.stderr)
            return 2
        replacement = args.block_file.read_text(encoding="utf-8")
        sys.stdout.write(upsert(description, replacement))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
