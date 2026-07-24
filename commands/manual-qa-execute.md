---
description: Execute Automated QA1 against one or all queued Medtrics MRs. Reads the human-authored QA Checklist from the MR thread attachment or the Optimus ticket description, attempts the deterministic API lane, falls back to the agentic UI lane, judges every step by code, and writes the verdict to Mem and Slack. Optimus and GitLab writes are phase-gated. Pass --all to walk every queued ticket in priority order.
argument-hint: "[ticket-id] [--all] [--no-confirm] [--dry-run] [--lane=api|ui]"
---

# /manual-qa-execute

You are running Medtrics QA1 verification. The contract is **execute, don't author** — the checklist is human-authored (on the MR thread or the Optimus ticket); this command runs it.

Three invocation modes:

- `/manual-qa-execute` → pop the next queued ticket and run it.
- `/manual-qa-execute M1-1190` → run that specific ticket.
- `/manual-qa-execute --all` → walk **every** queued ticket in priority order. See "Batch mode" at the bottom.

## What to do

1. **Resolve config.** Invoke `qa-config`. If missing, tell the user to run `/setup-medtrics-qa-automation` and stop.

2. **Pick a ticket.**
   - If the user passed a ticket id (e.g. `M1-1190`), use it.
   - Otherwise, read the Mem `QA Run Logs` collection for the next ticket whose `state` is `queued`, ordered by `optimus_snapshot.statusChangedAt` ascending (oldest first). If none are queued, print a friendly "queue empty" message and stop.

3. **Read the checklist + resolve the MR.** Invoke `qa-checklist-reader` with `ticket=<id>`. The reader returns the `MrResolution`, the parsed `test_plan_steps[]`, the informational `tester_role` line (if the author included one), and the Mem note id. If the reader returns a blocked state (`checklist_missing`, `checklist_unparseable`, `no_open_mr_found`, `deploy_not_ready`, `gitlab_error`), stop and print the blocked reason — the dashboard will surface it. **Do not improvise a checklist.**

4. **Pre-execution timeout.** Read `qa-guardrails.HARD_TIMEOUT_S` (600s) and set the run deadline. (v0.9.3 — the persona allowlist gate was removed; login behavior is owned by the checklist.)

5. **Choose the lane.**
   - If the user passed `--lane=api` or `--lane=ui`, honor it.
   - Otherwise, ask the deterministic dispatcher:
     ```bash
     python3 skills/qa-chrome-executor/scripts/scenario_dispatcher.py \
       --matrix qa/scenario-matrix.yaml \
       --ticket-title "<mr_resolution.title>" \
       --ticket-type "bug" \
       --files-changed "<comma-join mr_resolution.changed_files>" \
       --plan-only
     ```
     If `matched=true` and `scanner_ok=true` → API lane. If `matched=false` → UI lane. If `matched=true` and `scanner_ok=false` → write Mem state `unreliable`, attach `negative_test_failures`, stop.

