---
name: qa-optimus-bridge
description: Read/write wrapper around the Optimus MCP for medtrics-qa-automation. Owns the polling pattern (list_lane_tasks → filter for MR-linked tickets), the post-verdict lane transitions (pass→qa2, fail→needs_changes, partial→needs_changes-or-on_hold), the description-append pointer block update, and the MR-link extraction regex. Writes are blocked during Phase 1 shadow.
---

# qa-optimus-bridge

Optimus is reached through the MCP layer, not direct HTTP — so this bridge
isn't transport (the MCP call sites live in the calling SKILL.md procedures).
Instead the bridge owns two things:

1. **Validation + payload composition** for every Optimus write, via the
   scripts under `scripts/`. Each script consumes raw inputs, applies the
   policy + phase gate, and emits the JSON payload the caller passes to
   `mcp__904fdec1-…__<tool>`.
2. **The verdict → lane policy** that governs post-QA1 ticket transitions.

## Layout

```
scripts/
  optimus_move_task.py              # verdict → target lane; phase-gated payload
  optimus_build_verdict_comment.py  # short markdown footer appended to the ticket description
tests/
  test_optimus_move_task.py
  test_optimus_build_verdict_comment.py
```

## Verdict → target lane policy (v0.10.2)

| Verdict + cause | Intended lane | Effective lane today | Config key | Rationale |
|---|---|---|---|---|
| `pass` | `qa2` | `qa2` | `qa2_lane` | All P0 + ≥90% P1 passed; advance. |
| `fail` | `needs_changes` | `needs_changes` | `needs_changes_lane` | Real failure — send back to dev with the fail-thread evidence. |
| `partial` + data-related cause | **`needs_review`** | `on_hold` *(transitional fallback)* | `needs_review_lane` | Env work needed — seed data missing or environment not provisioned. No code change needed. |
| `partial` + non-data-related cause (or no cause) | `needs_changes` | `needs_changes` | `needs_changes_lane` | Run revealed something the dev should look at — code defect, tooling failure, missing step. |
| `blocked` | (no move — stay in `qa1`) | (no move) | n/a | Dashboard surfaces `blocked_reason`; poller retries. |

### Transitional fallback (v0.10.2)

`needs_review` is the intended destination for data-related partials but
is **not yet in** Optimus's `product_task_statuses` enum (verified via
`get_meta` on 2026-06-08 — the enum stops at `pipeline_issues`). The
script handles this through `PENDING_RELEASE_LANES = {"needs_review":
"on_hold"}` — when the resolved target lane is `needs_review`, the
payload sends `on_hold` to the MCP call AND surfaces a `pending_release`
field documenting the intended lane.

Operator-visible effect today:
- Optimus column = `on_hold`
- Payload + Mem run-log + Slack staging card all record `pending_release.intended_lane = needs_review`

Once Optimus releases the `needs_review` status:
1. Verify via `get_meta` that the enum now contains `needs_review`.
2. Remove the `needs_review → on_hold` entry from `PENDING_RELEASE_LANES`
   in `optimus_move_task.py`.
3. Re-run the test suite. No other code changes needed.
4. (Optional) Backfill: re-move tickets that landed in `on_hold` with
   `pending_release.intended_lane = needs_review` to the new lane.

### Cause vocabulary

Data-related partial causes (controlled list, configurable):
`blocked_by_seed_data` · `no_seed_data` · `missing_test_data` · `environment_not_seeded`.

Anything else (or no cause at all) is treated as non-data-related and
routes to `needs_changes`.

### Config overrides

Lane names are overridable per-install through
`config.optimus.{qa2,needs_changes,on_hold,needs_review}_lane`. Defaults
listed above. Custom values override BEFORE the
`PENDING_RELEASE_LANES` substitution runs, so a tenant that already has
its own equivalent of `needs_review` can route there directly without
the transitional fallback.

## Reads

- **List qa1 tickets.** `mcp__904fdec1-…__list_lane_tasks(status=config.optimus.qa1_lane, product=config.optimus.product, limit=200)`.
- **Inspect a ticket.** `mcp__904fdec1-…__get_task(task=identifier)`.
- **Search by MR.** `mcp__904fdec1-…__search_tasks(query="!12345")` for cross-checking MR↔ticket linkage.

## MR-link discovery

The MR link lives inside the task `description` (not a structured field). Extraction is pure-Python in `qa-checklist-reader/scripts/extract_mr_link.py`; the bridge just consumes the candidates.

## Writes (Phase 2+ only)

Every write follows this two-step pattern:

