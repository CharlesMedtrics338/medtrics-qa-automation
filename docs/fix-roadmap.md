# medtrics-qa-automation — fix roadmap (v0.10 → v0.14)

A plan for closing the 18 open gaps in `engineering-gaps.md`, ordered by
dependency. Each phase ships one coherent capability. Read this top-to-bottom
to see *why* each gap lands when it does.

This is a **planning document**, not implementation. Each phase entry below
estimates the work + names the files touched + flags dependencies. Nothing
in the working tree changes from this doc alone.

---

## The shape of the work

Looking at all 18 open gaps, they cluster into **five themes**:

| Theme | Gaps | What it costs |
|---|---|---|
| **Quick wins** — line-level fixes, no design needed | GAP-3, GAP-11, GAP-13, GAP-14, GAP-19 | ~60 LOC total |
| **Bootstrap** — provisioning real-world state | GAP-2 | Configuration + 1 setup run |
| **Inner-loop architecture** — the heart of the executor | GAP-6 findings + GAP-12 + GAP-15 + GAP-16 + GAP-17 | ~400 LOC + new tests |
| **Write paths** — first live exercises of unproven integrations | GAP-5, GAP-7, GAP-8, GAP-18 | ~200 LOC + careful live testing |
| **Content + scheduling + ops** | GAP-4, GAP-9, GAP-10 | Author-time + 1 setup run |

Map each theme to a release. Five releases planned: **v0.10.0** (quick wins
+ bootstrap), **v0.11.0** (inner-loop refactor — the big one), **v0.12.0**
(write paths), **v0.13.0** (content + scheduling), **v0.14.0** (ops). Each
release stays small enough to test, big enough to be meaningful.

---

## Phase 1 — v0.10.0 · Quick wins + Mem bootstrap

**Time estimate:** 1 day. **Risk:** low — line-level, well-scoped.
**Net gap closure:** 6 gaps (GAP-2, GAP-3, GAP-11, GAP-13, GAP-14, GAP-19).

### v0.10.0 scope

**GAP-19 · Fix `gitlab_open_thread.py` thread_url construction** · LOW
- Use `mr.web_url` (from `get_mr`) as the base, append `#note_<note_id>`.
- Files: `skills/qa-gitlab-bridge/scripts/gitlab_open_thread.py` (~5 LOC).
- Test: add a case to `test_open_thread.py` (if not present, create it)
  asserting the URL contains the namespace path, not the numeric ID.

**GAP-11 · Default `--cache-ttl` to a non-zero value** · LOW
- `gitlab_get_mr.py`: default 300s. `gitlab_get_pipeline_status.py`: default 120s.
- Add `--no-cache` (already exists) as the bypass for callers that need
  authoritative reads.
- Files: 2 scripts, ~1 LOC change each.
- Test: existing tests still pass; add one that confirms a default-args
  invocation produces a cached payload after the second call.

**GAP-3 · Disable the two empty scenario-matrix rules** · MEDIUM
- Add a `disabled: true` field to the YAML schema. Set it on
  `missing_required_field` and `role_permission_regression`.
- `scenario_dispatcher.match_rule()` skips disabled rules.
- Files: `qa/scenario-matrix.yaml`, `skills/qa-chrome-executor/scripts/scenario_dispatcher.py`.
- Test: add a case to `test_ui_assertions.py` (or a new test file)
  verifying a disabled rule is never matched.

**GAP-13 · Login-URL discovery (no more hardcoded `/login` or `/users/login/`)** · MEDIUM
- New procedure in `qa-ui-executor/SKILL.md` step 1:
  1. Navigate to `mr_resolution.deploy_url` (bare root).
  2. Read final URL after the redirect via `tabs_context_mcp`.
  3. If the final URL contains `/login` (case-insensitive) OR `find` returns
     a password input on the page → it's the auth surface.
- No new code; SKILL.md procedure update only. Caller is the executor's
  step 1 prose.

**GAP-14 · Replace text-based "session inherited" detection with structural check** · MEDIUM
- `qa-ui-executor/SKILL.md` step 1: use `find("password input")` instead
  of text-matching "Sign in." If `find` returns a match → not authenticated.
