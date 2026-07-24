# Post-test findings — M1-1190 / MR !6865, 2026-06-05

What the live exercise (v0.10.0 against the 6865 deploy) actually exposed
about the plugin's scripts and commands. Source of truth for the v0.10.1
patch list and for new gaps to file.

## TL;DR

- **No script bugs found.** Every Python module we exercised — `gitlab_open_thread.py`, `gitlab_get_mr.py`, and the underlying `gitlab_client` — worked correctly.
- **One first-time-live confirmation:** Optimus accepts the literal status string `qa2`. That closes the open question in GAP-7.
- **The big finding is what we DIDN'T exercise.** This run was driven manually with Chrome MCP + Optimus MCP + bash scripts — `/manual-qa-execute` itself was never invoked end-to-end. Steps 5 (dispatcher lane choice), 7 (aggregate verdict), 8 (Mem persistence), 9 (Slack staging card), 10b-d (Optimus move payload + verdict comment + lane move via the script wrapper) were skipped. We have v0.10.0 scripts that work in isolation but the command's orchestration pipeline is still unproven as a sequence.
- **Five new gaps to file** (GAP-20 through GAP-24), all surfaced by what the live run made visible vs hidden.

---

## What proved out (live, no fix needed)

| Concern | Verified via |
|---|---|
| `/users/login` default + Devise auto-redirect to dashboard for authed users | Navigate succeeded, no 404. |
| Structural `find("password input")` → "no match" → session_inherited classification | Find returned the expected empty result on `/users/` |
| `gitlab_open_thread.py` returns a `thread_url` with namespace path | Two threads posted: notes 3427043560 + 3427055921, both URLs resolve in the browser |
| `gitlab_client` cache layer | Second navigate served from cache (300s default), no second API roundtrip |
| Optimus `move_task` accepts the literal `qa2` | M1-1190 transitioned `needs_changes → qa2` cleanly; `statusChangedAt` updated; closes GAP-7's main question |
| GAP-3's disabled-rule skip | Dispatcher unit tests; not live-exercised but no regression |

## What did NOT get exercised (silent coverage gap)

The audit ran by hand, not via `/manual-qa-execute`. These scripts have never been invoked in a live pipeline:

| Script | Purpose | Run count this exercise | Risk |
|---|---|---|---|
| `skills/qa-chrome-executor/scripts/scenario_dispatcher.py --plan-only` | Lane decision (API vs UI) for the ticket | 0 | The "auto-route to UI when no matrix rule matches" path is untested live |
| `skills/qa-chrome-executor/scripts/aggregate_verdict.py` | Compute pass/fail/partial from per-step results | 0 | The aggregate signature + JSON shape is unproven against real step results |
| `skills/qa-fail-reporter/scripts/build_fail_thread.py` | Compose the GitLab fail-thread body when verdict is `fail`/`partial` | 0 (verdict was `pass`) | Fail-path entirely untested against a real MR |
| `skills/qa-optimus-bridge/scripts/optimus_move_task.py` | Build the MCP `move_task` arguments + phase-gate the write | 0 — I called `move_task` directly via MCP | Output JSON shape + exit-code semantics unproven against a real verdict context |
| `skills/qa-optimus-bridge/scripts/optimus_build_verdict_comment.py` | Build the verdict pointer block + footer that updates the Optimus description | 0 | M1-1190's Optimus description still has no verdict-block footer — the operator (you) sees only the lane change, not the verdict justification |
| `skills/qa-checklist-reader/scripts/find_pointer_block.py --upsert` | Idempotent splice of the pointer block into the description | 0 | The upsert behavior against a real Optimus description is untested |
| `skills/qa-memory/...` write path into `QA Run Logs` | One note per ticket, updated through the run | 0 | The dashboard shows nothing for this run |

**That last row matters.** The dashboard widget (`build_dashboard_widget.py`) loads from Mem. Because this run didn't write a Mem note, the dashboard won't show the M1-1190 PASS verdict to anyone reviewing the queue.

## New gaps to file

