---
name: qa-chrome-executor
description: Deterministic Chrome MCP driver for the medtrics-qa-automation pipeline. Loads scenario-matrix.yaml, matches the ticket, expands scenarios, runs each through Chrome MCP with a closed verb vocabulary (fetch, navigate, upload_and_verify), captures responses, runs structured assertions, and emits a verdict. NO LLM at execution time. Steps outside the verb whitelist mark as needs_human, never pass/fail.
---

# qa-chrome-executor

Runs the deterministic execution half of the QA automation. Consumes the
`MrResolution` object produced by `qa-checklist-reader`'s resolver, runs
the scenario-matrix dispatcher, drives Chrome MCP through every resolved
scenario, and writes the verdict back to Mem.

This skill replaces the v0.1 stub that talked about LLM interpretation
of natural-language steps. The dispatcher (`scripts/scenario_dispatcher.py`)
is the source of truth; this SKILL.md is the procedural wrapper that
turns its plans into Chrome MCP calls.

## Inputs

| Input | Required | Source |
|---|---|---|
| `ticket` | Yes | Optimus identifier (e.g. `M1-1129`) |
| `mr_resolution` | Yes | Output of `resolve_mr_via_gitlab.md` — has `mr_iid`, `deploy_url`, `source_branch`, `changed_files`, `title` |
| `run_id` | No | ISO timestamp; auto-generated if absent |

## Procedure

### 1. Load configuration and matrix

Read `~/.medtrics-qa-automation/config.json`. Load the scenario matrix:

```bash
python3 scripts/scenario_dispatcher.py \
  --matrix qa/scenario-matrix.yaml \
  --ticket-title "<mr_resolution.title>" \
  --ticket-type "bug" \
  --files-changed "<comma-join mr_resolution.changed_files>" \
  --plugin-root . \
  --plan-only
```

The dispatcher returns a JSON plan. Three terminal outcomes:

| Plan output | Behavior |
|---|---|
| `matched=false` | No rule covered this ticket. Set Mem run state `needs_human`, summary `"no scenario-matrix rule matched"`. Stop. |
| `matched=true, scanner_ok=false` | A negative test failed — the scanner is broken. Set Mem run state `unreliable`, attach `negative_test_failures`. Stop. NEVER run real assertions when scanner_ok is false. |
| `matched=true, scanner_ok=true` | Continue to step 2 with the resolved scenarios. |

### 2. Open Chrome MCP at the deploy URL

Skip the auth dance. The per-MR deploy at
`mr_resolution.deploy_url` (e.g. `https://6848.medtrics.dev`) inherits
the user's existing medtrics.dev session cookies — that's how the manual
M1-1129 verification worked, and that's how Cowork sees the same DOM.

```text
call mcp__Claude_in_Chrome__navigate(url = mr_resolution.deploy_url)
```

Then verify the page loaded and the user is authenticated:

```text
call mcp__Claude_in_Chrome__get_page_text()
```

