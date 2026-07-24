#!/usr/bin/env python3
"""
optimus_move_task.py — payload builder for the post-verdict lane transition.

Optimus is reached through the MCP layer (no direct HTTP), so this script is
NOT the transport. It validates the verdict → target-lane mapping, applies
the phase gate, and emits the JSON payload the calling SKILL.md procedure
passes to `mcp__904fdec1-…__move_task`.

This mirrors qa-gitlab-bridge's per-action layout — one script per write —
even though the actual MCP call still happens upstream.

## Verdict → target lane policy (v0.10.1)

| Verdict + cause | Target lane | Why |
|---|---|---|
| `pass` | `qa2` | All P0 + ≥90% P1 passed; advance. |
| `fail` | `needs_changes` | Real failure — send back to dev with the fail-thread. |
| `partial` + data-related cause | `on_hold` | Run couldn't complete because the environment lacks seed data (e.g. `blocked_by_seed_data`). Holds the ticket pending env work — no code change needed. |
| `partial` + non-data-related cause (or no cause given) | `needs_changes` | The run revealed something the dev should look at — code defect, tooling failure, missing step, etc. **v0.10.1 change:** previously `needs_review`, which didn't exist in Optimus's enum. |
| `blocked` | (no move) | Stays in `qa1`; the dashboard surfaces the blocker. |

Data-related partial causes (controlled list): `blocked_by_seed_data`,
`no_seed_data`, `missing_test_data`, `environment_not_seeded`. Any other
partial cause (or omitted cause) routes to `needs_changes`.

Lane names default to the canonical ones above but are overridable through
`qa-config` (config.optimus.{qa2,needs_changes,on_hold}_lane). All defaults
are validated against Optimus's `product_task_statuses` enum via
`get_meta` — `needs_review` was removed in v0.10.1 (not a valid Optimus
status; see the live evidence on M1-1195's run log).

## Phase gating

In `shadow` phase, ALL Optimus writes are refused. The script exits code 2
and the caller treats that as a planned no-op. Mem and Slack still record
the verdict; the human QA Lead reviews shadow output every Friday before
flipping the phase.

## Usage

    python3 optimus_move_task.py \\
        --ticket M1-1190 \\
        --verdict pass \\
        --phase writes-on \\
        --config ~/.medtrics-qa-automation/config.json

Output (stdout):
    {
      "ok": true,
      "ticket": "M1-1190",
      "from_lane": "qa1",
      "target_lane": "qa2",
      "verdict": "pass",
      "mcp_tool": "mcp__904fdec1-f755-42c5-a32e-a3a9eb8ba1da__move_task",
      "args": {"task": "M1-1190", "status": "qa2"},
      "audit_action": "optimus_moved_to_qa2"
    }

Exit codes:
    0 — payload built; the orchestrating SKILL.md should call the MCP tool with `args`
    1 — invalid input (unknown verdict, missing config, etc.)
    2 — phase blocks the write (`shadow`); caller no-ops gracefully
    3 — verdict is `blocked` — no lane move (stays in qa1)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Causes that route `partial` → `on_hold` instead of `needs_changes`.
# Anything else (code defect, plugin tooling, missing step, etc.) is
# treated as a non-data-related failure that the dev should pick up.
DATA_RELATED_PARTIAL_CAUSES = frozenset({
    "blocked_by_seed_data",
    "no_seed_data",
    "missing_test_data",
    "environment_not_seeded",
})

# Verdict + optional partial_cause → target lane key in config.optimus
def _verdict_lane_key(verdict: str, partial_cause: str | None) -> str | None:
    if verdict == "pass":
        return "qa2_lane"
    if verdict == "fail":
        return "needs_changes_lane"
    if verdict == "partial":
        # Data-related failures park in `needs_review` — no code change
        # needed, just operator/env work to seed the environment.
        # Non-data-related failures go back to dev to look at.
        if partial_cause in DATA_RELATED_PARTIAL_CAUSES:
            return "needs_review_lane"
        return "needs_changes_lane"
    return None


# Default lane names if config doesn't override.
# Most values are present in Optimus's `product_task_statuses` enum verified
# via get_meta on 2026-06-06:
#   triage · backlog · validation · ux_candidate · ux_in_progress · ux_ready ·
#   tech_spec · upcoming · dev_todo · dev_in_progress · needs_changes · qa1 ·
#   qa2 · code_review · ready · cancelled · done · on_hold · pipeline_issues
# `needs_review` is NOT in the enum yet — it's a pending-release lane.
# Until it lands, the PENDING_RELEASE_LANES map below transparently
# substitutes `on_hold` so the move actually succeeds. Once `needs_review`
# is live in Optimus, drop the substitution.
DEFAULT_LANES = {
    "qa1_lane":           "qa1",
    "qa2_lane":           "qa2",
    "needs_changes_lane": "needs_changes",
    "on_hold_lane":       "on_hold",
    "needs_review_lane":  "needs_review",  # v0.10.2 — pending Optimus release
}


# Lanes that aren't yet live in Optimus's `product_task_statuses` enum.
# The script substitutes the value (the fallback lane that IS live) for
# any resolved target_lane that hits this map. The payload's
# `pending_release` field records the intended lane so the operator
# can see where the ticket "really" should be. v0.10.2.
PENDING_RELEASE_LANES = {
    "needs_review": "on_hold",
}

OPTIMUS_MOVE_TOOL = "mcp__904fdec1-f755-42c5-a32e-a3a9eb8ba1da__move_task"


def resolve_target_lane(verdict: str, partial_cause: str | None,
                         optimus_config: dict) -> str | None:
    """Return the lane the ticket should move to, or None when no move applies."""
    key = _verdict_lane_key(verdict, partial_cause)
    if key is None:
        return None
    return optimus_config.get(key) or DEFAULT_LANES[key]


def build_payload(ticket: str, verdict: str, phase: str, config: dict,
                   partial_cause: str | None = None) -> dict:
    """Pure function: compose the move-task payload from inputs.

    Raises ValueError on invalid verdict or missing required input. Returns a
    dict whose `decision` field is one of: 'move', 'no_move_blocked',
    'no_move_phase_shadow', 'no_move_unknown_verdict'.
    """
    if not ticket:
        raise ValueError("ticket is required")
    if verdict not in {"pass", "fail", "partial", "blocked"}:
        raise ValueError(f"unknown verdict {verdict!r} (expected pass/fail/partial/blocked)")
    if phase not in {"shadow", "writes-on"}:
        raise ValueError(f"unknown phase {phase!r} (expected shadow/writes-on)")

    optimus_config = config.get("optimus") or {}
    from_lane = optimus_config.get("qa1_lane") or DEFAULT_LANES["qa1_lane"]

    if verdict == "blocked":
        return {
            "ok": True,
            "decision": "no_move_blocked",
            "ticket": ticket,
            "verdict": verdict,
            "from_lane": from_lane,
            "target_lane": None,
            "reason": "Verdict is `blocked` — ticket stays in qa1; the dashboard surfaces the blocked_reason.",
        }

    intended_lane = resolve_target_lane(verdict, partial_cause, optimus_config)
    if intended_lane is None:
        return {
            "ok": False,
            "decision": "no_move_unknown_verdict",
            "ticket": ticket,
            "verdict": verdict,
            "reason": f"No target lane mapped for verdict {verdict!r}.",
        }

    # Transitional substitution for pending-release lanes.
    # `needs_review` is the intended destination for data-related partials
    # but isn't in Optimus's product_task_statuses enum yet (verified
    # 2026-06-08 via get_meta). Substitute the effective lane that IS
    # live; surface the intended lane in `pending_release` for the
    # operator to see where the ticket "really" should be.
    pending_release = None
    target_lane = intended_lane
    if intended_lane in PENDING_RELEASE_LANES:
        target_lane = PENDING_RELEASE_LANES[intended_lane]
        pending_release = {
            "intended_lane": intended_lane,
            "effective_lane": target_lane,
            "reason": (
                f"Lane {intended_lane!r} is not yet in Optimus's "
                f"product_task_statuses enum. Falling back to "
                f"{target_lane!r} until the lane is released. "
                f"Remove the substitution from PENDING_RELEASE_LANES "
                f"once Optimus publishes the new status."
            ),
        }

    if phase == "shadow":
        payload = {
            "ok": True,
            "decision": "no_move_phase_shadow",
            "ticket": ticket,
            "verdict": verdict,
            "from_lane": from_lane,
            "target_lane": target_lane,
            "reason": "Phase is `shadow` — refusing the Optimus write. Mem + Slack still record the verdict.",
            "audit_action": f"would_have_moved_to_{target_lane}",
        }
        if pending_release:
            payload["pending_release"] = pending_release
        return payload

    payload = {
        "ok": True,
        "decision": "move",
        "ticket": ticket,
        "verdict": verdict,
        "from_lane": from_lane,
        "target_lane": target_lane,
        "mcp_tool": OPTIMUS_MOVE_TOOL,
        "args": {"task": ticket, "status": target_lane},
        "audit_action": f"optimus_moved_to_{target_lane}",
    }
    if pending_release:
        payload["pending_release"] = pending_release
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticket", required=True, help="Optimus ticket identifier (e.g. M1-1190).")
    p.add_argument("--verdict", required=True,
                   choices=["pass", "fail", "partial", "blocked"],
                   help="Aggregated run verdict.")
    p.add_argument("--phase", required=True, choices=["shadow", "writes-on"],
                   help="config.phase — shadow blocks all Optimus writes.")
    p.add_argument("--partial-cause",
                   help="Optional cause classifier for verdict=partial. When "
                        "set to one of the data-related causes (e.g. "
                        "'blocked_by_seed_data', 'no_seed_data', "
                        "'missing_test_data', 'environment_not_seeded') the "
                        "ticket routes to on_hold. Any other value (or "
                        "missing) routes partial to needs_changes — the dev "
                        "should look at it. v0.10.1.")
    p.add_argument("--config", type=Path,
                   help="Path to ~/.medtrics-qa-automation/config.json. "
                        "When omitted, defaults from this module are used.")
    args = p.parse_args()

    config: dict = {}
    if args.config:
        if not args.config.exists():
            print(json.dumps({"ok": False, "error": "config_not_found",
                              "path": str(args.config)}), file=sys.stderr)
            return 1
        try:
            config = json.loads(args.config.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": "config_invalid_json",
                              "detail": str(e)}), file=sys.stderr)
            return 1

    try:
        payload = build_payload(args.ticket, args.verdict, args.phase, config,
                                 partial_cause=args.partial_cause)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": "invalid_input", "detail": str(e)}),
              file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2))

    if payload["decision"] == "no_move_blocked":          return 3
    if payload["decision"] == "no_move_phase_shadow":     return 2
    if payload["decision"] == "no_move_unknown_verdict":  return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
