---
name: qa-config
description: Per-user configuration discovery, schema, and bootstrap for medtrics-qa-automation. Every other skill reads from here for the Optimus product slug, Slack staging channel, GitLab project ID, polling cadence, phase flag (shadow / writes-on), classification thresholds, and the known-flake catalog. Triggered automatically by every command; never invoked directly. Companion to /setup-medtrics-qa-automation.
---

# qa-config

## What this skill owns
- Discovery of `~/.medtrics-qa-automation/config.json` for the current user.
- The JSON schema and defaults for every field below.
- A bootstrap path that creates the file with safe defaults on first use.

## Config schema (v0.9 — v0.11.0)
```json
{
  "schemaVersion": "0.11",
  "phase": "shadow",                       // shadow | writes-on
  "optimus": {
    "product": "medtrics",
    "qa1_lane": "qa1",
    "qa2_lane": "qa2",                     // pass    → here
    "needs_changes_lane": "needs_changes", // fail / partial(non-data) → here  (v0.10.1)
    "needs_review_lane": "needs_review",   // partial(data-related)    → INTENDED (v0.10.2)
    "on_hold_lane": "on_hold"              // transitional fallback for needs_review
  },
  "gitlab": {
    "project_id": null,                // filled by /setup
    "fail_thread_template": "qa1-fail",// looked up in templates/
    "deploy_environment_pattern": "{mr_iid}.medtrics.dev"  // v0.9.2 — convention name
  },
  "deploy": {
    "login_path": "/users/login"       // v0.10.0 (GAP-13) — Medtrics canonical
                                       // (Devise convention). Per-tenant override
                                       // when an install routes auth elsewhere.
  },
  "slack": {
    "staging_channel": null,           // e.g. "#qa-automation-staging"
    "regression_channel": "#dream-team"
  },
  "polling": {
    "interval_minutes": 5
  },
  "checklist": {
    "sources": ["gitlab_mr_attachment", "optimus_description"],   // try in order
    "filename_pattern": "{branch_slug}-manual-qa-checklist.txt",  // v0.9+
    "suffix_glob": "*-manual-qa-checklist.txt"                    // fallback match
  },
  "mem": {
    "run_logs_collection_id": null     // provisioned by /setup on first run
  },
  "thresholds": {
    "p0_pass_required": 1.0,           // 100%
    "p1_pass_required": 0.9,           // 90%
    "review_floor_confidence": 0.6
  },
  "screenshot": {                      // v0.11.0 — per-step visual evidence
    "enabled": true,
    "download_path": "/sessions/<session>/mnt/Downloads",  // set by /setup
    "per_step": true,                  // capture on every step (not just fails)
    "include_console": true,
    "include_network": true,
    "include_dom_snapshot": false,     // DOM snapshots are large + link-only
    "poll_timeout_s": 15,              // wait for browser download to finalize
    "max_per_step": 1                  // cap screenshots per step (avoids dupes)
  },
  "flake_catalog": []                  // [{ "checklist_item_id": "...", "until": "2026-06-15" }]
}
```

### `screenshot` block (v0.11.0)

The qa-screenshot-capture skill drives `gif_creator` per step and routes the
exported recording through the user's `~/Downloads/` folder into the run's
outputs directory, then uploads to GitLab uploads.

| Field | Meaning | Default |
|---|---|---|
| `enabled` | Master switch. `false` skips capture and renders text-only threads. | `true` |
| `download_path` | Sandbox path to the mounted `~/Downloads/`. Set by `/setup-medtrics-qa-automation` after `mcp__cowork__request_cowork_directory(~/Downloads)` succeeds. | `null` until setup |
| `per_step` | Capture on every step. When `false`, capture only on failing steps (legacy v0.5 behavior). | `true` |
| `include_console` | Write per-step `console.json` and upload it as an attachment. | `true` |
| `include_network` | Write per-step `network.json` and upload it as an attachment. | `true` |
| `include_dom_snapshot` | Capture `document.documentElement.outerHTML` per step and upload as `.html`. Renders as a download link, not inline. | `false` |
| `poll_timeout_s` | Max seconds to wait for the GIF to finish writing to the mount. | `15` |
| `max_per_step` | Hard cap on screenshots per step to keep the thread compact. | `1` |

## Blocked-reason vocabulary

Every blocked Mem note carries a `blocked_reason` from this fixed vocabulary
so the dashboard and audit log can group them:

| Reason | Source |
|---|---|
| `checklist_missing`       | No `## QA Checklist` heading in the Optimus description. **New in v0.4** — replaces the v0.3 auto-generation fallback. |
| `checklist_unparseable`   | Heading present but no recognizable numbered steps. |
| `no_candidates`           | No MR URL, branch slug, or ticket-id reference in the description. |
| `no_open_mr_found`        | Candidates existed but no open MR matched. |
| `deploy_not_ready`        | MR found but pipeline is running/skipped/failed. |
| `gitlab_error`            | Transient GitLab failure. |
| `optimus_write_failed`    | Optimus update rejected after retry. |
| `not_authenticated`       | Chrome MCP could not log in. |
| `login_form_not_found`    | Neither the canonical login path (`/users/login`) nor the bare deploy root surfaced a password input or an authenticated dashboard. **v0.10.0** — operator triage required. |
| `timeout`                 | `HARD_TIMEOUT_S` or `STEP_TIMEOUT_S` breached. |
| `multi_session_required`  | Step required switching identities; out of scope in v0.4. |
| `download_mount_unavailable` | qa-screenshot-capture detected no `~/Downloads/` mount on the session. Re-run `/setup-medtrics-qa-automation`. **New in v0.11.0.** |
| `download_timeout`        | qa-screenshot-capture exported the GIF but the file never appeared in the mounted `~/Downloads/` within `screenshot.poll_timeout_s`. **New in v0.11.0.** |
| `empty_export`            | qa-screenshot-capture found the exported GIF but its size was zero bytes. **New in v0.11.0.** |
| `gitlab_upload_failed`    | qa-screenshot-capture wrote the artifact to disk but the GitLab uploads endpoint returned a non-200. **New in v0.11.0.** |
| `chrome_mcp_unavailable`  | qa-screenshot-capture lost the Chrome MCP connection mid-step. **New in v0.11.0.** |


## Reads
- Called at the top of every command.
- Called by `qa-queue`, `qa-chrome-executor`, `qa-optimus-bridge`, `qa-gitlab-bridge`.

## Writes
- Only `/setup-medtrics-qa-automation` writes the initial file.
- The weekly review flow may append to `flake_catalog`.

## Failure mode
If the config is missing, surface `/setup-medtrics-qa-automation` to the user and refuse to proceed. Never auto-create with placeholder values that could cause writes against the wrong Optimus product.