If the response indicates a login page or the title contains "Sign in",
set Mem run state `blocked`, reason `not_authenticated`, summary
`"Chrome MCP is not logged in to medtrics.dev"`. Stop. (This is the
gap HANDOFF engineering ask #2 covers — a QA admin fixture would close
it. At-desk runs with Sahil's session open will not hit this.)

### 3. For each resolved scenario, dispatch on action.kind

The dispatcher's closed verb vocabulary is `fetch`, `navigate`,
`upload_and_verify`. One handler per verb.

#### 3a. `kind == "fetch"`

Hit the URL via `javascript_tool` running in the deploy origin so
session cookies attach automatically. Return the response as a byte
array (Cowork's safety filter blocks anything resembling raw CSV bytes
in tool output, so collect bytes inside the page and emit only a
length-prefixed array literal).

```javascript
// Execute via mcp__Claude_in_Chrome__javascript_tool
const r = await fetch("<scenario.action.url>", { credentials: 'include' });
const b = await r.arrayBuffer();
const bytes = Array.from(new Uint8Array(b));
return JSON.stringify({
  status: r.status,
  headers: Object.fromEntries(r.headers.entries()),
  byte_length: bytes.length,
  body_b64: btoa(String.fromCharCode(...bytes)),
});
```

Parse the returned JSON. Reconstruct a `CapturedResponse(status,
headers, body_bytes)` where `body_bytes` is `base64.b64decode(body_b64)`.
Pass it plus `scenario.assertions` to `run_assertions()` (importable
from `scripts/scenario_dispatcher.py`). Record the result.

#### 3b. `kind == "navigate"`

Visit a UI route and assert text or console-message conditions. Use
`mcp__Claude_in_Chrome__navigate` then `get_page_text` /
`read_console_messages` and feed the captured strings into the
assertion vocabulary (`body_contains`, `body_not_contains`).

#### 3c. `kind == "upload_and_verify"`

`mcp__Claude_in_Chrome__navigate` to the upload route,
`mcp__Claude_in_Chrome__file_upload` with the fixture path, then a
follow-up `get_page_text` to verify the success message via
`body_contains`.

#### 3d. Anything else

Mark the scenario `needs_human`. Do not fabricate an action. The run's
overall verdict will be `partial`, never `pass`.

### 4. Aggregate

After every scenario in the plan has a `StepResult`, call
`aggregate(results, scanner_ok=True)` from
`scripts/scenario_dispatcher.py`. The function returns a `RunVerdict`:

- `pass` — 100% P0 pass, ≥90% P1 pass, no `needs_human`
- `fail` — at least one P0 failure or P1 below threshold
- `partial` — incomplete P0 or `needs_human` present
- `unreliable` — scanner self-check failed (already handled in step 1)

### 5. Capture format per step (written into the Mem note)

The Mem run-log is structured to read like a human QA tester's report.
Three first-class arrays + one assessment block. The dashboard's
"View Result" expansion reads these directly.

#### 5a. `test_plan_steps[]` — what QA was supposed to follow

Pulled from the human-authored `## QA Checklist` section on the Optimus
ticket: `qa-checklist-reader` extracts the block and `parse_checklist_steps.py`
lifts each numbered step into the {n, priority, action, expected} shape.
For matrix-driven runs that bypass the human checklist (rare — only when
the matrix rule fully covers the bug class), synthesize the plan from
the matched rule + its resolved scenarios (one entry per `for_each` URL
plus the implicit auth + navigation steps).

```json
{
  "n": 2,
  "priority": "P0",
  "action": "Fetch /api/v2/data_import/export/template/?content_type=curriculum.curriculumcourcerotation with credentials.",
  "expected": "HTTP 200, response is a UTF-8 BOM-prefixed CSV with ASCII-clean headers and zero mojibake characters."
}
```

#### 5b. `execution_trace[]` — what the agent actually did

One entry per concrete action driven against the deploy. Records the
literal MCP call and the observation, not the abstract intent.

```json
{
  "n": 2,
  "started_at": "2026-05-28T17:30:14.823Z",
  "action_taken": "GET /api/v2/data_import/export/template/?content_type=curriculum.curriculumcourcerotation",
  "observed": "HTTP 200 · 6316 bytes · ✓ utf8_bom_present · ✓ no_mojibake · ✓ status_2xx · ✓ byte_length_gte",
  "verdict": "pass",
  "duration_ms": 423,
  "evidence": {
    "url": "/api/v2/data_import/export/template/?content_type=curriculum.curriculumcourcerotation",
    "status": 200,
    "byte_length": 6316,
    "headers_summary": {"content-type": "text/csv; charset=utf-8"},
    "assertion_results": [
      {"kind": "status_2xx", "passed": true},
      {"kind": "utf8_bom_present", "passed": true},
      {"kind": "no_mojibake", "passed": true},
      {"kind": "byte_length_gte", "passed": true}
    ]
  }
}
```

#### 5c. `assessment{}` — what worked, what didn't, untested

```json
{
  "passed": [
    "Step 1: Authentication on https://6848.medtrics.dev/ — session inherited",
    "Step 2a: curriculum.curriculumcourcerotation template — 6316 bytes, BOM ✓, 0 mojibake",
    "Step 2b: curriculum.sessioncourcerotation template — 2038 bytes, BOM ✓, 0 mojibake",
    "..."
  ],
  "failed": [],
  "untested": [],
  "issues_summary": "No issues. Encoding fix verified across all 8 reachable templates.",
  "next_actions": []
}
```

When the run is partial / blocked / needs_human, `failed[]` and
`untested[]` carry human-readable reasons. `next_actions[]` is the QA
reviewer's queue (e.g. "Run with academic_period_id context to cover
the 10 context-required slugs").

#### 5d. Top-level Mem note fields

In addition to the three arrays above, the Mem note keeps:

```json
{
  "ticket": "M1-1129",
  "state": "complete",
  "verdict": "pass",
  "p0_pass_rate": 1.0,
  "p1_pass_rate": null,
  "run_id": "2026-05-28T17:30:00Z",
  "last_updated_at": "2026-05-28T17:30:24Z",
  "branch": "fix/m1-1129/bug-curriculum-a-import-encoded",
  "deploy_url": "https://6848.medtrics.dev",
  "mr_url": "https://gitlab.com/medtrics/medtrics/-/merge_requests/6848",
  "mr_id": "6848",
  "changed_files": ["src/apps/data_import/services/csv_template.py", "..."],
  "test_plan_steps": [ /* §5a */ ],
  "execution_trace":  [ /* §5b */ ],
  "assessment":       { /* §5c */ },
  "summary": "PASS — 8 scenarios in 4.2s. Encoding fix confirmed across every reachable template.",
  "optimus_snapshot": { /* title, assignee, dueDate, ... */ }
}
```

DO NOT include raw response bodies in the Mem note — Cowork's safety
filter strips them and the assertion outcomes + byte counts in the
trace are sufficient evidence. For screenshots, store them as Mem note
attachments and reference by id, not as inline base64.

#### 5e. Legacy compatibility

The dashboard's View Result panel falls back to deriving Test Plan +
Execution Trace + Assessment from legacy fields (`evidence` dict,
`failed_items`, `not_yet_tested`) for older notes like M1-1129's
existing one. New runs SHOULD use the new arrays; the legacy fields
are read-only fallbacks and need not be written going forward.

### 6. Update the Mem run log

Find the run log by `ticket` (created earlier by `qa-checklist-reader`).
`update_note` with:

```python
update = {
  "state": "complete" if verdict.overall == "pass" else "needs_review",
  "verdict": verdict.overall,
  "p0_pass_rate": verdict.p0_pass_rate,
  "p1_pass_rate": verdict.p1_pass_rate,
  "step_results": step_results,
  "summary": f"{verdict.overall} — {len(step_results)} scenarios, "
             f"P0 {verdict.p0_pass_rate*100:.0f}%, "
             f"P1 {verdict.p1_pass_rate*100:.0f}%",
  "completed_at": now_iso(),
}
```

### 7. Phase-gated writes back to Optimus and Slack

- `phase == "shadow"`: emit the would-have-written messages to the audit
  log. Do not call Optimus update or Slack send. The dashboard reads
  the Mem note directly.
- `phase == "writes-on"`:
  - Update Optimus pointer block on the ticket description with the
    verdict + p0/p1 rates + scenario count.
  - Post a Slack staging card to the configured channel via
    `mcp__5f6545e3...__slack_send_message`. Card includes ticket id,
    verdict, deploy URL, top 3 failing scenarios (if any), and a "View
    in Cowork" link to the dashboard artifact.

### 8. Audit

One row per run, action `executor_completed` with verdict, step count,
and any blocked-reason. Same audit substrate as `qa-checklist-reader`.

## Pass criteria

Decided by the dispatcher's `aggregate` function. Not re-implemented
here. See `scripts/scenario_dispatcher.py` for the exact thresholds.

## Failure handling

| Failure | Behavior |
|---|---|
| `navigate` returns a login page | `state=blocked, reason=not_authenticated`. Stop. |
| `javascript_tool` returns a CORS / network error | Mark scenario `fail` with assertion `network_error`. Continue with remaining scenarios. |
| Deploy returns 5xx for every scenario | Run completes with verdict `fail`. The pointer block on Optimus surfaces the pattern; a real bug, not a flake. |
| Run takes longer than 10 minutes total | Hard timeout. `state=blocked, reason=timeout`. Stop. |

## Reads

- `mcp__Claude_in_Chrome__navigate`
- `mcp__Claude_in_Chrome__get_page_text`
- `mcp__Claude_in_Chrome__read_console_messages`
- `mcp__Claude_in_Chrome__read_network_requests`
- `mcp__Claude_in_Chrome__javascript_tool`
- `mcp__Claude_in_Chrome__file_upload` (for upload_and_verify only)
- `qa/scenario-matrix.yaml`
- `tests/fixtures/*` (for negative-test self-check, run by the dispatcher)

## Writes

- One Mem `QA Run Logs` note update (the row created by
  `qa-checklist-reader` earlier).
- One audit row per scenario, plus one per run.
- Phase-gated: one Optimus description update, one Slack staging card.

## Deprecated

- `scripts/resolve_step_action.py` — the v0.1 LLM-fallback resolver.
  Kept on disk for one release in case the dispatcher needs to fall
  back during the shadow window. Will be deleted in v0.3.0.
- The "natural-language step interpretation" path from v0.1 SKILL.md.
  Deterministic verb dispatch replaces it.

## Idempotence

- Mem run log keyed on `ticket`. Re-runs update the existing row.
- Optimus pointer block has stable markers (handled by
  `qa-checklist-reader/scripts/find_pointer_block.py --upsert`).
- Slack staging card: in writes-on mode, post once per `(ticket, verdict)`
  tuple. If the verdict changes on a re-run, post a new card with a
  thread-reply linking to the previous one.
