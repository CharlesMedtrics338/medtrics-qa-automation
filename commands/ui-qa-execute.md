---
description: Force the agentic UI lane against one Medtrics MR. Skips the deterministic scenario-matrix lookup. Reads the QA Checklist from the Optimus ticket, drives Claude in Chrome through every step, and judges each by code via run_ui_assertions. Use when /manual-qa-execute would have routed to the API lane but you want a full UI walkthrough.
argument-hint: "<ticket-id> [--dry-run]"
---

# /ui-qa-execute

You are running the agentic UI lane for one Medtrics QA1 ticket — bypassing the deterministic scenario-matrix. Use this when:
- A ticket has both an API-matrix match AND a UI workflow you also want to verify.
- The matrix rule covers part of the ticket but the human checklist covers the rest.
- You're debugging the UI lane against a ticket the matrix would normally claim.

For routine runs, prefer `/manual-qa-execute` — it picks the right lane automatically.

## What to do

1. **Resolve config.** Invoke `qa-config`. Refuse if missing.

2. **Require an explicit ticket id.** This command does not pop from the queue — the user must pass `<ticket-id>` (e.g. `M1-1190`).

3. **Read the checklist + resolve the MR.** Invoke `qa-checklist-reader` with `ticket=<id>`. Same blocking behavior as `/manual-qa-execute`: if the reader returns `checklist_missing`, `checklist_unparseable`, or any other blocked reason, stop with the blocked reason. Do not improvise.

4. **Pre-execution timeout.** Read `qa-guardrails.HARD_TIMEOUT_S` (600s) and set the run deadline. (v0.9.3 — the persona allowlist gate was removed; login is declared inside the checklist itself.)

5. **Drive the UI lane.** Follow `skills/qa-ui-executor/SKILL.md` end-to-end. The procedure:
   - Land on `mr_resolution.deploy_url` and observe the auth state. If session-inherited, continue. If a login form is present, the checklist's own first step should be an explicit `Log in as <email>` instruction — the executor follows it like any other step. If the checklist has no login step AND the page shows a form, run blocks with `not_authenticated`. Stop.
   - **Per-step screenshot capture (v0.11.0+).** Around every step's action, wrap a `gif_creator(start_recording, tabId=<medtrics_tab>)` / `gif_creator(stop_recording, ...)` pair per `skills/qa-screenshot-capture/SKILL.md` (**v0.12.2 auto-wrap contract (MANDATORY):** every non-visual MCP action (`javascript_tool` / `read_page` / `read_console_messages` / `read_network_requests` / `get_page_text` / `find`) MUST go through `python3 skills/qa-screenshot-capture/scripts/qa_action_with_marker.py --kind <kind> --step-n <n> --tab-id <medtrics_tab> --step-label '<label>' [--script '<JS>']`. Direct invocation of those six tools during a run is a contract violation. For visual actions, PREFER a real `computer.left_click` at coordinates for every state change — Chrome MCP paints an orange click-indicator overlay that guarantees a distinct recorder frame. When you already have the element's centre coordinates (from `find` or `read_page`) run `python3 skills/qa-screenshot-capture/scripts/force_frame_step.py --kind click --step-n <n> --tab-id <medtrics_tab> --x <px> --y <py> --step-label '<short label>' ` and use its emitted `computer.left_click` verbatim. For scroll-driven state, use `--kind scroll --dx <dx> --dy <dy>`. Only when the state change genuinely cannot be driven through the mouse (e.g. injecting an XHR interceptor, writing localStorage) fall back to `--kind marker`, which paints a 4×4 px per-step-coloured marker div + takes a `computer.screenshot` — per the Force-frame policy section of qa-screenshot-capture/SKILL.md — so the GIF captures a keyframe for every action the executor drives, not only for `computer`/`navigate` calls). After stop, export with `download=true` and the filename from `derive_filename.py`, poll the mounted `~/Downloads/` for the file via `poll_download.py`, move it into `outputs/qa/<ticket>/<run_id>/step<n>/screenshot.gif`. The same step also captures per-step `console.json` and `network.json` siblings. Each artifact is uploaded via `qa-gitlab-bridge/scripts/gitlab_upload_file.py` and the result is piped to `build_attachment_record.py`; the records collect into `outputs/qa/<ticket>/<run_id>/.attachments/`. If `~/Downloads/` is not mounted, screenshot capture short-circuits cleanly — the run continues without screenshots and a `blocked: download_mount_unavailable` attachment surfaces in the dashboard.
   - For each step in `test_plan_steps[]`:
     - `qa-guardrails.screen_action` — refuse destructive actions in shadow; flag unrecognized verbs as `needs_human`.
     - Translate `step.action` into a Chrome MCP verb (`navigate`, `click`, `fill`, `upload`, `wait_for_text`, `screenshot`, `capture`). Prefer the optional hand-authored `selectors.json` sidecar if present (format: `qa-chrome-executor/templates/selectors-schema.json`); otherwise fall back to Chrome MCP `find()`.
     - Capture a `CapturedPage` (url, title, text, elements, console, downloads) — query only the selectors this step cares about.
     - Build the assertion list from the step's `expected` text via `templates/expected-to-assertion.md`. If no structured assertion can be derived, mark the step `needs_human` — **never auto-pass**.
     - Run `scenario_dispatcher.run_ui_assertions(page, assertions)`. Record verdict + evidence in `execution_trace[]`.

   If `--dry-run`, stop after parsing + lane-choice: print the action plan, do not drive Chrome and do not capture screenshots.

