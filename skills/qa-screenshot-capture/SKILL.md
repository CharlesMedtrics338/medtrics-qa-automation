---
name: qa-screenshot-capture
description: Capture per-step visual evidence for medtrics-qa-automation. Drives Chrome MCP gif_creator to record a step's browser activity, polls the user's ~/Downloads mount for the exported GIF, moves it into the run's outputs folder, uploads it to GitLab uploads, and returns an attachment record the verdict-thread renderer consumes. Also writes the per-step console log and network capture as sibling files. Triggered automatically by qa-ui-executor for every step in writes-on mode and on demand for shadow-mode dry runs.
---

# qa-screenshot-capture

The visual-evidence layer for v0.11.0. Every QA step gets a screenshot in the
GitLab verdict thread. The skill orchestrates the four moving pieces — Chrome
MCP recording, browser download, sandbox file mount, GitLab uploads — into one
async-safe call.

## Prerequisite

The session must have `~/Downloads/` mounted. Setup-medtrics-qa-automation
ensures this via `mcp__cowork__request_cowork_directory(path="~/Downloads")`.
Without the mount, the skill writes a `blocked: download_mount_unavailable`
attachment record instead of failing the run.

## Inputs

| Input | Required | Source |
|---|---|---|
| `ticket` | Yes | Optimus identifier, used in filenames |
| `run_id` | Yes | ISO timestamp, used in output paths |
| `step_n` | Yes | Step number from the parsed checklist |
| `medtrics_tab_id` | Yes | The Chrome MCP tab driving the deploy |
| `outputs_dir` | Yes | Plugin's `outputs/qa/<ticket>/<run_id>/step{n}/` |
| `mount_downloads_path` | Yes | Sandbox path to the mounted `~/Downloads`, default `/sessions/.../mnt/Downloads` |
| `kind` | No | `"step"` (default) or `"baseline"` for the initial state capture |

## Outputs

An attachment record per artifact, matching the shape `build_verdict_thread.py`
consumes:

```json
{
  "step_n": 3,
  "label": "screenshot",
  "kind": "image",
  "path": "outputs/qa/M1-1206/2026-06-17T...Z/step3/screenshot.gif",
  "gitlab_url": "/uploads/abc.../screenshot.gif",
  "gitlab_markdown": "![M1-1206-step-3](/uploads/abc.../screenshot.gif)"
}
```

The skill always emits a `screenshot` attachment record. It additionally emits
`console` and `network` attachment records when the step has captured those.

## Procedure

### 1. Resolve the deterministic filename

The exported GIF must have a stable name so the poller can find it:

    qa-{ticket}-{run_id_short}-step-{step_n}.gif

where `run_id_short` is the last 12 chars of `run_id` after stripping
non-alphanumerics. Example: `qa-M1-1206-T031550Z-step-3.gif`.

### 2. Drive Chrome MCP

```
gif_creator(start_recording, tabId=<medtrics_tab_id>)
   ... executor runs the step action (click, type, scroll, etc.) ...
   ... settle delay 1500ms ...
gif_creator(stop_recording, tabId=<medtrics_tab_id>)
gif_creator(export, tabId=<medtrics_tab_id>,
            download=true, filename=<deterministic-name>,
            options={showWatermark: false, showProgressBar: false,
                     showActionLabels: false, showClickIndicators: false})
```

The download lands at
`<mount_downloads_path>/<deterministic-name>.gif` because the user's Chrome
default download folder is `~/Downloads` and that folder is mounted.

### 3. Poll for the file

`scripts/poll_download.py` polls `<mount_downloads_path>/<deterministic-name>.gif`
every 250ms for up to 15 seconds. Exit 0 when the file exists and is non-empty
and stable for at least 250ms (size unchanged across two consecutive polls).

If the file never appears: emit a `blocked: download_timeout` attachment and
return — the verdict thread will reference the gap without screenshots.

### 4. Move the file

```
mv <mount_downloads_path>/<deterministic-name>.gif \
   <outputs_dir>/screenshot.gif
```

Moving (not copying) ensures the user's `~/Downloads/` stays clean and avoids
filename collisions across runs.

### 5. Capture console and network as sibling files

```
read_console_messages(tabId=<medtrics_tab_id>, limit=200, pattern=".*", clear=false)
  → write to <outputs_dir>/console.json

read_network_requests(tabId=<medtrics_tab_id>, limit=200,
                      urlPattern=<deploy_origin>, clear=false)
  → write to <outputs_dir>/network.json
```

These run after the recording is exported so they capture the same time window
the GIF reflects.

### 6. Upload to GitLab uploads endpoint

For each artifact (`screenshot.gif`, `console.json`, `network.json`,
optionally `dom.html`), call `qa-gitlab-bridge/scripts/gitlab_upload_file.py`.
Collect the returned `markdown` field per upload.

### 7. Emit attachment records

Return a list of attachment records — one per uploaded artifact — joined into
the run-wide attachments index that `qa-fail-reporter/scripts/build_verdict_thread.py`
will format.

## Reads

- `mcp__Claude_in_Chrome__gif_creator` — start, stop, export with download=true
- `mcp__Claude_in_Chrome__read_console_messages`
- `mcp__Claude_in_Chrome__read_network_requests`
- `mcp__Claude_in_Chrome__javascript_tool` — optional, for the DOM-snapshot capture

## Writes

- `<mount_downloads_path>` — Chrome writes here; we move out
- `<outputs_dir>/{screenshot.gif, console.json, network.json[, dom.html]}`
- One `POST /api/v4/projects/:id/uploads` per artifact (via the gitlab-bridge script)
- One audit row per call

