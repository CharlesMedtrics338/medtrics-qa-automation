#!/usr/bin/env python3
"""
qa_action_with_marker.py

The v0.12.2 auto-wrap contract for qa-ui-executor.

Problem this fixes
------------------

v0.12.1 shipped ``force_frame_step.py`` — a helper the executor *could* call to
guarantee a frame after every non-visual action. In practice the executor
sometimes forgot to invoke it during source-verification sequences (fetching
JS from the deploy, reading the DOM, checking console messages), which meant
those actions never landed in the GIF. Under-recorded runs (7 frames when 15
actions were taken) came back.

v0.12.2 removes the "sometimes forgets" gap by moving the contract from
"remember to call force_frame_step" to "there is only ONE way to invoke a
non-visual action during a run, and it always emits a marker".

Contract
--------

During an active qa-ui-executor run the following Chrome MCP tools are BANNED
from direct invocation by the executor:

    - ``javascript_tool``
    - ``read_page``
    - ``read_console_messages``
    - ``read_network_requests``
    - ``get_page_text``
    - ``find``

Instead, the executor MUST call ``qa_action_with_marker`` — this script — to
build a fused action plan that:

    1. Emits the underlying MCP action.
    2. IMMEDIATELY emits the v0.12.1 force-frame ``marker`` plan (a 4×4 px
       HSL-rotating visible div + a screenshot).

The result is a single ordered plan the executor executes end-to-end. No
frame can be lost.

Real mouse actions (``computer.left_click`` / ``computer.scroll`` /
``computer.mouse_move`` / ``navigate``) do not need this wrapper — they
already paint distinct pixels the recorder captures. Prefer them where the
action is genuinely a UI interaction.

CLI
---

.. code-block:: sh

    # Wrap a JS state-inspection call
    qa_action_with_marker.py --kind javascript --step-n 3 --tab-id 648662081 \\
      --step-label "Read replaceUploadedDocument body" \\
      --script "return window.document.title"

    # Wrap a read_page call
    qa_action_with_marker.py --kind read_page --step-n 4 --tab-id 648662081 \\
      --step-label "Snapshot form 36956"

    # Wrap a read_console_messages call
    qa_action_with_marker.py --kind read_console --step-n 5 --tab-id 648662081 \\
      --step-label "Check upload console errors"

Every mode emits a JSON action plan on stdout the executor consumes.

Importable as a module:
    ``build_wrapped_plan(kind=..., step_n=..., tab_id=..., step_label=...,
                         script=..., since_last_seen=None)`` returns the same
    dict.

Pure-Python. Zero dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

from force_frame_step import build_action_plan as _build_force_frame_plan


VALID_WRAPPED_KINDS = (
    "javascript",
    "read_page",
    "read_console",
    "read_network",
    "get_page_text",
    "find",
)


def _underlying_action(
    *, kind: str, tab_id: int, script: Optional[str], since_last_seen: Optional[bool]
) -> Dict[str, Any]:
    """Return the MCP action dict for the requested non-visual kind."""
    if kind == "javascript":
        if not script:
            raise ValueError("kind=javascript requires --script")
        return {
            "name": "javascript_tool",
            "purpose": "wrapped_state_inspection",
            "input": {
                "action": "javascript_exec",
                "tabId": tab_id,
                "text": script,
            },
        }
    if kind == "read_page":
        return {
            "name": "read_page",
            "purpose": "wrapped_page_snapshot",
            "input": {"tabId": tab_id},
        }
    if kind == "read_console":
        return {
            "name": "read_console_messages",
            "purpose": "wrapped_console_snapshot",
            "input": {"tabId": tab_id, "sinceLastSeen": bool(since_last_seen)},
        }
    if kind == "read_network":
        return {
            "name": "read_network_requests",
            "purpose": "wrapped_network_snapshot",
            "input": {"tabId": tab_id, "sinceLastSeen": bool(since_last_seen)},
        }
    if kind == "get_page_text":
        return {
            "name": "get_page_text",
            "purpose": "wrapped_get_page_text",
            "input": {"tabId": tab_id},
        }
    if kind == "find":
        return {
            "name": "find",
            "purpose": "wrapped_find",
            "input": {"tabId": tab_id},
        }
    raise ValueError(f"kind must be one of {VALID_WRAPPED_KINDS!r}, got {kind!r}")


def build_wrapped_plan(
    *,
    kind: str,
    step_n: int,
    tab_id: int,
    step_label: str = "",
    script: Optional[str] = None,
    since_last_seen: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fuse a non-visual MCP action with a v0.12.1 force-frame marker frame.

    Returned plan:

        {
          "step_n": int,
          "step_label": str,
          "kind": "wrapped_<kind>",
          "actions": [
             <underlying MCP action>,
             <force_frame marker javascript_tool call>,
             <force_frame screenshot>,
          ],
          "wrapped_kind": kind,
          "policy_version": 3,   # v0.12.2 auto-wrap contract
        }

    The executor MUST run the actions in order. Failure to run any of the
    three renders the whole plan invalid and MUST log a
    ``qa_action_with_marker.violation`` audit entry.
    """
    if kind not in VALID_WRAPPED_KINDS:
        raise ValueError(f"kind must be one of {VALID_WRAPPED_KINDS!r}, got {kind!r}")
    if step_n < 0:
        raise ValueError("step_n must be >= 0")
    if tab_id <= 0:
        raise ValueError("tab_id must be a positive integer")

    underlying = _underlying_action(
        kind=kind, tab_id=tab_id, script=script, since_last_seen=since_last_seen
    )
    marker_plan = _build_force_frame_plan(
        kind="marker",
        step_n=step_n,
        tab_id=tab_id,
        step_label=step_label,
    )
    return {
        "step_n": step_n,
        "step_label": step_label,
        "kind": f"wrapped_{kind}",
        "wrapped_kind": kind,
        "actions": [underlying] + marker_plan["actions"],
        "policy_version": 3,
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=VALID_WRAPPED_KINDS)
    parser.add_argument("--step-n", type=int, required=True)
    parser.add_argument("--tab-id", type=int, required=True)
    parser.add_argument("--step-label", default="")
    parser.add_argument("--script", help="JS body for --kind javascript")
    parser.add_argument(
        "--since-last-seen",
        action="store_true",
        help="Passed through to read_console / read_network",
    )
    args = parser.parse_args()

    try:
        plan = build_wrapped_plan(
            kind=args.kind,
            step_n=args.step_n,
            tab_id=args.tab_id,
            step_label=args.step_label,
            script=args.script,
            since_last_seen=args.since_last_seen if args.since_last_seen else None,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    json.dump(plan, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