- SKILL.md change only.

**GAP-2 · Provision the Mem `QA Run Logs` collection** · HIGH ← the unblocker
- Run `/setup-medtrics-qa-automation` against the live Mem instance. Setup
  step 4 already does `create_collection("QA Run Logs")` and records the
  returned UUID in `config.json`.
- Then remove the three hardcoded UUID references in favor of reading
  `config.mem.run_logs_collection_id`:
  - `skills/qa-memory/SKILL.md` line 58
  - `skills/qa-queue/SKILL.md` line 47
  - `skills/qa-queue/scripts/build_dashboard_widget.py` line 27 (CLI example)
- Files touched: 3 docs, 1 script (~10 LOC total).
- Unblocks GAP-7 (first Optimus write) and the dashboard's enrichment.

### v0.10.0 deliverable
- Plugin still 148 tests + ~3 new for the bug fixes.
- Real Mem collection exists; the four hardcoded references replaced.
- `gitlab_open_thread.py` returns a working `thread_url` next time it
  posts.
- Caching enabled by default.
- The two empty matrix rules no longer fire false matches.

---

## Phase 2 — v0.11.0 · Inner-loop architecture (the big one)

**Time estimate:** 3–5 days. **Risk:** medium — a real refactor.
**Net gap closure:** 9 gaps (all 9 findings inside GAP-6, plus GAP-12, GAP-15, GAP-16, GAP-17).

This is one architectural change with several visible surfaces. The whole
phase ships together because each piece depends on the others.

### The core idea

Today the executor does:

```
for step in test_plan_steps:
    drive_chrome(step.action)
    page = build_captured_page()      # snapshot AFTER
    run_ui_assertions(page, assertions)
```

The audit proved this misses everything that happens **during** the
action — the POST that fired, the console error thrown by the handler,
the navigation that redirected mid-step. The fix is to flip the model:

```
for step in test_plan_steps:
    arm_captures()                    # clear console + clear network
    drive_chrome(step.action)
    settle()                          # GAP-17 — wait for DOM to stop mutating
    trace = build_step_trace()        # during-events + after-snapshot
    run_ui_assertions(trace, assertions)
```

### v0.11.0 scope (the seven deliverables)

**GAP-12 · `StepTrace` data class + per-step runner** · HIGH
- New file: `skills/qa-ui-executor/scripts/step_runner.py` (~150 LOC).
- The runner: arms via `read_network_requests({clear: true})` +
  `read_console_messages({clear: true})`, drives the verb, settles, drains
  via the same two tools (no `clear`), builds an after-snapshot via
  `find` + targeted JS reads.
- New data class `StepTrace`:
  ```python
  @dataclass
  class StepTrace:
      step_id: str
      verb: str
      action: dict
      armed_at: str
      completed_at: str
      during: dict          # {console, network, downloads}
      after: dict           # {url, title, elements, page_text}
  ```
- Files: new `step_runner.py`; updates to `qa-ui-executor/SKILL.md` steps 2–5.

**GAP-15 · Extend `run_ui_assertions()` with four new kinds** · MEDIUM
- New kinds, each ~10 LOC implementation + ~3 tests:
  - `value_persisted_after_save(selector, expected)`
  - `network_request_fired(method, url_pattern)`
  - `network_response_status(url_pattern, status_eq|status_in_range)`
  - `console_warning_present(pattern)`
- Update `ALLOWED_UI_ASSERTION_KINDS` in `scenario_dispatcher.py`.
- Update `templates/expected-to-assertion.md` with `Expected:` text
  patterns that map to each new kind (e.g., `"the row keeps showing X"`
  → `value_persisted_after_save`).
- Files: `skills/qa-chrome-executor/scripts/scenario_dispatcher.py`,
  `skills/qa-ui-executor/templates/expected-to-assertion.md`.

**GAP-16 · Add `verification_inconclusive` blocked-reason** · MEDIUM
- Add to the vocabulary in `qa-config/SKILL.md`.
- `qa-ui-executor` returns this verdict when an assertion can't prove
  the expected outcome (e.g., `network_request_fired` is part of the
  assertion list but the during-trace shows no request).