```
1. <script>.py → emits payload + audit_action
2. SKILL.md procedure calls mcp__904fdec1-…__<tool> with the args field
3. SKILL.md procedure logs the audit_action and any thread/note ids
```

### `move_task` — post-verdict lane transition

```bash
python3 scripts/optimus_move_task.py \
  --ticket M1-1190 --verdict pass --phase writes-on \
  --config ~/.medtrics-qa-automation/config.json
```

Outputs JSON with `decision ∈ {move, no_move_blocked, no_move_phase_shadow, no_move_unknown_verdict}`. Exit code reflects the decision:

| Exit | Meaning |
|---|---|
| `0` | `decision=move` — caller passes `args` to `mcp__904fdec1-…__move_task`. |
| `1` | Invalid input. |
| `2` | Phase is shadow — caller no-ops the write; Mem + Slack still record the verdict. |
| `3` | Verdict is `blocked` — no lane move; dashboard surfaces the blocker. |

### `update_task` — description + pointer-block update

Owned by `qa-checklist-reader` (steps 10–11). The pointer block is composed
by `qa-checklist-reader/scripts/build_pointer_block.py`, inserted in-place via
`find_pointer_block.py --upsert`, then the full updated description is passed
to `mcp__904fdec1-…__update_task(task=ticket, description=...)`.

### Verdict comment footer

`optimus_build_verdict_comment.py` composes a short markdown line that sits
under the pointer block — names the target lane, links the GitLab fail-thread
(when verdict=fail), and links the Mem run log. The orchestrating command
splices it into the description update before calling `update_task`.

## Write sequencing

Order matters when verdict is `fail` or `partial`:

```
1. qa-fail-reporter posts the GitLab discussion thread       (evidence first)
   → captures thread_url
2. optimus_build_verdict_comment.py composes the footer
   with the thread_url
3. qa-checklist-reader updates the Optimus description
   (pointer block + verdict footer)
4. optimus_move_task.py emits the move payload
5. SKILL.md procedure calls mcp__904fdec1-…__move_task
```

For `pass`, steps 1 and 2's `--gitlab-thread-url` flag are skipped — the comment links the Mem run log instead.

## Authentication

The Optimus MCP server handles its own auth. The bridge has no token discovery layer — the user's Cowork session is the auth boundary.

## Phase gating

Every Optimus write goes through `qa-guardrails.gate_write("optimus", phase)`. The `optimus_move_task.py` script applies the gate internally and refuses on shadow (exit 2). The pointer-block / description-update path follows the same rule — `qa-checklist-reader` only calls `update_task` when `phase == "writes-on"`.

## Failure handling

| Failure | Behavior |
|---|---|
| `move_task` rejected (404/permission) | Audit `optimus_move_failed`. Caller does not retry — surfaces to the QA Lead via the Slack staging card. |
| `update_task` rejected | Same as above. The verdict pointer block stays in the local Mem run log either way. |
| Phase shadow | No write attempted. Audit `would_have_moved_to_<lane>`. |
| Blocked verdict | No move. Ticket stays in qa1; dashboard surfaces the blocker. |

## What this skill does NOT do

- Compose GitLab fail-threads (that's `qa-fail-reporter`).
- Compose the verdict pointer block (that's `qa-checklist-reader/scripts/build_pointer_block.py`).
- Make MCP calls directly. The scripts emit payloads; the orchestrating SKILL.md procedure invokes the MCP tool.
- Reply to existing Optimus comments. There is no "add comment" tool in the Optimus MCP — context is delivered via the description footer composed by `optimus_build_verdict_comment.py`.

## Reads / Writes table

| Operation | Script | MCP tool | Phase 1 | Phase 2+ |
|---|---|---|---|---|
| List qa1 lane | (inline) | `list_lane_tasks` | ✅ | ✅ |
| Get task | (inline) | `get_task` | ✅ | ✅ |
| Search by MR | (inline) | `search_tasks` | ✅ | ✅ |
| Move task (pass→qa2) | `optimus_move_task.py` | `move_task` | ❌ blocked | ✅ |
| Move task (fail→needs_changes) | `optimus_move_task.py` | `move_task` | ❌ blocked | ✅ |
| Move task (partial→needs_changes-or-on_hold) | `optimus_move_task.py` | `move_task` | ❌ blocked | ✅ |
| Update description | (via qa-checklist-reader) | `update_task` | ❌ blocked | ✅ |

Phase 1 blocks are enforced by `qa-guardrails.gate_write("optimus", phase)` and by `optimus_move_task.py`'s internal phase check.
