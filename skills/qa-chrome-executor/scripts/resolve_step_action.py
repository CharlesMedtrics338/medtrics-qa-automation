#!/usr/bin/env python3
"""
Resolve a checklist step into a structured Chrome MCP action using the hybrid
selector-first / LLM-fallback strategy.

Decision order:
  1. selector_file — if the step ID has an entry in checklist.selectors.json, use it.
  2. cache         — if a prior LLM resolution for the same step is in the on-disk
                     cache (`~/.medtrics-qa-automation/action-cache.json`), use it.
  3. llm           — propose a structured action by interpreting the natural-language
                     step. (In dry-run mode this returns a placeholder so the loop
                     can be tested without an LLM call.)
  4. unresolvable  — no selector, no cache, LLM declined or timed out.

The script is pure — no MCP calls, no LLM calls when invoked in --offline mode.
Real LLM resolution is handled by the orchestrating SKILL.md procedure; this
helper only encodes the decision tree.

Action schema (canonical):
  {
    "kind": "navigate" | "click" | "fill" | "wait_for_text" | "assert_present"
          | "assert_absent" | "submit_form" | "screenshot" | "noop",
    "selector": "<CSS or [data-testid=...]>" | null,
    "url": "<for navigate only>" | null,
    "value": "<for fill only>" | null,
    "text": "<for wait_for_text / assert_present / assert_absent>" | null,
    "timeout_ms": <int, default 30000>,
    "confidence": <float 0..1>,
    "source": "selector_file" | "cache" | "llm" | "heuristic" | "unresolvable",
    "rationale": "<short why-this-action string>"
  }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


VALID_ACTION_KINDS = {
    "navigate", "click", "fill", "wait_for_text",
    "assert_present", "assert_absent", "submit_form",
    "screenshot", "noop",
}


def load_selectors(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("steps") or {}
    except json.JSONDecodeError:
        return {}


def load_cache(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def normalize_action(action: dict, source: str, rationale: str = "") -> dict:
    """Coerce a partial action into the canonical schema with safe defaults."""
    kind = action.get("kind") or action.get("action_kind") or "noop"
    if kind not in VALID_ACTION_KINDS:
        kind = "noop"
    return {
        "kind": kind,
        "selector": action.get("selector"),
        "url": action.get("url"),
        "value": action.get("value"),
        "text": action.get("text") or action.get("expected"),
        "timeout_ms": int(action.get("timeout_ms") or 30000),
        "confidence": float(action.get("confidence") or (0.95 if source == "selector_file" else 0.75)),
        "source": source,
        "rationale": rationale or action.get("rationale", ""),
    }


def heuristic_action(step_text: str) -> dict | None:
    """
    Last-ditch heuristic for very common step shapes when no selector and no
    LLM is available. Used only in --offline mode. Recognizes:
      - "Navigate to /path" → navigate
      - "Click <Button Label>" → click by text
      - "Verify <text>" / "Expect <text>" → assert_present
    Returns None when nothing reasonable matches.
    """
    s = step_text.strip()

    m = re.match(r"(?i)(?:navigate to|go to|open)\s+([/A-Za-z0-9_\-?=&.]+)", s)
    if m:
        return {"kind": "navigate", "url": m.group(1), "rationale": "heuristic: navigate verb"}

    m = re.match(r"(?i)click(?: the)?\s+[\"`]?([^\"`]+?)[\"`]?(?:\s+button)?\.?$", s)
    if m:
        return {
            "kind": "click",
            "selector": f"text=\"{m.group(1).strip()}\"",
            "rationale": "heuristic: click verb",
        }

    m = re.match(r"(?i)(?:verify|expect|confirm|ensure|assert)\s+(.+)", s)
    if m:
        return {
            "kind": "assert_present",
            "text": m.group(1).strip().rstrip("."),
            "rationale": "heuristic: assertion verb",
        }

    return None


def resolve(
    step_id: str,
    step_text: str,
    *,
    selectors: dict,
    cache: dict,
    allow_llm: bool,
    allow_heuristics: bool = True,
) -> dict:
    # 1. selector_file
    sel = selectors.get(step_id)
    if sel:
        return normalize_action(sel, "selector_file",
                                rationale=f"step {step_id} in checklist.selectors.json")

    # 2. cache
    cached = cache.get(step_id)
    if cached:
        return normalize_action(cached, "cache",
                                rationale=f"cached resolution for {step_id}")

    # 3. llm (real implementation lives in the SKILL.md orchestrator; this
    #    helper only signals that an LLM call is needed when allow_llm=true).
    if allow_llm:
        return normalize_action(
            {"kind": "noop"},
            "llm",
            rationale="LLM resolution required — orchestrator handles this",
        )

    # 4. offline mode heuristics
    if allow_heuristics:
        guess = heuristic_action(step_text)
        if guess:
            return normalize_action(guess, "heuristic", rationale=guess.get("rationale", "heuristic"))

    return normalize_action(
        {"kind": "noop"},
        "unresolvable",
        rationale="no selector, no cache, no heuristic match, llm disabled",
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--step-id", required=True)
    p.add_argument("--step-text", required=True)
    p.add_argument("--selectors-file", type=Path)
    p.add_argument("--cache-file", type=Path)
    p.add_argument("--allow-llm", action="store_true", help="Signal that the orchestrator may invoke an LLM. Otherwise heuristics only.")
    args = p.parse_args()

    selectors = load_selectors(args.selectors_file)
    cache = load_cache(args.cache_file)

    action = resolve(
        args.step_id, args.step_text,
        selectors=selectors, cache=cache,
        allow_llm=args.allow_llm,
    )
    print(json.dumps(action, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
