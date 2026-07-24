---
name: qa-checklist-reader
description: Read the human-authored QA Checklist section from an Optimus qa1 ticket description, resolve the MR via GitLab, and emit the structured test_plan_steps that the API and UI executors consume. Writes a verdict pointer block back to the Optimus description (phase-gated). Idempotent — re-running on the same ticket replaces the pointer block in place. Replaces the v0.3 qa-checklist-uploader, which generated checklists from the diff.
---

# qa-checklist-reader

v0.4 reverses the input boundary. The plugin no longer authors checklists from
the branch diff — checklists are **human-authored** inside the Optimus ticket
description, under a stable `## QA Checklist` heading. This skill reads that
section, resolves the MR, and emits the structured input the executors need.

## Inputs

| Input | Required | Source |
|---|---|---|
| `ticket` | Yes | Optimus identifier (e.g. `M1-1190`) |
| `run_id` | No | ISO timestamp; auto-generated |
| `force` | No | Re-read even when a current verdict exists |

## Outputs

- `mr_resolution` — `{mr_iid, deploy_url, source_branch, changed_files, title, state}`
- `test_plan_steps[]` — structured steps in the shape `qa-ui-executor` consumes
- `persona`, `branch` — extracted from the checklist header
- Mem `QA Run Logs` note (created or updated) — keyed on ticket id
- Verdict pointer block on the Optimus description (phase-gated)

## Procedure

### 1. Load configuration
Read `~/.medtrics-qa-automation/config.json`. Refuse to proceed if absent.

### 2. Fetch the Optimus task
Call `mcp__904fdec1-…__get_task(task=<ticket>)`. Verify `task.status == "qa1"`.
Keep the full task object — its description is the input.

### 3. Resolve the MR via GitLab
Follow `resolve_mr_via_gitlab.md` end-to-end. Use the cached fast path:

```bash
python3 ../qa-gitlab-bridge/scripts/gitlab_get_mr.py \
  --iid <candidate.value.iid> --cache-ttl 300
```

Outcomes:
- `resolved=true` → continue with the full `MrResolution` (incl. `head_sha`).
- `blocked_reason="no_candidates"` → write blocked Mem note. The author needs to
  add an MR link to the description. Poller will retry next cycle.
- `blocked_reason="no_open_mr_found"` → write blocked Mem note.
- `blocked_reason="deploy_not_ready"` → MR found but deploy is `running`,
  `skipped`, or `failed`. Write blocked Mem note. Poller will retry on next tick.
- `blocked_reason="gitlab_error"` → transient. Write blocked Mem note. Retry.

### 3a. Mem dedup — short-circuit if we already verdicted this head_sha (v0.7+)

**This is the early-exit that saves the rest of the procedure.** Before parsing
the checklist or running the executor, search the Mem `QA Run Logs` collection
for the ticket's existing note:

```python
notes = mem.search_notes(
    collection_id = config.mem.run_logs_collection_id,
    query         = ticket,                # "M1-1190"
    include_note_content = True,
    limit = 5,
)
existing = pick_by_ticket(notes, ticket)   # parse the JSON block, match on .ticket
```

If `existing` is present and `force` is False:

| Existing state | mr_head_sha matches current? | Action |
|---|---|---|
| `passed` | yes | **Stop.** Return `state=already_processed, reason=verdict_cached_for_head_sha`. No execution needed. Audit-log `dedup_hit`. |
| `failed` | yes | **Stop.** Same as above. The MR author must push a new commit (= new `head_sha`) to re-trigger. Audit `dedup_hit`. |
| `passed` or `failed` | no (new commits since) | Continue to step 4 — this is a re-run on a fresh head. The Mem note will be updated in step 8. |
| `blocked` | n/a | Continue — we want to retry blocked tickets in case the blocker resolved. |
| `queued` / `in_progress` | n/a | Continue — picking up a previously-staged run. |

Force-override: `--force` skips this check entirely. Use sparingly; the dedup
exists to keep the polling loop from re-doing work on every tick.

### 3.5. Try the GitLab MR attachment first (v0.9+)

