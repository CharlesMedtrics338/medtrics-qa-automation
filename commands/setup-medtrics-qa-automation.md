---
description: First-run bootstrap for medtrics-qa-automation. Collects Optimus product slug, GitLab project ID, Slack staging channel, polling cadence, and the phase flag. Writes ~/.medtrics-qa-automation/config.json. Optionally creates the 5-minute polling task and the bi-weekly regression task.
argument-hint: "[--update]"
---

# /setup-medtrics-qa-automation

You are running the first-time bootstrap for the Medtrics QA automation plugin. This is the only command in this plugin that prompts the user — every other command reads the config you write here.

## What to do

0. **Verify Python dependencies.** Check `PyYAML` is importable:

   ```bash
   python3 -c "import yaml" 2>/dev/null
   ```

   If the import fails, prompt the user to install the runtime dependencies and stop until they confirm:

   ```bash
   pip install -r requirements.txt
   # or, on systems that reject pip without it:
   pip install -r requirements.txt --break-system-packages
   ```

   Without `PyYAML` the deterministic API lane (`scenario_dispatcher.py`) cannot load `qa/scenario-matrix.yaml`. The UI lane still works without it, but the user should know what they're opting out of. Do not auto-pip-install — let the user decide where the dependency lands.

1. **Detect existing config.** Check whether `~/.medtrics-qa-automation/config.json` already exists.
   - If yes and the user did not pass `--update`: ask whether to update or quit. If they choose update, proceed but pre-fill answers from the existing file.
   - If no: proceed with the bootstrap.

2. **Gather inputs via AskUserQuestion.** Ask in one batch:
   - Optimus product slug (default `medtrics`).
   - GitLab project ID (no default — required; numeric ID or `namespace/repo`).
   - GitLab personal access token (no default — required; scope: `api`).
   - GitLab base URL (default `https://gitlab.com`).
   - Slack staging channel (no default — required; this is where verdict cards land).
   - Slack regression channel (default `#dream-team`).
   - Polling interval in minutes (default `5`; `0` disables the scheduled poll).
   - Phase (`shadow` recommended for first install; `writes-on` only after Phase 1 exit criteria are met).
   - Whether to create the 5-minute polling scheduled task now.
   - Whether to create the bi-weekly regression scheduled task now.

2.5. **Write the GitLab `.env` file** at `~/.cowork/medtrics-qa-automation/.env` with mode `0600`:

    ```env
    GITLAB_TOKEN=<token from step 2>
    GITLAB_PROJECT_ID=<project id from step 2>
    GITLAB_URL=<base url from step 2>
    ```

    Then verify the token end-to-end with `python3 skills/qa-gitlab-bridge/scripts/gitlab_whoami.py`. If exit code is non-zero, surface the failure (display the script's stderr) and STOP before writing `config.json`. The user can edit `.env` and rerun setup. Authentication must work before polling can be scheduled.

3. **Write the config file.** Build the JSON object per `skills/qa-config/SKILL.md` schema v0.4 and write to `~/.medtrics-qa-automation/config.json`. Create the directory if it does not exist. Schema essentials:

   ```json
   {
     "schemaVersion": "0.9",
     "phase": "shadow",
     "optimus": { "product": "medtrics", "qa1_lane": "qa1", "qa2_lane": "qa2" },
     "gitlab": { "project_id": <int>, "fail_thread_template": "qa1-fail" },
     "deploy": { "login_path": "/users/login" },
     "slack":  { "staging_channel": "#...", "regression_channel": "#dream-team" },
     "polling": { "interval_minutes": 5 },
     "mem": { "run_logs_collection_id": null },
     "thresholds": { "p0_pass_required": 1.0, "p1_pass_required": 0.9, "review_floor_confidence": 0.6 },
     "flake_catalog": []
   }
   ```

   `deploy.login_path` defaults to Medtrics's Devise convention — override per
   tenant if an install routes auth elsewhere (GAP-13, v0.10.0).

4. **Provision the Mem `QA Run Logs` collection** if it does not exist. Call `mcp__34ae805e-…__list_collections` to look for it; if absent, call `create_collection(title="QA Run Logs")` and store the returned UUID into `config.mem.run_logs_collection_id`.

5. **Create scheduled tasks** (only if the user opted in):
   - **Polling.** `mcp__scheduled-tasks__create_scheduled_task` with cron `*/{interval} * * * *` running `/qa1-poll`. Skip if interval is `0`.
   - **Regression.** `mcp__scheduled-tasks__create_scheduled_task` with cron `0 9 * * 3` (every other Wednesday 9am ET — caller may need to disable on alternate weeks) running `/regression-execute`.

5.5. **Mount `~/Downloads/` for screenshot capture (v0.11.0+).** The qa-screenshot-capture skill drives Chrome MCP's `gif_creator` to record per-step browser activity, exports the recording as a GIF via the browser's native download mechanism, then picks the file up from the user's `~/Downloads/` folder. To make that file readable from the sandbox, the session needs a mount of `~/Downloads/`:

   ```text
   call mcp__cowork__request_cowork_directory(path="~/Downloads")
   ```

   Tell the user the prompt is one-time per session: approve once, screenshots flow into every QA verdict thread from that point on. If the user declines, qa-screenshot-capture short-circuits cleanly with `blocked: download_mount_unavailable` and QA still runs — the dashboard surfaces the gap so they can re-prompt later.

   After the mount succeeds, write into `config.json` under `screenshot`:

   ```json
   "screenshot": {
     "enabled": true,
     "download_path": "/sessions/<session>/mnt/Downloads",
     "per_step": true,
     "include_console": true,
     "include_network": true,
     "include_dom_snapshot": false
   }
   ```

   `download_path` is computed from the response of the directory-request tool. `include_dom_snapshot` defaults `false` because DOM snapshots are large and link-only (no inline render). Operators can enable per tenant.

6. **Provision the Cowork Live Artifact dashboard.** Invoke `/qa-dashboard` (or its underlying procedure):
   - Reads the just-written `config.json` (which now has `mem.run_logs_collection_id` from step 4).
   - Runs `skills/qa-queue/scripts/build_dashboard_widget.py --config ~/.medtrics-qa-automation/config.json` to compose the HTML widget with the user's collection UUID + product slug baked in.
   - Calls `mcp__cowork__create_artifact` with `id="qa1-queue-dashboard"`, the widget HTML, and the two MCP tools the widget needs to call (`config.mcp.optimus_list_lane_tasks_tool`, `config.mcp.mem_list_notes_tool`).
   - On idempotent re-runs, calls `mcp__cowork__update_artifact` instead.
   - Failure here is non-fatal — print the error and tell the user they can re-run `/qa-dashboard` manually. The rest of setup (config + scheduled tasks) is already persisted.

7. **Confirm and summarize.** Print:
   - The config file path.
   - The Mem collection UUID (`mem.run_logs_collection_id`).
   - Scheduled task IDs (if created).
   - The dashboard artifact id (`qa1-queue-dashboard`) and how to open it from Cowork's artifact panel.
   - A one-paragraph "what's next" pointing at `/qa1-poll` for a manual check and the `## QA Checklist` ticket-author convention so developers know where the input lives.

## Notes
- Safe to re-run. Each re-run only updates the fields the user touches.
- In Phase 1 (`shadow`), no Optimus or GitLab writes will fire even after setup completes. The phase flag is the only switch — flip it in the config file when ready.
