---
name: qa-ui-executor
description: Agentic UI execution lane for medtrics-qa-automation. Takes the structured test_plan_steps parsed from the human-authored QA Checklist section on the Optimus ticket (plus optional selectors.json hints) and drives Claude in Chrome like a manual QA tester — logs in as the right persona, navigates, clicks, fills forms, uploads files, screenshots — then judges each step DETERMINISTICALLY with the UI assertion vocabulary and writes per-step pass or fail into execution_trace. The agent drives; the verdict is structured. Outside-vocabulary judgments are marked needs_human, never auto-passed.
---

# qa-ui-executor

The missing half of the pipeline. `qa-chrome-executor` (the deterministic
lane) runs the scenario-matrix for known API-correctness bug classes.
`qa-ui-executor` (this skill) is the **agentic lane**: it tests anything a
human QA tester would do by clicking the UI, for tickets that have no matrix
rule.

The two lanes converge on the same Mem verdict schema and the same dashboard
"View Result" panel, so the operator experience is identical regardless of
which lane ran.

## The core principle (read this first)

> **The agent drives. The verdict is deterministic.**

The agent interprets each natural-language checklist step, finds the right
element, and performs the action in Chrome. But whether a step **passed** is
decided by running a structured assertion (`scenario_dispatcher.run_ui_assertions`)
against a captured projection of the page — *not* by the agent's opinion of
whether it "looks right". A step whose expected outcome cannot be reduced to a
structured assertion is marked `needs_human` — **never** auto-passed. This is
the same trust property the API lane gets from its negative-test self-check.

## MANDATORY — v0.12.2 auto-wrap contract for the GIF recorder

**Every non-visual MCP action during a run MUST go through the auto-wrap
helper.** No exceptions, no "read-only introspection" carve-out. This exists
because Chrome MCP's `gif_creator` only records `computer` / `navigate`
calls — a `javascript_tool`, `read_page`, `read_console_messages`,
`read_network_requests`, `get_page_text`, or `find` call performs real work
but never lands in the GIF, so the operator gets a walkthrough missing
half its steps. That failure mode shipped once (M1-1309, 7-frame GIF from
~14 actions). It cannot ship again.

### Banned direct calls during a run

The executor MUST NOT call any of these tools directly:

  - `mcp__claude-in-chrome__javascript_tool`
  - `mcp__claude-in-chrome__read_page`
  - `mcp__claude-in-chrome__read_console_messages`
  - `mcp__claude-in-chrome__read_network_requests`
  - `mcp__claude-in-chrome__get_page_text`
  - `mcp__claude-in-chrome__find`

Every direct invocation of the above during a run is a contract violation
and MUST be logged as `qa_action_with_marker.violation` in the audit trail.

### The single wrapped path

Instead, call the wrapper for every non-visual step:

```
python3 skills/qa-screenshot-capture/scripts/qa_action_with_marker.py \
  --kind <javascript|read_page|read_console|read_network|get_page_text|find> \
  --step-n <n> --tab-id <medtrics_tab_id> --step-label "<short label>" \
  [--script "<JS body — required for --kind javascript>"] \
  [--since-last-seen]
```

The helper returns a 3-action plan the executor MUST run in order:

  1. The underlying MCP call.
  2. A `javascript_tool` marker inject (4×4 px HSL-rotating visible div).
  3. A `computer.screenshot` — captured as a distinct GIF frame.

**Visual actions (`computer.left_click`, `computer.scroll`,
`computer.mouse_move`, `navigate`) do not need the wrapper** — they already
paint distinct pixels the recorder captures. Prefer `force_frame_step.py
--kind click` / `--kind scroll` when the target element's centre
coordinates are already known.

### Post-run self-check

After the run completes and the GIF is exported, the executor MUST run:

```
python3 skills/qa-screenshot-capture/scripts/verify_gif_completeness.py \
  --run-dir outputs/qa/<ticket>/<run_id>/
```