## Failure handling

| Failure | Behavior |
|---|---|
| `~/Downloads` not mounted | Emit `blocked: download_mount_unavailable`, audit-log, continue. Verdict thread still posts without the screenshot. |
| `gif_creator` rejects (browser disconnected) | Retry once after 2s. Second failure → `blocked: chrome_mcp_unavailable`. |
| Export times out at 15s | `blocked: download_timeout`. |
| Exported file is 0 bytes | `blocked: empty_export`. |
| GitLab upload returns non-200 | Save the file in outputs/ so it can be re-uploaded later; `blocked: gitlab_upload_failed`. |

In every failure case the run continues. The screenshot gap is documented in
the thread but the QA verdict is not affected.

## Force-frame policy (v0.12.2 — auto-wrap contract)

**Problem.** Chrome MCP `gif_creator` ingests only `computer` and `navigate`
calls and deduplicates adjacent frames whose pixel diff is small. Non-visual
MCP calls — `javascript_tool`, `read_page`, `read_console_messages`,
`read_network_requests`, `get_page_text`, `find` — perform real work but
paint no distinct pixels, so the recorder never sees them.

### Version history

**v0.12.0 (rejected).** Symmetric `scrollBy(0, +1)` then `scrollBy(0, -1)` +
`body.dataset.qaFrame` write. The ±1 px scroll cancelled itself out before
the screenshot fired, and `dataset` writes render no pixels. Did NOT work.

**v0.12.1 (partial).** Introduced `force_frame_step.py` with real-mouse-first
policy and a 4×4 px HSL-rotating visible marker fallback. **Verified working**
when called — produced 22-frame GIFs on M1-1317 and 17-frame GIFs on M1-1304.
BUT it was an opt-in helper: the executor could still forget to invoke it,
especially during source-verification sequences where "read-only JS
introspection" was granted an exception. M1-1309 produced a 7-frame GIF from
~14 actions because those actions took the read-only exception.

**v0.12.2 (this version) — auto-wrap contract, no exceptions.** The
executor cannot bypass force-frame emission during a run because the ONLY
way to invoke a non-visual MCP tool is through `qa_action_with_marker`, which
fuses the underlying call with a `force_frame` marker in a single ordered
plan. The read-only exception is REMOVED — every non-visual step emits a
frame, without exception.

### The banned-tool contract

During an active qa-ui-executor run, the executor MUST NOT directly invoke:

| Banned tool                     | Auto-wrap kind    |
|---------------------------------|-------------------|
| `javascript_tool`               | `javascript`      |
| `read_page`                     | `read_page`       |
| `read_console_messages`         | `read_console`    |
| `read_network_requests`         | `read_network`    |
| `get_page_text`                 | `get_page_text`   |
| `find`                          | `find`            |

Instead, the executor calls the auto-wrap helper:

```
python3 skills/qa-screenshot-capture/scripts/qa_action_with_marker.py \
  --kind <banned_tool_kind> --step-n <n> --tab-id <medtrics_tab_id> \
  --step-label "<short label>" [--script "<JS>"]
```

The helper emits an ordered action plan:

  1. The underlying MCP call the executor requested.
  2. A `force_frame` marker `javascript_tool` call (v0.12.1 marker — a 4×4
     px HSL-rotating visible div in the top-left corner).
  3. A `computer.screenshot` — captured as a distinct frame by the recorder
     because the marker's colour is unique per step.

The executor MUST run all three actions in order. Skipping any of them
renders the plan invalid.

### Visual actions — no wrap needed

Real mouse actions (`computer.left_click`, `computer.scroll`,
`computer.mouse_move`) and `navigate` calls paint distinct pixels the
recorder captures directly. Use them where the action is a genuine UI
interaction. The v0.12.1 `force_frame_step.py --kind click` / `--kind
scroll` helpers remain the preferred path when the executor already knows
the target element's centre coordinates.

### Choice matrix (v0.12.2)

| Executor context                                          | Use                                    |
|-----------------------------------------------------------|----------------------------------------|
| Element target known + coordinates available (typical UI) | `force_frame_step --kind click`        |
| Long-scroll to bring section into view                    | `force_frame_step --kind scroll`       |
| Any JS state inspection / DOM read / console / network read | `qa_action_with_marker --kind <kind>` |
| Injecting a page-level script or writing `localStorage`   | `qa_action_with_marker --kind javascript` |

### Post-run sanity check

`scripts/verify_gif_completeness.py` counts the frames in the exported GIF
and compares against the expected step count from `execution_trace.json`.
If `frames < expected * 0.80` the run is marked `under_recorded`, an audit
event is written, and the verdict thread carries a warning line the
operator can act on. Non-blocking by default (verdict still posts); the
`--strict` flag makes it a hard failure for CI-style runs.

**Cost.** Click / scroll: 1 MCP round-trip. Marker or auto-wrap: 3 round-
trips (underlying + marker JS + screenshot). Roughly +200 ms per non-
visual step. Worth it — the operator gets a complete GIF and the executor
loses the "forgot to call force_frame" gap.

**Tested by** `tests/test_force_frame_step.py` (19 tests, all three modes)
+ `tests/test_qa_action_with_marker.py` (v0.12.2 auto-wrap, six kinds)
+ `tests/test_verify_gif_completeness.py` (frame counter + threshold logic).

## Tested by

`tests/test_filename_derivation.py` and `tests/test_attachment_record_shape.py`
cover the pure-Python parts. `tests/test_force_frame_step.py` covers the
force-frame helper. The Chrome MCP integration is exercised via the live
acceptance test on M1-1206 documented in CHANGELOG v0.11.0.
