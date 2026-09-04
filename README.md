# medtrics-qa-automation

Automated QA1 and bi-weekly regression for Medtrics (Claude Code / Cowork & Cursor plugin). Implements the QA Process
v2.2 contract.

## Plugin & Marketplace Manifests

The plugin is structured for dual distribution across Claude Code / Cowork and Cursor:

- **Claude Plugin:**
  - `.claude-plugin/plugin.json` — plugin metadata and capability paths.
  - `.claude-plugin/marketplace.json` — marketplace catalog entry for Claude marketplace publishing.
- **Cursor Plugin:**
  - `.cursor-plugin/plugin.json` & `.cursor-plugin/manifest.json` — Cursor plugin manifest mapping skills and slash commands.
  - `.cursor-plugin/marketplace.json` — Cursor marketplace catalog entry.
  - `manifest.json` — root manifest for direct Cursor plugin packaging and upload tooling.

## Status — v0.10.2

**Verdict→lane policy reshaped.** The M1-1195 / M1-1205 live exercises
showed that `partial` doesn't have one canonical destination — it splits
on whether the cause is data-related (env work) or non-data-related
(code/tooling). New mapping:

- `pass` → `qa2`
- `fail` → `needs_changes`
- `partial` + data-related cause → **`needs_review`** *(intended; falls back
  to `on_hold` until Optimus releases the lane — see
  `PENDING_RELEASE_LANES`)*
- `partial` + non-data-related cause → `needs_changes`
- `blocked` → no move

Removed the invented `needs_review_lane` mapping that 4xx'd against
Optimus's actual enum (live-discovered during M1-1195). 166 tests pass.
Five tickets QA'd live during this iteration with all verdicts persisted
to the Mem `QA Run Logs` collection.

## Status — v0.10.0

**Phase 1 of the fix-roadmap.** Closes 6 gaps in one release. Mem
collection UUID is no longer hardcoded — readers resolve it from
`config.mem.run_logs_collection_id` and the dashboard builder hard-
refuses to render without it (GAP-2). The two empty matrix rules are
flagged `disabled: true` so they no longer fire phantom passes (GAP-3).
Read caches default on for `gitlab_get_mr` (300s), `gitlab_get_pipeline_status`
(120s), and `gitlab_download_upload` (600s) — `--no-cache` remains the
bypass (GAP-11). `qa-ui-executor` Step 1 visits `/users/login` (the
Medtrics canonical Devise path) and detects auth state structurally via
`find("password input")`, not via text-matching "Sign in" (GAP-13/14).
`config.deploy.login_path` lets a tenant override the path. The
`gitlab_open_thread.py` script now constructs URLs from `mr.web_url`,
not the numeric project ID (GAP-19). Test suite: 162 (up from 148).
Gap count: **13 open**, 7 closed.

## Status — v0.9.5

**First live audit run + cascading-findings analysis.** Drove M1-1190 against
MR !6865 deploy as admin. Posted the audit summary to the MR via
`gitlab_open_thread.py` (first live exercise — worked). Logged 9 immediate
Chrome MCP gotchas (GAP-6 expanded) and 8 structural cascading issues
(GAP-12 through GAP-19). Gap count: **19 open**, 1 closed. The doubling
is honesty post-audit, not regression — most of the new gaps were always
there, just invisible until something ran live. The plugin's inner loop
(per-step `arm → action → drain → snapshot → judge`) is where v0.10's work
should concentrate. Read `docs/engineering-gaps.md` for the full picture.

## Status — v0.9.4

**Engineering-gap audit.** Docs-only release. `docs/engineering-gaps.md`
now lists ten gaps with severity tags and verified-against-system
findings. Headline takeaways:
- The Mem `QA Run Logs` collection at the hardcoded UUID doesn't exist
  yet (GAP-2, HIGH).
- Chrome MCP execution, Optimus writes, and scheduled-task creation
  have never run end-to-end against a real system (GAP-6/7/9, HIGH).
- 2 of 3 scenario-matrix rules are empty stubs (GAP-3, MEDIUM).
- Slack posts, regression module checklists, and the pointer-block
  round-trip are all spec-only (GAP-4/5/8, MEDIUM).
- Phase metrics and cache-by-default are operational drift (GAP-10/11,
  LOW).

