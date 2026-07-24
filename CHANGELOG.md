# Changelog

All notable changes to `medtrics-qa-automation` are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses semantic versioning relative to the v0.3 baseline that shipped
as a scaffold.

## [0.12.2] — 2026-07-06

**Close the under-recorded-GIF gap for good.** v0.12.1 shipped a working
force-frame helper (real-click first, visible marker fallback) that produced
22-frame GIFs on M1-1317 and 17-frame GIFs on M1-1304 — but only when the
executor remembered to invoke it. M1-1309 shipped a **7-frame GIF from ~14
actions** because the executor took the SKILL.md's "read-only exemption"
during a source-verification sequence and never called the helper. The gap
was documentation: v0.12.1 said read-only JS was fine to skip.

v0.12.2 removes the exemption. The executor cannot bypass force-frame
emission for a non-visual action because there is now a wrapper helper that
fuses the action with a marker + screenshot in a single ordered plan, and
the SKILL.md flat-bans direct invocation of the six non-visual MCP tools
during a run.

### Added

- **`skills/qa-screenshot-capture/scripts/qa_action_with_marker.py`** — the
  v0.12.2 auto-wrap helper. Takes `--kind
  <javascript|read_page|read_console|read_network|get_page_text|find>` and
  returns a 3-action plan: [underlying MCP call, `force_frame` marker JS,
  `computer.screenshot`]. Reuses the v0.12.1 marker (4×4 px HSL-rotating
  visible div) via `force_frame_step.build_action_plan(kind="marker", ...)`
  so there is exactly one marker implementation. Zero deps, stdlib-only.

- **`skills/qa-screenshot-capture/scripts/verify_gif_completeness.py`** —
  post-run sanity check. Walks the GIF byte structure to count image
  descriptors (no Pillow), compares against `execution_trace.json` step
  count, and returns an `ok` / `under_recorded` / `skipped_no_trace`
  verdict. Warn-only by default; `--strict` makes it a hard failure.

- **`skills/qa-screenshot-capture/tests/test_qa_action_with_marker.py`** —
  24 tests covering the six wrapped kinds, plan-shape, validation, marker
  rotation, and the "all six banned tools are covered" property.

- **`skills/qa-screenshot-capture/tests/test_verify_gif_completeness.py`** —
  15 tests including a byte-precise synthetic GIF generator that exercises
  the frame counter and a regression check for the exact M1-1309 shape
  (7 frames / 14 expected → under_recorded).

### Changed

- **`skills/qa-ui-executor/SKILL.md`** — added a top-level `MANDATORY —
  v0.12.2 auto-wrap contract` section directly after "The core principle".
  Direct invocation of `javascript_tool` / `read_page` /
  `read_console_messages` / `read_network_requests` / `get_page_text` /
  `find` during a run is now a contract violation. The read-only exemption
  from v0.12.1's screenshot-capture SKILL is gone.

- **`skills/qa-screenshot-capture/SKILL.md`** — rewrote the "Force-frame
  policy" section for the auto-wrap contract. Includes a version-history
  block (v0.12.0 rejected, v0.12.1 partial, v0.12.2 closed), the banned-
  tool table, and a pointer to the post-run sanity check.

- **`commands/manual-qa-execute.md`** + **`commands/ui-qa-execute.md`** —
  the inline reminder in the executor step now leads with the v0.12.2
  auto-wrap contract instead of the v0.12.1 real-click preference (the
  real-click preference is preserved for visual actions).

### Verification

269/269 unit tests pass under the new files. Live verification lands with
the next multi-step QA1 run — the run's GIF frame count should track the
executor's action count within ~20% instead of collapsing to 7.

## [0.12.1] — 2026-07-06

**Fix the force-frame policy so it actually works.** v0.12.0 shipped a helper
that emitted a symmetric `scrollBy(0, +1)` / `scrollBy(0, -1)` "nudge" plus a
`body.dataset.qaFrame` write, on the assumption those would defeat the
recorder's adjacent-frame dedup. They did not — the scroll cancelled itself
out before the screenshot fired, and the dataset attribute is not rendered as
pixels so the dedup pass never noticed it. Verified live on M1-1317 (4-frame
GIF) and M1-1304 (7-frame GIF) after v0.12.0 was installed — the wrapper
produced zero observable improvement over baseline.

v0.12.1 replaces the mechanic with what actually works: real mouse actions
first, visible marker fallback second.

### Changed

- **`skills/qa-screenshot-capture/scripts/force_frame_step.py`** — rewritten
  as a three-mode helper. `--kind` is now required:
    - `click` (preferred): emits a `computer.left_click` at the given
      `--x` / `--y`. Chrome MCP paints an orange click-indicator overlay
      that is baked into the recorder frame, so the frame is always
      distinct from its neighbours. This is the reliable path — verified
      live on M1-1317 producing a **22-frame** GIF from 22 executor
      actions.
    - `scroll`: emits a `computer.scroll` at the given `--dx` / `--dy`.
      Real scroll delta reads as a distinct pixel diff.
    - `marker`: fallback for JS-only state changes (XHR interceptor
      injection, `localStorage` writes, page-level `eval()`). Injects a
      4×4 px absolute-positioned `<div>` with an HSL hue that rotates 36°
      per step, then takes a `computer.screenshot`. 16 pixels of unique
      colour is enough to defeat dedup; the marker is small enough to be
      invisible to the operator.
  `policy_version` bumped to `2`.
- **`skills/qa-screenshot-capture/SKILL.md`** — new "Force-frame policy
  (v0.12.1)" section spelling out the choice matrix (click for element-
  targeted UI, scroll for viewport, marker for JS-only) and explicitly
  documenting why v0.12.0 didn't work.
- **`commands/manual-qa-execute.md`** + **`commands/ui-qa-execute.md`** —
  updated the inline addendum to require the click-first pattern with
  `--kind click --x <px> --y <py>` and marker only as fallback.

### Added

- **`skills/qa-screenshot-capture/tests/test_force_frame_step.py`** — grew
  from 11 to 19 tests, covering all three modes:
    - `TestClickMode` — 3 tests
    - `TestScrollMode` — 2 tests
    - `TestMarkerMode` — 4 tests including a regression guard that the
      marker JS does NOT contain `scrollBy` (the v0.12.0 mistake)
    - `TestSharedValidation` — 4 tests
    - `TestCli` — 6 tests including invalid-`--kind` rejection and CLI
      `--raw` output for each mode.

### Verified

Full plugin test suite green after the change. Live proof point: M1-1317
re-run on 6933.medtrics.dev produced a 22-frame GIF (4.2 MB) with every
executor action captured as a distinct keyframe — see the follow-up thread
on !6933.

## [0.12.0] — 2026-07-06

Force-frame policy for the GIF recorder. Every state-changing
`javascript_tool` call inside a recording window now produces its own
recorder keyframe, so the operator's QA1 GIF reflects the full run instead
of only the ~7 keyframes Chrome MCP's `gif_creator` retains when actions
flow through `javascript_tool`.

### Added

- **`skills/qa-screenshot-capture/scripts/force_frame_step.py`** — helper
  that emits the deterministic action plan every executor path must run
  after a state-changing `javascript_tool` call:
    1. A `javascript_tool` "nudge" that scrolls the viewport 1 px down and
       back and writes `document.body.dataset.qaFrame = "<step_n>"`. Invisible
       to the operator; the pixel perturbation defeats the recorder's
       adjacent-frame dedup pass.
    2. A `computer` screenshot on the same tab, which the recorder now
       captures as a fresh keyframe.
  CLI: `python3 force_frame_step.py --step-n <n> --tab-id <tab> --step-label '<label>'`
  emits a JSON action plan on stdout; `--raw` prints just the nudge JS for
  callers that build their own action list.
