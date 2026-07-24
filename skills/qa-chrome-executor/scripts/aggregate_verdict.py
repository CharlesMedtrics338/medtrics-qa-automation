#!/usr/bin/env python3
"""
Aggregate per-step verdict records into a run-level verdict.

Reads either a directory of step JSON files (one per step) or a single JSON
file containing a list of step records, and computes:

  - p0_pass_rate, p1_pass_rate, p2_pass_rate
  - overall verdict: 'pass' iff 100% P0 and ≥90% P1; else 'fail'
  - verdict_confidence: mean of per-step confidence on the path that decided
    the verdict (P0 path if a P0 failed; else P1 path)
  - failed_items: list of failing P0 and P1 step IDs (in priority order)
  - unresolvable_p0_count: counts unresolvable P0 steps as failures
  - duration_ms: sum of per-step duration_ms when present

Per-step record schema:
  {
    "step_id": "p0-1-step-3",
    "priority": "P0" | "P1" | "P2",
    "result": "pass" | "fail" | "skip" | "flake" | "error" | "unresolvable",
    "confidence": 0.0..1.0,
    "duration_ms": <int>,
    "title": "<short>"
  }

Pass criteria (configurable via flags but defaults match the QA Process v2.2 doc):
  - Every P0 item must `pass`. Any `fail` / `error` / `unresolvable` P0 → fail.
  - ≥90% of P1 items must `pass`.
  - P2 items do not affect the verdict.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def load_steps(input_path: Path) -> list[dict]:
    if input_path.is_dir():
        steps: list[dict] = []
        for f in sorted(input_path.glob("step-*.json")):
            try:
                steps.append(json.loads(f.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return steps
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    return raw.get("steps", []) or []


def _is_failure(result: str) -> bool:
    return result in {"fail", "error", "unresolvable"}


def aggregate(
    steps: list[dict],
    *,
    p0_required: float = 1.0,
    p1_required: float = 0.9,
) -> dict:
    by_prio: dict[str, list[dict]] = {"P0": [], "P1": [], "P2": []}
    for s in steps:
        prio = (s.get("priority") or "").upper()
        if prio in by_prio:
            by_prio[prio].append(s)

    def pass_rate(items: list[dict]) -> float | None:
        if not items:
            return None
        passes = sum(1 for s in items if s.get("result") == "pass")
        return passes / len(items)

    p0_pass = pass_rate(by_prio["P0"])
    p1_pass = pass_rate(by_prio["P1"])
    p2_pass = pass_rate(by_prio["P2"])

    p0_fail_items = [s for s in by_prio["P0"] if _is_failure(s.get("result", ""))]
    p1_fail_items = [s for s in by_prio["P1"] if _is_failure(s.get("result", ""))]

    # Verdict:
    # - Any P0 failure → fail.
    # - Otherwise, P1 pass rate must clear the threshold (or P1 has no items).
    p0_meets = p0_pass is None or p0_pass >= p0_required
    p1_meets = p1_pass is None or p1_pass >= p1_required
    verdict = "pass" if (p0_meets and p1_meets) else "fail"

    # Confidence: mean over the priority path that decided things.
    decisive = by_prio["P0"] if not p0_meets else by_prio["P1"] if not p1_meets else (by_prio["P0"] + by_prio["P1"])
    confidences = [float(s.get("confidence", 0.0)) for s in decisive if s.get("confidence") is not None]
    verdict_confidence = round(statistics.mean(confidences), 3) if confidences else None

    failed_items = [
        f"{s.get('step_id')}: {s.get('title') or '(no title)'}"
        for s in (p0_fail_items + p1_fail_items)
    ]

    durations = [int(s.get("duration_ms") or 0) for s in steps]
    total_duration = sum(durations)

    unresolvable_p0 = sum(1 for s in by_prio["P0"] if s.get("result") == "unresolvable")

    return {
        "verdict": verdict,
        "verdict_confidence": verdict_confidence,
        "p0_pass_rate": round(p0_pass, 3) if p0_pass is not None else None,
        "p1_pass_rate": round(p1_pass, 3) if p1_pass is not None else None,
        "p2_pass_rate": round(p2_pass, 3) if p2_pass is not None else None,
        "p0_count": len(by_prio["P0"]),
        "p1_count": len(by_prio["P1"]),
        "p2_count": len(by_prio["P2"]),
        "failed_items": failed_items,
        "unresolvable_p0_count": unresolvable_p0,
        "duration_ms": total_duration,
        "thresholds": {"p0_required": p0_required, "p1_required": p1_required},
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path, help="Path to a step file, a directory of step-*.json files, or a single JSON list.")
    p.add_argument("--p0-required", type=float, default=1.0)
    p.add_argument("--p1-required", type=float, default=0.9)
    args = p.parse_args()

    steps = load_steps(args.input)
    if not steps:
        print(json.dumps({"error": "no_steps_found", "input": str(args.input)}), file=sys.stderr)
        return 2

    result = aggregate(steps, p0_required=args.p0_required, p1_required=args.p1_required)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