### GAP-20 (MEDIUM, downgraded from HIGH) — `/manual-qa-execute` has never been invoked end-to-end

**Filed:** 2026-06-05.

**Verified:** This run, the v0.9.5 audit, and every prior exercise drove the steps manually. The command's orchestration sequence (dispatcher → executor → aggregator → Mem write → Slack post → GitLab thread → Optimus move) has never run as a single transaction. We have unit tests for each script, but no integration evidence.

**Consequence:** The script-to-script handoffs (JSON shapes, exit codes, argument names, file paths) are unverified at the boundaries. The first real `/manual-qa-execute` invocation will surface shape mismatches we can't predict from unit tests alone.

**Closes when:** One live `/manual-qa-execute M1-1190 --dry-run` succeeds (the dry-run mode exercises the dispatcher + lane choice + plan emission without driving Chrome). Then one full run end-to-end against a low-stakes test ticket.

**Smoke-run evidence captured 2026-06-05 17:48 UTC** (post-finding-draft):

| Script | Invocation | Result |
|---|---|---|
| `scenario_dispatcher.py --plan-only` | M1-1190 title, files-changed=`apps/scheduling/forms.py` | `{"matched": false, "verdict": "needs_human"}` exit 0 — correctly routes to UI lane (no API matrix rule for block-schedule bugs) |
| `optimus_move_task.py` pass + shadow | `--ticket M1-1190 --verdict pass --phase shadow` | exit 2; JSON `decision: no_move_phase_shadow`; `audit_action: would_have_moved_to_qa2`. Matches command step 10b spec. |
| `optimus_move_task.py` pass + writes-on | same with `--phase writes-on` | exit 0 — args ready to pass to MCP. |
| `optimus_move_task.py` blocked | `--verdict blocked --phase writes-on` | exit 3 — no move, stays in qa1. |
| `optimus_build_verdict_comment.py` | run-log JSON | one-line footer: `**Automated QA1 → moved to qa2.** P0 100% · P1 100% · lane ui. Run log: mem://QA Run Logs/M1-1190.` |

Severity downgraded to MEDIUM. The script-level contracts hold. What's left is exercising the orchestration prose in the command itself — primarily a dry-run invocation followed by a full live run.

### GAP-21 (MEDIUM) — `find` returns dialogs that aren't visually painted

**Filed:** 2026-06-05.

**Verified live:** `find("any modal dialog visible")` returned ref_401 ("Add Blocks") — but the screenshot proved the dialog was not on screen. Vue's `v-dialog` keeps the markup in the DOM with `display: none` or off-viewport, and the Chrome MCP a11y tree includes it as "currently visible."

**Consequence:** A `qa-ui-executor` step that says "verify the Save dialog opened" can pass against a hidden dialog. False positive.

**What closes it:** A two-step structural check in the executor — `find(...)` AND a viewport/visibility probe. The `settle()` verb proposed for GAP-17 needs to include a viewport-intersection assertion as one of its built-in `until=` modes (e.g. `until=visible(ref)`).

### GAP-22 (LOW) — `computer.scroll_to(ref)` silently no-ops on detached elements

**Filed:** 2026-06-05.

**Verified live:** Called `scroll_to(ref_401)` on the ghost dialog; the screenshot afterward was identical. No error, no scroll.

**Consequence:** A scripted "scroll to row X before clicking Edit" sequence can drift past the target without raising. The plugin can't currently tell scroll-succeeded from scroll-noop.

**What closes it:** After `scroll_to`, the executor reads the target's bounding-client-rect via `javascript_tool` (one-liner) and asserts the rect intersects the viewport. If not, raise `blocked_reason: scroll_failed`.

### GAP-23 (MEDIUM) — Verdict vocabulary lacks visual-vs-persistence distinction

**Filed:** 2026-06-05.

**Verified live:** The M1-1190 verdict reads as `pass`, but the run only verified the visual-acceptance criterion ("edit form shows the same dates as the list view"). We did NOT click Save, so the data-integrity criterion ("saved dates persist correctly") remains unverified. The Optimus ticket is now in `qa2`, but the QA2 reviewer has no signal that a sub-criterion was deferred.

