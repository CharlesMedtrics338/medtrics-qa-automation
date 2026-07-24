---
description: Create or refresh the qa1-queue-dashboard Cowork Live Artifact. Composes the widget_code from skills/qa-queue/templates/dashboard.html, injects the config-time values (Mem QA Run Logs collection UUID, Optimus product/lane, MCP tool names), and idempotently calls mcp__cowork__create_artifact (first run) or mcp__cowork__update_artifact (subsequent runs). After this command, the dashboard reads Optimus + Mem on every Reload click — no Mem-as-cache.
argument-hint: "[--force-recreate]"
---

# /qa-dashboard

You are provisioning (or refreshing) the Medtrics Automated QA1 dashboard
inside Cowork's Live Artifact system. The artifact ID is the stable
identifier `qa1-queue-dashboard`. Running this command again is safe — it
updates the existing artifact in place rather than creating a duplicate.

## What to do

1. **Resolve config.** Invoke `qa-config`. If `~/.medtrics-qa-automation/config.json` is missing, tell the user to run `/setup-medtrics-qa-automation` first and stop. Read `config.mem.run_logs_collection_id` — if `null`, tell the user setup didn't provision the Mem collection (rerun `/setup`) and stop.

2. **Compose the widget HTML.** Run the builder against the user's config:

   ```bash
   python3 skills/qa-queue/scripts/build_dashboard_widget.py \
     --config ~/.medtrics-qa-automation/config.json \
     --out /tmp/qa1-queue-dashboard.html
   ```

   On non-zero exit, surface the script's stderr to the user and stop. Typical failures: missing `mem.run_logs_collection_id`, template not found.

3. **Check for an existing artifact.** Call `mcp__cowork__list_artifacts` and look for one whose id is `qa1-queue-dashboard`.

4. **Create or update.**
   - If absent (or `--force-recreate` was passed and the user confirmed): `mcp__cowork__create_artifact` with `id="qa1-queue-dashboard"`, `title="Automated QA1 — Queue"`, and the widget HTML as `widget_code`. Declare the required MCP tools so the artifact's `callMcpTool` calls are allowed:
     ```
     mcp_tools = [config.mcp.optimus_list_lane_tasks_tool (default mcp__904fdec1-…__list_lane_tasks),
                  config.mcp.mem_list_notes_tool (default mcp__34ae805e-…__list_notes)]
     ```
   - If present: `mcp__cowork__update_artifact` with the same `id` and the new `widget_code`. Title and tool declarations can be re-asserted to keep them in sync.

5. **Confirm.** Print the artifact id, a deep link to open it (if Cowork returns one), and a one-line note: "Re-runs on every Reload — Optimus + Mem are the source of truth; nothing is cached."

6. **Audit.** One row, action `dashboard_provisioned` (create) or `dashboard_refreshed` (update). Includes `widget_byte_length` and the resolved Mem collection UUID.

## Idempotency
- The artifact id `qa1-queue-dashboard` is the stable handle. Running this command twice in a row replaces the widget code in place.
- The widget itself is stateless — every load re-fetches Optimus + Mem. There's no migration step when the HTML changes.

## Failure handling
| Failure | Behavior |
|---|---|
| Missing config | Refuse and direct the user to `/setup-medtrics-qa-automation`. |
| Missing Mem collection UUID in config | Refuse — the dashboard can't render without it. Direct to setup. |
| `mcp__cowork__create_artifact` rejected | Audit and surface. If the failure is "id already exists", retry as `update_artifact`. |
| `mcp__cowork__update_artifact` rejected | Audit and surface. Do not auto-fall-back to create. |

## Notes
- The widget HTML lives at `skills/qa-queue/templates/dashboard.html`. Edits there flow through automatically the next time `/qa-dashboard` runs.
- The Mem collection UUID and Optimus product slug are baked into the widget at create-artifact time (string substitution), so a config change requires re-running this command.
- The reviewer filter on the rendered page persists per-user, per-machine in `localStorage["qa1-dashboard:reviewerFilter"]`.
