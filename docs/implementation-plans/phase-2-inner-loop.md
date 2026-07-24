# Phase 2 — v0.11.0 · Inner-loop architecture

## Goal

Replace the per-step `action → snapshot → judge` flow with `arm → action → settle → drain → snapshot → judge`. After this phase, the executor sees during-action events (network requests, console warnings), the M1-1190 audit re-runs and produces a real verdict instead of `partial`, and the assertion vocabulary covers what the audit actually needed to express.

This is the architectural bet of the whole plan. Nine gaps collapse into one coherent refactor.

## Why this is one phase, not nine

The audit surfaced nine Chrome MCP-related findings (GAP-6 #1–#9) and four cascading architectural gaps (GAP-12, 15, 16, 17). If we patched each finding in isolation, we'd touch `qa-ui-executor` nine times for nine slightly different reasons, each leaving the next finding's fix harder. Treating them as one refactor lets the new shape — `StepTrace` plus the per-step runner plus the expanded assertion vocabulary plus the `settle` verb — close all nine simultaneously.

## The core idea (diagram)

```
                       BEFORE                                          AFTER
                     ─────────                                       ─────────
  for step in plan:                            for step in plan:
      drive(step.action)                           arm()                       ← clear console + network
      page = snapshot()                            drive(step.action)          ← + Vue reactivity dispatch
      judge(page, step.assertions)                 settle(2000)                ← wait for DOM stability
                                                   during = drain()            ← read console + network (no clear)
                                                   after = snapshot()
                                                   trace = StepTrace(during, after, …)
                                                   judge(trace, step.assertions)
```

The bottom-most call (`judge`) takes a richer input. Every assertion kind keeps working; four new kinds are added that read from `trace.during` (the during-events).

## Gaps closed

### GAP-12 · Snapshot becomes a trace · HIGH (the heart of the refactor)

**Files (new)**
- `skills/qa-ui-executor/scripts/step_runner.py` — ~150 LOC.
- `skills/qa-ui-executor/scripts/step_trace.py` — data class file, ~40 LOC.
- `skills/qa-ui-executor/tests/test_step_runner.py` — ~80 LOC.

**Files (modified)**
- `skills/qa-ui-executor/SKILL.md` — Steps 2–5 rewritten around `run_step()`.
- `skills/qa-chrome-executor/scripts/scenario_dispatcher.py` — `run_ui_assertions` signature accepts `StepTrace` (back-compat shim accepts `CapturedPage` and converts).

**The `StepTrace` shape**

```python
@dataclass(frozen=True)
class StepTrace:
    step_id: str
    verb: str                       # "click" | "fill" | "navigate" | "submit_form" | "upload" | "settle"
    action: dict                    # the original step.action payload
    armed_at: str                   # ISO 8601 UTC
    completed_at: str               # ISO 8601 UTC
    during: DuringEvents            # captured between arm and drain
    after: AfterSnapshot            # captured after settle
    blocked: bool
    blocked_reason: Optional[str]   # one of the closed-vocabulary reasons

@dataclass(frozen=True)
class DuringEvents:
    console: List[ConsoleMsg]       # {level, text, timestamp, source}
    network: List[NetworkEvent]     # {method, url, status, started_at, ended_at}
    downloads: List[Download]       # {filename, mime_type, started_at}

@dataclass(frozen=True)
class AfterSnapshot:
    url: str
    title: str
    elements: Dict[str, FindResult] # keyed by selector; lazily populated by assertions
    page_text: Optional[str]        # only fetched if any assertion requires it
```

The `elements` field is lazily populated — `step_runner` doesn't blanket-grab every node. An assertion that needs an element calls `find(selector)` through a helper that caches into `trace.after.elements`.

**The `run_step()` outline (pseudocode, NOT code-to-write)**

```python
def run_step(step: Step, ctx: ExecutionContext) -> StepTrace:
    armed_at = now()
    arm_captures(ctx)                              # clear console + network
    try:
        verb_result = drive(step, ctx)             # dispatch to verb handler
    except BlockedError as exc:
        return StepTrace(blocked=True, blocked_reason=exc.reason, ...)
    settle(timeout_ms=step.settle_ms or 2000)      # GAP-17
    during = drain_captures(ctx)                   # read console + network (no clear)
    after = snapshot_after(ctx, step.assertions)   # find-only, lazy
    completed_at = now()
    return StepTrace(...)
```

**Tests**
- `test_step_runner_arm_drain_cycle` — patch the Chrome MCP tools; assert clear-before-drive, no-clear-after.
- `test_step_runner_records_during_events` — inject a fake POST during the verb; assert `trace.during.network` contains it.
- `test_step_runner_records_console_warning` — inject a `console.warn` during the verb; assert it appears.
- `test_step_runner_blocked_propagates` — drive raises; trace has `blocked=True` + reason.

**Acceptance**
- Re-run M1-1190 audit; the deprecation warning that fires on page render appears in `trace.during.console` of step 4 (the `save` step).

---

### GAP-15 · Four new assertion kinds · MEDIUM

**Files (modified)**
- `skills/qa-chrome-executor/scripts/scenario_dispatcher.py` — extend `ALLOWED_UI_ASSERTION_KINDS` + add 4 dispatch arms.
- `skills/qa-ui-executor/templates/expected-to-assertion.md` — add Expected-text patterns mapping to each new kind.
- `skills/qa-chrome-executor/tests/test_ui_assertions.py` — ~12 new test cases.

**The four kinds (specs)**

1. **`value_persisted_after_save(selector, expected)`**
   - Reads `trace.after.elements[selector].value` (or `.text` for non-input).
   - Passes iff the value equals `expected`.
   - Expected-text trigger: `"the row keeps showing X"`, `"the value persists as X"`, `"after save, X is still displayed"`.

2. **`network_request_fired(method, url_pattern)`**
   - Reads `trace.during.network`.
   - Passes iff any event matches both `method` (exact) and `url_pattern` (regex).
   - Expected-text trigger: `"a POST is made to /api/blocks/save"`, `"the X endpoint is called"`.

3. **`network_response_status(url_pattern, status_eq | status_in_range)`**
   - Reads `trace.during.network`.
   - Picks the latest event whose URL matches `url_pattern`; passes iff its status matches.
   - Args are exclusive — either `status_eq: 200` or `status_in_range: [200, 299]`.
   - Expected-text trigger: `"the save returns 2xx"`, `"the request succeeds"`.

4. **`console_warning_present(pattern)`**
   - Reads `trace.during.console`.
   - Passes iff any message with `level=warn` matches the regex.
   - Note: when this kind is part of a step where the warning is EXPECTED (e.g., a known-deprecated path), it asserts presence. When the warning is unwanted, use the existing `no_console_warnings` assertion instead.

**Tests**
- Per kind: one passing case, one failing case, one edge case (regex special chars, status range boundary, etc.).

**Acceptance**
- M1-1190 re-run: the step that submits the edit form has `network_response_status(url_pattern=".*save.*", status_in_range=[200,299])` and passes (or fails with a clear status).

---

### GAP-16 · `verification_inconclusive` blocked-reason · MEDIUM

**Files (modified)**
- `skills/qa-config/SKILL.md` — add to the closed vocabulary of `blocked_reason`.
- `skills/qa-ui-executor/SKILL.md` — when to emit it.
- `skills/qa-chrome-executor/tests/test_ui_assertions.py` — one test.

**When to emit**
- An assertion kind requires `trace.during.network` to contain at least one matching event AND the trace contains zero network events at all (i.e., the drain returned nothing). This means the page never actually called the network for this step — could be a misconfigured assertion OR a real bug where the JS didn't fire. Don't pass; don't fail; emit `verification_inconclusive`.
- Similarly when `network_response_status` is asked but no matching URL exists in the trace at all (vs. matching URL with wrong status — that's a real `fail`).

**Why it matters**
- Today, "assertions couldn't determine pass/fail" gets reported as `partial`. `partial` is overloaded — sometimes it means "some assertions failed", sometimes "couldn't tell". This disambiguates.

**Tests**
- `test_inconclusive_when_no_matching_network` — set up a step with a `network_request_fired` assertion; provide an empty trace.during.network; assert verdict is `verification_inconclusive`.

**Acceptance**
- Audit log on a re-run never has `partial` paired with "couldn't observe" prose.

---

### GAP-17 · The `settle` verb · MEDIUM

**Files (modified)**
- `skills/qa-ui-executor/SKILL.md` — add `settle` to the closed verb vocabulary.
- `skills/qa-ui-executor/scripts/step_runner.py` — the `_settle()` helper.
- `skills/qa-ui-executor/tests/test_step_runner.py` — 2 tests.

**Settle behaviors (specs)**

- **No-args / `settle(timeout_ms=2000)`** — DOM stability mode.
  - Loop: every 100ms, snapshot `document.documentElement.outerHTML.length` (cheap proxy).
  - Settled when 2 consecutive snapshots are identical and 200ms has passed without a change.
  - Bounded by `timeout_ms` — return either way after the cap.
- **`settle(timeout_ms, until=FindQuery)`** — predicate mode.
  - Loop: every 100ms, call `find(until)`.
  - Settled the moment `find` matches.
  - Bounded by `timeout_ms`.

**Auto-settle policy**
- `step_runner.run_step` calls `_settle(2000)` automatically after `click`, `fill`, `upload`, `submit_form`. No author-side change to checklists.
- `navigate` calls `_settle(5000)` (longer for page loads).
- Authors can override with `settle_ms` field on the step OR insert an explicit `settle` step with an `until` predicate when they need to wait for a specific element to appear.

**Tests**
- `test_settle_returns_on_stability` — patch the DOM-length probe to return 100, 100, 200, 200, 200; assert settle returns after the second 200.
- `test_settle_returns_on_predicate_match` — patch find to return [] twice then [match]; assert settle returns after the third call.

**Acceptance**
- M1-1190 re-run: the Vue post-save re-render finishes settling before drain captures network/console, so the deprecation warning is in the trace.

---

### GAP-6 findings folded into the refactor

Of the 9 findings in GAP-6:

| Finding | How it closes |
|---|---|
| #1 Screenshot per-domain permission | Separate small handler in `qa-fail-reporter` — see below. |
| #2 Silent navigate no-op | `step_runner` verifies post-navigate URL via `tabs_context_mcp`; if URL didn't change, retry once, then emit `blocked_reason: navigate_no_op`. |
| #3 Wrong login URL | Closed by GAP-13 in Phase 1. |
| #4 `document.forms` empty | `step_runner.snapshot_after` uses `find` queries from assertions, never raw `document.forms`. |
| #5 Password redaction | Same — `find` returns sanitized values; we never read password fields. |
| #6 Base64 URL redaction | Same — `find` results don't include data-URI hrefs; if needed, use predicate-based assertions instead of reading hrefs. |
| #7 Vue reactivity on fill | `step_runner.fill` calls `form_input` then `javascript_tool` to dispatch `input` + `change` events. |
| #8 Network capture only-after-first-call | `arm_captures` calls `read_network_requests({clear: true})` once at the start of every step. |
| #9 Console capture only-after-first-call | Same — `read_console_messages({clear: true})` in arm. |

**Files for finding #1 (the only one that doesn't fall out of the refactor automatically)**
- `skills/qa-fail-reporter/scripts/build_fail_thread.py` — wrap the screenshot upload in try/except for `Permission denied for this action on this domain`.
- `skills/qa-fail-reporter/SKILL.md` — footer text for permission-denied case.

**Change shape**
- On permission-denied, set `step.screenshot_ref = None`.
- Thread footer adds: `_Screenshots are unavailable for this deploy domain. Grant screenshot permission in Chrome MCP settings to enable them._`

---

## Phase-wide acceptance test

**Re-run M1-1190 audit against MR !6865 deploy** (the same scenario used to surface these gaps).

Expected differences vs the Phase 0 run:
- The moment.js deprecation warning is in the trace, attributed to the save step.
- The save's network request shows up in `trace.during.network`; its response status is captured.
- The verdict is now one of `pass`, `fail`, or `verification_inconclusive` — never `partial`.
- If `fail`, the fail-thread on the MR shows the response body OR a `console_warning_present` finding linked to the deprecation.
- Vue's reactivity works (the form updates after `fill`).

**Numeric target**: 0 `partial` verdicts in 10 sample runs across different tickets.

## Risks

- **The `find`-only snapshot is slower than blanket JS reads.** Mitigation: lazy population — only assertions that need an element trigger the find call. Budget: a step with 3 assertions shouldn't add >500ms to the loop.
- **Auto-settle of 2000ms slows every step.** Mitigation: stability mode usually returns under 500ms when the page is quiet; predicate mode returns immediately on match. The 2000ms is the cap, not the typical.
- **Back-compat for `CapturedPage`-typed callers.** Mitigation: keep a shim in `scenario_dispatcher.py` that wraps a `CapturedPage` into a `StepTrace` with empty `during` events. Deprecate but don't remove.
- **The Vue reactivity dispatch leaks DOM events that other handlers care about.** Mitigation: dispatch is gated by `event_emit: true` in the step config; default on for `fill`, off for `upload` (which already handles its own events).

## Out of scope

- New verbs beyond `settle` (e.g., `scroll_into_view`, `hover`). Leave for v0.11.1+ as needs surface.
- Replacing `scenario_dispatcher`'s rules loader — keep its core stable.
- Live writes to Optimus or Slack — those are Phase 3.
- The qa-ui-observer rewrite (GAP-18) — Phase 3.

## Effort

- **Code:** ~400 LOC across `step_runner.py` (new), `step_trace.py` (new), `scenario_dispatcher.py` (modified), `build_fail_thread.py` (modified).
- **Tests:** ~15 new test cases.
- **Docs:** Step rewrite of `qa-ui-executor/SKILL.md`; vocabulary additions to `qa-config/SKILL.md`.
- **Time:** 3–5 days, including the M1-1190 re-run acceptance test.

## Decisions to confirm before starting

1. Is the `during`/`after` split the right shape for `StepTrace`? Alternative: single `events: List[Event]` with a kind discriminator. Trade-off: split is easier to assert against; flat is easier to serialize.
2. Are the four new assertion kinds the right four? Are `dom_diff_present`, `element_attribute_eq`, `download_started` worth including now?
3. Auto-settle policy — `2000ms` default cap. Higher or lower?
4. Vue reactivity dispatch — gate by per-verb default (current proposal) or always-on for `fill`?
