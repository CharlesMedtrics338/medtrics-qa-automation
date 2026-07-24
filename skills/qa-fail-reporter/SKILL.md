---
name: qa-fail-reporter
description: Build and post the GitLab merge-request discussion thread when a QA1 run fails. Reads the Mem run log, picks the before/after screenshot pair for each failing step, uploads the images via the GitLab uploads endpoint, renders a structured thread body that includes per-step action/expected/observed, captured console errors, network errors (4xx and 5xx asset loads), and any non-blocking UI/UX observations from qa-ui-observer, then posts via qa-gitlab-bridge. Phase-gated through qa-guardrails — refuses in shadow.
---

# qa-fail-reporter

Closes the loop after a failed QA1 run. Turns the structured Mem run log into
a thread the MR author can act on — screenshots, console errors, and network
errors inline; UI/UX observations called out separately.

## When to invoke

- `/manual-qa-execute` and `/ui-qa-execute` call this skill when the aggregated
  verdict is `fail` AND `config.phase == "writes-on"`.
- The skill refuses on `phase == "shadow"` via `qa-guardrails.gate_write`. The
  shadow output is the Slack staging card only — same as today.
- Manual invocation (e.g. "/fail-thread M1-1190") is supported for replaying a
  prior failed run from its Mem note.

## Inputs

| Input | Required | Source |
|---|---|---|
| `ticket` | Yes | Optimus identifier — keys the Mem run log |
| `run_log` | Yes | The Mem `QA Run Logs` note for the ticket (read by caller) |
| `screenshot_dir` | Yes | Default `outputs/qa/<ticket>/` — where qa-ui-executor wrote PNGs |
| `mr_resolution` | Yes | From qa-checklist-reader — `{mr_iid, project_id, head_sha}` |
| `dry_run` | No | If true, render the thread body and return; do not upload or post |

## Procedure

### 1. Pre-flight guardrail
```python
d = qa_guardrails.gate_write("gitlab", config.phase)
if not d.allowed:
    return {"posted": False, "reason": d.reason}
```

Refuse on block. The shadow flow ends here.

### 2. Identify failing steps
From `run_log.execution_trace[]`, select entries with `verdict == "fail"`.
Preserve their order — failures are reported in execution sequence so the
author can reconstruct the run.

If `failed_items` is empty (i.e. verdict was `partial` from `needs_human`),
fall through to the partial path: still post a thread but with `partial`
framing rather than `fail`.

### 3. Select screenshot attachments

```bash
python3 scripts/select_attachments.py --run-log run_log.json --screenshot-dir outputs/qa/<ticket>/
```

Per failing step, the script picks **two** screenshots:
- The screenshot from the step immediately before (if it exists) — "state going in"
- The screenshot from the failing step itself — "state at failure"

Output: `[{step_id, label, path}]` ordered by step number. Max 8 attachments
total — if there are more than 4 failures, the script keeps the first 4 pairs
and notes the truncation in the thread.

### 4. Upload screenshots to GitLab

For each attachment, invoke the bridge script:

```bash
python3 ../qa-gitlab-bridge/scripts/gitlab_upload_file.py \
  --path <attachment.path>
# returns JSON: {ok, alt, url, full_path, markdown, id}
```

GitLab's response shape:

```json
{
  "alt": "step-3.png",
  "url": "/uploads/abc123/step-3.png",
  "full_path": "/medtrics-legacy/uploads/abc123/step-3.png",
  "markdown": "![step-3.png](/uploads/abc123/step-3.png)"
}
```

Splice the `markdown` field into each attachment record before passing the
augmented attachments file to `build_fail_thread.py`. If `gitlab_upload_file.py`
exits non-zero, leave `gitlab_markdown` absent on that attachment — the
renderer falls back to a `_(screenshot upload failed)_` placeholder so the
thread still posts.

### 5. Build the thread body

```bash
python3 scripts/build_fail_thread.py --run-log run_log.json --attachments attachments.json
```