If `verdict == under_recorded` (frames < 80% of expected step count), the
verdict-thread renderer surfaces a warning line the operator can act on.
Non-blocking by default — the verdict still posts — but the audit trail
holds a `verify_gif_completeness.under_recorded` event that the weekly
review reads.

### What "read-only" no longer buys you

Reading `document.title`, computing bounding rects, extracting an XPath,
inspecting a form's `checked` state, `fetch()`ing a JS file from the
deploy for source verification — all of these MUST go through
`qa_action_with_marker`. The v0.12.1 doc granted these an exemption. That
was the mistake that produced the M1-1309 7-frame GIF. v0.12.2 removes it.

**If you are reading this and about to invoke `javascript_tool` /
`read_page` / `read_console_messages` / `read_network_requests` /
`get_page_text` / `find` directly — STOP and use `qa_action_with_marker`
instead.**

## Inputs

| Input | Required | Source |
|---|---|---|
| `ticket` | Yes | Optimus id, e.g. `M1-1190` |
| `mr_resolution` | Yes | From `resolve_mr_via_gitlab.md` — `mr_iid`, `deploy_url`, `source_branch`, `changed_files`, `title` |
| `test_plan_steps[]` | Yes | From `parse_checklist_steps.py` over the human-authored `## QA Checklist` section on the Optimus ticket (see qa-checklist-reader). Each: `{n, step_id, priority, action, expected}` |
| `persona` | Yes | From the checklist's "Tester role:" line (parser fills it). Defaults to `coordinator` if absent. |
| `selectors` | No | Optional `checklist.selectors.json` sidecar (hand-authored or future-tool-emitted) matching `qa-chrome-executor/templates/selectors-schema.json`. Provides deterministic `{step_id -> action}` hints. When absent, the agent uses Chrome MCP `find()` against the visible DOM. |
| `run_id` | No | ISO timestamp; auto-generated |

## Procedure

### 0. Preconditions and guardrails