Checklists can also live as `.txt` attachments on the MR's discussion threads
— authored, reviewed, and versioned alongside the code change instead of in
the Optimus description. This is the **preferred** source when present; the
description is the fallback.

```bash
python3 ../qa-gitlab-bridge/scripts/gitlab_find_mr_attachment.py \
  --iid <mr_resolution.mr_iid> \
  --branch <mr_resolution.source_branch> \
  --ticket <ticket>
```

The finder returns the best match by priority: **exact branch-slug filename**
(`{branch-slashes-as-hyphens}-manual-qa-checklist.txt`) → **suffix glob**
(`*-manual-qa-checklist.txt`) → **ticket-id-in-filename** (`*<ticket>*.txt`).
On tie, the most recent attachment wins so a re-uploaded checklist supersedes
the earlier copy.

If a match is found, download it:

```bash
python3 ../qa-gitlab-bridge/scripts/gitlab_download_upload.py \
  --secret <match.secret> \
  --filename <match.filename> \
  --out /tmp/checklist.txt
```

Then jump to step 5 with the downloaded text as input. The Mem run-log
records `checklist.source: "gitlab_mr_attachment"` along with the matched
filename and note id.

If `gitlab_find_mr_attachment.py` exits code 3 (no matching attachment),
fall through to step 4. Source precedence is configurable via
`config.checklist.sources` (default `["gitlab_mr_attachment", "optimus_description"]`).

### 4. Extract the QA Checklist section from the description (fallback)

```bash
python3 scripts/extract_checklist_block.py --stdin --json < <task.description>
```

Two outcomes:
- `present=true` → continue with `checklist` text. The Mem run-log records
  `checklist.source: "optimus_description"`.
- `present=false, reason="checklist_missing"` → AND step 3.5 also missed →
  write a Mem note with `state="blocked", blocked_reason="checklist_missing",
  summary="No checklist on the MR threads and no '## QA Checklist' section
  in the ticket description. Author must add one."` Audit, surface on the
  dashboard, stop.

### 5. Parse the checklist into structured steps

```bash
python3 scripts/parse_checklist_steps.py --stdin < <checklist_text>
```

Yields `{branch, persona, step_count, priority_counts, steps[]}`. If
`step_count == 0`, write blocked Mem note with
`blocked_reason="checklist_unparseable"` — the heading was present but no
numbered steps were recognized. Include the raw section in the note's
`summary` so the author can see what we saw.

### 6. Sanity-check the parsed output

- Each step must have a non-empty `action`. Steps with an empty `expected`
  field are flagged `needs_human` at execution time but do not block the run.
- The `Tester role:` line (when present) is informational metadata only —
  surfaced on the dashboard, written to the audit row, never consulted by
  the executor. Login behavior is owned by the checklist's own steps
  (typically a `Log in as <email>` step at the top). The reader does not
  refuse a checklist that lacks a `Tester role:` line — that field went
  from required-input to informational in v0.9.3 when the 6-persona model
  was removed.

### 7. Identify the existing Mem note id for the upcoming update

Dedup already short-circuited in step 3a if a current verdict existed. By the
time we reach step 7 we've decided this is a real run. Capture the existing
note's id (from the step-3a `search_notes` response we cached) so step 9 can
`update_note` against it instead of creating a duplicate.
- Otherwise → proceed (new run, e.g. after a force-push).

### 8. Build the Mem note content