**Consequence:** A ticket can pass display-only checks and still ship a regression that breaks persistence. The current vocabulary can't surface that distinction.

**What closes it:** Per-step `criterion: visual | persistence | side_effect` field in the parsed checklist. The aggregate verdict carries both dimensions, e.g. `verdict: pass · visual=pass · persistence=not_verified`. This rides on Phase 2's vocabulary extension (GAP-15) — add the criterion field alongside the four new assertion kinds.

### GAP-24 (LOW) — "Edit" pattern in Medtrics is inline-row, not modal-popup

**Filed:** 2026-06-05.

**Verified live:** Clicking the row's `Edit` button converted the row to inline-edit inputs (`<input placeholder="Start Date">` rendered in place). The find tool's "modal dialog Add Blocks" was a separate always-present dialog, not the edit affordance.

**Consequence:** `qa-ui-executor/SKILL.md`'s step 3 implies "after a click, find the modal." For tickets like M1-1190 there's no modal — the action surfaces inline inputs. Checklist authors don't know whether to phrase the step as "open the edit modal" or "click Edit and read the row."

**What closes it:** Two updates:
- `qa-ui-executor/SKILL.md` step 3: when looking for the result of an Edit click, probe in this order: (1) inline-row inputs in the clicked row, (2) modal dialog with viewport-visibility check (GAP-21 fix), (3) inline expansion panel beneath the row.
- A note in the checklist-author guide explaining the inline-edit pattern is the Medtrics convention for "Manage Blocks"-style screens.

---

## What to actually patch (v0.10.1)

Small, surgical follow-ups to v0.10.0 — none architectural. Architecture work waits for Phase 2.

1. **`qa-ui-executor/SKILL.md` Step 3 — inline-edit-aware lookup order.** Closes GAP-24. ~10 lines of SKILL.md prose.

2. **`scenario_dispatcher.py --plan-only` mode** — confirm it exists and prints valid JSON. The command references it; we need to know it executes. *Verification, not necessarily code.*

3. **`optimus_move_task.py` smoke run.** Invoke with `--ticket M1-1190 --verdict pass --phase shadow` (still shadow, no write) and confirm the JSON output's `args.status` field equals `"qa2"`. Closes the script-to-MCP-call handoff doubt. *Verification.*

4. **`optimus_build_verdict_comment.py` smoke run.** Invoke with the M1-1190 run-log JSON to produce the description footer. Don't push to Optimus yet, but inspect the output to confirm it'd splice cleanly. *Verification.*

5. **Mem dashboard backfill.** Manually write one note to the `QA Run Logs` collection for M1-1190 with the v0.10.0 PASS verdict, so the dashboard reflects today's exercise. *One-time data fix.*

## What to file in engineering-gaps.md

- Close **GAP-7** (Optimus write proven live; status literal `qa2` works).
- File **GAP-20** through **GAP-24** as documented above.
- Net gap count after this update: **17 open** (was 13 after v0.10.0), **8 closed** (was 7). The increase isn't regression — it's coverage. The live run exposed surface area we didn't have visibility into.

## What this means for Phase 2 priorities

The five new gaps reinforce Phase 2's existing direction, not change it:

- **GAP-20** is the strongest argument for shipping `/manual-qa-execute --dry-run` mode and making it the acceptance test for v0.11.0.
- **GAP-21 + GAP-22** are concrete sub-tasks of GAP-17 (settle verb) — `settle` needs `until=visible` and `until=scroll_committed` as built-in modes.
- **GAP-23** is one more assertion kind for GAP-15's list — `criterion_dimension`.
- **GAP-24** is a SKILL.md change that can ship in v0.10.1.

Total Phase 2 scope unchanged in spirit, slightly extended in surface area. The v0.11.0 acceptance test should now read: "re-run M1-1190 via `/manual-qa-execute M1-1190` end-to-end, save included, with verdict carrying both visual + persistence dimensions."