- Files: `skills/qa-config/SKILL.md`, `skills/qa-ui-executor/SKILL.md`.

**GAP-17 · `settle` verb in the closed verb vocabulary** · MEDIUM
- New verb in `qa-ui-executor`: `settle(timeout_ms=2000, until=None)`.
  - With `until`: poll until the find-query matches (or doesn't).
  - Without: poll the DOM until two consecutive snapshots are identical
    for K=200ms.
- Default behavior: `qa-ui-executor` calls `settle(2000)` after every
  `click`, `fill`, `upload`, `submit_form` — automatic, not a separate step.
- Files: `skills/qa-ui-executor/SKILL.md`, `skills/qa-ui-executor/scripts/step_runner.py`.

**GAP-6 finding #1 · Catch screenshot permission-denied in qa-fail-reporter** · HIGH
- `qa-fail-reporter` already has a fallback for upload failures. Extend
  the same path to handle `Permission denied for this action on this domain`.
- Set `screenshot_ref: null` on the step; thread footer notes
  "Screenshots not available for this deploy domain — grant permission in Chrome MCP to enable."
- Files: `skills/qa-fail-reporter/SKILL.md`, `skills/qa-fail-reporter/scripts/build_fail_thread.py`.

**GAP-6 finding #2 · Verify-after-navigate retry pattern** · HIGH
- `step_runner.py` (from GAP-12) handles this: every `navigate` is
  followed by a `tabs_context_mcp` check; if URL didn't commit, retry once.
- Folded into the per-step loop.

**GAP-6 finding #4 + #5 · Use `find` not raw JS for form/element introspection** · MEDIUM
- `step_runner.py` builds the after-snapshot's `elements` field via
  `find` queries listed by the step's assertions (not via blanket
  `document.querySelectorAll`).
- Same change handles finding #6 (URL redaction) — we never read href
  directly.
- Documented in `qa-ui-executor/SKILL.md` step 3.

**GAP-6 finding #7 · Vue reactivity dispatch on `fill`** · HIGH
- `step_runner.py`'s `fill` verb wraps `form_input` plus a `javascript_tool`
  call that fires `new Event('input', {bubbles: true})` and
  `new Event('change', {bubbles: true})` on the underlying input.
- Files: `step_runner.py` + a test.

### v0.11.0 deliverable
- ~400 LOC of new code in `step_runner.py`.
- 4 new assertion kinds + ~12 new tests.
- `qa-ui-executor` SKILL.md rewritten around the new flow.
- After this phase, the M1-1190 audit could be RE-run against the same
  MR 6865 and produce a real verdict, not `partial`.