The companion "Verified capabilities" table inventories what works
today (~8 capabilities verified live: GitLab read path, MR thread
attachment fetch, checklist parse, Cowork artifact, the `unwrapMcp`
shape handling, deploy resolver, etc.). Read `docs/engineering-gaps.md`
before treating any spec-only capability as ready.

## Status — v0.9.3

**6-persona model removed.** The plugin used to assume a fixed set of test
users (`qa-coordinator@test.medtrics.invalid` etc.) existed on every deploy,
seeded by a Django management command that was never built. Deleted the
schema, the `check_persona` guardrail, the `QA_PERSONA_*` env convention,
and the 4 supporting tests. Login is now declared by the checklist itself
(typically a `Log in as <email>` first step). The same human who writes
"click Save and expect X" also picks who's logged in to do it. Tests
148/148. Engineering gap GAP-1 closed by obsolescence — the dependency
was removed, not satisfied.

## Status — v0.9.2

**Deploy-URL resolver actually works now.** v0.9.1 returned `(none)` for
real MRs because it only scanned the first 20 project deployments by SHA
prefix — for a project with thousands of deployments, those almost never
included the MR you care about. v0.9.2 switches to environment-name
lookup via `{mr_iid}.medtrics.dev` against GitLab's `/environments` API.
Verified live: MR !6865, !6834, !6849 all resolve correctly via
`deploy_strategy: environment_lookup`. Also: `docs/engineering-gaps.md`
now tracks plugin capabilities blocked on out-of-plugin eng work (first
entry: persona seeding via the not-yet-built `seed_qa_personas`).
Tests 152/152.

## Status — v0.9.1

**Batch execution.** `/manual-qa-execute --all` walks every queued ticket
in priority order, with confirmation gates between each ticket. Use
`--no-confirm` for unattended scheduled-task runs. The batch is sequential
on purpose (Chrome MCP can't drive parallel sessions safely in one Cowork
session). Per-ticket failures don't abort the batch; only environmental
issues (Optimus unreachable, config missing) do. Tests still 144/144.

## Status — v0.9.0

**GitLab MR thread attachments are now a primary checklist source.** The
checklist can be uploaded as a `.txt` attachment on any MR discussion
comment — the plugin finds it by branch-derived filename
(`{branch-as-hyphens}-manual-qa-checklist.txt`), downloads via the
`/api/v4/projects/:id/uploads/...` endpoint (the raw `/uploads/` URL is
Cloudflare-blocked), and feeds it to the same parser. Falls through to
the `## QA Checklist` Optimus description on miss. Verified live against
MR !6865 — finder + downloader + parser pipeline produced 12 structured
steps. Tests now 144/144.

## Status — v0.8.0

**Post-verdict Optimus writes are now scripted.** `qa-optimus-bridge` gained
two action scripts mirroring the `qa-gitlab-bridge` pattern (payload-builders
since Optimus is reached via MCP, not HTTP). The verdict → lane policy is
now testable code: `pass`→`qa2`, `fail`→`needs_changes`, `partial`→`needs_review`,
`blocked`→no move. The execute commands sequence the writes explicitly:
GitLab fail-thread posts first (evidence on the MR before the ticket moves),
then the Optimus description update with the verdict footer, then the
`move_task` call. Tests now 130/130.

## Status — v0.7.1

**Dashboard template ships the version proven live.** The v0.7.0 template
had two bugs the smoke test surfaced: it was a fragment (`mcp__cowork__create_artifact`
expects a full HTML document), and it assumed `window.cowork.callMcpTool`
returned the unwrapped payload (it returns the standard MCP wrapper with
`content[].text` + `structuredContent`). Both fixed in-place. The template
is now a `<!doctype html>` light-mode document with `unwrapMcp()`,
`extractTasks()`, and `indexRunLogs()` handling every known response shape.
Verified live: 8 real qa1 tickets render correctly. Tests 109/109.

## Status — v0.7.0