Read `~/.medtrics-qa-automation/config.json`. Confirm `phase`. This skill runs
**read-only by default** (see "Guardrails" below). Refuse to start if:
- `mr_resolution.deploy_url` is empty → Mem `state=blocked, reason=no_deploy`.
- `test_plan_steps[]` is empty → Mem `state=blocked, reason=checklist_unparseable`
  (the ticket's `## QA Checklist` section had no recognizable numbered steps).

### 1. Land on the deploy and observe the auth state

```text
# v0.10.0 (GAP-13/14): visit the canonical login path directly. The
# Medtrics canonical login path is /users/login (Devise convention —
# verified empirically across tenants on 2026-06-05). Override per-install
# via config.deploy.login_path.
login_path = config.deploy.login_path or "/users/login"
mcp__Claude_in_Chrome__navigate(url = mr_resolution.deploy_url + login_path)
```

Detect the auth state **structurally**, not by text-matching. A page that
is the login surface MUST have a password input; a page that returns the
operator straight into the app (because the cookie carried over) will not.

```text
pw_probe = mcp__Claude_in_Chrome__find(query = "password input")
```

Two outcomes:

**A. `pw_probe` is empty → session inherited.** The operator's browser
was already logged in to `*.medtrics.dev` and Cowork's Chrome MCP picked
up the cookie. Record step 0 as `session_inherited`, continue to step 2.

**B. `pw_probe` returns a match → login surface.** Do **not** try to log
in here. Hand control back to the checklist — its very first step should
be an explicit instruction like `Log in as <email>` with the matching
`Expected:` that proves login succeeded. The executor reaches that step
in the normal loop (steps 2–4 below) and treats it like any other verb:
`fill`, `click`, `wait_for_text`. The checklist author owns:

- Which user to log in as (email or username)
- Where to source the password (a step value, a referenced secret, or
  manual entry before the run)
- What proves login worked (the `Expected:` text — usually "Dashboard
  loads" or a `url_matches: !/users/login/` assertion)

If the checklist has no login step AND the structural probe matches, the
run blocks with `state=blocked, reason=not_authenticated`. The fix is
upstream — the author adds the login step to the checklist.

**Fallback when /users/login 404s.** A handful of tenants route auth
through a different path. If the navigate above returns a non-2xx OR the
page has neither a password input nor an obvious authenticated dashboard
(`find("dashboard navigation")` empty too), fall back to:

```text
mcp__Claude_in_Chrome__navigate(url = mr_resolution.deploy_url)
# Inspect the final URL via tabs_context_mcp after the redirect chain.
# Re-run the structural pw_probe at the landing URL.
```

If even the fallback can't find a password input AND can't confirm an
authenticated session, block the run with
`state=blocked, reason=login_form_not_found` and surface the deploy URL
to the operator for manual triage. Do not hardcode a third path.

> **Why this changed (v0.10.0, GAP-13/14).** The plugin used to text-match
> "Sign in" against the rendered page to decide whether the operator was
> authenticated. Multiple Medtrics screens carry "Sign in" as a button or
> link elsewhere on the page, so the check fired false positives. The
> structural `find("password input")` is unambiguous: a login surface has
> a password field; an authenticated page does not.
>
> **Why this changed (v0.9.3).** The plugin used to assume six test
> personas (`qa-coordinator@test.medtrics.invalid` etc.) existed on every
> deploy, seeded by a Django command that was never built. That spec was
> deleted. Login is now declarative inside each checklist, which is
> where it belongs — the same checklist that says "click Save and expect
> the row to appear" can say "log in as admin@medtricslab.com first." No
> separate schema, no env-var convention, no eng-side blocker.

### 2. For each step, resolve an action plan

Translate `step.action` into one or more **step verbs**. Prefer the
`selectors.json` hint for this `step_id` when present (deterministic);
otherwise use Chrome MCP `find` to locate the element by visible text / role.

Step-verb → Chrome MCP mapping (the closed driving vocabulary):

| Step verb | Chrome MCP call(s) | Notes |
|---|---|---|
| `navigate` | `navigate(deploy_url + url)` | relative path from selectors.json or inferred route |
| `click` | `find(selector\|text)` → `computer` click (or `javascript_tool` click) | prefer `data-testid` selectors |
| `fill` | `form_input(field, value)` | one per field |
| `upload` | `file_upload(selector, fixture_path)` | fixture from sk-csv-creation / tests/fixtures |
| `wait_for_text` | `get_page_text()` poll (≤ timeout_ms) | for async UI |
| `screenshot` | `computer(screenshot)` / `read_page` | **v0.5: capture on every step**, write to `outputs/qa/<ticket>/step-<n>.png`. Used by qa-fail-reporter to attach the before/after pair to the GitLab thread. |
| `capture` | see step 3 | builds the projection judged in step 4 |

Anything that can't be mapped to a verb → mark the step `needs_human`,
`reason: action_unmappable`. Do **not** improvise destructive actions.

### 3. Capture the page projection

After the step's action, build a `CapturedPage` (the structure
`scenario_dispatcher.CapturedPage` reads):

```text
url      <- javascript_tool: return location.href
title    <- get_page_text (document.title)
text     <- get_page_text (visible text)            # counts/booleans only; Cowork strips bulk bytes
elements <- for each selector the step cares about: find(selector) ->
            FoundElement{selector, exists, visible, text, value,
                         tag, natural_width, alt,
                         scroll_width, client_width,
                         scroll_height, client_height,
                         is_scrollable_declared}
console  <- read_console_messages -> [ConsoleMessage{level, text}]
                                       # capture ALL levels including warn
network  <- read_network_requests -> [{method, url, status}]
                                       # capture every request; observer filters
downloads<- filenames observed after a download-triggering click
screenshot <- computer(screenshot) → outputs/qa/<ticket>/step-<n>.png
                                       # v0.5: captured on every step
```

Only query the selectors this step asserts on — keep the projection small.
The `tag`, `natural_width`, `alt`, and `scroll_*` fields are read via
`javascript_tool` against the already-found element handles; they cost one
extra JS evaluation per element and feed `qa-ui-observer`.

### 4. Derive the step's assertions and judge deterministically

Build the assertion list for the step, in priority order of source:

1. **From `selectors.json`** — `assert_present`→`element_visible`,
   `assert_absent`→`element_absent`, `wait_for_text`→`text_present`.
2. **From the step's `expected` text**, only via the deterministic mapping in
   `templates/expected-to-assertion.md` (e.g. "no error" → `console_clean`;
   "shows <X>" → `text_present:[X]`; "downloads <name>.csv" →
   `download_filename_eq`; "date shows 2026-05-12" → `text_present:["2026-05-12"]`).
3. **If neither yields a structured assertion** → step verdict `needs_human`,
   `reason: expectation_not_structurable`. Screenshot for the human reviewer.
   Never auto-pass.

Then:

```python
from scenario_dispatcher import run_ui_assertions, CapturedPage, Assertion
ok, failed = run_ui_assertions(page, assertions)
verdict = "pass" if ok else "fail"
```

### 4b. Collect UI/UX observations (v0.5, advisory)

Immediately after the verdict, run the deterministic UI/UX checks:

```python
import sys; sys.path.insert(0, "../qa-ui-observer/scripts")
from check_observations import observe
obs_this_step = observe(step, captured_page)
ui_observations_all.extend(obs_this_step)
```

Observations are **advisory only** — they never flip the step verdict.
Catalog: `console_warning`, `asset_load_error`, `broken_image`,
`missing_alt_text` (P0 only), `layout_overflow`, `deprecated_api_warning`.
The full per-run array is written to the Mem run log and `qa-fail-reporter`
includes it in the GitLab thread.

### 5. Record the execution_trace entry

One entry per step, in the schema `qa-chrome-executor/SKILL.md` §5b already
defines:

```json
{
  "n": 2,
  "step_id": "step-2",
  "priority": "P0",
  "started_at": "2026-05-29T18:00:14.823Z",
  "action_taken": "Clicked [data-testid=download-csv-template] on /curriculum/imports/",
  "observed": "download: courses.csv · ✓ download_filename_eq · ✓ console_clean",
  "verdict": "pass",
  "duration_ms": 612,
  "evidence": {
    "url": "/curriculum/imports/",
    "assertions": [
      {"kind": "download_filename_eq", "passed": true},
      {"kind": "console_clean", "passed": true}
    ],
    "screenshot_ref": "outputs/qa/M1-1190/step-2.png",
    "console_errors": [],
    "network_errors": []
  }
}
```

### 6. Aggregate and write the Mem note

Reuse the deterministic aggregator — no separate thresholds for the UI lane:

```python
from scenario_dispatcher import aggregate, StepResult
results = [StepResult(scenario_id=s["step_id"], priority=s["priority"],
                      verdict=s["verdict"], failed_assertions=s["failed"],
                      evidence=s["evidence"]) for s in step_results]
verdict = aggregate(results, scanner_ok=True)
```

Write the Mem `QA Run Logs` note (keyed on `ticket`) with `test_plan_steps[]`,
`execution_trace[]`, `assessment{}`, `verdict`, `p0_pass_rate`, `p1_pass_rate`,
`lane: "ui"`, `deploy_url`, `mr_url`, and **`ui_observations[]`** (v0.5 —
the per-run aggregate from the qa-ui-observer calls in step 4b). Same fields
the dashboard already reads; `lane` lets it badge UI vs API runs.

### 7. Phase-gated writes

Identical to the API lane: `shadow` → Slack staging card + Mem run log only;
`writes-on` → Optimus pointer block, Slack staging card, plus (on failure)
the GitLab fail-thread via `qa-fail-reporter`. Gated on `config.phase`.

## Guardrails (enforced — P1-3)

Safety is now enforced by `qa-guardrails/scripts/guardrails.py`, not by this
skill's prose. Call it at four points (see `qa-guardrails/SKILL.md` for the full
contract). Refuse on `severity == "block"`; record `reason` on `warn`.

