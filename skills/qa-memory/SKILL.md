---
name: qa-memory
description: Mem warm-tier substrate for medtrics-qa-automation. Owns the QA Run Logs, Regression Run Logs, and QA Flake Catalog collections. Reads are cheap; writes go through the shared PII scrubber. Failures never block the parent flow — the audit log is the durable record.
---

# qa-memory

v0.3 architecture: **Optimus is the source of truth for what's in qa1.** Mem stores QA enrichment — what we've measured about each ticket — not the queue itself. The old `QA1 Queue` collection from v0.2 was deleted on 2026-05-27.

## Two-tier memory (v0.7+)

The plugin has **two distinct memory layers**, each with a different job. They never substitute for each other; they cooperate.

| Layer | Skill | Where it lives | Lifetime | Job |
|---|---|---|---|---|
| **Warm tier — Mem** | `qa-memory` (this skill) | Cloud collections via the Mem MCP | **Indefinite** — the durable verdict archive | Per-ticket QA Run Log: did we already verdict this MR's head_sha? What's the pass-rate history? Semantic search across past failures (`find_related_notes` used by `qa-fail-reporter` to surface "we've seen this before"). |
| **Hot tier — Cache** | `qa-cache` | Local filesystem at `~/.cache/medtrics-qa-automation/` | **Seconds to minutes** (TTL per namespace) | Don't re-fetch the same answer twice in 5 minutes. Skips re-doing expensive reads from GitLab, Optimus, and (sometimes) Mem itself when the polling loop fires and nothing has changed. |

### How they cooperate on a single polling tick

```
/qa1-poll fires (5-min cron)
   │
   ├─ list_lane_tasks(qa1)              ← cached 60s (hot)
   │
   └─ for each ticket:
      ├─ search Mem QA Run Logs           ← cached 300s (hot)
      │  for ticket=<id>
      │
      ├─ if existing.state ∈ {passed, failed}
      │  and existing.mr_head_sha == current.head_sha:
      │     ──► short-circuit: state=already_processed   (warm tier hit)
      │
      ├─ else: gitlab_get_mr --cache-ttl 300  ← cached 300s (hot)
      │  ──► fresh MrResolution
      │
      └─ continue normal run; on completion, update_note(Mem)  (warm tier write)
```

The hot tier prevents API-call thrash during a single polling cycle. The warm tier prevents re-execution across cycles when the underlying MR hasn't changed. Together they make the polling loop nearly free on quiet periods (5 unchanged tickets → 5 Mem lookups + 5 cache hits + 0 GitLab calls).

### What goes in which tier — quick reference

- **Mem (warm):** QA Run Logs, Regression Run Logs, QA Flake Catalog. Cross-session semantic archive. PII scrubbed.
- **Cache (hot):** `gitlab.get_mr`, `gitlab.pipeline`, `optimus.get_task`, `optimus.list_lane_tasks`, `mem.search_notes`. Never the source of truth — just a speed layer. Bypassable with `--no-cache`.

### Failure modes

- Mem unreachable → log to audit, continue with stale local snapshot. The polling loop still runs; dedup degrades to "always process" until Mem returns.
- Cache unreadable (disk error, perms) → silent miss; every read falls through to the source. No-op for correctness.
- Cache corrupted entry → treated as expired and pruned on next read.



## Collections