**Two-tier memory.** Hot tier `qa-cache` (new skill) — local JSON-file cache
at `~/.cache/medtrics-qa-automation/` with TTL semantics, namespaced for
GitLab/Optimus/Mem reads. Warm tier `qa-memory` — Mem `QA Run Logs`
collection, persistent verdict archive. `qa-checklist-reader` step 3a now
does Mem dedup by `(ticket, mr_head_sha)` before any expensive work, so
polling cycles short-circuit when nothing has changed. `gitlab_get_mr.py`
and `gitlab_get_pipeline_status.py` gained `--cache-ttl` / `--no-cache`
flags. Skill count: 14. Tests: 109/109.

## Status — v0.6.2

**Dependency manifest.** Audit across every `.py` in the plugin found exactly
two third-party imports: `PyYAML` (runtime, scenario-matrix loader) and
`pytest` (dev, test runner). Both declared in `requirements.txt` /
`requirements-dev.txt`. Setup step 0 checks for PyYAML and prompts a
`pip install` if missing. Tests still 97/97.

## Status — v0.6.1

**Dashboard auto-provisioning.** `qa-queue` now ships an actual HTML widget
(`templates/dashboard.html`) plus a builder script. `/setup-medtrics-qa-automation`
calls `mcp__cowork__create_artifact` automatically after writing config, so
the `qa1-queue-dashboard` Live Artifact is alive the moment setup finishes.
Standalone `/qa-dashboard` slash command refreshes the widget idempotently.
On every Reload the dashboard re-fetches Optimus + Mem — no Mem-as-cache.
Tests now 97/97.

## Status — v0.6.0

**Dead-path cleanup.** Removed `qa-selector-extractor` (342 LOC of script +
105 lines of SKILL.md) — it was demoted to optional in v0.4 and no execution
path ever invoked it. The hand-authorable `selectors.json` sidecar format
still works; only the auto-generator goes away. Skill count now 13. Tests
still 89/89.

## Status — v0.5.3

**Test colocation.** Tests now live next to the skill they exercise —
`skills/qa-checklist-reader/tests/`, `skills/qa-guardrails/tests/`, and so on
— with their fixtures alongside. The top-level `tests/` directory is gone.
Each skill is now a self-contained unit: `SKILL.md` + `scripts/` +
`templates/` + `tests/`. The plugin-root `conftest.py` handles `sys.path`
discovery so individual test files have no boilerplate. 89/89 tests still
green under `-W error`.

## Status — v0.5.2

**Polish pass.** No contract changes. Added `pytest.ini`, `tests/conftest.py`
(centralizes `sys.path` discovery — test files dropped the boilerplate), a
proper `CHANGELOG.md`, and a small lint pass on the scripts (dropped unused
`asdict` / `Any` / `Iterable`, fixed a `SyntaxWarning` from a `\s` in a
non-raw docstring, freshened one stale comment). Tests run under
`-W error`: 89 passed, 0 failed.

## Status — v0.5.1

**Vendored GitLab scripts.** v0.5.1 ports the per-action GitLab pattern from
`medtrics-code-review` into qa-automation. `qa-gitlab-bridge/scripts/` now ships:

- `lib/gitlab_client.py` (~520 LOC, stdlib `urllib`, `.env` discovery, retry/rate-limit handling, vendored from code-review)
- `gitlab_whoami.py` — pre-flight token check; runs during `/setup`
- `gitlab_get_mr.py` — consolidated MR fetch (metadata + changes + pipeline status + deploy)
- `gitlab_get_pipeline_status.py` — the green-pipeline gate
- `gitlab_upload_file.py` — multipart upload for screenshots
- `gitlab_open_thread.py` — posts the fail-thread on the MR

`.env` discovery: `./.env` → `~/.cowork/medtrics-qa-automation/.env` → `<plugin_root>/.env`. Setup writes the canonical location with mode `0600`. Token scope: `api`. Test count: 89 (74 carried + 15 new for `gitlab_client.py` + the multipart formatter).

## Status — v0.5.0

**GitLab fail-threads + UI/UX observations.** v0.5 closes the loop on failed
runs: every step now captures a screenshot, every captured `CapturedPage`
runs through a deterministic UI/UX observer (console warnings, broken images,
4xx asset loads, missing alt text on P0 pages, layout overflow, deprecated
API warnings), and on failure (`writes-on` only) `qa-fail-reporter` uploads
the before/after screenshot pair for each failing step to GitLab and posts a
structured discussion thread on the MR with action / expected / observed,
console errors, network errors, and the UI/UX observations.