Renders `templates/fail-thread.md`. Structure:

```markdown
## ❌ Automated QA1 Failed — {ticket}

| Field | Value |
|---|---|
| Ticket | [{ticket}]({optimus_url}) |
| Branch | `{branch}` |
| Deploy | {deploy_url} |
| Lane | `{lane}` |
| Verdict | **fail** (confidence {verdict_confidence}) |
| Pass rates | P0 **{p0_rate}** · P1 **{p1_rate}** · P2 {p2_rate} |
| Failing steps | {failed_count} of {total} |

### Failing steps

#### Step {n} · [{priority}] — {action_summary}
**Expected:** {expected}
**Observed:** {observed}
**Failed assertions:** `{assertion_kinds_joined}`

{before_screenshot_markdown}
*State entering the step*

{at_failure_screenshot_markdown}
*State at failure*

{if console_errors}
**Console errors during this step:**
```
{console_excerpts}
```
{endif}

{if network_errors}
**Network errors during this step:**
| Method | URL | Status |
|---|---|---|
{network_rows}
{endif}

---

### UI/UX observations (advisory, do not affect verdict)

{ui_observations_list}

---

🧠 Full run log: [Mem run log]({mem_url}) · 📺 [Cowork dashboard]({dashboard_url})
_Posted by `medtrics-qa-automation:qa-fail-reporter` v{plugin_version}._
```

### 6. PII redact + final check
Run the rendered body through `qa-guardrails.redact_pii`. If
`assert_evidence_clean` reports residual PII, refuse to post — log the failure
and notify the QA Lead via the Slack staging card.

### 7. Post the thread

```bash
python3 ../qa-gitlab-bridge/scripts/gitlab_open_thread.py \
  --iid <mr_iid> \
  --body-file <rendered_body.md>
# returns JSON: {ok, discussion_id, note_id, thread_url}
```

`gitlab_open_thread.py` refuses on closed/merged MRs by default — pass
`--no-refuse-on-closed` only with explicit justification. Capture the
returned `discussion_id` and `thread_url` for step 8.

### 8. Persist + audit
- Update the Mem run log with `gitlab_thread_id`, `gitlab_thread_url`,
  `attachments_uploaded`, `posted_at`.
- Audit one row `gitlab_thread_posted` with `step_count`, `attachment_count`,
  `ui_observation_count`.

## Outputs
- One GitLab discussion thread on the MR (writes-on only).
- Updated Mem run log with thread metadata.
- One audit row.

## Failure handling

| Failure | Behavior |
|---|---|
| GitLab unreachable on upload | Retry once after 5 s. On second failure, fall back to embedding the screenshot's local path as plain text and post the thread without images. Audit with `attachment_upload_failed`. |
| GitLab unreachable on thread post | Audit `gitlab_thread_post_failed`. The Slack staging card carries the human-actionable verdict; the team has a recovery path. |
| `assert_evidence_clean` blocks | Refuse to post. Surface to QA Lead via Slack. |
| `run_log.execution_trace` empty | Refuse — without trace data the thread would have no content. Audit `no_trace_to_report`. |

## What this skill does NOT do
- Does not author console-error fix advice. The thread surfaces evidence; the
  human author triages.
- Does not move the Optimus ticket. That's `qa-optimus-bridge.move_task`,
  called separately by `/manual-qa-execute`.
- Does not write to threads the bot has not opened. Replies to author comments
  are out of scope in v0.5; a future `qa-thread-replier` would handle that.

## Reads
- Mem `QA Run Logs` note for the ticket (caller fetched).
- Screenshot files in `outputs/qa/<ticket>/`.
- `qa-guardrails` for `gate_write` and `redact_pii`.

## Writes
- GitLab project uploads (`POST /uploads`).
- GitLab MR discussion thread (`POST /merge_requests/:iid/discussions`).
- Mem run log update (`update_note`).
- One audit row.