```python
run_log = {
  "ticket": ticket,
  "state": "queued",
  "run_id": run_id,
  "lane": None,                           # set by the executor
  "branch": mr_resolution.source_branch,
  "deploy_url": mr_resolution.deploy_url,
  "deploy_status": mr_resolution.deploy_status,
  "mr_url": mr_resolution.mr_url,
  "mr_id": mr_resolution.mr_iid,
  "mr_state": mr_resolution.state,
  "mr_head_sha": mr_resolution.head_sha,
  "changed_files": mr_resolution.changed_files,
  "checklist": {
    "source": "optimus_description",
    "persona": parsed["persona"],
    "branch_declared": parsed["branch"],
    "step_count": parsed["step_count"],
    "priority_counts": parsed["priority_counts"],
    "steps": parsed["steps"],             # the full test_plan_steps[]
  },
  "verdict": None,
  "blocked_reason": None,
  "summary": "Checklist parsed. Awaiting executor.",
  "last_updated_at": now_iso(),
  "optimus_snapshot": {
    "title": task.title,
    "type": task.type,
    "priority": task.priority,
    "highRisk": task.highRisk,
    "assignee": task.assignee,
    "qa1_reviewer": task.qa1,
    "qa2_reviewer": task.qa2,
    "code_reviewer": task.codeReview,
    "dueDate": task.dueDate,
    "statusChangedAt": task.statusChangedAt,
  },
}
```

### 9. Persist to Mem
- New ticket: `create_note(content=…, collection_titles=["QA Run Logs"])`.
- Existing ticket: `update_note(id=existing.id, content=…)`.
- Persist the note id to the audit log for later updates by the executors.

### 10. Build the verdict pointer block
`scripts/build_pointer_block.py` renders the markdown block. In v0.4 the block
is a *verdict marker* — it carries the lane, verdict, pass rates, deploy URL,
Mem run link, and dashboard link — not a "checklist generated" announcement.

Until the executor runs, the block shows `state=queued`.

### 11. Write back to the Optimus description
- `phase == "shadow"` → print the pointer block, audit-log
  `would_have_uploaded`, stop. **Do not write the block back to the
  description in shadow** — that gives QA Lead a clean stream to review.
- `phase == "writes-on"` → `scripts/find_pointer_block.py --upsert` to merge
  the block into the description, then call `update_task(task=<ticket>,
  description=<updated>)`.

### 12. Audit
One row, action `checklist_read` (writes-on) or `checklist_read_shadow`
(shadow). Includes `step_count`, `priority_counts`, `persona`.

## Output handoff

The Mem note's `checklist.steps[]` is the canonical input both lanes consume.
`/manual-qa-execute` reads it directly; the executor never re-parses the
description.

## Idempotence

- Mem note: keyed on ticket id. Subsequent runs `update_note`.
- Optimus description: pointer block carries stable markers, `find_pointer_block.py --upsert` replaces in place.
- Net effect: re-running on the same ticket is safe.

## Failure handling

| Failure | Behavior |
|---|---|
| `get_task` fails | Refuse — without the task we can't snapshot it or read the checklist. Audit-log and exit. |
| MR unresolved | Write a `blocked` Mem note with the specific `blocked_reason`. Poller retries. |
| Checklist section missing | Write `blocked, checklist_missing`. **Authors must add one — no auto-generation in v0.4.** |
| Checklist heading present but no steps recognized | `blocked, checklist_unparseable`. Include the raw section in `summary`. |
| Mem `create_note` fails | Audit-log, continue. Pointer block in the description carries the essentials. |
| Optimus update fails (writes-on) | Retry once after 5 s. Second failure → `blocked, optimus_write_failed`. |

## Reads
- `mcp__904fdec1-…__get_task`
- `mcp__34ae805e-…__list_notes` (for the existing-note check)
- GitLab MCP (per `resolve_mr_via_gitlab.md`)

## Writes
- One Mem `QA Run Logs` note (create or update).
- Optionally one Optimus description update (phase-gated).
- One audit row.

## What changed from v0.3

| v0.3 (`qa-checklist-reader`) | v0.4 (`qa-checklist-reader`) |
|---|---|
| Called `.agents/skills/sk-manual-qa` to generate a checklist from the diff | Reads a human-authored `## QA Checklist` section from the Optimus description |
| Wrote a "checklist generated" pointer block to Optimus | Writes a *verdict* pointer block carrying lane, verdict, pass rates |
| Blocked only on MR resolution failures | Also blocks on `checklist_missing` and `checklist_unparseable` |
| Depended on the external `.agents/skills/sk-manual-qa` repo | No external skill dependency |
| Author of the test cases: the plugin (from the diff) | Author of the test cases: the human writing the ticket |