**v0.4 (carried forward).** Input boundary is the human-authored
`## QA Checklist` section on the Optimus ticket. The plugin reads what's
there, drives the deployed build through it, and writes back a verdict. No
external `.agents/skills/sk-manual-qa` dependency.

The deterministic API lane (scenario-matrix) and the agentic UI lane both
survive unchanged from v0.3. The guardrails layer, the deterministic
assertion vocabulary, and the test suite (45 tests passing) are untouched.

## The contract

```
INPUT  (per Optimus qa1 ticket)
  ├─ MR link in the description
  ├─ Successful MR deploy (GitLab deployment_summary)
  └─ '## QA Checklist' section authored by a human
                            │
                            ▼
   qa-checklist-reader extracts + parses
                            │
                            ▼
   scenario-matrix match? ─┐
       ├ yes → API lane   │  (qa-chrome-executor, deterministic, no LLM)
       └ no  → UI lane    │  (qa-ui-executor, drives Chrome, judges by code)
                            │
                            ▼
   verdict (100% P0 · ≥90% P1) ─▶ Mem run log + Slack card
                                  └─▶ (Phase 2+) Optimus move / GitLab thread
```

The agent **drives** the browser. Pass/fail is decided by
`scenario_dispatcher.run_ui_assertions()` against a captured page projection,
not by the agent's opinion. Safety decisions come from `guardrails.py`, also
code.

## The QA Checklist format (the input)

Inside the Optimus ticket description:

```markdown
## QA Checklist

Tester role: coordinator
Branch: feat/m1-1234/csv-encoding-fix

1. [P0] Navigate to /curriculum/imports and click "Download CSV template"
   Expected: A CSV file downloads; UTF-8 punctuation, no mojibake.

2. [P0] Upload tests/fixtures/courses-good.csv to the same page
   Expected: Success banner reads "8 rows imported"; no console errors.

3. [P1] Visit /curriculum/courses
   Expected: Table shows 8 rows.
```

Rules: heading must be exactly `## QA Checklist`. `Tester role:` is required.
Steps are numbered; priority tags `[P0]`/`[P1]`/`[P2]` are optional (untagged
defaults to P1). `Expected:` is the assertion source — phrasings map to
structured assertions via `qa-ui-executor/templates/expected-to-assertion.md`.
Expectations that can't be reduced to a structured assertion are marked
`needs_human` at runtime, never auto-passed.

A ticket without a `## QA Checklist` section blocks with
`blocked_reason: checklist_missing`. The plugin will not auto-generate one.

## What's in the box

### Commands (`commands/`)
- `/setup-medtrics-qa-automation` — first-run config + optional scheduled tasks
- `/qa1-poll` — single Optimus qa1 poll (read-only); also the 5-min scheduled task
- `/manual-qa-execute` — per-ticket executor; picks lane automatically
- `/ui-qa-execute` — forces the agentic UI lane on one ticket
- `/regression-execute` — bi-weekly module-pack runner

### Skills (`skills/`)
- **Substrate**: `qa-config`, `qa-memory`, `qa-audit`, `qa-queue` (Cowork dashboard)
- **Input**: `qa-checklist-reader` (the v0.4 input boundary — replaces `qa-checklist-uploader`)
- **Execution**: `qa-chrome-executor` (API lane), `qa-ui-executor` (UI lane)
- **v0.5 new**: `qa-ui-observer` (deterministic UI/UX checks per step), `qa-fail-reporter` (uploads screenshots + posts GitLab fail-threads)
- **Bridges**: `qa-optimus-bridge`, `qa-gitlab-bridge` (now also uploads files)
- **Safety**: `qa-guardrails` (enforced via `guardrails.py`)
- **Optional sidecar format**: `qa-chrome-executor/templates/selectors-schema.json` documents a hand-authorable `selectors.json` file the UI lane will consume if present. No auto-generator ships in-plugin.

