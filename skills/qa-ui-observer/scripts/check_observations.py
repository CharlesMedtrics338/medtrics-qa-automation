#!/usr/bin/env python3
"""
check_observations.py

Deterministic UI/UX observation checks for medtrics-qa-automation. Pure
function: takes one step and one CapturedPage projection, returns a list of
observations. Never affects the run verdict.

The catalog of kinds is FIXED (see SKILL.md). New kinds require new check
functions + tests.

Catalog:
  - console_warning
  - asset_load_error
  - broken_image
  - missing_alt_text
  - layout_overflow
  - deprecated_api_warning

Observation shape:
  {
    "kind": str,
    "severity": "warn" | "info",
    "step_id": str,
    "step_n": int,
    "step_priority": "P0" | "P1" | "P2",
    "location": str,        # CSS selector, URL, or element descriptor
    "evidence": str,        # human-readable snippet
  }

CapturedPage shape (matching qa-ui-executor's projection):
  {
    "url": str,
    "title": str,
    "elements": [
      {"selector": str, "exists": bool, "visible": bool, "text": str|None,
       "value": str|None, "tag": str|None, "natural_width": int|None,
       "alt": str|None, "scroll_width": int|None, "client_width": int|None,
       "scroll_height": int|None, "client_height": int|None,
       "is_scrollable_declared": bool|None}
    ],
    "console": [{"level": "log"|"info"|"warn"|"error", "text": str}],
    "network": [{"method": str, "url": str, "status": int}]
  }
"""

from __future__ import annotations

import re

STATIC_ASSET_RE = re.compile(
    r"\.(?:js|mjs|css|svg|png|jpg|jpeg|webp|gif|ico|woff2?|ttf|otf|map)(?:\?|#|$)",
    re.IGNORECASE,
)

# Built-in deprecated-API regex bank. Overridable via config.
DEFAULT_DEPRECATED_PATTERNS = (
    re.compile(r"\bdeprecated\b", re.IGNORECASE),
    re.compile(r"\bwill be removed\b", re.IGNORECASE),
    re.compile(r"\bsince version\b", re.IGNORECASE),
    re.compile(r"\bno longer supported\b", re.IGNORECASE),
)


def _obs(kind: str, severity: str, step: dict, location: str, evidence: str) -> dict:
    return {
        "kind": kind,
        "severity": severity,
        "step_id": step.get("step_id"),
        "step_n": step.get("n"),
        "step_priority": step.get("priority"),
        "location": location,
        "evidence": evidence,
    }


def _check_console(step: dict, captured: dict,
                   deprecated_patterns=DEFAULT_DEPRECATED_PATTERNS) -> list[dict]:
    out = []
    for msg in captured.get("console") or []:
        if (msg.get("level") or "").lower() != "warn":
            continue
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        if any(p.search(text) for p in deprecated_patterns):
            out.append(_obs("deprecated_api_warning", "info", step,
                            location="(console)", evidence=text))
        else:
            out.append(_obs("console_warning", "info", step,
                            location="(console)", evidence=text))
    return out


def _check_network(step: dict, captured: dict) -> list[dict]:
    out = []
    for req in captured.get("network") or []:
        try:
            status = int(req.get("status") or 0)
        except (TypeError, ValueError):
            continue
        if status < 400:
            continue
        url = (req.get("url") or "").strip()
        if not STATIC_ASSET_RE.search(url):
            continue
        method = (req.get("method") or "GET").upper()
        out.append(_obs("asset_load_error", "warn", step,
                        location=url,
                        evidence=f"{method} {url} → {status}"))
    return out


def _check_images(step: dict, captured: dict) -> list[dict]:
    out = []
    priority = (step.get("priority") or "").upper()
    for el in captured.get("elements") or []:
        tag = (el.get("tag") or "").lower()
        if tag != "img":
            continue
        sel = el.get("selector") or "<img>"
        if not el.get("exists", True):
            continue
        nw = el.get("natural_width")
        if isinstance(nw, int) and nw == 0:
            out.append(_obs("broken_image", "warn", step,
                            location=sel,
                            evidence=f"{sel} has naturalWidth=0 (asset failed to load)"))
        if priority == "P0":
            alt = el.get("alt")
            if alt is None or (isinstance(alt, str) and not alt.strip()):
                out.append(_obs("missing_alt_text", "info", step,
                                location=sel,
                                evidence=f"{sel} has empty or missing alt attribute on a P0 page"))
    return out


def _check_overflow(step: dict, captured: dict) -> list[dict]:
    out = []
    for el in captured.get("elements") or []:
        if el.get("is_scrollable_declared"):
            continue
        sw = el.get("scroll_width")
        cw = el.get("client_width")
        sh = el.get("scroll_height")
        ch = el.get("client_height")
        sel = el.get("selector") or "(element)"
        if isinstance(sw, int) and isinstance(cw, int) and sw > cw + 1:
            out.append(_obs("layout_overflow", "warn", step,
                            location=sel,
                            evidence=f"{sel}: scrollWidth={sw} exceeds clientWidth={cw}; content may be clipped"))
        elif isinstance(sh, int) and isinstance(ch, int) and sh > ch + 1:
            out.append(_obs("layout_overflow", "warn", step,
                            location=sel,
                            evidence=f"{sel}: scrollHeight={sh} exceeds clientHeight={ch}; content may be clipped"))
    return out


CHECKS = (
    _check_console,    # console_warning + deprecated_api_warning
    _check_network,    # asset_load_error
    _check_images,     # broken_image + missing_alt_text
    _check_overflow,   # layout_overflow
)


def observe(step: dict, captured: dict,
            deprecated_patterns: tuple = DEFAULT_DEPRECATED_PATTERNS) -> list[dict]:
    """Run every check against one step's CapturedPage. Returns observations
    in stable catalog order (console → network → images → overflow)."""
    out: list[dict] = []
    out.extend(_check_console(step, captured, deprecated_patterns))
    out.extend(_check_network(step, captured))
    out.extend(_check_images(step, captured))
    out.extend(_check_overflow(step, captured))
    return out


def main() -> int:
    """CLI for ad-hoc inspection — `python3 check_observations.py step.json captured.json`."""
    import argparse
    import json
    import sys

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("step", help="JSON file with the step record.")
    p.add_argument("captured", help="JSON file with the CapturedPage projection.")
    args = p.parse_args()

    step = json.loads(open(args.step).read())
    captured = json.loads(open(args.captured).read())
    obs = observe(step, captured)
    print(json.dumps(obs, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
