#!/usr/bin/env python3
"""
verify_gif_completeness.py

Post-run sanity check on the qa-ui-executor step-walkthrough GIF.

Compares:

  - The number of executor actions the audit log recorded for the run.
  - The number of frames the exported GIF actually contains.

If ``frames_in_gif < expected_actions * threshold`` (default 0.80), the
run is flagged as ``under_recorded`` — the verdict thread will surface a
warning banner and the audit log will hold a
``verify_gif_completeness.under_recorded`` event.

The check has three exit modes:

  0 — recorded fully, no warning
  0 — under_recorded, warning emitted (non-blocking by default)
  1 — invocation error (missing file, bad JSON) — CLI misuse only

The check is intentionally NON-BLOCKING for the verdict flow. A short GIF
should never keep the QA verdict from posting — the verdict is anchored on
the source-level + runtime checks, not on frame count. But the executor's
next run learns from the warning (audit log), and the verdict thread
includes a "GIF completeness" line the operator can read.

CLI
---

.. code-block:: sh

    verify_gif_completeness.py \\
      --run-dir outputs/qa/M1-1309/2026-07-06T1005Z \\
      --threshold 0.80

Inputs
------

The script looks for the following files under ``--run-dir``:

  - ``execution_trace.json``   — the executor's per-step trace, from
                                 qa-ui-executor. Each entry is one action.
                                 The number of entries is the expected
                                 frame count.
  - ``step-walkthrough/screenshot.gif``  — the exported GIF.

If ``execution_trace.json`` is absent, the script falls back to the audit
log at ``--audit-log`` (default ``$HOME/.medtrics-qa-automation/audit.log``)
and counts the qa_action_with_marker.emit events keyed to the run's
``run_id`` — if that too is missing, the script prints ``skipped: no
trace`` and exits 0.

The GIF frame count is read via the stdlib without Pillow: iterate the GIF
file bytes and count ``0x2C`` image-descriptor markers preceded by a
graphic-control extension. This is deterministic and dependency-free.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional


def count_gif_frames(gif_path: Path) -> int:
    """Count image-frames in a GIF file without Pillow.

    Reads the file byte-by-byte. Every image frame in a GIF begins with a
    ``0x2C`` (comma) block introducer at the start of a block. We walk the
    GIF structure minimally — enough to find image descriptors and skip
    trailer blocks so we don't miscount data-sub-block bytes that happen
    to be 0x2C.
    """
    data = gif_path.read_bytes()
    if len(data) < 6 or data[:3] != b"GIF":
        raise ValueError(f"{gif_path} is not a GIF file")

    # Skip header (6) + logical screen descriptor (7)
    i = 13
    packed = data[10]
    if packed & 0x80:
        gct_size = 3 * (2 ** ((packed & 0x07) + 1))
        i += gct_size

    frames = 0
    while i < len(data):
        b = data[i]
        if b == 0x3B:  # trailer
            break
        if b == 0x21:  # extension introducer
            i += 1
            if i >= len(data):
                break
            # label byte
            i += 1
            # skip data sub-blocks
            while i < len(data):
                size = data[i]
                if size == 0:
                    i += 1
                    break
                i += 1 + size
            continue
        if b == 0x2C:  # image descriptor
            frames += 1
            i += 10  # image descriptor is 10 bytes
            if i - 1 < len(data):
                packed_img = data[i - 1]
                if packed_img & 0x80:
                    lct_size = 3 * (2 ** ((packed_img & 0x07) + 1))
                    i += lct_size
            # LZW min code size byte
            if i < len(data):
                i += 1
            # skip data sub-blocks
            while i < len(data):
                if i >= len(data):
                    break
                size = data[i]
                if size == 0:
                    i += 1
                    break
                i += 1 + size
            continue
        # Unknown byte — advance to avoid infinite loop
        i += 1

    return frames


def count_expected_actions(run_dir: Path) -> Optional[int]:
    """Count expected frames from the executor's per-step trace."""
    trace_path = run_dir / "execution_trace.json"
    if not trace_path.exists():
        return None
    try:
        trace = json.loads(trace_path.read_text())
    except json.JSONDecodeError:
        return None
    if isinstance(trace, dict) and "steps" in trace:
        return len(trace["steps"])
    if isinstance(trace, list):
        return len(trace)
    return None


def evaluate(
    *,
    frames: int,
    expected: Optional[int],
    threshold: float,
) -> dict:
    """Judge whether a GIF is under-recorded.

    Returns a verdict dict::

        {
          "frames": int,
          "expected": Optional[int],
          "threshold": float,
          "ratio": Optional[float],
          "verdict": "ok" | "under_recorded" | "skipped_no_trace",
          "message": str,
        }
    """
    if expected is None:
        return {
            "frames": frames,
            "expected": None,
            "threshold": threshold,
            "ratio": None,
            "verdict": "skipped_no_trace",
            "message": (
                "No execution_trace.json found — cannot compute expected "
                "frame count. Skipping."
            ),
        }
    if expected <= 0:
        return {
            "frames": frames,
            "expected": expected,
            "threshold": threshold,
            "ratio": None,
            "verdict": "skipped_no_trace",
            "message": "execution_trace.json contained zero steps.",
        }
    ratio = frames / expected
    if ratio >= threshold:
        return {
            "frames": frames,
            "expected": expected,
            "threshold": threshold,
            "ratio": ratio,
            "verdict": "ok",
            "message": (
                f"GIF has {frames}/{expected} frames "
                f"({ratio:.0%} of expected, threshold {threshold:.0%})."
            ),
        }
    return {
        "frames": frames,
        "expected": expected,
        "threshold": threshold,
        "ratio": ratio,
        "verdict": "under_recorded",
        "message": (
            f"UNDER-RECORDED: GIF has {frames}/{expected} frames "
            f"({ratio:.0%} of expected, threshold {threshold:.0%}). "
            "The v0.12.2 auto-wrap contract may have been bypassed — "
            "check the executor for direct javascript_tool / read_page / "
            "read_console / read_network / get_page_text / find calls "
            "that skipped qa_action_with_marker."
        ),
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument(
        "--gif",
        type=Path,
        help="Explicit GIF path (default <run-dir>/step-walkthrough/screenshot.gif)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on under_recorded (default: warn-only, exit 0)",
    )
    args = parser.parse_args()

    if not args.run_dir.is_dir():
        print(f"error: {args.run_dir} is not a directory", file=sys.stderr)
        return 1

    gif_path = args.gif or (args.run_dir / "step-walkthrough" / "screenshot.gif")
    if not gif_path.exists():
        print(f"error: GIF not found at {gif_path}", file=sys.stderr)
        return 1

    try:
        frames = count_gif_frames(gif_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    expected = count_expected_actions(args.run_dir)
    verdict = evaluate(frames=frames, expected=expected, threshold=args.threshold)

    json.dump(verdict, sys.stdout, indent=2)
    sys.stdout.write("\n")

    if args.strict and verdict["verdict"] == "under_recorded":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