- **`skills/qa-screenshot-capture/SKILL.md`** — new "Force-frame policy
  (v0.12.0+)" section spelling out when to apply the wrapper (state-changing
  calls: `.click()` on checkboxes/radios, form fills, scrolls, accordion
  toggles, localStorage writes, filter clears) and when to skip it
  (read-only DOM introspection). Documents the ~200 ms/step cost.
- **`skills/qa-screenshot-capture/tests/test_force_frame_step.py`** — 11
  unit tests covering the two-action ordering, the load-bearing JS pieces
  (`window.scrollBy(0, 1)` / `-1` / `body.dataset.qaFrame`), tab-id
  propagation, argument validation, and the JSON + `--raw` CLI modes.

### Changed

- **`commands/manual-qa-execute.md`** + **`commands/ui-qa-execute.md`** —
  each UI-lane step's screenshot-capture paragraph now requires the
  force-frame sequence around every state-changing `javascript_tool` call.
  Read-only JS calls are exempt.

### Why

QA1 operator feedback on M1-1304 (2026-07-05): the exported GIF held only
7 keyframes even after ~14 executor actions. Root cause: Chrome MCP's
`gif_creator` only ingests `computer` and `navigate` MCP calls and dedups
adjacent frames whose pixel diff is small — programmatic `.click()` calls
through `javascript_tool` never produced a frame, and follow-up screenshots
whose pixel content barely moved got collapsed. This release does not
modify the upstream MCP tool (it isn't ours); it changes how the plugin
drives the tool so each executor action produces a distinct, non-dedupable
frame.

### Tests

11 new tests in `test_force_frame_step.py` — full pass. Existing tests
unaffected.

## [0.11.1] — 2026-06-17

Plain-English summary section. Every QA1 verdict thread now opens with a
non-technical block QA2 reviewers can read at a glance — what was tested,
what was observed, what wasn't covered. Per-step technical evidence
(screenshots, console captures, network captures) follows.

### Added

- **`skills/qa-fail-reporter/scripts/build_verdict_thread.py`** new helpers:
  - `_clean_action()` strips checklist-prefix noise (`Step 3 —`, `1.`,
    `4)`, `-`) and truncates long action sentences.
  - `_format_test_summary_narrative()` — bullet list of what was tested:
    one line per step with priority + verdict emoji, capped at 15 steps
    with a `… N more` suffix.
  - `_format_outcomes_narrative()` — verdict-aware one-paragraph summary.
    For pass: "All N executable steps passed." For fail: anchors the
    first failing step. For partial: maps the `partial_cause` to a
    plain-English explanation via `PARTIAL_CAUSE_PLAIN_ENGLISH` (e.g.
    `missing_test_data` → "The dev tenant did not have the seeded test
    data the fix specifically targets…"). For blocked: surfaces the
    `blocked_reason` verbatim.
  - `_format_gaps_narrative()` — lists every `needs_human` / `skipped` /
    `not_run` / `blocked` step with its action and the `note` /
    `observed` field as the *why*. Notes are truncated at 140 chars.

- **`skills/qa-fail-reporter/templates/verdict-thread.md`** — new
  "Plain-English summary for QA2 review" section between the summary
  table and the per-step technical evidence. Three subsections:
  *What was tested*, *What we observed*, *What we did NOT cover*.

- **`skills/qa-fail-reporter/tests/test_verdict_narrative.py`** — 21 new
  tests covering `_clean_action`, the three narrative renderers, and
  the end-to-end render including the new section.

### Tests

- 21 new tests; 211/211 total tests pass across the plugin.

## [0.11.0] — 2026-06-17

Screenshots in every GitLab thread. The pipeline now captures per-step
visual evidence (animated GIF + console + network) and embeds it inline
in the verdict comment posted on the MR — for **every** verdict, not just
fails. QA2 reviewers can audit a QA1 run without re-driving the browser.

### Added

- **`skills/qa-screenshot-capture/`** — new skill that wraps Chrome MCP
  `gif_creator` around each step. Records the step's browser activity,
  exports the recording via `download=true` with a deterministic filename
  (`derive_filename.py`), polls the mounted `~/Downloads/` folder for the
  exported file (`poll_download.py`), moves it into the run's outputs
  directory, captures `console.json` and `network.json` siblings, uploads
  each artifact via `qa-gitlab-bridge/scripts/gitlab_upload_file.py`, and
  emits attachment records via `build_attachment_record.py` for the
  verdict-thread renderer to consume. `merge_attachments.py` aggregates
  per-step records into the index `build_verdict_thread.py` reads.

- **`skills/qa-fail-reporter/scripts/build_verdict_thread.py`** —
  successor to `build_fail_thread.py`. Renders the per-step evidence
  table inside collapsible `<details>` blocks so the thread stays
  scannable. Handles every verdict (pass / partial / fail / blocked) and
  embeds screenshots inline, console output as fenced code blocks (with
  size caps + attachment fallback), network captures as Markdown tables,
  and DOM snapshots as download links.

- **`skills/qa-fail-reporter/templates/verdict-thread.md`** — new
  template the verdict builder fills. Wider header (passed / failed /
  needs_human counts), partial-cause + lane-decision block, per-step
  evidence section, UI-observations section.

- **Live acceptance test** — proven end-to-end against MR !6888 on the
  M1-1206 deploy. A 228 KB GIF screenshot recorded via gif_creator,
  routed through the user's mounted `~/Downloads/`, uploaded via
  `gitlab_upload_file.py`, embedded in a thread comment posted via
  `gitlab_open_thread.py`. GitLab rendered the GIF inline.

### Changed

- **`commands/manual-qa-execute.md`** — step 6 (UI lane) now wraps every
  step in a gif_creator recording. Step 10a now posts the verdict thread
  for **every** verdict (was: fail/partial only) via
  `build_verdict_thread.py` instead of the legacy
  `build_fail_thread.py`. The fail-thread script is retained for
  backwards-compatible callers but no longer invoked by the default
  flow.

- **`commands/ui-qa-execute.md`** — same wiring as `/manual-qa-execute`:
  per-step screenshot capture + always-on verdict thread.

- **`commands/setup-medtrics-qa-automation.md`** — new step 5.5 calls
  `mcp__cowork__request_cowork_directory(path="~/Downloads")` and writes
  the resulting sandbox path into `config.screenshot.download_path`.
  Without the mount, screenshot capture short-circuits cleanly with
  `blocked: download_mount_unavailable` and the run continues without
  visuals.

- **`skills/qa-config/SKILL.md`** — schema bumped to `0.11`. New
  `screenshot` block with `enabled`, `download_path`, `per_step`,
  `include_console`, `include_network`, `include_dom_snapshot`,
  `poll_timeout_s`, `max_per_step`.

### Blocked-reason vocabulary additions

- `download_mount_unavailable` — `~/Downloads/` not mounted.
- `download_timeout` — exported GIF never appeared.
- `empty_export` — file is 0 bytes.
- `gitlab_upload_failed` — uploads endpoint returned non-200.
- `chrome_mcp_unavailable` — connection lost mid-step.

### Known constraints documented

- Native `computer({action:'screenshot', save_to_disk:true})` does **not**
  persist to a sandbox-readable path on the Cowork harness (explicit
  harness note: *"save_to_disk had no effect"*). The screenshot flow
  uses `gif_creator(download:true)` exclusively, routed through the
  user's `~/Downloads/` mount.
- `upload_image` cannot bridge a Chrome MCP `imageId` to a GitLab file
  input — the imageId namespace is firewalled cross-tool.
- The Cowork harness redacts long base64/hex/decimal-array strings
  returned through `javascript_tool`, so the html2canvas → base64 →
  sandbox path is blocked. Only the browser-download path is viable.

### Tests

- `skills/qa-screenshot-capture/tests/test_derive_filename.py` — 9 tests
  covering the deterministic filename generation.
- `skills/qa-screenshot-capture/tests/test_build_attachment_record.py` —
  6 tests covering successful + failed upload record composition + label
  → kind mapping.
- `skills/qa-fail-reporter/tests/test_build_verdict_thread.py` — 9 tests
  covering pass/partial/fail rendering, screenshot inlining, attachment
  fallback to link, truncation notice, empty-trace fallback.

24/24 new tests pass.

## [0.10.5] — 2026-06-08

Third (and definitive) pass at the Cowork validator failure. Root cause
**finally** isolated: six SKILL.md / commands files had embedded quote
pairs inside their YAML frontmatter `description:` values. The pattern
that broke it most clearly was `qa-guardrails.gate_write('gitlab', phase)`
in `qa-fail-reporter/SKILL.md` — strict YAML parsers see the inner
`'gitlab'` as a nested single-quoted scalar starting mid-value and fail
the parse. PyYAML's `safe_load` tolerates it; Cowork's strict validator
does not.

### Fixed
Stripped inner quote characters and other YAML-risky tokens from every
SKILL.md and command description:
- `qa-fail-reporter`: removed `'gitlab'` paired single quotes.
- `qa-cache`: removed `"Two-tier memory"` paired double quotes.
- `qa-poller`: removed `state="blocked"` paired double quotes.
- `qa-checklist-reader`, `qa-ui-executor`, `manual-qa-execute`,
  `qa1-poll`, `ui-qa-execute`: removed the `'## QA Checklist'` apostrophe
  pairs (5 files).
- `qa-ui-observer`: removed `<img>` angle brackets, `don't` apostrophe.
- `qa-checklist-reader`: removed `v0.3's` possessive.
- `regression-execute`: removed `module's` possessive and `<module>`
  brackets in the prose (kept in `argument-hint:` which is properly
  double-quoted).

### Why earlier fixes missed this
- v0.10.3 fixed the `(v0.9.3: ...)` colon-space token in qa-guardrails —
  necessary but not sufficient.
- v0.10.4 stripped `license` and `homepage` from `plugin.json` — also
  unnecessary in retrospect (working plugins like medtrics-code-review
  don't have those keys but Cowork doesn't reject them either; the
  reference-plugin comparison happened to mask the real issue).

### Rule for future skill/command authors
Inside YAML frontmatter `description:` values:
- **No paired quote characters** (`'X'` or `"X"`) anywhere in the string.
- **No colon-space patterns** (`X: Y`) inside the string.
- Possessive `'s` is tolerated by most parsers but better avoided.
- Angle brackets `<X>`, square brackets `[X]`, braces `{X}` should only
  appear when the whole value is double-quoted (as in `argument-hint:
  "[--flag <value>]"`).

The pre-package check in build flow now runs a strict YAML parse using
both PyYAML safe_load AND a custom regex sweep for the patterns above.

## [0.10.4] — 2026-06-08

Second pass at the Cowork plugin-validator failure. v0.10.3 fixed the
qa-guardrails YAML frontmatter but the install still rejected — the
plugin.json itself carried fields the schema doesn't accept.

### Fixed
- Removed `license: "Internal"` from `plugin.json` — non-SPDX values are
  rejected by the validator. Reference plugins (medtrics-code-review,
  pdf-viewer) carry no `license` field at all.
- Removed `homepage` from `plugin.json` — not part of the accepted
  schema. Reference plugins don't include it.
- Shortened the `description` from 631 → 460 chars and stripped the
  embedded `'## QA Checklist'` markdown-heading-looking token. Schema
  matches medtrics-code-review's pattern.

### Notes
The accepted `plugin.json` keys (observed from working plugins):
`name`, `version`, `description`, `author{name,email?}`, `keywords[]`.

## [0.10.3] — 2026-06-08

Bugfix release — v0.10.2 failed Cowork's plugin validator because
`qa-guardrails/SKILL.md`'s frontmatter `description` contained an
unquoted colon-space sequence (`(v0.9.3: persona allowlist removed —`)
which YAML reads as a key-value separator. The bad sequence was present
since v0.9.3 but newer Cowork validators enforce strict YAML.

### Fixed
- `qa-guardrails/SKILL.md` description — replaced `(v0.9.3: persona ...)`
  with `(v0.9.3 — persona ...)` so the description parses as a single
  scalar string instead of an ill-formed nested map.
- Added a frontmatter-validation pre-package check in the build flow.

### Lesson
- Any colon followed by space inside an unquoted YAML scalar terminates
  the scalar and starts a new mapping. Either avoid `: ` in
  descriptions, or quote the entire value with single quotes.

## [0.10.2] — 2026-06-08

Re-targets data-related partials to a new `needs_review` lane (intended),
with a transitional fallback to `on_hold` until Optimus releases the
status. Pure policy / docs / tests change — no execution path
architecture has moved.

### Changed
- `optimus_move_task.py` — data-related partial verdicts (`blocked_by_seed_data`,
  `no_seed_data`, `missing_test_data`, `environment_not_seeded`) now resolve to
  `needs_review_lane` (default `"needs_review"`). Non-data-related partials
  and `fail` still route to `needs_changes_lane`. **GAP-policy reshape.**
- New module-level constant `PENDING_RELEASE_LANES = {"needs_review": "on_hold"}`.
  When the resolved target lane is in this map, `build_payload` transparently
  substitutes the effective lane and emits a `pending_release` field in
  the payload recording the intended lane.
- `qa-optimus-bridge/SKILL.md` policy table updated with intended-vs-effective
  columns and the removal procedure for when Optimus ships the new lane.
- `qa-config/SKILL.md` config schema documents `needs_review_lane` alongside
  `on_hold_lane`.

### Added
- 2 new unit tests:
  - `test_partial_data_related_intends_needs_review_falls_back_on_hold` —
    proves the substitution path AND that `pending_release` surfaces correctly.
  - `test_pending_release_substitution_removable` — forward-compat: clearing
    the substitution map makes the same input route to `needs_review`
    natively, no other code changes needed.

### Operator notes
- M1-1195 Mem run-log updated (v3) to record the new intent. Effective
  Optimus position unchanged (`on_hold`).
- Once Optimus releases `needs_review` in `product_task_statuses`:
  1. Verify via `get_meta`.
  2. Remove the `needs_review → on_hold` entry from
     `PENDING_RELEASE_LANES`.
  3. (Optional) Backfill: re-move tickets currently at `on_hold` whose Mem
     note carries `pending_release.intended_lane = needs_review`.

### Test suite
- **166 passing** (was 165) — net +1.


## [0.10.1] — 2026-06-08

Reshapes the verdict→lane policy after the M1-1205 live exercise exposed
that `partial` doesn't have a single canonical destination — it depends
on whether the cause is data-related (environment) or non-data-related
(code defect / tooling). Also removes the invented `needs_review` lane
that didn't exist in Optimus's enum (live-discovered when M1-1195's move
was rejected with `invalid input value for enum product_task_status`).

### Changed
- **Verdict → lane policy** (`qa-optimus-bridge`):
  - `pass` → `qa2` *(unchanged)*
  - `fail` → `needs_changes` *(unchanged)*
  - `partial` + data-related cause (`blocked_by_seed_data`,
    `no_seed_data`, `missing_test_data`, `environment_not_seeded`) →
    `on_hold` **NEW** — env work needed, no code change
  - `partial` + non-data-related cause (or no cause) → `needs_changes`
    **NEW** — surface to dev so it gets eyes
  - `blocked` → no move *(unchanged)*
- `optimus_move_task.py` — `build_payload` and `resolve_target_lane` now
  take an optional `partial_cause`; `DATA_RELATED_PARTIAL_CAUSES` is a
  module-level frozenset; new CLI `--partial-cause` flag.
- `DEFAULT_LANES` — dropped invented `needs_review_lane`, added
  `on_hold_lane`. All defaults now map to valid enum values per
  `get_meta`.
- `qa-optimus-bridge/SKILL.md` + `qa-config/SKILL.md` updated.

### Migration
- **M1-1195** stays at `on_hold` (data-related partial — new policy
  destination unchanged).
- **M1-1205** moved retroactively `on_hold → needs_changes` — its
  partial had a non-data-related cause (form_input + submit didn't
  fire / Vue reactivity blocker).

### Test suite
- **165 passing** (was 162) — net +3 (replaced 5 stale tests, added 7).

## [0.10.0] — 2026-06-05

Phase 1 of the fix-roadmap. Closes 6 gaps that were either trivial-to-fix
quick wins or unblockers for later phases. Code shape is unchanged; the
inner step loop (Phase 2) is the next major change.

### Added
- `qa-config` schema v0.9 — new `deploy.login_path` field (default
  `/users/login`, the Medtrics canonical Devise path). Per-tenant override
  for installs that route auth elsewhere. **GAP-13**.
- `qa-config` blocked-reason vocabulary — added `login_form_not_found`
  for the case where neither the canonical login path nor the bare deploy
  root surfaces a password input. **GAP-13**.
- `Rule.disabled` field in `scenario_dispatcher`; rules with
  `disabled: true` in `scenario-matrix.yaml` are skipped during matching.
  **GAP-3**.
- 4 new tests: `test_open_thread.py`, `test_cache_defaults.py`,
  `test_matrix_disabled.py`, plus a CLI gate test in
  `test_build_dashboard.py`. Total suite: 162 tests (up from 148).

### Changed
- `qa-ui-executor/SKILL.md` Step 1 — login detection now uses the
  structural probe `find("password input")` instead of text-matching
  "Sign in". Visits `{deploy_url}/users/login` directly (the Medtrics
  canonical path) with a fallback to the bare root if that 404s.
  **GAP-13 + GAP-14**.
- `gitlab_open_thread.py` — `thread_url` now uses `mr.web_url` (namespace
  path) instead of the numeric `GITLAB_PROJECT_ID`. Old construction
  produced 404-ing links; the new one resolves to the discussion in the
  browser. Falls back to the legacy form with a logged warning if
  `mr.web_url` is missing. **GAP-19**.
- `gitlab_get_mr.py` default `--cache-ttl` is now `300` (was `0`).
  `gitlab_get_pipeline_status.py` default is `120`. `gitlab_download_upload.py`
  default is `600` and now uses the cache (uploads are immutable per
  secret/filename). `--no-cache` remains the bypass. **GAP-11**.
- `scenario-matrix.yaml` — `missing_required_field` and
  `role_permission_regression` flagged `disabled: true` until populated
  with real assertions. **GAP-3**.
- `build_dashboard_widget.py` — refuses to render with a null
  `MEM_RUN_LOGS_COLLECTION_ID`; exits with an actionable error pointing
  at `/setup-medtrics-qa-automation`. **GAP-2**.

### Removed
- Hardcoded Mem collection UUID `35339860-244c-4c54-825b-85d768ecc5df`
  from `qa-memory/SKILL.md`, `qa-queue/SKILL.md`, and
  `build_dashboard_widget.py` usage example. All readers now resolve the
  UUID from `config.mem.run_logs_collection_id`. **GAP-2**.

### Migration notes
- Existing `config.json` files: bump `schemaVersion` from `0.8` to `0.9`
  and add `"deploy": {"login_path": "/users/login"}`. Setup will write
  the new field on next run; manual edit is also safe.
- The Mem collection placeholder UUID is gone. On first run after upgrade,
  re-run `/setup-medtrics-qa-automation` if `config.mem.run_logs_collection_id`
  is null — the dashboard builder now hard-refuses to render without it.

## [0.9.5] — 2026-06-05

Docs + first-live-exercise release. Drove the plugin's M1-1190 audit
against MR !6865 deploy as `admin@medtricslab.com`. Posted the audit
summary to the MR as the first live exercise of `gitlab_open_thread.py`.
Found 9 immediate Chrome MCP gotchas + 8 structural cascading issues.

### Added (docs)
- `docs/engineering-gaps.md` GAP-6 expanded with the 2026-06-05 audit
  run — 9 verified-against-Chrome-MCP findings, each with plugin-impact
  callouts and concrete fixes.
- **8 new gaps** filed: GAP-12 through GAP-19 — the structural issues
  the 9 immediate findings exposed.

### The new gaps in one line each
- **GAP-12 (HIGH)** — `CapturedPage` is a snapshot when it needs to be a
  trace. Per-step capture must arm before action, not snapshot after.
- **GAP-13 (MEDIUM)** — Login URL is per-tenant, not per-app. Hardcoded
  path won't work across tenants.
- **GAP-14 (MEDIUM)** — "Session inherited" detection via text-matching
  "Sign in" is fragile. Use `find` for password input presence instead.
- **GAP-15 (MEDIUM)** — UI assertion vocabulary is missing the
  assertions the audit needed: `value_persisted_after_save`,
  `network_request_fired`, `network_response_status`, `console_warning_present`.
- **GAP-16 (MEDIUM)** — "Step succeeded silently" is not a representable
  verdict. Need `verification_inconclusive` blocked-reason.
- **GAP-17 (MEDIUM)** — Vue settle-time isn't modeled. Add a `settle`
  verb to the closed vocabulary.
- **GAP-18 (MEDIUM)** — `qa-ui-observer` checks depend on JS introspection
  that gets `[BLOCKED]`-redacted on Medtrics pages. Some checks must
  switch to `find`; some can't be deterministic at all.
- **GAP-19 (LOW)** — `gitlab_open_thread.py` returns a `thread_url` using
  the numeric project ID instead of the namespace path. Caught while
  posting the audit summary — link 404s.

### Verified live (first time for each)
- `gitlab_open_thread.py` — posted the audit summary to MR !6865 as
  discussion `1ea34d5e…`, note `3426507991`.
- Full login flow against a live Medtrics deploy with provided
  credentials — worked on first try.
- Deploy resolver against `6865.medtrics.dev` — `environment_lookup`
  strategy resolved correctly.
- Block-schedule navigation + edit-row datepicker interaction — UI
  surface is reachable.

### Cumulative gap status
- **19 open** (was 9), **1 closed** (GAP-1). The doubling reflects
  honesty post-audit, not regression — most of the new gaps were
  always present, just not visible until something ran live.

## [0.9.4] — 2026-06-04

Docs-only release. Full engineering-gap audit pass after v0.9.3 wrapped.

### Added (docs)
- `docs/engineering-gaps.md` expanded from 1 gap to 10 gaps, severity-
  tagged (HIGH / MEDIUM / LOW). Each entry includes a
  Verified-against-system or Verified-against-code section showing how
  the gap was confirmed.
- "Verified capabilities" table at the bottom of the gaps doc — the
  positive surface, what actually works against a real system today.
  Roughly 8 capabilities verified live, 8 spec-only, 2 partial.

### The new gaps
- **GAP-2 (HIGH)** — Mem `QA Run Logs` collection at the hardcoded UUID
  doesn't exist. Verified by calling `get_collection` against the user's
  Mem instance ("Requested resource was not found").
- **GAP-3 (MEDIUM)** — 2 of 3 rules in scenario-matrix.yaml have
  `scenarios: []`. Latent bug in the executor's aggregate path if they
  ever match.
- **GAP-4 (MEDIUM)** — `qa/regression/` directory doesn't exist; module
  checklists never authored; `/regression-execute` unrunnable today.
- **GAP-5 (MEDIUM)** — Slack writes are paper-only. No wrapper script,
  no test, no live post.
- **GAP-6 (HIGH)** — Chrome MCP step execution unproven end-to-end.
  scenario_dispatcher has unit tests against fixtures; no real ticket
  has been driven through the executor against a live deploy.
- **GAP-7 (HIGH)** — Optimus write path (`move_task`, `update_task`)
  never fired live. First production `pass → qa2` could 4xx.
- **GAP-8 (MEDIUM)** — Pointer-block HTML-comment markers untested
  through round-trip with a real Optimus description renderer.
- **GAP-9 (HIGH)** — Scheduled-task creation has never been done
  end-to-end. The "every 5 min auto-poll" promise is unproven.
- **GAP-10 (LOW)** — Phase transition (shadow → writes-on) has no
  automation or metric collection. The "<5% false positives" gate is
  README text only.
- **GAP-11 (LOW)** — `qa-cache` is opt-in via `--cache-ttl` but no
  default invocation passes it. The cache is enabled in code, disabled
  in practice.

### Why this matters
The plugin's mental model is sound. The audit isn't a list of bugs;
it's a list of "next bites of work to validate the model against
reality." High-severity gaps (2, 6, 7, 9) cluster around "we have never
actually run this against a real system." Medium-severity gaps
(3, 4, 5, 8) cluster around "we documented this path but didn't build
the wrapper." Low-severity gaps (10, 11) are observability + ergonomics.

### Tests
- 148/148 (unchanged — docs-only).

## [0.9.3] — 2026-06-04

Removed the 6-persona model. v0.4–v0.9.2 had carried a spec that assumed
six test users (`qa-coordinator@test.medtrics.invalid` etc.) existed on
every deploy, seeded by a Django `seed_qa_personas` management command
that was never built. v0.9.3 deletes the spec. Login is now declared
inside each checklist as a normal step.

### Removed
- `skills/qa-chrome-executor/templates/personas-schema.yaml` (the
  6-persona spec).
- `check_persona()` from `skills/qa-guardrails/scripts/guardrails.py`
  and its supporting constants (`READONLY_PERSONAS`, `PRIVILEGED_PERSONAS`,
  `ALL_PERSONAS`).
- 4 corresponding tests in `test_guardrails.py`
  (`test_readonly_persona_ok`, `test_admin_blocked_without_justification`,
  `test_admin_warns_when_required`, `test_unknown_persona_blocks`).
- The `QA_PERSONA_<ROLE>` env-var convention. No `qa-credentials` skill
  will be built; login is now the checklist's responsibility.

### Changed
- `skills/qa-ui-executor/SKILL.md` step 1 rewritten — no persona schema
  lookup. The executor lands on the deploy, observes auth state, then
  walks the checklist's own steps. If a login form is showing and the
  checklist has no login step, the run blocks. Login behavior is
  declarative, owned by the checklist author.
- `skills/qa-checklist-reader/SKILL.md` step 6 — `Tester role:` is now
  informational metadata (logged to audit + dashboard), not a required
  input. The reader no longer refuses checklists that lack it.
- `commands/manual-qa-execute.md`, `commands/ui-qa-execute.md`,
  `commands/regression-execute.md` — dropped the `check_persona()` call
  from each pre-execution guard. Timeouts still apply.
- `skills/qa-guardrails/SKILL.md` description + body — removed the
  persona allowlist section, updated the call-sequence diagram, noted
  that login is now declarative.
- `docs/engineering-gaps.md` — GAP-1 moved to "Closed by obsolescence"
  with a note that the gap was closed by removing the dependency, not
  by building the absent command.

### Why this is right
The persona spec was an architectural shortcut that broke as soon as it
hit reality. By design, checklists are the human-authored input — making
them ALSO declare who logs in (and where the password comes from, if
the deploy needs one) puts the decision next to the test logic that
needs it. The plugin reads, the human authors; that boundary applies to
login the same way it applies to "click this and expect that."

### Tests
- 148/148 (152 prior − 4 dropped persona tests).

## [0.9.2] — 2026-06-03

Deploy-URL resolver rewrite. v0.9.1's resolver looked at the first 20 project
deployments project-wide and matched by SHA prefix — for a project the size
of medtrics-legacy that almost never includes the MR you care about. Fixed
by switching to environment-name lookup, which is both more reliable and
faster.

### Added
- `skills/qa-gitlab-bridge/scripts/lib/gitlab_client.py` gains two helpers:
  - `get_environment_by_name(env, name, project_id=...)` — `GET
    /environments?name=<name>`. Returns the environment dict or None.
  - `list_deployments_for_environment(env, name, project_id=..., per_page=5)`
    — `GET /deployments?environment=<name>&order_by=created_at&sort=desc`.
    Returns the recent deployment list.
- `gitlab.deploy_environment_pattern` config knob (default
  `"{mr_iid}.medtrics.dev"`) — per-install override for non-Medtrics deploy
  conventions. Passed through `gitlab_get_mr.py --deploy-env-pattern`.
- New `deploy_strategy` field on the `gitlab_get_mr.py` output JSON: one of
  `environment_lookup` / `deployments_by_environment` / `sha_prefix_scan`
  / `environment_unavailable` / `no_match` / `no_inputs`. Lets the audit
  trail record which path resolved a given deploy.
- New `deploy_env_name` field showing the resolved environment name (e.g.
  `6865.medtrics.dev`) for visibility.
- `skills/qa-gitlab-bridge/tests/test_resolve_deploy.py` — 8 tests across
  the three strategies, the override pattern, and the edge cases (env
  stopped, empty inputs).

### Changed
- `_resolve_deploy()` in `gitlab_get_mr.py` rewritten. New signature:
  `_resolve_deploy(env, *, mr_iid, head_sha, project_id, deploy_env_pattern)`.
  Tries three strategies in order:
  - **A. Environment-name lookup.** Builds `{mr_iid}.medtrics.dev`,
    queries `/environments?name=`. If `state=available` with an
    `external_url`, use that — defaults status to `success`.
  - **B. Deployments filtered by environment-name.** Picks up status
    when (A) had no URL.
  - **C. Legacy SHA-prefix scan.** v0.5–v0.9.1 behavior, kept as last
    resort for projects without the convention.

### Verified live
- MR !6865 → `https://6865.medtrics.dev` via `environment_lookup` (was
  `(none)` in v0.9.1).
- MR !6834 → `https://6834.medtrics.dev` via `environment_lookup`.
- MR !6849 → `https://6849.medtrics.dev` via `environment_lookup`.
- MR !9999 (nonexistent) → cleanly errors.

### Added docs
- `docs/engineering-gaps.md` (NEW) — tracks plugin capabilities blocked on
  out-of-plugin eng work. First entry: **GAP-1** — the persona-seeding
  command (`seed_qa_personas`) doesn't exist in medtrics-legacy. Spelled
  out with verified-against-code findings.
- `qa-ui-executor/SKILL.md` step 1 rewritten to be honest about which
  login path actually works today (session-inherited only) and references
  GAP-1.

### Tests
- 152/152 (144 prior + 8 new for the resolver).

## [0.9.1] — 2026-06-03

Batch execution. `/manual-qa-execute --all` walks every queued ticket in
priority order with confirmation gates between each. Mirrors the
`medtrics-code-review` `/review-next --all` pattern.

### Added
- `--all` flag — discovers the queue (Optimus qa1 ∩ Mem-needs-verdict),
  orders by priority score, prints the plan, asks once for confirmation,
  then walks each ticket through the full single-ticket flow.
- `--no-confirm` flag — skips both the initial scope prompt and the
  between-ticket prompts. Intended for unattended polling-task use.
- `--dry-run` extended for batch mode — builds the queue + prints the plan
  without executing any tickets.
- Between-ticket confirmation prompts unless `--no-confirm`.
- Batch-level audit row `manual_qa_batch_completed` with counts +
  duration + which tickets got Optimus moves + GitLab threads.

### Changed
- `commands/manual-qa-execute.md` invocation summary at the top calls out
  the three modes (`pop next`, `specific ticket`, `--all`).
- Failure-handling table extended with the batch-mode stop conditions
  (Optimus down aborts; Mem down soft-warns; per-ticket blocked/fail
  continues; user `n` or Ctrl-C emits partial summary).

### What's deliberately NOT in batch mode
- No parallelism — Chrome MCP can't safely drive multiple sessions in one
  Cowork session.
- No batch-level Mem-dedup shortcut — `qa-checklist-reader` step 3a is
  authoritative per ticket.
- No auto-skip of blocked tickets — process them in case the blocker has
  resolved.

## [0.9.0] — 2026-06-03

GitLab MR thread attachments as a primary checklist source. Verified live
against MR !6865: the `fix-m1-1190-block-schedule-manage-blocks-form-manual-qa-checklist.txt`
attachment was found by branch slug, downloaded via the API path, and
parsed into 12 structured steps without any change to the downstream
executor.

### Added
- `skills/qa-gitlab-bridge/scripts/lib/gitlab_client.py` gains two helpers:
  - `extract_upload_refs(note_body)` — pure regex over a discussion note,
    returns `[{alt, url, secret, filename}]` for every `[name](/uploads/<hex>/<file>)`
    reference. Filters out malformed/short secrets defensively.
  - `get_project_upload(env, secret, filename, project_id=...)` — downloads
    the file via `GET /api/v4/projects/:id/uploads/<secret>/<filename>` with
    PRIVATE-TOKEN. The raw `gitlab.com/<namespace>/<repo>/uploads/...` URL
    is Cloudflare-gated (403 bot-check); the API path is the only viable
    download surface for automation.
- `skills/qa-gitlab-bridge/scripts/gitlab_find_mr_attachment.py` — walks
  the MR's discussions, gathers upload candidates, picks the best match by
  priority: `exact_branch_slug` → `suffix` glob → `ticket_id` substring.
  Tiebreaks on `created_at` (newest wins). Returns the secret + filename
  + note metadata as JSON.
- `skills/qa-gitlab-bridge/scripts/gitlab_download_upload.py` — thin CLI
  around `get_project_upload`. Writes to `--out` or stdout.
- `branch_to_filename_slug()` — pure helper, owns the convention
  `fix/m1-1190/block-schedule-foo` → `fix-m1-1190-block-schedule-foo`.
- `skills/qa-gitlab-bridge/tests/test_find_mr_attachment.py` — 14 tests
  over slug conversion, upload-ref extraction, match priority, tiebreak.

### Changed
- `skills/qa-checklist-reader/SKILL.md` gains **step 3.5**: try the GitLab
  MR attachment first using the branch-derived filename, fall through to
  step 4 (Optimus description) on miss. The Mem run-log now records
  `checklist.source ∈ {"gitlab_mr_attachment", "optimus_description"}`.
- `skills/qa-config/SKILL.md` schema (v0.9) gains
  `checklist.sources` (default `["gitlab_mr_attachment", "optimus_description"]`),
  `checklist.filename_pattern` (default `"{branch_slug}-manual-qa-checklist.txt"`),
  `checklist.suffix_glob` (default `"*-manual-qa-checklist.txt"`).

### Verified live
- MR !6865 on `medtrics/medtrics`: finder returned `match_kind=exact_branch_slug`,
  downloader pulled 8873 bytes, parser produced 12 P1 steps.

### Tests
- 144/144 (130 prior + 14 new).

## [0.8.0] — 2026-06-03

Post-verdict Optimus writes. The verdict→lane policy (`pass`→`qa2`,
`fail`→`needs_changes`, `partial`→`needs_review`, `blocked`→stay) was
prose in the v0.5 commands; v0.8 makes it scripted, validated, and
phase-gated.

### Added
- `skills/qa-optimus-bridge/scripts/optimus_move_task.py` — payload
  builder for `mcp__904fdec1-…__move_task`. Validates verdict→lane,
  applies phase gate, emits the args + audit_action. Four decision
  paths with distinct exit codes: `0=move`, `1=invalid`, `2=phase
  shadow`, `3=blocked verdict`.
- `skills/qa-optimus-bridge/scripts/optimus_build_verdict_comment.py` —
  composes the short markdown footer appended to the ticket description
  below the verdict pointer block. Three flavors (pass/fail/partial/
  blocked); embeds the GitLab thread URL when `--gitlab-thread-url` is
  passed.
- `skills/qa-optimus-bridge/tests/test_optimus_move_task.py` — 14 tests
  over the mapping, phase gate, blocked-stay, config overrides,
  validation.
- `skills/qa-optimus-bridge/tests/test_optimus_build_verdict_comment.py` —
  7 tests across the verdict variants.

### Changed
- `skills/qa-optimus-bridge/SKILL.md` rewritten as a documentation-+-
  scripts skill (was prose-only). Adds the verdict→lane policy table,
  the explicit write sequencing, and the reads/writes table.
- `skills/qa-config/SKILL.md` config schema gains
  `optimus.needs_changes_lane` (default `needs_changes`) and
  `optimus.needs_review_lane` (default `needs_review`). Schema bumped
  to 0.8.
- `commands/manual-qa-execute.md` step 10 rewritten with explicit
  sub-steps (a)–(e): **GitLab fail-thread first** (so MR has evidence
  before the ticket moves), then `optimus_move_task.py`, then
  `optimus_build_verdict_comment.py`, then the description update, then
  the actual move. Captures `thread_url` from (a) and threads it into
  (c).
- `commands/ui-qa-execute.md` step 8 updated to follow the same
  sequence.

### Tests
- 130/130 (109 prior + 21 new).

## [0.7.1] — 2026-06-03

Dashboard fixes from the live smoke test. The v0.7.0 template was a fragment
in a dark theme; the actual `mcp__cowork__create_artifact` tool wants a
**self-contained light-mode HTML document**, and Cowork's `callMcpTool`
returns the standard wrapped MCP response (`content[].text` + structured
form), not the unwrapped payload. Both issues fixed in-template so every
future `/setup` provisions the working version.

### Changed
- `skills/qa-queue/templates/dashboard.html` rewritten as a complete
  `<!doctype html>` light-mode document. The container is still
  transparent-friendly; the page bg is white to match Cowork's chrome.
- Added a `unwrapMcp()` helper at the top of the widget script that
  handles the three known Cowork bridge response shapes:
  - direct structured payload (`{tasks: [...]}`)
  - wrapped `{ content: [{type:"text", text:"<json>"}], structuredContent }`
  - plain JSON string
- Added `extractTasks()` and `indexRunLogs()` that walk known list keys
  (`tasks` / `results` / `items` / `data` for Optimus, `results` / `notes`
  for Mem) so unexpected response shapes don't silently zero out the lists.
- Added an in-widget **Refresh** button alongside the Cowork Reload — useful
  when iterating during setup, harmless in production.
- Lane label in the masthead now uses `{{OPTIMUS_QA1_LANE}}` instead of
  hardcoded "qa1", matching the rest of the placeholder set.

### Verified live
- Created the artifact in a real Cowork session via `mcp__cowork__create_artifact`.
- Optimus call against `(status=qa1, product=medtrics)` returned 8 tickets;
  all 8 rendered as cards under "Queued" with priority scores.
- Mem call against a placeholder UUID surfaced the expected soft-warn banner.
- Reviewer dropdown auto-populated with `chris`, `karen`, `sahil` from the
  live data.

### Tests
- 109/109. The existing `test_build_dashboard.py` placeholder tests passed
  unchanged — the placeholder names didn't move, only the template body did.

## [0.7.0] — 2026-06-03

Two-tier memory. The plugin now has a proper hot-tier filesystem cache
(`qa-cache`) alongside the existing warm-tier Mem archive (`qa-memory`).
Polling cycles no longer thrash GitLab on every tick; tickets whose MR
head_sha hasn't changed short-circuit before any execution.

### Added
- **`qa-cache` (new skill).** Stdlib JSON-file cache at
  `~/.cache/medtrics-qa-automation/`. Namespaced (`gitlab.get_mr`,
  `gitlab.pipeline`, `optimus.get_task`, `optimus.list_lane_tasks`,
  `mem.search_notes`). TTL-based; prune-on-read; per-user `0600` perms.
  Public API: `get / put / invalidate / cleanup_expired / stats`.
  Includes a tiny CLI (`python3 cache.py stats|cleanup|invalidate`).
- `skills/qa-cache/scripts/cache.py` (~245 LOC, pure stdlib).
- `skills/qa-cache/tests/test_cache.py` — 12 tests covering TTL expiry +
  prune, namespace isolation, single-key + whole-namespace invalidate,
  cleanup, stats reporting, zero-TTL rejection.

### Changed
- `skills/qa-gitlab-bridge/scripts/gitlab_get_mr.py` gained `--cache-ttl`
  + `--no-cache`. Default disabled; recommended 300s. Misses fall through
  to GitLab; only successful responses get memoized.
- `skills/qa-gitlab-bridge/scripts/gitlab_get_pipeline_status.py` gained
  the same flags. Recommended TTL 120s.
- `skills/qa-checklist-reader/SKILL.md` gained a new **step 3a — Mem
  dedup**: searches `QA Run Logs` for the ticket immediately after MR
  resolution and short-circuits when `(state ∈ {passed, failed} AND
  mr_head_sha == current.head_sha)`. `--force` overrides. Step 7 trimmed
  to "capture the note id for the upcoming update" since the dedup work
  now happens up front.
- `skills/qa-memory/SKILL.md` gained a **Two-tier memory** section
  documenting which data lives in which tier, how they cooperate on a
  polling tick, and the failure modes (Mem unreachable, cache corrupted).

### Skill count
14 (was 13). `qa-cache` is the new substrate skill.

## [0.6.2] — 2026-06-03

Explicit dependency manifest. An audit across every `.py` file in the plugin
turned up exactly two third-party imports — `PyYAML` (runtime, for the
scenario-matrix loader) and `pytest` (dev, for the test suite). Both are now
declared.

### Added
- `requirements.txt` — runtime dependencies. One line: `PyYAML>=6.0`. With
  inline docs explaining what it powers (the deterministic API-lane
  dispatcher) and how the plugin degrades when it's absent (UI lane still
  works, API lane refuses to load the matrix).
- `requirements-dev.txt` — extends the runtime file with `pytest>=7.0` for
  running the suite.

### Changed
- `commands/setup-medtrics-qa-automation.md` step 0 now checks `import yaml`
  before any other work; on failure prompts the user to run
  `pip install -r requirements.txt` and stops. The install is not auto-run
  — the user picks where the dep lands (system pip, virtualenv, etc.).
- `INSTALL.md` documents the install command before the CLI / Cowork
  install steps, mentions `--break-system-packages` fallback, and adds the
  two requirements files to the layout tree.

## [0.6.1] — 2026-06-03

Dashboard auto-provisioning. The Cowork Live Artifact dashboard
(`qa1-queue-dashboard`) is now part of the plugin and is created automatically
by setup. The audit pointed out that v0.6.0 still treated the dashboard as
documentation-only — this release closes that gap.

### Added
- `skills/qa-queue/templates/dashboard.html` — self-contained HTML widget
  (~370 lines). On every load, reads Optimus `list_lane_tasks` + Mem
  `list_notes` via `window.cowork.callMcpTool`, joins by ticket id, renders
  state-grouped cards with priority score + reviewer filter (persists in
  `localStorage["qa1-dashboard:reviewerFilter"]`). Handles three failure
  modes: no Cowork bridge / Optimus unreachable / Mem unreachable.
- `skills/qa-queue/scripts/build_dashboard_widget.py` — pure-Python composer
  that injects six `{{PLACEHOLDERS}}` (MCP tool names, Mem collection UUID,
  Optimus product + lane, dashboard title) into the template. Reads from
  `--config <config.json>` or accepts the values via flags. Idempotent —
  same input produces byte-identical output.
- `skills/qa-queue/tests/test_build_dashboard.py` — 8 tests over the
  builder: every placeholder substituted, values injected, missing-value
  + unknown-leftover errors, idempotence, config-file value derivation.
- `commands/qa-dashboard.md` — slash command that runs the builder and
  calls `mcp__cowork__create_artifact` (or `update_artifact` if the id
  already exists). Idempotent.

### Changed
- `commands/setup-medtrics-qa-automation.md` step 6 now invokes the
  dashboard provisioning automatically after writing config + scheduled
  tasks. Failure is non-fatal — setup tells the user they can re-run
  `/qa-dashboard` manually.
- `qa-queue/SKILL.md` documents the new implementation layout and the
  config → builder → artifact handoff.

### Skill count
Still 13. `qa-queue` got scripts + templates + tests; the skill itself
already existed.

## [0.6.0] — 2026-06-03

Dead-path removal. v0.4 demoted `qa-selector-extractor` to "optional pre-pass,
never required"; v0.5 added Chrome MCP `find()` as the runtime fallback. No
execution path called the extractor — it was 342 LOC of script + a SKILL.md
nobody invoked. This release removes it. The hand-authorable `selectors.json`
sidecar format (consumed by `qa-ui-executor` when present) stays — only the
auto-generator goes away.

### Removed
- `skills/qa-selector-extractor/` (entire directory: SKILL.md + scripts/extract_selectors.py + 105 lines of docs).
- All cross-references in `qa-ui-executor/SKILL.md`, `commands/ui-qa-execute.md`,
  the README, and INSTALL.md.

### Changed
- `qa-chrome-executor/templates/selectors-schema.json` description rewritten:
  the sidecar is now described as hand-authorable (or future-tool-emitted),
  with `generator` reframed as a free-form identifier. The example block uses
  `"generator": "hand-authored"`.
- `qa-ui-executor` `selectors` input documented as an optional hand-authored
  sidecar; runtime falls back to Chrome MCP `find()` when absent.

### Skill count
13 (was 14). Each remaining skill earns its keep against the three-question
audit (clear job · not covered elsewhere · depended on as-is).

## [0.5.3] — 2026-06-03

Test architecture refactor. Each skill is now a self-contained unit: SKILL.md +
scripts/ + templates/ (where applicable) + tests/. No contract changes; the
same 89 tests pass against the same scripts.

### Changed
- Tests moved from the top-level `tests/` directory into the owning skill:
  - `test_checklist_steps.py` + `test_extract_checklist_block.py` →
    `skills/qa-checklist-reader/tests/`
  - `test_guardrails.py` → `skills/qa-guardrails/tests/`
  - `test_ui_assertions.py` → `skills/qa-chrome-executor/tests/`
  - `test_ui_observations.py` → `skills/qa-ui-observer/tests/`
  - `test_build_fail_thread.py` → `skills/qa-fail-reporter/tests/`
  - `test_gitlab_client.py` → `skills/qa-gitlab-bridge/tests/`
- Fixtures moved with their tests:
  - `sample-ui-checklist.txt` → `skills/qa-checklist-reader/tests/fixtures/`
  - `mojibake-corpus.csv` → `skills/qa-chrome-executor/tests/fixtures/`
- `conftest.py` relocated from `tests/conftest.py` to the plugin root so
  pytest auto-discovers it for every skill's tests directory.
- `pytest.ini` `testpaths = skills` (was `tests`); `norecursedirs` extended
  to skip `scripts`, `templates`, `references`, `commands`, `fixtures`.

### Removed
- The top-level `tests/` directory.

## [0.5.2] — 2026-06-03

Polish-only release. No contract changes; tests still green at 89/89.

### Added
- `pytest.ini` at the plugin root with `testpaths=tests`, warning-to-error,
  and `--durations=5`.
- `tests/conftest.py` that walks `skills/*/scripts/` (and `lib/`) and
  prepends every directory to `sys.path` once at collection time.
- Top-level `CHANGELOG.md` (this file).

### Changed
- Each test file dropped its `sys.path.insert(...)` boilerplate now that
  `conftest.py` handles discovery. Imports are plain (`import guardrails as G`)
  with no `# noqa: E402` annotations.
- Test docstrings reference `pytest tests/test_*.py` consistently.

## [0.5.1] — 2026-06-03

Wires the GitLab write path into actual stdlib scripts, matching the pattern
`medtrics-code-review` and `medtrics-release-notes` use.

### Added
- `skills/qa-gitlab-bridge/scripts/lib/gitlab_client.py` (~520 LOC, vendored
  from `medtrics-code-review`, retargeted at
  `~/.cowork/medtrics-qa-automation/.env` and extended with two helpers):
  - `upload_file(env, file_path, project_id=...)` — multipart `POST /uploads`.
  - `get_pipeline_status(env, iid, project_id=...)` — green-pipeline gate.
- Per-action wrapper scripts under `skills/qa-gitlab-bridge/scripts/`:
  - `gitlab_whoami.py` — `GET /user`; pre-flight token check.
  - `gitlab_get_mr.py` — consolidated MR fetch (metadata + changes + pipeline + deploy).
  - `gitlab_get_pipeline_status.py` — green-pipeline gate, callable standalone.
  - `gitlab_upload_file.py` — screenshot uploader for qa-fail-reporter.
  - `gitlab_open_thread.py` — posts the fail-thread on the MR (refuses on
    closed/merged MRs by default).
- `tests/test_gitlab_client.py` — 15 tests covering `.env` discovery,
  content-type guessing, multipart body construction (mocked `urlopen`),
  `get_pipeline_status` paths, and project-ID URL encoding.

### Changed
- `qa-gitlab-bridge/SKILL.md` rewritten as a "thin transport" — each
  operation row in the reads/writes table now names the script that
  implements it.
- `qa-checklist-reader/resolve_mr_via_gitlab.md` retargeted at
  `gitlab_get_mr.py` + the `gitlab_client` library (was: MCP placeholders).
- `qa-fail-reporter/SKILL.md` calls `gitlab_upload_file.py` and
  `gitlab_open_thread.py` by path; falls back to a plain-text placeholder
  if `gitlab_upload_file.py` returns non-zero.
- `commands/setup-medtrics-qa-automation.md` gained a step 2.5 that writes
  the `.env` and runs `gitlab_whoami.py` as the pre-flight gate before any
  config persists.

## [0.5.0] — 2026-06-03

Closes the loop on failed runs. The agent drives the browser; the verdict
remains deterministic; the MR author now gets a structured GitLab thread
with evidence on every failure.

### Added
- **`qa-fail-reporter`** (new skill). Reads the Mem run log, picks the
  before/after screenshot pair for each failing step (cap 8 attachments,
  truncation notice when more failures exist), uploads via the GitLab
  bridge, renders a structured thread body — per-step
  action / expected / observed, captured console errors, captured network
  errors (4xx/5xx), embedded screenshots, advisory UI/UX observations —
  and posts it to the MR. Phase-gated; refuses in shadow.
- **`qa-ui-observer`** (new skill). Six deterministic UI/UX checks per
  step — `console_warning`, `deprecated_api_warning`, `asset_load_error`,
  `broken_image`, `missing_alt_text` (P0 only), `layout_overflow`.
  Advisory only; never affects verdict. Pure-Python, fully unit-tested.
- `templates/fail-thread.md` — the per-MR thread skeleton.
- `scripts/build_fail_thread.py` and `scripts/select_attachments.py` in
  `qa-fail-reporter/scripts/`.
- `scripts/check_observations.py` in `qa-ui-observer/scripts/`.
- `tests/test_build_fail_thread.py` (8 tests) and
  `tests/test_ui_observations.py` (21 tests).

### Changed
- `qa-ui-executor`: captures a screenshot on **every** step (was: fail +
  P0 milestones). Extended `CapturedPage.elements` with `tag`,
  `natural_width`, `alt`, `scroll_width`, `client_width`, `scroll_height`,
  `client_height`, `is_scrollable_declared`. Adds `network[]` capture.
  Calls `qa-ui-observer.observe()` after each `CapturedPage` and appends
  the returned observations into `ui_observations[]`.
- `commands/manual-qa-execute.md` and `commands/ui-qa-execute.md` invoke
  `qa-fail-reporter` on `verdict in {fail, partial}` when
  `phase == writes-on`. The reporter calls `qa-guardrails.gate_write`
  internally, so the commands don't pre-gate the GitLab path.
- `plugin.json` description: now advertises GitLab fail-threads + UI/UX
  observations + screenshot capture.

## [0.4.0] — 2026-06-02

Reverses the input boundary. The plugin no longer authors checklists from
the branch diff. Checklists are human-authored inside the Optimus ticket
description, under a stable `## QA Checklist` heading.

### Added
- **`qa-checklist-reader`** (replaces `qa-checklist-uploader`). Reads the
  `## QA Checklist` section from the Optimus task description, resolves
  the MR via GitLab, parses steps into `test_plan_steps[]`.
- `scripts/extract_checklist_block.py` — isolates the `## QA Checklist`
  section out of an Optimus description; strips any prior verdict pointer
  block; refuses on missing heading.
- `commands/` directory with five proper slash-command files:
  `setup-medtrics-qa-automation`, `qa1-poll`, `manual-qa-execute`,
  `ui-qa-execute`, `regression-execute`.
- `blocked_reason` vocabulary expanded with `checklist_missing` and
  `checklist_unparseable`.
- `tests/test_extract_checklist_block.py` (6 tests).

### Changed
- `plugin.json` to v0.4.0 with author email and a sharper description.
- `parse_checklist_steps.py` accepts `--stdin` so it can read piped
  content from `extract_checklist_block.py` without temp files.
- Pointer block on the Optimus description becomes a **verdict marker**
  (lane, verdict, pass rates, deploy URL) rather than a "checklist
  generated" announcement.

### Removed
- External dependency on `.agents/skills/sk-manual-qa`. Plugin is
  self-contained.
- The five STUB entry-point skills (`manual-qa-execute`, `ui-qa-execute`,
  `regression-execute`, `qa1-poll`, `setup-medtrics-qa-automation`). The
  commands now own the orchestration.
- The `qa-selector-extractor` is no longer required — demoted to an
  optional offline pre-pass; the UI executor falls back to Chrome MCP
  `find()` at runtime when no `selectors.json` is present.

## [0.3.0] — 2026-05-29 (inherited baseline)

The scaffold this project repaired. Documented for completeness.

### Carried forward (still in the plugin)
- `scenario_dispatcher.py` (~660 LOC) — deterministic API lane
  + closed verb / assertion vocabularies + UI assertion vocabulary.
- `guardrails.py` + 24 tests — destructive-action blocking,
  phase-gated writes, persona allowlist, PII/PHI redaction, timeouts.
- `scenario-matrix.yaml` — one live rule (`import_template_encoding`)
  + two stubs (`missing_required_field`, `role_permission_regression`).
- The deterministic core, the substrate (`qa-config`, `qa-memory`,
  `qa-audit`, `qa-queue`), and the bridges' contracts.

### Replaced in v0.4+
- `qa-checklist-uploader` (replaced by `qa-checklist-reader`).
- `.agents/skills/sk-manual-qa` dependency (dropped).
- Entry-point SKILL.md stubs (replaced by `commands/*.md`).