### Tests (colocated under each skill)
- `skills/qa-checklist-reader/tests/` — `test_extract_checklist_block.py` + `test_checklist_steps.py` (with `fixtures/sample-ui-checklist.txt`)
- `skills/qa-guardrails/tests/test_guardrails.py` — 24 cases against the safety layer
- `skills/qa-chrome-executor/tests/test_ui_assertions.py` — the deterministic UI assertion vocabulary (with `fixtures/mojibake-corpus.csv`)
- `skills/qa-ui-observer/tests/test_ui_observations.py` — 21 cases over the UI/UX observation catalog
- `skills/qa-fail-reporter/tests/test_build_fail_thread.py` — thread rendering + attachment selection
- `skills/qa-gitlab-bridge/tests/test_gitlab_client.py` — .env discovery + multipart upload + pipeline status

Run from the plugin root: `pytest`. The root `conftest.py` and `pytest.ini` handle discovery — testpaths is `skills` and the conftest walks `skills/*/scripts/` to populate `sys.path`.

### Scenario matrix (`qa/`)
- `scenario-matrix.yaml` — one live rule (`import_template_encoding`) + two stubs

## Phase gates

| Phase | Behavior | Gate to next phase |
|---|---|---|
| **1 — shadow** | Verdict-only. No Optimus moves, no GitLab threads. | 3 consecutive weeks with <5% false positives and zero missed P0 fails. |
| **2 — writes-on** | Auto-move on pass, auto-thread on fail. Bi-weekly regression on Scheduling + Evaluations. | One full regression cadence with no P0 escape. |
| **3 — broad regression** | Forms + Reports join the regression cadence. Recurring P0 fails fold into Stage 6 pre-deploy checks. | Indefinite. |

The phase flag in `~/.medtrics-qa-automation/config.json` is the single switch.
No code change needed to flip phases.

## What changed in v0.5

| Area | Change |
|---|---|
| **GitLab fail-threads** | New skill `qa-fail-reporter` builds a structured per-failing-step thread (action / expected / observed, console errors, network errors, UI/UX observations) and posts it on the MR. |
| **Screenshots** | `qa-ui-executor` now captures a screenshot on every step (not just on fail/P0). The reporter selects the before/after pair per failing step (max 8 attachments per thread). |
| **GitLab file uploads** | `qa-gitlab-bridge` extended with `upload_file(project_id, path)` against `POST /api/v4/projects/:id/uploads`. Returns the GitLab markdown link for splicing into the thread body. |
| **UI/UX observations** | New skill `qa-ui-observer` runs deterministic checks per step — `console_warning`, `asset_load_error`, `broken_image`, `missing_alt_text` (P0 only), `layout_overflow`, `deprecated_api_warning`. Advisory only; never affects verdict. |
| **CapturedPage extended** | New fields: `tag`, `natural_width`, `alt`, `scroll_width`/`client_width`/`scroll_height`/`client_height`, `is_scrollable_declared`, plus `network[]` with `{method, url, status}` for all requests. |
| **Mem run log** | Adds `ui_observations[]` (per-run aggregate) and per-step `evidence.console_errors[]`, `evidence.network_errors[]` to feed the fail-thread. |

## What changed from v0.3 → v0.4

| v0.3 | v0.4 |
|---|---|
| `qa-checklist-uploader` generated checklists from the diff via `sk-manual-qa` | `qa-checklist-reader` reads the human-authored `## QA Checklist` from the Optimus description |
| `commands/` directory missing — entry-points were SKILL.md stubs | Five proper command files in `commands/` |
| External `sk-manual-qa` dependency required | Plugin is self-contained |
| `qa-selector-extractor` was a required pre-pass | Demoted to optional offline analysis |
| Blocked reasons: MR-resolution failures only | Adds `checklist_missing` and `checklist_unparseable` |

## Conventions

- All skills follow the `medtrics-sentry-triage` / `medtrics-code-review` pattern:
  side-effects gated through `qa-audit`, persistent state through `qa-memory`,
  every external write checked by `qa-guardrails`.
- PII scrubbing happens before any Mem / Slack / Optimus / GitLab write.
- Optimus and GitLab writes refuse to fire during Phase 1 — controlled by the
  single `phase` flag in `qa-config`.
- The audit log (`~/.medtrics-qa-automation/audit.jsonl`) is the durable
  record. Mem and Optimus are derived views; if either is unreachable, the
  audit log carries the truth.

See `/Users/sahilmedtrics/projects/medtrics/docs/qa/qa-v22-decisions-brief.pdf`
for the full decisions brief.
