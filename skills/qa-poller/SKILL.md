---
name: qa-poller
description: The 5-minute trigger for medtrics-qa-automation. Pulls the current Optimus qa1 lane and the Mem QA Run Logs collection, identifies tickets that have not yet produced a current verdict (no Mem note) or whose previous run was blocked (Mem state is blocked), and hands each to qa-checklist-reader. Read-only against Optimus. The only Mem write path is via qa-checklist-reader itself. Lives as a Cowork scheduled task; runs every 5 minutes by default.
---

# qa-poller

The trigger. Phase 1's chosen architecture per the decisions brief.

## What changed in v0.2

In v0.1 the poller copied Optimus state into a Mem `QA1 Queue` collection so the dashboard could read fast. v0.3 of qa-queue dropped that pattern — the dashboard now reads Optimus directly and joins with Mem `QA Run Logs` for enrichment. So the poller's only remaining job is **the trigger**: notice when a new ticket enters qa1 (or when a previously-blocked ticket is now unblocked) and fire `qa-checklist-reader`.

## Inputs
None. Reads `~/.medtrics-qa-automation/config.json` for the Optimus product and the Mem `QA Run Logs` collection UUID.

## Output contract
- Zero or more `qa-checklist-reader` invocations.
- One audit row per ticket inspected (`polled_already_processed`, `polled_to_enqueue`, or `polled_to_retry`).
- One summary audit row at the end (`poll_completed`).

## Procedure

### 1. Load configuration
Read `~/.medtrics-qa-automation/config.json`. Refuse to proceed if absent.

### 2. Pull the Optimus qa1 lane
`list_lane_tasks(status="qa1", product=<config.optimus.product>, limit=200)` → write to `/tmp/qa-poller-optimus.json`.

### 3. Pull the Mem QA Run Logs
`list_notes(collection_id=<config.mem.run_logs_collection_id>, include_note_content=true, limit=100)` → write to `/tmp/qa-poller-mem.json`.

### 4. Diff
```bash
python3 scripts/diff_qa1_lane.py \
  --optimus-file /tmp/qa-poller-optimus.json \
  --mem-file /tmp/qa-poller-mem.json \
  --json
```

The helper returns three buckets:
- `to_enqueue` — in Optimus qa1, not in Mem run logs → fire `qa-checklist-reader` (first run).
- `to_mark_stale` — in Mem run logs, not in Optimus qa1 → **normal history under v0.2 semantics, ignore.**
- `in_sync` — in both → may include `blocked` tickets that need a retry; see step 5.

### 5. Retry blocked tickets
For each ticket in `in_sync`, parse its Mem note. If `state == "blocked"`, add it to a `to_retry` list and call `qa-checklist-reader` for it (with `force=true`). The uploader will re-attempt MR extraction in case the developer has since added an MR link to the description.

### 6. Stale handling (v0.2 — none)
The `to_mark_stale` bucket is informational only. Tickets that moved out of qa1 (to qa2, needs_changes, etc.) keep their Mem run log forever — that's the QA history. A future `qa-reaper` skill may garbage-collect very old entries; v0.2 does nothing.

### 7. Audit
Per-ticket rows for `polled_to_enqueue`, `polled_to_retry`, `polled_already_processed`, `polled_moved_on` (stale). One `poll_completed` summary row.

## Failure handling

| Failure | Behavior |
|---|---|
| `list_lane_tasks` fails | Audit-log and exit. Next poll picks up the work. |
| `list_notes` fails | Treat Mem as empty — every Optimus ticket becomes a candidate enqueue. `qa-checklist-reader` short-circuits on existing pointer blocks, so worst case is wasted compute, not duplicated artifacts. |
| Individual `qa-checklist-reader` call fails | Audit-log that ticket's failure, continue to the next. Don't abort the whole poll. |

## Architectural ceiling

Scheduled tasks run inside the user's Cowork session. The polling fires only when the session is live. This is the documented Phase 1 limitation in the decisions brief — addressed at install time by `/setup-medtrics-qa-automation`, and resolved long-term by the Phase 2 migration to a GitLab webhook receiver.

## Reads
- `mcp__904fdec1-f755-42c5-a32e-a3a9eb8ba1da__list_lane_tasks`
- `mcp__34ae805e-f0aa-44cb-b932-07a4b31578c1__list_notes`

## Writes
- None directly. Delegates all Mem and Optimus writes to `qa-checklist-reader`.
