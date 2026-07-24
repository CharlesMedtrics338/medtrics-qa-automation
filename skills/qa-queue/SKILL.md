---
name: qa-queue
description: Cowork Live Artifact dashboard for medtrics-qa-automation. Reads the Optimus qa1 lane directly on every load and joins each ticket with its run log from the Mem QA Run Logs collection. Single shared dashboard for the whole QA team; per-user reviewer filter persists in localStorage. Backed by the qa1-queue-dashboard artifact ID.
---

# qa-queue

The single shared view the QA team opens to see what's in flight. Reads two data sources every page load and joins them — there is no Mem-as-cache pattern.

## Architecture (v0.3 — refactor)

```
Cowork artifact (qa1-queue-dashboard)
        │
        ├──► Optimus list_lane_tasks(status="qa1", product="medtrics")
        │       returns the current set of tickets in qa1 — the source of truth
        │       for "is this ticket here right now"
        │
        └──► Mem list_notes(collection="QA Run Logs")
                returns per-ticket QA enrichment (checklist counts, verdict,
                pass rates, reviewer names, due dates) for every ticket the
                automation has ever processed
```

The dashboard merges by `ticket id`. A ticket that's in Optimus qa1 but has no run log shows up immediately with a `no run yet` badge and a default `queued` state. A ticket that has a run log but is no longer in Optimus qa1 simply doesn't appear — Optimus is the source of truth for "what's in the lane."

## Artifact ID
`qa1-queue-dashboard` — created via `mcp__cowork__create_artifact`, updated via `mcp__cowork__update_artifact`.

## Implementation (v0.6.1)

The widget code ships in-plugin and is provisioned automatically by setup.

```
skills/qa-queue/
  templates/
    dashboard.html              ← the actual self-contained HTML widget
  scripts/
    build_dashboard_widget.py   ← injects config-time values into the template
  tests/
    test_build_dashboard.py     ← builder substitution tests
```

`/setup-medtrics-qa-automation` calls `build_dashboard_widget.py --config ~/.medtrics-qa-automation/config.json` and passes the result to `mcp__cowork__create_artifact`. The standalone `/qa-dashboard` command does the same idempotently (create on first run, update on re-runs). After provisioning, the artifact is alive — every Cowork Reload re-fetches Optimus + Mem; no caching layer in between.

## Mem collection
`QA Run Logs` — collection UUID is resolved at runtime from
`config.mem.run_logs_collection_id` in `~/.medtrics-qa-automation/config.json`.
Provisioned by `/setup-medtrics-qa-automation` step 4. If the field is null,
run `/setup-medtrics-qa-automation` before invoking the dashboard. GAP-2
(v0.10.0) removed the previous hardcoded placeholder UUID — never embed a
literal UUID here.

## What's in a run log note

The body is markdown. The first line is the title, the body holds a short summary, and a fenced ` ```json ``` ` block carries:

```json
{
  "ticket": "M1-1154",
  "state": "queued | in_progress | passed | failed | blocked",
  "run_id": "2026-05-27T16-15-00Z",
  "branch": "feat/...",
  "deploy_url": "https://m1-1154.medtrics.dev",
  "mr_url": "https://..." | null,
  "mr_id": "8421" | null,
  "checklist": {"total": 15, "p0": 3, "p1": 4, "p2": 2, "untagged": 6} | null,
  "verdict": "pass | fail" | null,
  "verdict_confidence": 0.94 | null,
  "p0_pass_rate": 1.0 | null,
  "p1_pass_rate": 1.0 | null,
  "p2_pass_rate": 0.8 | null,
  "failed_items": [] | null,
  "blocked_reason": null | "no_mr_or_branch_in_description" | "checklist_generation_failed",
  "pinned_at": null | "2026-05-27T...",
  "pinned_by": null | "qa-lead-handle",
  "summary": "Human-readable one-liner",
  "last_updated_at": "2026-05-27T16:18:00Z",
  "optimus_snapshot": {
    "title": "...",
    "type": "feature",
    "priority": "medium",
    "highRisk": false,
    "assignee": "chris",
    "qa1_reviewer": "sahil",
    "qa2_reviewer": "daren",
    "code_reviewer": "rio",
    "dueDate": "2026-08-01",
    "statusChangedAt": "2026-05-24T01:22:54Z"
  }
}
```

The `optimus_snapshot` is captured at checklist-generation time by `qa-checklist-reader` (which already does `get_task` for the full ticket). The dashboard uses it for fields like reviewer names and due date that `list_lane_tasks` does not return — avoiding N extra `get_task` calls on every dashboard load.

## Priority score formula
```
score =
    PRIORITY_WEIGHT[priority]
  + TYPE_WEIGHT[type]
  + (highRisk ? 30 : 0)
  + min(50, max(0, ageHoursInLane * 0.5))     # requires Mem snapshot
  + dueDateBonus                              # requires Mem snapshot
  + (pinned_at ? 10000 : 0)
```

Tickets without a Mem run log get only the type + priority + highRisk components. They still rank correctly relative to each other; the age/due bonuses kick in once the first checklist runs.

## Layout
- Masthead with wordmark, page title, total-counts deck, reviewer filter, last-updated timestamp.
- State chips: in_progress / queued / failed / blocked / passed.
- Section per state, in that order.
- Two-column cards: left has ticket id (linked to Optimus), title, priority/type/high-risk/due/no-run badges, summary, metadata row; right has priority score, checklist priority mix, optional verdict bar, optional blocked-reason.

## Filter persistence
Reviewer filter persists in `localStorage` under `qa1-dashboard:reviewerFilter`. Per-user, per-machine. No state lives in Mem.

## Failure modes
- **No Cowork bridge.** Outside the sidebar → "open from Cowork" notice.
- **Optimus unreachable.** Fatal red banner — dashboard cannot render without the lane data.
- **Mem unreachable.** Soft yellow warning — dashboard still renders Optimus data without QA enrichment.

## What this skill does NOT do
- Not an editor. Action buttons (move to QA2, mark blocked) belong to `/manual-qa-execute` and `qa-checklist-reader`.
- Does not poll on a timer. Each open / Reload triggers fresh reads.
- Does not author checklists. Authorship is the ticket author's job — the dashboard only renders what the executors have observed.