6. **Run the lane.**
   - **API lane.** Follow `skills/qa-chrome-executor/SKILL.md`. Drives Chrome MCP via the closed verb vocabulary (`fetch`, `navigate`, `upload_and_verify`), captures responses, runs structured assertions per `scenario_dispatcher.run_assertions()`.
   - **UI lane.** Follow `skills/qa-ui-executor/SKILL.md`. The executor lands on the deploy, observes auth state (session-inherited or not), then walks every step in `test_plan_steps[]` — including any explicit `Log in as <email>` step the author included. For each step: screens the action via `qa-guardrails.screen_action`, **starts `gif_creator(start_recording, tabId=<medtrics_tab>)` per the qa-screenshot-capture contract (**v0.12.2 auto-wrap contract (MANDATORY):** every non-visual MCP action (`javascript_tool` / `read_page` / `read_console_messages` / `read_network_requests` / `get_page_text` / `find`) MUST go through `python3 skills/qa-screenshot-capture/scripts/qa_action_with_marker.py --kind <kind> --step-n <n> --tab-id <medtrics_tab> --step-label '<label>' [--script '<JS>']`, which fuses the underlying call with a force-frame marker + screenshot in one ordered 3-action plan. Direct invocation of those six tools during a run is a contract violation. This closes the "read-only exemption" that let M1-1309 ship a 7-frame GIF from 14 actions. For visual actions, PREFER a real `computer.left_click` at coordinates for every state change — Chrome MCP paints an orange click-indicator overlay that guarantees a distinct recorder frame. When you already have the element's centre coordinates (from `find` or `read_page`) run `python3 skills/qa-screenshot-capture/scripts/force_frame_step.py --kind click --step-n <n> --tab-id <medtrics_tab> --x <px> --y <py> --step-label '<short label>' ` and use its emitted `computer.left_click` verbatim. For scroll-driven state, use `--kind scroll --dx <dx> --dy <dy>`. Only when the state change genuinely cannot be driven through the mouse (e.g. injecting an XHR interceptor, writing localStorage) fall back to `--kind marker`, which paints a 4×4 px per-step-coloured marker div + takes a `computer.screenshot`  — per the Force-frame policy section of qa-screenshot-capture/SKILL.md — so the GIF captures a keyframe for every action the executor drives, not only for `computer`/`navigate` calls)**, executes the verb, captures a `CapturedPage`, runs `run_ui_assertions()`, **stops the recording, exports with `download=true` and the deterministic filename from `qa-screenshot-capture/scripts/derive_filename.py`, polls the mounted `~/Downloads/` for the file via `poll_download.py`, moves it into `outputs/qa/<ticket>/<run_id>/step<n>/screenshot.gif`, captures the per-step console + network as sibling files, and uploads each via `qa-gitlab-bridge/scripts/gitlab_upload_file.py`**. Each upload result is piped to `qa-screenshot-capture/scripts/build_attachment_record.py` and written to `outputs/qa/<ticket>/<run_id>/.attachments/`. Steps whose expected text cannot be reduced to a structured assertion are marked `needs_human` — never auto-passed.

   If `--dry-run`, stop here: print the lane choice and the action plan; do not drive Chrome and do not capture screenshots.

   **Screenshot-capture gate.** If `~/Downloads/` is not mounted on this session, qa-screenshot-capture short-circuits to a `blocked: download_mount_unavailable` attachment record and the run continues without screenshots. The dashboard surfaces the gap so the operator can re-run `/setup-medtrics-qa-automation` to re-prompt the mount.

7. **Aggregate the verdict.** Call `scenario_dispatcher.aggregate(results, scanner_ok=True)`. Verdict is `pass` iff 100% P0 + ≥90% P1. Any `needs_human` step → `partial`.

8. **Persist evidence.**
   - Update the Mem note via `qa-checklist-reader`'s stored note id with the final `verdict`, `lane`, `p0_pass_rate`, `p1_pass_rate`, `failed_items[]`, `execution_trace[]`, `verdict_confidence`, and the v0.5 `ui_observations[]` array collected by `qa-ui-observer`.
   - All free-form fields pass through `qa-guardrails.redact_pii` first; final check via `assert_evidence_clean`.

9. **Post the Slack staging card** to `config.slack.staging_channel`. Required in both phases. Card includes ticket id, MR link, verdict, pass rates, ui-observation count, and link to the Cowork dashboard.

10. **Phase-gated writes** (only if `config.phase == "writes-on"`). Order matters — evidence on the MR before the ticket moves:

    **(a) GitLab verdict-thread first (every verdict — pass, partial, fail, blocked).** Merge the per-step attachment records collected in step 6 via `qa-screenshot-capture/scripts/merge_attachments.py --records-dir outputs/qa/<ticket>/<run_id>/.attachments/`. Then render the body:
    ```bash
    python3 skills/qa-fail-reporter/scripts/build_verdict_thread.py \
      --run-log <mem_run_log.json> \
      --attachments <merged-attachments-index.json> \
      --plugin-version 0.11.0 \
      --out /tmp/verdict-thread.md
    ```
    Post via `qa-gitlab-bridge/scripts/gitlab_open_thread.py --iid <mr_iid> --body-file /tmp/verdict-thread.md`. **Capture the returned `thread_url`** — step 10c uses it.

    For pass verdicts the verdict thread shows the per-step screenshots + console + network captures so QA2 reviewers can audit the run without re-driving the browser. For fail / partial verdicts the same template surfaces the failing steps' evidence more prominently. The legacy `build_fail_thread.py` is retained for backwards-compatible callers but not invoked by the default flow.

    **(b) Compute the Optimus move payload.**
    ```bash
    python3 skills/qa-optimus-bridge/scripts/optimus_move_task.py \
      --ticket <id> --verdict <pass|fail|partial|blocked> --phase writes-on \
      --config ~/.medtrics-qa-automation/config.json
    ```
    Read the resulting JSON. Exit code says what to do:
    - `0` → `args` is ready to pass to `mcp__904fdec1-…__move_task`.
    - `2` → phase shadow; skip the rest of step 10. Audit `would_have_moved_to_<lane>`.
    - `3` → verdict is `blocked`; no move. Stop here.

    **(c) Update the Optimus description** with the verdict pointer block + the verdict footer:
    ```bash
    python3 skills/qa-optimus-bridge/scripts/optimus_build_verdict_comment.py \
      --run-log <mem_run_log.json> \
      --target-lane <target_lane from step 10b> \
      [--gitlab-thread-url <thread_url from step 10a>]
    ```
    Splice the footer below the verdict pointer block (composed by `qa-checklist-reader/scripts/build_pointer_block.py`), then `find_pointer_block.py --upsert` into the existing description, then `mcp__904fdec1-…__update_task(task=<ticket>, description=<updated>)`.

    **(d) Move the ticket** by invoking the MCP tool with the args from step 10b:
    ```text
    call mcp__904fdec1-f755-42c5-a32e-a3a9eb8ba1da__move_task(
        task=<ticket>, status=<target_lane>)
    ```
    Verdict → lane policy (from `qa-optimus-bridge/SKILL.md`):
    - `pass` → `qa2` (advance to next QA stage)
    - `fail` → `needs_changes` (back to dev with the fail-thread)
    - `partial` → `needs_review` (human QA Lead reviews the `needs_human` steps)
    - `blocked` → no move (stays in qa1; dashboard surfaces the blocker)

    **(e) Audit each write.** `gitlab_thread_posted` (if applicable), `optimus_description_updated`, and the `audit_action` field from step 10b (e.g. `optimus_moved_to_qa2`).

11. **Audit.** One row per externally-visible action (queue read, checklist read, lane decision, each step, verdict, Slack post, Optimus move, GitLab thread). The audit log is the durable record.

## Failure handling
- Chrome MCP timeout → mark run `blocked`, reason `timeout`, surface to QA Lead.
- Deploy URL unreachable → wait 60s, retry once, then `blocked`.
- All-pass verdict with confidence below `config.thresholds.review_floor_confidence` → flag `needs_review` even in Phase 2+.
- Single-step failure → continue the rest of the run (we want a complete failure picture). Stop only on `blocked` / `not_authenticated` / `timeout`.

## Batch mode (v0.9.1+) — `--all`

Walk every queued ticket in priority order. Mirrors `medtrics-code-review`'s `/review-next --all`.

### What to do

1. **Build the queue.** Invoke the same discovery `qa-poller` uses:

   ```
   mcp__904fdec1-…__list_lane_tasks(status=config.optimus.qa1_lane,
                                    product=config.optimus.product,
                                    limit=200)
   ```

   For each returned ticket, look it up in the Mem `QA Run Logs` collection (one `list_notes` call, cached for the run). A ticket is **queued** if any of:
   - It has no Mem run-log note yet.
   - Its existing note state is `blocked` (we want to retry blocked tickets — the blocker may have resolved).
   - Its existing note has a verdict (`passed` / `failed`) but the recorded `mr_head_sha` does NOT match the MR's current head (force-push → re-test).

   Skip tickets whose existing note is `passed`/`failed` against the current head_sha — Mem dedup already covers them.

2. **Order by priority score.** Use the same formula the dashboard does: `PRIORITY_WEIGHT + TYPE_WEIGHT + (highRisk ? 30 : 0) + age_in_lane_bonus + due_date_bonus + (pinned ? 10000 : 0)`. Highest score first. The pinned tickets float to the top so they're never skipped.

3. **Print the plan.** Before any work fires, print a numbered list to confirm scope:

   ```
   Found N queued tickets. Will process in priority order:
     [1] M1-1185  P0 critical · score 198 · "CSV import: mojibake…"
     [2] M1-1078  critical_feature high-risk · score 175 · "Schedules > Clinical…"
     [3] M1-1190  P0 high-risk · score 189 · "Block schedule date…"
     …
   ```

4. **Confirmation gate.** Unless `--no-confirm` is set, ask:

   > Process all N tickets in sequence? [y/N]

   Bail on N. On y, proceed.

5. **Per-ticket loop.** For each ticket in order, invoke the existing single-ticket flow (steps 1–11 above) with `ticket_id` set explicitly. Capture:
   - Final verdict (`pass` / `fail` / `partial` / `blocked`)
   - Duration in seconds
   - Whether GitLab thread + Optimus move actually fired (phase-gated)
   - Any `blocked_reason`

   Print one progress line per ticket as it completes:

   ```
   [3/8] M1-1190 — pass · qa2 · 142s · GitLab thread n/a
   [4/8] M1-1185 — fail · needs_changes · 88s · GitLab thread posted
   [5/8] M1-1162 — blocked: checklist_missing · 6s
   [6/8] M1-1154 — partial · needs_review · 167s · 2 steps needs_human
   ```

6. **Between-ticket confirmation** (unless `--no-confirm`). After each ticket completes, ask:

   > Continue to next ticket ([k/N] `<id>`)? [Y/n]

   `n` stops the batch early; partial-completion summary still fires in step 7.

7. **Final summary.** When the batch ends (either all tickets done, or the user said `n`), print:

   ```
   ──────────────────────────
   Batch summary
     Processed: 6 of 8
     Pass:      3   → qa2
     Fail:      1   → needs_changes (GitLab threads on: M1-1185)
     Partial:   1   → needs_review (M1-1154)
     Blocked:   1   (M1-1162: checklist_missing)
     Total time: 9m 14s
   ──────────────────────────
   ```

   Also append one batch-level audit row: `manual_qa_batch_completed` with counts + duration.

### Stop conditions (abort the batch immediately)

| Condition | Reason |
|---|---|
| Config missing | The plugin can't make any informed decision. |
| Optimus unreachable mid-batch | Can't read the next ticket. Wait + retry once; if still down, abort. |
| Mem unreachable mid-batch | Soft warning — continue (the per-ticket flow already tolerates this). Do NOT abort. |
| User answers `n` at any between-ticket prompt | Graceful stop; emit the summary. |
| `Ctrl-C` (interrupt) | Same as user stopping — emit the partial summary. |
| Per-ticket `blocked` (any reason) | **Do NOT abort the batch.** Continue to the next ticket. The blocked reason goes in the summary. |
| Per-ticket logical fail | Continue. That's the whole point — gather verdicts across the queue. |

### Flags

| Flag | Effect |
|---|---|
| `--all` | Walk every queued ticket. Required for batch mode. |
| `--no-confirm` | Skip the initial scope-confirmation prompt AND between-ticket prompts. Intended for the scheduled polling task (`/qa1-poll` followed by `/manual-qa-execute --all --no-confirm` in unattended mode). |
| `--dry-run` | Build the queue + print the plan; do NOT execute any tickets. Cheap way to preview what `--all` would do. |
| `--lane=api|ui` | Force one lane for every ticket in the batch. Default is per-ticket auto-detect via the scenario matrix. |

### What NOT to do in batch mode

- **Don't parallelize.** Each ticket gets the full single-ticket flow before the next starts. Chrome MCP can't safely drive multiple browser sessions concurrently in a single Cowork session.
- **Don't pre-cache verdicts.** Mem dedup runs per-ticket inside `qa-checklist-reader/SKILL.md` step 3a — that's the authority. Don't short-circuit at the batch layer.
- **Don't auto-skip blocked tickets.** Process them — the blocker might have resolved since the last run.
