#!/usr/bin/env python3
"""
derive_filename.py

Derive the deterministic download filename for one step's screenshot. Keeps
the naming convention in one place so the poller, mover, and uploader all
agree.

The filename pattern is:

    qa-{ticket}-{run_id_short}-step-{step_n}.gif

`run_id_short` is the last 12 alphanumeric characters of the run_id, lowercased,
so that any prefix the run_id may have (e.g. "2026-06-17T03:15:50.123Z") still
produces a short, filename-safe suffix.

Pure-Python. No I/O. Importable as a module or runnable as a CLI.
"""

from __future__ import annotations

import argparse
import re
import sys


_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def short_run_id(run_id: str, n: int = 12) -> str:
    """Compress an arbitrary run_id into a short filename-safe suffix.

    Strips non-alphanumeric characters, lowercases, and returns the last `n`
    characters. Returns the full stripped string if it is shorter than `n`.
    """
    if not run_id:
        return "run"
    stripped = _ALNUM.sub("", run_id).lower()
    if not stripped:
        return "run"
    return stripped[-n:] if len(stripped) > n else stripped


def derive_screenshot_filename(ticket: str, run_id: str, step_n: int,
                                *, ext: str = "gif") -> str:
    """Return the filename for one step's screenshot/recording."""
    if not ticket:
        ticket = "unknown"
    if not isinstance(step_n, int):
        try:
            step_n = int(step_n)
        except (TypeError, ValueError):
            step_n = 0
    rid = short_run_id(run_id)
    safe_ticket = _ALNUM.sub("-", ticket).strip("-") or "unknown"
    return f"qa-{safe_ticket}-{rid}-step-{step_n}.{ext}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticket", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--step", type=int, required=True)
    p.add_argument("--ext", default="gif")
    args = p.parse_args()
    sys.stdout.write(derive_screenshot_filename(args.ticket, args.run_id, args.step, ext=args.ext))
    return 0


if __name__ == "__main__":
    sys.exit(main())
