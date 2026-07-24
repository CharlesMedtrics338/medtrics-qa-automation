---
description: Poll the Optimus qa1 lane once. For each ticket without a current QA verdict, read the QA Checklist from the description, resolve the MR, and stage a Mem run log. Read-only against Optimus. Runs every 5 minutes as a scheduled task by default; can also be invoked manually.
argument-hint: "[--dry-run] [--verbose]"
---

# /qa1-poll

You are running the polling tick for the Medtrics QA automation pipeline. This command **discovers** work — it does not execute checklists. Execution is `/manual-qa-execute` or `/ui-qa-execute`.

## What to do

1. **Resolve config.** Invoke `qa-config`. If `~/.medtrics-qa-automation/config.json` is missing, tell the user to run `/setup-medtrics-qa-automation` first and stop.

2. **Read the Optimus qa1 lane.** Call `mcp__904fdec1-…__list_lane_tasks(status="qa1", product=config.optimus.product, limit=200)`. Cache the response to `/tmp/qa-poller-optimus.json`.

3. **Read the Mem QA Run Logs.** Call `mcp__34ae805e-…__list_notes(collection_id=config.mem.run_logs_collection_id, include_note_content=true, limit=200)`. Cache to `/tmp/qa-poller-mem.json`.

4. **Diff.** Run `python3 skills/qa-poller/scripts/diff_qa1_lane.py --optimus-file /tmp/qa-poller-optimus.json --mem-file /tmp/qa-poller-mem.json --json`. The output has three buckets:
   - `to_enqueue` — in Optimus qa1, no Mem run log yet.
   - `in_sync` — in both. Inspect each: if `state == "blocked"`, add to `to_retry`. Otherwise skip.
   - `to_mark_stale` — in Mem but not in Optimus qa1. Informational only in v0.4. Ignore.

5. **For each ticket in `to_enqueue` and `to_retry`:**
   - If `--dry-run`, print the candidate and continue (do not call the reader).
   - Otherwise, invoke `qa-checklist-reader` with `ticket=<id>` (and `force=true` for retries). The reader handles the rest — MR resolution, checklist extraction, Mem note creation. Each ticket succeeds or fails independently; do not abort the whole poll on one ticket's failure.

6. **Audit and summarize.** Append one row per ticket inspected (`polled_to_enqueue`, `polled_to_retry`, `polled_already_processed`) and one summary row (`poll_completed`) with counts and duration.

7. **Print a concise summary** in the format documented in `skills/qa1-poll/SKILL.md`:
   ```
   qa-poller @ <iso-timestamp>
     optimus qa1 lane: N tickets
     mem QA Run Logs:  N tickets
     to_enqueue:       N (<ids>)
     to_retry:         N (<ids>)
     in_sync:          N
     poll_completed in X.Xs
   ```
   With `--verbose`, also list the `in_sync` tickets and their current verdict states.

## Failure handling
- `list_lane_tasks` fails → audit-log and exit. Next poll picks up the work.
- `list_notes` fails → treat Mem as empty. The reader short-circuits on existing pointer blocks, so worst case is wasted compute.
- Per-ticket reader failures → audit, continue.

## Notes
- This command is read-only against Optimus. All Optimus writes go through `qa-checklist-reader` and the executors.
- Scheduled tasks run inside the user's Cowork session — polling fires only when the session is live. This is the documented Phase 1 limitation; the Phase 2 migration to a GitLab webhook receiver closes the gap.