6. **Aggregate the verdict.** `scenario_dispatcher.aggregate(results, scanner_ok=True)`. The UI lane uses the same pass criteria as the API lane.

7. **Persist + report.** Update the Mem `QA Run Logs` note with `lane: "ui"`, the verdict, pass rates, full `execution_trace[]`, screenshot refs, and the `ui_observations[]` collected per-step by `qa-ui-observer`. Apply `qa-guardrails.redact_pii` to every free-form field before write. Post the Slack staging card.

8. **Phase-gated writes** (writes-on only) — follow `/manual-qa-execute` step 10 exactly. In sequence:
   - (a) **For every verdict** (pass / partial / fail / blocked), merge per-step attachments via `qa-screenshot-capture/scripts/merge_attachments.py --records-dir outputs/qa/<ticket>/<run_id>/.attachments/`, then render the body with `qa-fail-reporter/scripts/build_verdict_thread.py --run-log <run_log.json> --attachments <merged>.json --out /tmp/verdict-thread.md`, then post via `qa-gitlab-bridge/scripts/gitlab_open_thread.py`. Capture the `thread_url`.
   - (b) `python3 skills/qa-optimus-bridge/scripts/optimus_move_task.py --ticket <id> --verdict <v> --phase writes-on --config <path>` → read the JSON; exit codes 0=move / 2=shadow / 3=blocked.
   - (c) `python3 skills/qa-optimus-bridge/scripts/optimus_build_verdict_comment.py --run-log <run_log.json> --target-lane <lane> [--gitlab-thread-url <url>]` → splice under the pointer block, `find_pointer_block.py --upsert`, then `mcp__904fdec1-…__update_task(task=<ticket>, description=<updated>)`.
   - (d) Call `mcp__904fdec1-…__move_task(task=<ticket>, status=<target_lane>)` with the args from step 8b.
   - Verdict → lane: `pass`→`qa2`, `fail`→`needs_changes`, `partial`→`needs_review`, `blocked`→no move.

9. **Audit.** One row per step + one per run.

## Failure handling
Per `skills/qa-ui-executor/SKILL.md`:
- Element not found after `find` + one retry → step `fail`, `element_not_found`. Continue.
- Console error during a step → `console_clean` fails → step `fail`. Continue.
- Navigate lands on login → `blocked, not_authenticated`. Stop.
- Network blip → retry once; if still failing, step `fail`, `network_error`. Continue.
- Step verb unmappable or expectation not structurable → `needs_human`. Continue.
- Step requires switching identity mid-run → `needs_human, multi_session_required` (single-session limit in v0.9.x — Chrome MCP can't safely manage two logins in one session).
