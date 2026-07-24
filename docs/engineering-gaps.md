# medtrics-qa-automation — engineering gaps

This document tracks plugin capabilities whose **readiness depends on
work that has not happened yet** — either out-of-plugin engineering
(deploy seeding, CI pipeline changes) or in-plugin work that's documented
in SKILL.md prose but never lived against a real system.

Audit each gap by reading the **Verified-against-code / Verified-against-system**
column. That column records exactly what was grep'd, queried, or executed
to confirm the gap is real on the date the gap was filed.

When eng (or the plugin authors) close a gap, move the entry to
**Closed gaps** at the bottom with a one-line note on what shipped.

**For the fix plan**, see [`fix-roadmap.md`](fix-roadmap.md) (strategic
view) and [`implementation-plans/`](implementation-plans/) (per-phase
detail). Each gap below is closed by exactly one phase.

| Gap | Closed in | Plan |
|---|---|---|
| GAP-2, 3, 11, 13, 14, 19 | v0.10.0 (shipped) | [phase-1-quick-wins](implementation-plans/phase-1-quick-wins.md) |
| GAP-24 | v0.10.1 (proposed) | inline-edit SKILL.md note — see post-test-findings |
| GAP-6 (×9), 12, 15 (+ 23 dimension), 16, 17 (+ 21/22 visibility & scroll modes), 20 | v0.11.0 | [phase-2-inner-loop](implementation-plans/phase-2-inner-loop.md) |
| GAP-5, 7 (remaining update_task half), 8, 18 | v0.12.0 | [phase-3-write-paths](implementation-plans/phase-3-write-paths.md) |
| GAP-4, 9 | v0.13.0 | [phase-4-content-scheduling](implementation-plans/phase-4-content-scheduling.md) |
| GAP-10 | v0.14.0 | [phase-5-metrics](implementation-plans/phase-5-metrics.md) |

---

## Severity legend

- **HIGH** — Blocks a core capability. The plugin literally cannot do
  the documented thing without this work. Failure mode is usually
  "first real run blocks with a typed reason."
- **MEDIUM** — Degrades a capability. The plugin runs, but a documented
  side-effect doesn't happen (e.g. Slack card silently missing).
- **LOW** — Operational drift. Doesn't affect a run; affects long-term
  observability or onboarding ergonomics.

---

## Open gaps

### GAP-4 — Regression module checklists do not exist · MEDIUM

**Filed:** 2026-06-04.

**The plugin assumes:** `/regression-execute` reads
`qa/regression/<module>/checklist.md` for each active module. Verified:

```bash
ls qa/regression/
# → (directory does not exist)
```