```python
import sys; sys.path.insert(0, "../qa-guardrails/scripts")
import guardrails as G

# at login (step 1)
d = G.check_persona(persona, requires_admin=run_requires_admin)
if not d.allowed: stop(state="blocked", reason=d.reason)

# before driving each step's action (step 2)
d = G.screen_action({"kind": verb, "selector": sel, "label": label,
                     "expected": step["expected"]}, phase)
if not d.allowed:                      # e.g. destructive_action_in_shadow
    mark_step(step, "needs_human" if "destructive" in d.reason else "blocked", d.reason)
    continue

# before writing evidence to the Mem note (step 6)
observed, kinds = G.redact_pii(observed_text)        # scrub PII/PHI
if not G.assert_evidence_clean(observed).allowed:    # belt-and-suspenders
    observed = "[evidence withheld: residual PII]"

# writes-on only (step 7)
if G.gate_write("optimus", phase).allowed: ...        # shadow blocks optimus/gitlab
```

Behavioral summary:
- **Read-only persona by default** — `admin` blocked unless the run sets
  `requires_admin`.
- **Destructive controls blocked in shadow**; in writes-on allowed only when the
  step's `expected` is testing that destructive behavior.
- **PII/PHI redacted** before any Mem/Slack/Optimus/GitLab write.
- **Optimus/GitLab writes blocked in shadow**; Slack staging card + Mem run-log
  allowed.