### v0.11.0 acceptance test
**The same M1-1190 audit re-run**:
- Pick non-conflicting edit dates (e.g. `13 May 2026 – 02 Jun 2026`
  reverted via Block 2's start, OR shift end by one day only).
- Run end-to-end. Verdict should be `pass` (the fix works) or `fail`
  (with `network_response_status` showing the 4xx).
- No `verification_inconclusive` outcome — the new vocabulary disambiguates.

---

## Phase 3 — v0.12.0 · Write paths + observer hardening

**Time estimate:** 2–3 days. **Risk:** medium — first real writes to Optimus.
**Net gap closure:** 4 gaps (GAP-5, GAP-7, GAP-8, GAP-18).

### v0.12.0 scope

**GAP-5 · Slack integration scripts** · MEDIUM
- New skill: `skills/qa-slack-bridge/` (or fold into `qa-fail-reporter`).
- Scripts:
  - `slack_post_staging_card.py` — per-verdict Slack staging card.
    Reads run-log JSON, posts a structured message to
    `config.slack.staging_channel`.
  - `slack_post_regression_rollup.py` — bi-weekly summary to
    `#dream-team`.
- Tests use `mock.patch` over `mcp__5f6545e3-…__slack_send_message`.
- Files: ~60 LOC + 5 tests.
- Wire into `commands/manual-qa-execute.md` step 9 (Slack staging card)
  and `commands/regression-execute.md` step 4 (roll-up).

**GAP-7 · First live Optimus write** · HIGH
- One careful end-to-end execution of `optimus_move_task.py` payload
  → `mcp__904fdec1-…__move_task` against a low-stakes throwaway ticket.
- Verify: does Optimus accept `status="qa2"` literally? Or does it need
  `"qa_2"`, `"qa-2"`, etc.?
- If the literal value works, no code change. If not, update
  `DEFAULT_LANES` in `optimus_move_task.py`.
- Also exercise `update_task(task, description=...)` with the verdict
  pointer block to test GAP-8 simultaneously.
- Files: zero on success; some on failure.

**GAP-8 · Pointer-block round-trip against real Optimus** · MEDIUM
- Combined with GAP-7's first live write. After the update_task,
  immediately re-fetch the task and verify:
  - The `<!-- qa-automation:pointer:start -->` markers survived.
  - `find_pointer_block.py --upsert` on a re-run replaces in place (no
    duplicate blocks).
- If markers are stripped by Optimus's renderer, switch to a
  text-based delimiter (`---qa-automation-pointer-start---` or similar).
- Files: maybe `qa-checklist-reader/templates/pointer-block.md`,
  maybe `find_pointer_block.py`.

**GAP-18 · `qa-ui-observer` redaction-aware checks** · MEDIUM
- Audit each of the 6 observation kinds:
  - `console_warning` ✅ unaffected (console isn't redacted).
  - `deprecated_api_warning` ✅ unaffected.
  - `asset_load_error` ✅ unaffected (network URLs are visible).
  - `broken_image` ⚠️ may hit redaction — rewrite to use `find("img elements with no visible content")`.
  - `missing_alt_text` ⚠️ same — rewrite to use `find`.
  - `layout_overflow` ❌ probably not feasible deterministically on
    Medtrics pages. Drop and surface only via `console_warning` when
    the page's own JS fires a layout-warning event.
- Files: `skills/qa-ui-observer/scripts/check_observations.py`,
  `skills/qa-ui-observer/SKILL.md`, tests.

### v0.12.0 deliverable
- Slack integration proven live (staging card on first run).
- Optimus write path proven live (one ticket moved).
- Pointer-block round-trip confirmed (or fixed if it didn't round-trip).
- Observer's redaction-prone checks corrected.

### v0.12.0 acceptance test
- One full pass on M1-1190 — verdict moves the ticket, posts a Slack
  card, updates the Optimus description with the verdict pointer block.

---

## Phase 4 — v0.13.0 · Content + scheduling

**Time estimate:** 1–2 days (mostly authoring). **Risk:** low.
**Net gap closure:** 2 gaps (GAP-4, GAP-9).

### v0.13.0 scope

**GAP-4 · Author regression module checklists** · MEDIUM
- Files (need authoring by QA Lead or module owners):
  - `qa/regression/scheduling/checklist.md`
  - `qa/regression/evaluations/checklist.md`
  - `qa/regression/forms/checklist.md` (Phase 3 enablement)
  - `qa/regression/reports/checklist.md` (Phase 3 enablement)
- Same `## QA Checklist` format as per-ticket files.
- Plugin code change: zero. This is content work.

**GAP-9 · Schedule the polling and regression tasks live** · HIGH
- Run `/setup-medtrics-qa-automation` step 5 against a real Cowork
  session, accepting both scheduled-task creations.
- Verify both appear in `mcp__scheduled-tasks__list_scheduled_tasks`.
- Wait one full polling cycle (5 min). Verify the audit log records a
  `poll_completed` row.
- If anything breaks, document discoveries (cron format, command
  chaining, etc.) and fix in v0.13.1.

### v0.13.0 deliverable
- Bi-weekly regression suite is runnable (`/regression-execute --module scheduling`).
- 5-minute polling is live in production.

---

## Phase 5 — v0.14.0 · Operational metrics

**Time estimate:** 1 day. **Risk:** low.
**Net gap closure:** 1 gap (GAP-10).

### v0.14.0 scope

**GAP-10 · Phase-transition readiness metrics** · LOW
- New command: `/qa-phase-readiness`.
- Procedure: scan the last 21 days of `~/.medtrics-qa-automation/audit.jsonl`,
  compute false-positive rate (verdicts overridden by the QA Lead within 24h),
  print go/no-go recommendation for flipping `phase: writes-on`.
- Files: `commands/qa-phase-readiness.md`, optional helper script
  `skills/qa-audit/scripts/compute_fp_rate.py`.

### v0.14.0 deliverable
- The "3 consecutive weeks of <5% false positives" gate is computable.

---

## Summary table

| Phase | Version | Gaps closed | New code | New tests | Risk | Days |
|---|---|---|---|---|---|---|
| 1 | v0.10.0 | 6 (GAP-2, 3, 11, 13, 14, 19) | ~30 LOC | ~5 | low | 1 |
| 2 | v0.11.0 | 9 (GAP-6 ×9 findings + GAP-12, 15, 16, 17 — overlap) | ~400 LOC | ~15 | medium | 3–5 |
| 3 | v0.12.0 | 4 (GAP-5, 7, 8, 18) | ~200 LOC | ~8 | medium | 2–3 |
| 4 | v0.13.0 | 2 (GAP-4, 9) | ~0 LOC (content + provisioning) | 0 | low | 1–2 |
| 5 | v0.14.0 | 1 (GAP-10) | ~80 LOC | ~3 | low | 1 |
| **Total** | — | **18 of 18** | **~710 LOC** | **~31** | — | **8–12 days** |

Plus the 9 findings in GAP-6 close out as part of Phase 2 (already counted).

## Dependency graph

```
v0.10.0  ─►  v0.11.0  ─►  v0.12.0  ─►  v0.13.0  ─►  v0.14.0
   │           │              │              │              │
   GAP-2       Inner-loop     First live     Content +      Phase
   bootstrap   architecture   write paths    scheduling     metrics
   unblocks    (the heart     (rides on      (rides on      (rides on
   GAP-7       of the         working        working        sustained
   downstream  executor)      inner loop)    write paths)   ops data)
```

Phase 1 unblocks Phase 3 (GAP-2 must exist before GAP-7's Optimus write
test makes sense). Phase 2 unblocks Phase 3 (write paths need the
StepTrace verdict to be trustworthy). Phase 4 needs Phase 3 (scheduling
chains `/qa1-poll && /manual-qa-execute --all` which depends on writes
working). Phase 5 needs Phases 1–4 (metrics needs real audit data).

## What this plan does NOT include

- **The 9 specific Chrome MCP findings in GAP-6** are absorbed into Phase 2's
  architectural changes (the `step_runner.py` refactor closes findings
  #1, #2, #4, #5, #6, #7, #8, #9 simultaneously; finding #3 — wrong
  login URL — is closed by GAP-13 in Phase 1).
- **Refactoring `scenario_dispatcher.py`** more than necessary. Keep its
  core (`load_matrix`, `match_rule`, `run_assertions`, `aggregate`)
  stable; only extend the assertion vocabulary.
- **Replacing `qa-cache`**. It works; just turn it on by default in
  Phase 1 (GAP-11).
- **Re-running the M1-1190 audit** after each phase. Recommended at the
  end of Phase 2 and Phase 3 as acceptance tests.

## Decisions the user should make before Phase 2 starts

1. **The `StepTrace` schema** (above) — is the `during` / `after` split
   the right shape? Or should it be a single flat record with
   `events_during_step: [...]`?
2. **The four new assertion kinds in GAP-15** — are these the right
   four? Are there others (e.g., `dom_diff_present`,
   `element_attribute_eq`) that would be more useful?
3. **Slack integration in v0.12 vs v0.11** — if you want the audit-run
   experience to include Slack staging cards sooner, swap them.
4. **GAP-4 ownership** — the regression checklists need authoring, not
   coding. Should that be your work, or QA Lead?

## How to use this plan

- Read it once start-to-finish to confirm the shape.
- Pick one phase to start. Don't try to do multiple in parallel — the
  dependency chain matters.
- When a phase ships, update `engineering-gaps.md` to move the closed
  gaps to the "Closed gaps" section with the version + a one-line
  ship note.
- This document gets revised after each phase based on what we learn.
