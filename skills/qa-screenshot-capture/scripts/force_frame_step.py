#!/usr/bin/env python3
"""
force_frame_step.py

Emit the deterministic action plan the executor runs so the Chrome MCP
``gif_creator`` records a distinct keyframe for every action it drives.

Design (v0.12.1)
----------------

Chrome MCP's ``gif_creator`` ingests only ``computer`` and ``navigate`` calls
and deduplicates adjacent frames whose pixel diff is small.  v0.12.0 tried to
defeat that with an invisible ±1 px scroll nudge + a ``body.dataset`` write —
that failed because the scroll cancelled itself out before the follow-up
screenshot fired, and the dataset attribute isn't rendered.  v0.12.1 fixes it
in the only reliable way: **prefer a real mouse action, and if you must use
``javascript_tool`` for a state change, leave a lasting visible pixel diff
behind.**

Three modes, in priority order:

1. ``--kind click`` (STRONGLY preferred).  Executor already knows the target
   element's centre coordinates (from ``find`` / ``read_page``).  Emit one
   ``computer.left_click`` at those coordinates.  Chrome MCP overlays an
   orange dot at the click point that is baked into the recorder frame, so
   the frame is guaranteed distinct from its neighbours.

2. ``--kind scroll``.  A real ``computer.scroll`` action.  Recorder captures
   the intermediate scroll delta as a distinct pixel diff.

3. ``--kind marker`` (FALLBACK, only when the state change genuinely cannot
   be driven through the mouse).  Injects a 4×4 px absolute-positioned
   ``<div>`` in the top-left corner whose HSL background hue rotates 36° per
   step (step 1 red → step 2 orange → step 10 back to red).  Then emits a
   ``computer.screenshot``.  The 16 pixels of unique colour are enough that
   the recorder's dedup cannot fold the frame against the previous one, and
   the marker is small enough to be invisible to the operator.  It stays on
   the page after the screenshot so subsequent frames carry a monotonically
   changing marker.  The old v0.12.0 ±1 px scroll + dataset write is
   removed entirely — it does nothing observable.

CLI
---

.. code-block:: sh

    # Real mouse click (preferred)
    force_frame_step.py --kind click --step-n 3 --tab-id 648662081 \\
      --x 775 --y 284 --step-label "Open Sites filter"

    # Real scroll
    force_frame_step.py --kind scroll --step-n 4 --tab-id 648662081 \\
      --dx 0 --dy 400 --step-label "Scroll to Who will be evaluated"

    # JS-only fallback — visible marker + screenshot
    force_frame_step.py --kind marker --step-n 5 --tab-id 648662081 \\
      --step-label "Inject XHR interceptor"

Every mode emits a JSON action plan on stdout the executor consumes.
``--raw`` prints just the marker JavaScript for callers that build their own
action lists.

Importable as a module: ``build_action_plan(kind=..., step_n=..., tab_id=...,
step_label=..., x=..., y=..., dx=..., dy=...)`` returns the same dict.

Pure-Python. No I/O beyond stdin/stdout. Zero dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional


# 36° hue rotation per step — 10-step cycle, comes back around at step 11.
MARKER_JS_TEMPLATE = (
    "// force-frame marker (v0.12.1): a 4x4 px visible diff the recorder cannot dedup\n"
    "(function() {{\n"
    "  const id = 'qa-force-frame-marker';\n"
    "  let m = document.getElementById(id);\n"
    "  if (!m) {{\n"
    "    m = document.createElement('div');\n"
    "    m.id = id;\n"
    "    m.style.position = 'fixed';\n"
    "    m.style.top = '0';\n"
    "    m.style.left = '0';\n"
    "    m.style.width = '4px';\n"
    "    m.style.height = '4px';\n"
    "    m.style.zIndex = '2147483647';\n"
    "    m.style.pointerEvents = 'none';\n"
    "    document.documentElement.appendChild(m);\n"
    "  }}\n"
    "  const hue = ({step_n} * 36) % 360;\n"
    "  m.style.backgroundColor = 'hsl(' + hue + ', 100%, 50%)';\n"
    "  m.dataset.qaFrame = String(({step_n}));\n"
    "}})();\n"
    "await new Promise(r => setTimeout(r, 60));\n"
    "'force_frame_marker:step={step_n}'"
)

VALID_KINDS = ("click", "scroll", "marker")


def _click_plan(*, step_n: int, tab_id: int, step_label: str, x: int, y: int) -> Dict[str, Any]:
    return {
        "step_n": step_n,
        "step_label": step_label,
        "kind": "click",
        "actions": [
            {
                "name": "computer",
                "purpose": "force_frame_click",
                "input": {
                    "action": "left_click",
                    "coordinate": [x, y],
                    "tabId": tab_id,
                },
            }
        ],
        "policy_version": 2,
    }


def _scroll_plan(
    *, step_n: int, tab_id: int, step_label: str, dx: int, dy: int
) -> Dict[str, Any]:
    return {
        "step_n": step_n,
        "step_label": step_label,
        "kind": "scroll",
        "actions": [
            {
                "name": "computer",
                "purpose": "force_frame_scroll",
                "input": {
                    "action": "scroll",
                    "coordinate": [dx, dy],
                    "tabId": tab_id,
                },
            }
        ],
        "policy_version": 2,
    }


def _marker_plan(*, step_n: int, tab_id: int, step_label: str) -> Dict[str, Any]:
    marker_js = MARKER_JS_TEMPLATE.format(step_n=step_n)
    return {
        "step_n": step_n,
        "step_label": step_label,
        "kind": "marker",
        "actions": [
            {
                "name": "javascript_tool",
                "purpose": "force_frame_marker",
                "input": {
                    "action": "javascript_exec",
                    "tabId": tab_id,
                    "text": marker_js,
                },
            },
            {
                "name": "computer",
                "purpose": "force_frame_screenshot",
                "input": {"action": "screenshot", "tabId": tab_id},
            },
        ],
        "marker_js": marker_js,
        "policy_version": 2,
    }


def build_action_plan(
    *,
    kind: str,
    step_n: int,
    tab_id: int,
    step_label: str = "",
    x: Optional[int] = None,
    y: Optional[int] = None,
    dx: Optional[int] = None,
    dy: Optional[int] = None,
) -> Dict[str, Any]:
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS!r}, got {kind!r}")
    if step_n < 0:
        raise ValueError("step_n must be >= 0")
    if tab_id <= 0:
        raise ValueError("tab_id must be a positive integer")

    if kind == "click":
        if x is None or y is None:
            raise ValueError("kind=click requires --x and --y coordinates")
        return _click_plan(
            step_n=step_n, tab_id=tab_id, step_label=step_label, x=int(x), y=int(y)
        )
    if kind == "scroll":
        if dx is None or dy is None:
            raise ValueError("kind=scroll requires --dx and --dy deltas")
        return _scroll_plan(
            step_n=step_n, tab_id=tab_id, step_label=step_label, dx=int(dx), dy=int(dy)
        )
    # marker
    return _marker_plan(step_n=step_n, tab_id=tab_id, step_label=step_label)


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=VALID_KINDS)
    parser.add_argument("--step-n", type=int, required=True)
    parser.add_argument("--tab-id", type=int, required=True)
    parser.add_argument("--step-label", default="")
    parser.add_argument("--x", type=int)
    parser.add_argument("--y", type=int)
    parser.add_argument("--dx", type=int)
    parser.add_argument("--dy", type=int)
    parser.add_argument("--raw", action="store_true")
    args = parser.parse_args()

    try:
        plan = build_action_plan(
            kind=args.kind,
            step_n=args.step_n,
            tab_id=args.tab_id,
            step_label=args.step_label,
            x=args.x,
            y=args.y,
            dx=args.dx,
            dy=args.dy,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.raw:
        if plan["kind"] == "marker":
            sys.stdout.write(plan["marker_js"])
        else:
            # For click/scroll there's no JS to emit — dump the action.
            json.dump(plan["actions"][0], sys.stdout, indent=2)
            sys.stdout.write("\n")
    else:
        json.dump(plan, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