### `QA Run Logs` — live
- **UUID source:** `config.mem.run_logs_collection_id` in `~/.medtrics-qa-automation/config.json`. Provisioned by `/setup-medtrics-qa-automation` step 4 (it calls `create_collection(title="QA Run Logs")` and records the returned UUID). If the field is `null`, the run blocks with `blocked_reason: mem_collection_missing` and points the operator at `/setup-medtrics-qa-automation`.
- **GAP-2 (v0.10.0):** the hardcoded placeholder UUID that previously appeared here has been removed. All readers and writers must resolve the UUID from config.
- **Reference (Charles's install, provisioned 2026-06-07):** `6d15e4a6-516b-43a6-a4ee-2f74937492a8`. This UUID is per-install; other operators will get a different UUID from their own setup run. Do NOT hardcode this value in any plugin file — it's recorded here only as the audit reference for the first live provisioning.
- **One note per ticket** that `qa-checklist-reader` or `qa-chrome-executor` has ever processed.
- **Cardinality:** one note per `ticket`, not per run — subsequent runs update the same note via `update_note` and bump its `run_id`.
- **State field:** `queued | in_progress | passed | failed | blocked` — set by the writer skill, read by the dashboard.
- **Title format:** `QA Run Log · {ticket}`.
- **Body format:** A short summary followed by a fenced ` ```json ``` ` block. See `qa-queue/SKILL.md` for the full JSON schema (the dashboard owns the schema; this skill owns the write path).
- **Writer:** `qa-checklist-reader` (creates / updates on enqueue), `qa-chrome-executor` (updates state during a run), `/manual-qa-execute` (writes final verdict).
- **Reader:** `qa-queue` (dashboard), `qa-poller` (deciding which tickets need checklist generation).

### `Regression Run Logs` — to be provisioned
- One note per `/regression-execute` run, per module.
- Roll-up posted to `#dream-team` references these.

### `QA Flake Catalog` — to be provisioned
- Time-boxed list of known-flaky checklist items.
- The executor reads this and tags matching items `skip`/`flake` rather than failing the run.

## Write pattern

```python
content = "\n".join([
    f"QA Run Log · {ticket}",
    "",
    f"State: {state} · Branch: {branch or '(unresolved)'}{verdict_suffix}",
    "",
    "```json",
    json.dumps(run_log_dict, indent=2),
    "```",
    "",
    summary_line,
])

# First write for a ticket:
note = create_note(content=content, collection_titles=["QA Run Logs"])
# Persist the note id; subsequent runs:
update_note(id=note.id, content=updated_content)
```

The note id is persisted in the audit log so subsequent state transitions update the same note rather than creating duplicates.

## optimus_snapshot

When `qa-checklist-reader` runs, it has already called `get_task` for the full ticket (needed for description body, dueDate, reviewer slots). Before writing the Mem note, it captures the relevant fields into a nested `optimus_snapshot` object. This lets the dashboard render rich cards (reviewer names, due dates, statusChangedAt for age-in-lane) without making per-ticket `get_task` calls itself.

The snapshot is **not refreshed on every read**. It reflects the Optimus state at the most recent checklist generation. If a reviewer is reassigned or a dueDate changes mid-run, the dashboard will show the snapshot value until the next checklist generation. This is an intentional trade-off — fresh enough for queue ordering, cheap to read.

## PII scrub

Run all free-form fields through the shared scrub bank in `qa-audit/SKILL.md` before write:
- email addresses
- internal user IDs like `MRN-\d+` or `user_\d+`
- access tokens / API keys (`Bearer …`, `xoxb-…`)
- file paths with home dirs (`/Users/[^/]+/…` → `/Users/<redacted>/…`)

## Failure handling
- Mem MCP unavailable → log to audit, continue. The Optimus pointer block on the ticket carries enough info for a human to reconstruct state.
- `create_note` returns 409 → fall back to `update_note` against the conflicting id.
- Any other error → audit-log and surface to QA Lead. Do not retry endlessly.

## Bootstrap

The collection is created exactly once. `/setup-medtrics-qa-automation` checks `list_collections` for `QA Run Logs`; if absent, creates it and stores the returned UUID in `~/.medtrics-qa-automation/config.json` under `mem.run_logs_collection_id`. The dashboard JS reads the same UUID baked at artifact-creation time. Re-running setup is safe.

## Migration from v0.2

The v0.2 `QA1 Queue` collection (UUID `092b873d-c7f8-4cf4-9ba4-e44118575168`) was deleted on 2026-05-27 after the four meaningful notes were migrated into `QA Run Logs` with the new schema. The old collection contained one note per ticket-in-qa1; the new collection contains one note per ticket-ever-processed. New schema adds `optimus_snapshot` and drops the redundant top-level fields that duplicated Optimus state.