- **Timeouts**: `G.HARD_TIMEOUT_S` (600s) per run, `G.STEP_TIMEOUT_S` (30s) per
  step → on breach `state=blocked, reason=timeout`.
- **One browser session.** No identity switching yet (P2-1). A step needing a
  second persona → `needs_human, reason: multi_session_required`.

## Pass criteria

Decided by `scenario_dispatcher.aggregate` — 100% P0 pass, ≥90% P1, P2
informational. Any `needs_human` step makes the run `partial`, never `pass`.

## Failure handling

| Failure | Behavior |
|---|---|
| Element not found after `find` + one retry | step `fail`, assertion `element_not_found`. Continue. |
| Console error during a step | `console_clean` fails → step `fail`. |
| Navigate lands on login | `state=blocked, reason=not_authenticated`. Stop. |
| Network blip on a step | retry once; if still failing, `fail` with `network_error` (P2-3 will mark intermittent separately). |
| Step action unmappable / expectation not structurable | `needs_human` (never pass). |

## Reads
- `mcp__Claude_in_Chrome__navigate | get_page_text | read_console_messages | read_network_requests | find | form_input | file_upload | computer`
- `scenario_dispatcher.py` (`run_ui_assertions`, `CapturedPage`, `aggregate`)
- `qa-chrome-executor/templates/personas-schema.yaml`
- `checklist.selectors.json` (optional sidecar matching `qa-chrome-executor/templates/selectors-schema.json`)
- `templates/expected-to-assertion.md`

## Writes
- One Mem `QA Run Logs` note (keyed on `ticket`, `lane: "ui"`).
- Screenshots to `outputs/qa/<ticket>/` (referenced by `screenshot_ref`).
- One audit row per step + one per run.
- Phase-gated: Optimus pointer block, Slack staging card.

## What this skill does NOT do
- Does not author checklists. The `## QA Checklist` section on the Optimus ticket is the human-authored input; this skill only executes it.
- Does not invent selectors not present in selectors.json or discoverable via
  `find` against the live page.
- Does not switch identities mid-run (P2-1).
- Does not flip the scheduled task to unattended (gated on P1-3 + P2-2).