**Consequence:** `/regression-execute` would fail every module with
"checklist file missing" — the bi-weekly regression suite is documented
but unrunnable. The Phase 2 promise ("regression on Scheduling +
Evaluations") and the Phase 3 promise ("Forms + Reports join") both
require these files to exist first.

**What closes the gap:** Four authored checklist files for the Phase
2/3 modules — `qa/regression/scheduling/checklist.md`,
`evaluations/checklist.md`, `forms/checklist.md`, `reports/checklist.md`.
Same `## QA Checklist` format the per-ticket reader uses. Author = QA
Lead or the module owner.

---

### GAP-5 — Slack integration is paper-only · MEDIUM

**Filed:** 2026-06-04.

**The plugin assumes:** Slack staging-card posts after every verdict,
regression roll-ups to `#dream-team`, optional bug-notification posts.
The Slack MCP tool is `mcp__5f6545e3-…__slack_send_message`.

**Verified-against-code:** searching the plugin for any wrapper script or
live call:

```bash
grep -rln "slack_send_message\|mcp__5f6545e3" --include="*.md" --include="*.py" \
  | grep -v __pycache__
# → skills/qa-chrome-executor/SKILL.md  (one mention in prose)
```

No script wraps it. No test exercises it. The "Slack staging channel
required during setup" prompt collects a channel name but nothing
actually posts there.

**Consequence:** Every documented post (staging card, regression roll-up,
bug notification) is a SKILL.md sentence with no executable path. The
QA Lead's Friday review of shadow output has no inbound stream.

**What closes the gap:** A `skills/qa-slack-bridge/` skill (or a section
in `qa-fail-reporter`) with:
- `slack_post_staging_card.py` — posts the per-verdict card to
  `config.slack.staging_channel`.
- `slack_post_regression_rollup.py` — posts the bi-weekly summary.
- Tests with `mock.patch` over the Slack MCP call.
- ~60 LOC + 5 tests.

---

### GAP-6 — Chrome MCP execution is unproven end-to-end · HIGH

> **Update (2026-06-05):** First real audit run executed against MR !6865
> deploy as `admin@medtricslab.com`. Logged in, navigated to the M1-1190
> block-schedule page (`/rotations/schedules/11/blocks/`), reached the
> edit-row datepicker, attempted to save modified dates. **Nine distinct
> Chrome MCP behaviors the plugin's SKILL.md didn't anticipate were
> surfaced** — see "Verified-against-Chrome-MCP findings" below. The audit
> stopped before completing all 12 checklist steps because the findings
> below would each require plugin-side code changes to handle correctly,
> and continuing further would have risked dirtying the live deploy.

**Verified-against-Chrome-MCP findings (2026-06-05 run):**

| # | Finding | Plugin impact |
|---|---|---|
| 1 | **Screenshots require per-domain permission grants.** `computer:screenshot` on a fresh domain returns `Permission denied for this action on this domain`. | qa-fail-reporter assumes screenshots "just work." First fail-thread will have a `_(screenshot upload failed)_` placeholder for every step until the operator clicks Allow once per deploy domain. |
| 2 | **First navigate to a new domain can silently no-op.** Initial `navigate` to `https://6865.medtrics.dev` reported success but the tab stayed on `chrome://newtab/`. A second explicit navigate worked. | qa-ui-executor step 1 must re-verify via `tabs_context_mcp` after every navigate — the success message from `navigate` is necessary but not sufficient. |
| 3 | **Medtrics' login URL is `/users/login/`, not `/login`.** Plugin SKILL.md showed `navigate(deploy_url + "/login")`. | The login URL has to be discovered by hitting the bare root and following the redirect, not hardcoded. |
| 4 | **`document.forms` came back empty `[]`.** The Django/Vue login page renders a real form but `document.forms` doesn't expose it. | CapturedPage's `elements` field can't rely on `document.forms` for form introspection — must use `find` (the natural-language tool) or `querySelectorAll`. |
| 5 | **Password input values are auto-redacted as `[BLOCKED: Sensitive key]`** when read via `javascript_tool`. Even checking `!!document.querySelector('input[type=password]')` (a boolean) gets blocked. | The executor can't introspect login forms to verify "is there a password field present" via JS. Must use `find` instead. |
| 6 | **URLs containing base64-like segments are redacted as `[BLOCKED: Base64 encoded data]`** when read via `javascript_tool`. The `/rotations/schedules/<id>/blocks/` URLs in the schedule list had their `href` attributes blanked. | The executor can't follow URLs read from the DOM via JS — has to click via `find` instead of constructing the next URL. Limits some action plans. |
| 7 | **`form_input` with Vue.js datepickers doesn't trigger framework reactivity reliably.** Setting `Start Date` and `End Date` text input values via `form_input` succeeded (the underlying input had the new value), but clicking Save apparently sent the ORIGINAL values — after page reload, the block still showed `May 11 – May 31` not `May 12 – Jun 1`. | qa-ui-executor's `fill` verb maps to `form_input`. For Vue/React datepickers, this isn't enough — has to dispatch `input` + `change` events explicitly via `javascript_tool`. |
| 8 | **`read_network_requests` starts capturing only AFTER the first call.** Pre-existing network traffic isn't recorded. | CapturedPage builds the `network` field at the END of a step; by then, the step's POST/PATCH has already happened and is invisible. The executor must call `read_network_requests` at the START of each step to arm capture. |
| 9 | **`read_console_messages` does the same** — captures only after the tool is first invoked. The Sentry init log and the moment.js deprecation warning were captured because they happened minutes after my first call to the tool. Anything earlier would be invisible. | Same fix as #8 — arm at step start, not at step end. |

**Other practical observations from the run:**

- **`form_input` succeeded but Save didn't persist** — confirmed by reload. The block ID 182's dates stayed at the original `Mon May 11, 2026 – Sun May 31, 2026` with duration `21 days`. Possible causes: (a) framework reactivity not fired, (b) my new end date `01 Jun 2026` collided with Block 2's start `01 Jun 2026` and the server rejected, (c) something else entirely. Without armed network capture (#8 above) the executor can't distinguish these.
- **Even the moment.js deprecation warning** (the actual root cause of the M1-1190 bug — moment's `_isUTC: false` fallback path when given a JS Date object) was visible in the console post-save. The plugin's `qa-ui-observer` would have flagged this correctly as a `deprecated_api_warning`. That part of the spec is sound.
- **The `find` tool is consistently reliable.** Every natural-language query returned exactly the element I wanted (the email input, the password input, the Sign In button, the Manage Blocks link, the Edit button for a specific block, the Start Date textbox in the block 182 edit row, etc.). This validates the executor's `find()` fallback strategy.
- **Authentication using the user-provided admin credentials worked on first try.** Login URL `/users/login/` → email field → password field → Sign In button → landed at `/users/`. Confirms the v0.9.3 "checklist owns the login" approach is workable in practice.

**What this means for the plugin:**

The audit didn't disprove the plugin's mental model. It surfaced specific
Chrome MCP gotchas that the SKILL.md docs over-simplified. Six of the nine
findings (#2, #4, #7, #8, #9, plus the per-domain permission gotcha #1) have
clear plugin-side fixes:

- (#1, screenshots) — `qa-fail-reporter` must catch the permission-denied
  error and fall back to a text-only thread instead of failing the whole run.
- (#2, silent navigate) — `qa-ui-executor` step 0 must do `navigate → wait
  → tabs_context_mcp` and verify the URL committed; retry once if not.
- (#4, document.forms empty) — `qa-ui-observer`'s "broken-image / missing-alt"
  checks should `find` elements via the natural-language tool, not raw DOM.
- (#7, Vue reactivity) — the `fill` verb wraps `form_input` plus a
  `javascript_tool` call that fires `new Event('input', {bubbles: true})`
  and `new Event('change', {bubbles: true})` on the underlying input.
- (#8, #9, capture arming) — `qa-ui-executor` step 3 must call
  `read_network_requests({clear: true})` and `read_console_messages({clear: true})`
  at the START of each step, then call them again at the end to get the delta.

The other three (#3, #5, #6) are facts about Chrome MCP / the target app
that the executor has to accept and code around. None of them are
showstoppers; they all have workarounds.

**Severity downgrade:** This gap is still HIGH (Chrome MCP execution end-to-end
isn't shipped yet), but the proven-doable side of it is now clearer.

---

### Cascading findings — what the 9-finding audit exposed structurally

The nine immediate findings have line-level fixes. Working through them
surfaced eight *second-order* issues — places where the plugin's mental
model is wrong, not just where a single function needs patching. These
are filed as new gaps below (GAP-12 through GAP-19).

### GAP-12 — `CapturedPage` is a snapshot when it needs to be a trace · HIGH

**Filed:** 2026-06-05.

**The mental model the plugin has:** Each step runs an action, then builds
a `CapturedPage` snapshot of the resulting DOM + console + network state,
then runs assertions against that snapshot.

**What's actually true:** Findings #8 and #9 prove that
`read_network_requests` and `read_console_messages` capture **only after
the tool's first call**. The Save POST fired by the step's `click` was
invisible to a post-action snapshot. So was any console error thrown
during the click handler.

**Architectural consequence:** The right shape isn't `CapturedPage`, it's
`StepTrace` — a record with separate `during` and `after` fields:

```python
StepTrace = {
  "step_id": str,
  "armed_at": iso,              # when capture was armed
  "completed_at": iso,
  "during": {
    "console_events":  [...],   # what fired between armed_at and completed_at
    "network_requests": [...],  # same
    "downloads": [...],         # same
  },
  "after": {                     # post-action snapshot
    "url": str, "title": str, "elements": [...],
    "page_text": str,
  }
}
```

This is a real refactor of `qa-ui-executor` step 3 + `scenario_dispatcher.run_ui_assertions()`'s
input shape. The assertion vocabulary needs additions too — see GAP-15.

**What closes the gap:** Rewrite the executor's per-step loop to: arm
captures → action → drain captures → snapshot → judge.

---

### GAP-15 — UI assertion vocabulary is missing the assertions the audit needed · MEDIUM — UI assertion vocabulary is missing the assertions the audit needed · MEDIUM

**Filed:** 2026-06-05.

**The plugin's vocabulary today** (from `scenario_dispatcher.run_ui_assertions`):
`element_visible`, `element_absent`, `text_present`, `text_absent`,
`url_matches`, `value_eq`, `console_clean`, `download_filename_eq`.

**What the audit needed but couldn't express:**

- `value_persisted_after_save(selector, expected)` — did the input
  retain my entered value after the Save round-trip?
- `network_request_fired(method, url_pattern)` — did the click
  actually POST anything? Critical for distinguishing "save succeeded"
  from "save silently failed."
- `network_response_status(url_pattern, status)` — what did the server
  return? Was it 4xx (validation error) vs 5xx (server bug) vs no
  request at all?
- `console_warning_present(pattern)` — proactively assert that a
  specific deprecation warning fired, not just that errors didn't.

Each maps directly to fields in the proposed `StepTrace` from GAP-12.

**What closes the gap:** Extend `scenario_dispatcher.run_ui_assertions`
with the four new kinds. Implementations are ~5 LOC each. Add to the
ALLOWED_UI_ASSERTION_KINDS set + the `templates/expected-to-assertion.md`
mapping so checklist `Expected:` text can specify them.

---

### GAP-16 — "Step succeeded silently" is not a representable verdict · MEDIUM

**Filed:** 2026-06-05.

**The plugin's blocked-reason vocabulary** today includes:
`checklist_missing`, `checklist_unparseable`, `no_open_mr_found`,
`deploy_not_ready`, `gitlab_error`, `not_authenticated`, `timeout`,
`multi_session_required`.

**The audit produced an unverdictable state:** the Save click "succeeded"
(no console error, no UI change visible to the executor), but the
underlying save **didn't persist** (verified by page reload). There's no
existing verdict for "the action's success cannot be determined from the
captured state."

**What closes the gap:** Add `verification_inconclusive` as a new
blocked-reason. The executor returns it whenever `run_ui_assertions`
can't prove the expected outcome — instead of falsely passing or
falsely failing. Forces the human reviewer to look at the screenshot
(once that works — see GAP-1 / screenshot permission).

---

### GAP-17 — Vue settle-time is not modeled · MEDIUM

**Filed:** 2026-06-05.

**The plugin assumed:** After every action, a `wait` verb of N seconds
is enough for the DOM to reflect the new state.

**What's actually true:** Vue (and React) re-renders run on the
microtask queue. A click handler can synchronously update Vue reactive
state, but the DOM doesn't update until the next tick. `wait` for
seconds is overkill in some cases and not enough in others (e.g.,
async fetches inside the click handler).

**Architectural consequence:** Replace blind `wait` with a "settle"
verb that waits for either (a) the DOM to stop mutating for K
milliseconds, or (b) a specified DOM marker to appear/disappear. For
Vue specifically, `[v-cloak]` absence is a useful settle signal.

**What closes the gap:** Add a `settle(timeout_ms, until?)` verb to
`qa-ui-executor`'s closed verb vocabulary. Default usage: `settle(2000)`
after every `click` / `fill` / `submit_form`.

---

### GAP-18 — `qa-ui-observer` checks depend on now-redacted JS introspection · MEDIUM

**Filed:** 2026-06-05.

**The plugin assumed:** `qa-ui-observer` reads `tag`, `natural_width`,
`alt`, `scroll_width`, `client_width` directly from a `CapturedPage.elements`
array populated via `javascript_tool` evaluation.

**What's actually true:** Findings #5 and #6 prove that JS access to
several DOM properties auto-redacts as `[BLOCKED]` on Medtrics pages.
The broken-image check (`natural_width == 0`) and the missing-alt-text
check (`alt == ""`) may both hit redaction depending on what the
element's surrounding context contains.

**Architectural consequence:** `qa-ui-observer` checks that need
element-property reads must go through `find` (natural language)
rather than `javascript_tool` (raw DOM). The `find` tool returns
human-friendly summaries that aren't redacted, but it doesn't expose
the raw property values either — so some checks (layout overflow,
exact pixel widths) may not be observable at all.

**What closes the gap:** Audit the six observer checks against the
redaction surface; rewrite the broken-image and missing-alt-text
checks to use `find` queries. Drop layout-overflow as deterministically
checkable on Medtrics pages — surface it only when the page's own JS
fires a layout warning to the console (covered by `console_warning`).

---

### GAP-25 — Optimus description has a hard byte cap that silently truncates · MEDIUM

**Filed:** 2026-06-06.

**Verified live (2026-06-06):** Filed M1-1223 ("QA1 Automation Plugin reference") with a ~5400-char description via `create_task`. Optimus stored the body truncated mid-word at section 5 ("How to author a QA checklist for a t") — roughly **~5000 chars**. Sections 5, 6, the Author-known context, and the Data Model Context line all dropped silently. The API did NOT return an error or warning; the response carried the truncated text verbatim. A follow-up `update_task` with a shortened ~4400-char body landed in full.

**Consequence:** `optimus_build_verdict_comment.py` appends a pointer block + verdict footer to the existing description on every run. If the existing description is anywhere near the cap, the verdict block gets eaten silently. This is the same description-length concern flagged in GAP-7's original text; today it has a concrete number.

**What closes the gap:**
- Add a length check in `optimus_build_verdict_comment.py` (and `find_pointer_block.py --upsert`) that computes `len(existing_description) + len(new_block_bytes)` and refuses or trims when it would exceed a safe cap. Conservative target: **4500 chars** of headroom after the existing body.
- On overflow, the plugin can (a) write the verdict block at the top of the description and trim the existing tail, surfacing the trim in the audit log, OR (b) refuse the description-update half of the write and keep the lane move + Mem note + Slack staging card (Mem becomes the canonical record).
- Document the cap and behavior in `qa-optimus-bridge/SKILL.md`.

**Discovered via:** filing the medtrics-qa-automation tester-reference feature ticket itself (M1-1223). The plugin's own documentation hit the very limit the plugin needs to handle for verdict updates.

---

## What this means in aggregate

The 9 immediate findings (in GAP-6) are line-level fixes. The 8
cascading findings (GAP-12 – GAP-19) are structural — they touch the
executor's per-step loop, the assertion vocabulary, the blocked-reason
enum, and the observer's introspection model.

The good news: the plugin's outer scaffolding (checklist read, MR
resolution, Cowork dashboard, Mem dedup, Optimus read, GitLab thread
posting just now proven live) is sound. The bad news: the inner loop —
the per-step `arm → action → drain → snapshot → judge` cycle — is
where the unverified design choices live. That's where v0.10's work
should concentrate.

Cumulative gap count after the audit: **19 open** (was 9), **1 closed**
(GAP-1).

**Update — v0.10.0 (2026-06-05):** Phase 1 of the fix-roadmap closed 6
more gaps (GAP-2, 3, 11, 13, 14, 19). Current count: **13 open**, **7
closed**.

**Update — v0.10.0 live exercise (2026-06-05, late):** Re-running
M1-1190 / MR !6865 with v0.10.0 produced a `pass` verdict (Block 182
edit form: `11 May 2026`/`31 May 2026` matches list view). Moving the
ticket from `needs_changes → qa2` via Optimus's MCP confirmed status
literal `qa2` works — **GAP-7's status-literal half is closed**. The
live exercise also surfaced **five new gaps**: GAP-20 through GAP-24.
Current count: **17 open**, **partially-closed GAP-7 plus the prior 7
fully closed**. See `docs/post-test-findings-2026-06-05.md` for the
patch list and Phase 2 implications.

**Update — M1-1223 filing (2026-06-06):** Filing the plugin's own
tester-reference feature ticket (M1-1194 + M1-1223) surfaced one more
gap: Optimus silently truncates descriptions at ~5000 chars (GAP-25).
Current count: **18 open**, 7 fully closed plus partial GAP-7.


**Filed:** 2026-06-04.

**The plugin assumes:** `qa-ui-executor` and `qa-chrome-executor` drive
Chrome MCP through the closed verb vocabulary (`navigate`, `click`,
`fill`, `upload`, `wait_for_text`, `screenshot`, `capture`) and build
`CapturedPage` projections from real DOM/console/network observations.

**Verified-against-code:** what actually exists:
- `scenario_dispatcher.py` is pure-Python and unit-tested with
  constructed `CapturedPage` fixtures (no real browser).
- `qa-ui-executor/SKILL.md` describes the Chrome MCP call sequence in
  prose.
- No script under the plugin drives Chrome MCP. No test exercises
  `mcp__Claude_in_Chrome__*` even with mocks.

The first real run against a real `<iid>.medtrics.dev` will be the
first time the plugin's CapturedPage assumptions meet reality. Likely
discoveries on that first run:
- The `tag`, `natural_width`, `alt`, `scroll_width`, `client_width`,
  `scroll_height`, `client_height`, `is_scrollable_declared` fields
  that `qa-ui-observer` consumes require ad-hoc JS evaluation via
  `mcp__Claude_in_Chrome__javascript_tool`. The exact JS to extract
  each field isn't written.
- `read_console_messages` and `read_network_requests` response shapes
  vary by Chrome MCP version; the observer's expected shape may not
  match.
- File upload via `file_upload(selector, fixture_path)` requires the
  fixture to exist at a path Chrome MCP can reach.

**Consequence:** Until the first live run, the entire UI lane is
spec'd-but-untested.

**What closes the gap:** One real end-to-end run against a known-good
ticket (e.g. M1-1190 → 6865.medtrics.dev with the live `.txt`
checklist). Walk every step manually first to confirm the deploy is
fully reachable; then run the executor in `--dry-run` to print its
action plan; then run it for real with `phase: shadow` so no Optimus
or GitLab writes fire. The audit log will surface what breaks.

---

### GAP-7 — Optimus write path (status-literal half) — **PARTIALLY CLOSED**

**Filed:** 2026-06-04. **Partial closure: 2026-06-05 (v0.10.0 live run).**

The `move_task` status-literal half of this gap is **closed** by the
live `needs_changes → qa2` move of M1-1190 on 2026-06-05. The literal
string `qa2` is accepted by Optimus as-is — no `qa_2`, `qa-2`, or
`qa-stage-2` variant required. Confirmed against the M1-1190 task
response: `status: "qa2"` post-move, `statusChangedAt: 2026-06-05T17:42:16Z`.

**Still open** (folded into GAP-20):
- `update_task` description-rewrite path with the verdict pointer block
  has NOT been live-exercised. The `optimus_build_verdict_comment.py`
  script produces the expected footer in isolation (smoke-tested
  2026-06-05); the round-trip splice + push has not run.
- `find_pointer_block.py --upsert` idempotency against a real Optimus
  description is untested.

These remaining concerns are tracked under GAP-20 below as part of the
broader "command-level orchestration unproven" gap.

---

### GAP-20 — `/manual-qa-execute` command-level orchestration is unproven · MEDIUM

**Filed:** 2026-06-05 (post-test findings).

**Verified:** Every M1-1190 audit run (today's v0.10.0 included) drove
the steps manually with Chrome MCP + Optimus MCP + bash. The
`/manual-qa-execute` command's orchestration sequence (steps 1–11 of
its prose) has never run as a single transaction.

**What HAS been smoke-tested in isolation** (2026-06-05 17:48 UTC):

| Script | Result |
|---|---|
| `scenario_dispatcher.py --plan-only` | Returns `{matched: false, verdict: needs_human}` for M1-1190 — correctly routes to UI lane. |
| `optimus_move_task.py` pass+shadow | exit 2, `audit_action: would_have_moved_to_qa2`. |
| `optimus_move_task.py` pass+writes-on | exit 0, args ready. |
| `optimus_move_task.py` blocked | exit 3, no move. |
| `optimus_build_verdict_comment.py` | one-line footer with target lane + run-log pointer. |

**What's still untested:** the script-to-script handoff (JSON shape +
exit-code routing inside the command's prose), the Mem write path, the
Slack staging-card post, and the description-update round-trip.

**What closes the gap:**
1. One `/manual-qa-execute M1-1190 --dry-run` invocation — exercises the
   dispatcher + plan emission without driving Chrome.
2. One full `/manual-qa-execute M1-1190` against a low-stakes test
   ticket — exercises the full pipeline including writes-on Optimus
   description update.

---

### GAP-21 — `find` returns dialogs that aren't visually painted · MEDIUM

**Filed:** 2026-06-05.

**Verified live (2026-06-05):** During the M1-1190 audit, `find("any
modal dialog visible")` returned `ref_401 dialog "Add Blocks"` — but
the screenshot proved that dialog was not on screen. Vue's `v-dialog`
keeps the markup in the DOM with `display: none` or off-viewport, and
the Chrome MCP a11y tree classifies it as "currently visible."

**Consequence:** A `qa-ui-executor` step that asserts "the Save dialog
opened" can pass against a hidden dialog. False-positive verdict.

**What closes the gap:** Two-step check — `find(...)` for presence in
the a11y tree, then a viewport-intersection probe (one-line JS via
`getBoundingClientRect`) to confirm visibility. The `settle` verb
proposed for GAP-17 needs `until=visible(ref)` as a built-in mode.

---

### GAP-22 — `computer.scroll_to(ref)` silently no-ops on detached elements · LOW

**Filed:** 2026-06-05.

**Verified live (2026-06-05):** Called `scroll_to(ref_401)` on the
ghost "Add Blocks" dialog. The screenshot taken immediately after was
identical to before. No error raised, no scroll occurred.

**Consequence:** A "scroll to row X before clicking Edit" sequence can
drift past the target without raising. The plugin can't distinguish
scroll-succeeded from scroll-noop.

**What closes the gap:** After `scroll_to`, the executor reads the
target's `getBoundingClientRect()` and asserts the rect intersects the
viewport. If not, raise `blocked_reason: scroll_failed`.

---

### GAP-23 — Verdict vocabulary lacks visual-vs-persistence dimension · MEDIUM

**Filed:** 2026-06-05.

**Verified live (2026-06-05):** The M1-1190 verdict reads as `pass`,
but the run only verified the visual-acceptance criterion ("edit form
shows the same dates as the list view"). Save was not clicked, so the
data-integrity criterion ("saved dates persist correctly") remains
unverified. The Optimus ticket is now in `qa2`, but the QA2 reviewer
has no signal that a sub-criterion was deferred.

**Consequence:** A ticket can pass display-only checks and still ship a
regression that breaks persistence. The current `pass | fail | partial
| blocked` vocabulary can't surface that distinction.

**What closes the gap:** Per-step `criterion: visual | persistence |
side_effect` field in the parsed checklist. The aggregate verdict
carries both dimensions, e.g. `verdict: pass · visual=pass ·
persistence=not_verified`. Rides on Phase 2's vocabulary extension
(GAP-15).

---

### GAP-24 — "Edit" pattern in Medtrics is inline-row, not modal-popup · LOW

**Filed:** 2026-06-05.

**Verified live (2026-06-05):** Clicking the row's `Edit` button on the
Manage Blocks page converted the row to inline-edit inputs in place —
no modal opened. The find tool's "modal dialog Add Blocks" was a
separate always-present dialog (the page's Add Blocks affordance), not
the edit result.

**Consequence:** `qa-ui-executor/SKILL.md` step 3 implies "after a
click, find the modal." For tickets like M1-1190 there's no modal —
the action surfaces inline inputs. Checklist authors don't know how to
phrase the "verify form opens" step.

**What closes the gap:** Two updates:
- `qa-ui-executor/SKILL.md` step 3 — when looking for the result of an
  Edit click, probe in order: (1) inline-row inputs in the clicked
  row, (2) modal dialog with viewport-visibility check (GAP-21 fix),
  (3) inline expansion panel beneath the row.
- A note in the checklist-author guide explaining the inline-edit
  pattern is the Medtrics convention for "Manage Blocks"-style screens.

---

### GAP-8 — Pointer-block upsert untested against real Optimus descriptions · MEDIUM

**Filed:** 2026-06-04.

**The plugin assumes:** `<!-- qa-automation:pointer:start -->` and
`<!-- qa-automation:pointer:end -->` HTML-comment markers survive
round-tripping through Optimus's description renderer.

**Verified-against-code:** `find_pointer_block.py` is unit-tested with
synthetic markdown. Never tested against a real Optimus task's
description after a real `update_task` write-and-readback.

**Likely failure modes:**
- Optimus may strip HTML comments on save (Notion-style renderers
  sometimes do).
- Optimus may render markdown such that `<!-- … -->` shows literally
  in the UI, breaking the human-readable description.
- A real description containing markdown code fences (```) with similar
  marker strings inside would conflict with the upsert regex.

**Consequence:** If markers don't round-trip, every re-run appends a
new pointer block instead of replacing the existing one — duplicating
content on the ticket.

**What closes the gap:** One round-trip test against a throwaway
Optimus ticket — write a description with the markers, read it back,
verify the markers are present in the response; then call upsert and
verify only one pointer block remains.

---

### GAP-9 — Scheduled-task creation has never been done end-to-end · HIGH

**Filed:** 2026-06-04.

**The plugin assumes:** `/setup-medtrics-qa-automation` step 5 creates
two scheduled tasks via `mcp__scheduled-tasks__create_scheduled_task`:
- `*/5 * * * *` → `/qa1-poll`
- `0 9 * * 3` (every other Wednesday) → `/regression-execute`

**Verified-against-code:** the only reference is in
`commands/setup-medtrics-qa-automation.md` step 5. No script exists. No
real Cowork session has executed setup against the scheduled-tasks MCP.

**Unknowns:**
- Whether `*/5 * * * *` actually fires every 5 min in Cowork (vs a
  longer minimum interval).
- Whether the scheduled task can chain multiple commands (e.g.
  `/qa1-poll && /manual-qa-execute --all --no-confirm`) in one
  invocation.
- Whether the scheduled task survives Cowork session restarts.

**Consequence:** Without the scheduled trigger, the entire "automated
QA1" promise reduces to manual `/qa1-poll` + `/manual-qa-execute --all`
on demand. The plugin still works; the operator has to be at the keyboard.

**What closes the gap:** One end-to-end setup run against a real
Cowork session; verify both tasks appear in
`mcp__scheduled-tasks__list_scheduled_tasks` and fire on cadence.

---

### GAP-10 — Phase transition has no automation or metric collection · LOW

**Filed:** 2026-06-04.

**The plugin assumes:** Moving from `shadow` to `writes-on` requires
"3 consecutive weeks with <5% false positives and zero missed P0 fails"
(per README phase table). Nothing measures this. The audit log
captures every verdict; no aggregator computes false-positive rate.

**Consequence:** The phase flag flip is a manual decision based on a
metric the plugin doesn't compute. Risk is one-sided (we'd flip too
early on vibes); the operational cost is low.

**What closes the gap:** A `/qa-phase-readiness` command that scans the
last 21 days of audit rows, computes false-positive rate against QA
Lead overrides recorded in Mem, and prints a go/no-go recommendation.
Out of scope for v0.9.x.

---

## Closed gaps

### GAP-19 — `gitlab_open_thread.py` returns a malformed `thread_url`

**Status:** **Closed by fix (2026-06-05, v0.10.0).** Replaced numeric-id
URL construction with `mr.web_url` + `#note_<id>`. Legacy form remains as
a logged-warning fallback if `web_url` is absent. 4 regression tests
under `skills/qa-gitlab-bridge/tests/test_open_thread.py`.

---

### GAP-14 — "Session inherited" detection is fragile

**Status:** **Closed by fix (2026-06-05, v0.10.0).** Replaced text-match
for "Sign in" with structural probe `find("password input")`. Update is
SKILL.md only — `qa-ui-executor/SKILL.md` Step 1.

---

### GAP-13 — Login-URL discovery is per-tenant, not per-app

**Status:** **Closed by fix (2026-06-05, v0.10.0).** New
`config.deploy.login_path` field (schema v0.9), default `/users/login`
(Medtrics canonical Devise path, verified across tenants 2026-06-05).
`qa-ui-executor` Step 1 navigates to that path first, then falls back to
the bare deploy root on 404 with the same structural probe. New
blocked-reason `login_form_not_found` for triage when neither path
surfaces a password input.

---

### GAP-11 — `qa-cache` is opt-in but no caller passes `--cache-ttl`

**Status:** **Closed by fix (2026-06-05, v0.10.0).** Defaults flipped:
`gitlab_get_mr.py` → `--cache-ttl 300`, `gitlab_get_pipeline_status.py`
→ `--cache-ttl 120`, `gitlab_download_upload.py` → `--cache-ttl 600`
(uploads are immutable per secret/filename; download script now uses the
cache, encoding bytes as base64 in the JSON-backed cache). `--no-cache`
remains the bypass. 6 regression tests under
`skills/qa-gitlab-bridge/tests/test_cache_defaults.py`.

---

### GAP-3 — `scenario-matrix.yaml` has 2 of 3 rules with empty `scenarios[]`

**Status:** **Closed by fix (2026-06-05, v0.10.0).** Added `disabled` to
`Rule` dataclass and matrix loader; `match_rule` skips disabled rules.
`missing_required_field` and `role_permission_regression` flagged
`disabled: true` in `qa/scenario-matrix.yaml` until they're populated
with real assertions. Re-enable by flipping the flag once scenarios are
added. 3 regression tests under
`skills/qa-chrome-executor/tests/test_matrix_disabled.py`.

---

### GAP-2 — Mem `QA Run Logs` collection does not exist

**Status:** **Closed by fix (2026-06-05, v0.10.0).** Removed the
hardcoded placeholder UUID from `qa-memory/SKILL.md`,
`qa-queue/SKILL.md`, and `build_dashboard_widget.py`'s example. All
readers now resolve the UUID from `config.mem.run_logs_collection_id`.
The dashboard builder hard-refuses to render with a null UUID — the
operator gets an actionable error pointing at
`/setup-medtrics-qa-automation` instead of a silently-empty widget.
Note: the **live provisioning of the Mem collection itself** is still a
one-time setup-time step (`/setup-medtrics-qa-automation` step 4);
that's per-install state, not a code change.

---

### GAP-1 — Test-persona seeding on per-MR deploys

**Status:** **Closed by obsolescence (2026-06-04, v0.9.3).** The plugin no
longer assumes the six personas exist. Removed `personas-schema.yaml`,
removed `check_persona` from `qa-guardrails`, removed the `QA_PERSONA_*`
env convention from the docs. Login is now declared inside each checklist
as a normal step (`Log in as <email>`), so the eng-side `seed_qa_personas`
work isn't a blocker for unattended mode — the checklist author picks
whichever real user exists on the deploy and embeds the credentials in
the test plan.

The original gap text is preserved below for context.

---

**Original gap (filed 2026-06-03):**

The plugin assumed: Six test users existed on every `<iid>.medtrics.dev`
deploy — `qa-admin@`, `qa-coordinator@`, `qa-pd@`, `qa-attending@`,
`qa-trainee@`, `qa-external@`, all `@test.medtrics.invalid`. Their
passwords came from `QA_PERSONA_<ROLE>` environment variables.

Verified-against-code (2026-06-03):

| Check | Result |
|---|---|
| `seed_qa_personas` Django management command exists? | **No** |
| Any `qa-*@test.medtrics.invalid` users in fixtures or initial_data? | **No** |
| What user IS seeded by `loadinitialdata`? | One — `admin@medtricslab.com` / password `admin` |
| When does that seed run? | Only on a clean database — not run per-MR |

**Owner (pre-closure):** Eng (medtrics-legacy + medtrics/infra). The gap
was closed by removing the dependency on this work, not by completing it.

---

## Verified capabilities (the surface that DOES work today)

For honesty's sake, here's what's proven against a real system or
covered by tests that mirror the real shape:

| Capability | Status | Evidence |
|---|---|---|
| GitLab MR fetch (`gitlab_get_mr.py`) | ✅ Verified live | MR !6865, !6834, !6849 resolved correctly; new resolver returns `deploy_strategy=environment_lookup` |
| GitLab pipeline-status fetch (`gitlab_get_pipeline_status.py`) | ✅ Verified live | MR 6865 returned `success` |
| GitLab MR thread-attachment download (`gitlab_find_mr_attachment.py` + `gitlab_download_upload.py`) | ✅ Verified live | MR 6865's `.txt` checklist found by branch-slug, downloaded (8873 bytes) |
| GitLab `/uploads` API path (the right one to use) | ✅ Verified live | API path works; raw `/uploads/...` URL returns Cloudflare 403 (documented) |
| Checklist parsing (`parse_checklist_steps.py`) | ✅ Verified live | Your real M1-1190 checklist parsed to 12 structured P1 steps |
| Checklist-block extraction (`extract_checklist_block.py`) | ✅ Verified live | Strips pointer block, isolates `## QA Checklist` section |
| Cowork artifact creation | ✅ Verified live | `qa1-queue-dashboard` provisioned in this session against your real Optimus queue (8 tickets rendered) |
| `unwrapMcp` response shape handling | ✅ Verified live | Three-shape cascade tested against the actual Cowork bridge return shape |
| Optimus `list_lane_tasks` read | ✅ Verified live | Pulled 8 qa1 tickets for the medtrics product |
| Optimus `get_task` read | ✅ Implicit (used by checklist-reader proofs) | — |
| Mem `list_collections` / `list_notes` reads | ✅ Verified live | 21 collections listed; reads work even though the QA-specific collection doesn't exist yet |
| Optimus `move_task` / `update_task` writes | ⚠️ Spec-only (GAP-7) | — |
| GitLab `open_thread` / `upload_file` writes | ⚠️ Spec-only | Scripts exist; never fired in writes-on phase against a real MR |
| Slack `slack_send_message` | ❌ Spec-only (GAP-5) | No wrapper, no test |
| Chrome MCP step execution | ❌ Spec-only (GAP-6) | scenario_dispatcher.py is unit-tested; no real Chrome MCP drive |
| Scheduled task creation | ❌ Spec-only (GAP-9) | — |
| Pointer-block upsert against real description | ❌ Spec-only (GAP-8) | Pure-Python markers tested; round-trip through Optimus untested |
| Mem `QA Run Logs` collection writes | ❌ Spec-only (GAP-2) | Collection doesn't exist |
| `/regression-execute` | ❌ Spec-only (GAP-4) | Module checklists don't exist |
| `qa-cache` actually fires | ⚠️ Opt-in but unused (GAP-11) | Tests pass; default off |
| API-lane matrix execution | ⚠️ 1 of 3 rules populated (GAP-3) | Live: `import_template_encoding`; stubs: 2 |

So roughly **eight things work for real**, **eight things are spec-only**,
and **two have partial coverage**. The plugin's mental model is sound;
the proof against reality is where the work remains.
