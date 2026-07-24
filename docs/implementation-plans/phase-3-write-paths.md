# Phase 3 — v0.12.0 · Write paths live

## Goal

Exercise four unproven integrations end-to-end for the first time: Slack staging cards, Optimus task moves, the pointer-block round-trip in Optimus descriptions, and the qa-ui-observer's redaction-aware introspection.

After this phase, a `/manual-qa-execute` run produces a real verdict, moves the Optimus ticket to the correct lane, updates the Optimus description with a verdict pointer block, and posts a Slack staging card. The full automation loop is closed.

## Why this lands AFTER Phase 2

Phase 2's inner-loop refactor produces trustworthy verdicts. Moving an Optimus ticket on a `partial`/`verification_inconclusive` verdict that we now never emit would mis-flag tickets. We need real verdicts before we trust the write paths to act on them.

## Gaps closed

### GAP-5 · Slack integration scripts · MEDIUM

**Files (new)**
- `skills/qa-slack-bridge/SKILL.md` — new skill.
- `skills/qa-slack-bridge/scripts/post_staging_card.py` — per-verdict card builder.
- `skills/qa-slack-bridge/scripts/post_regression_rollup.py` — bi-weekly summary.
- `skills/qa-slack-bridge/tests/test_staging_card.py`.
- `skills/qa-slack-bridge/tests/test_regression_rollup.py`.

**Files (modified)**
- `commands/manual-qa-execute.md` — Step 9 (Slack staging card) wires in `post_staging_card.py`.
- `commands/regression-execute.md` — Step 4 (roll-up) wires in `post_regression_rollup.py`.
- `skills/qa-config/SKILL.md` — `slack.staging_channel` + `slack.regression_channel` config fields documented.

**Staging card spec**
- One Slack `chat.postMessage` call per run via `mcp__5f6545e3-…__slack_send_message`.
- Channel resolved from `config.slack.staging_channel` (DM the QA Lead by default).
- Body uses Slack mrkdwn. Sections: ticket header (link to Optimus + MR), verdict + verdict-color emoji, per-step pass/fail summary, link to fail-thread (if any), link to dashboard.
- Color convention: `pass` 🟢, `fail` 🔴, `verification_inconclusive` 🟡, `blocked` ⚪️.

**Roll-up spec**
- Bi-weekly summary across all `regression-execute` runs since last roll-up.
- Counts by module: ran, passed, failed, inconclusive, blocked.
- Top 3 regressions surfaced (most recently failing tickets that previously passed).
- Posted to `config.slack.regression_channel` (default `#dream-team`).

**Tests**
- `test_staging_card_renders_pass` — given a `pass` verdict + stub MR + stub ticket, the produced mrkdwn contains the expected sections.
- `test_staging_card_renders_fail` — same with `fail`; fail-thread URL is included.
- `test_staging_card_renders_inconclusive` — same with `verification_inconclusive`; the 🟡 emoji + the inconclusive-reason text is included.
- `test_send_uses_config_channel` — patch `slack_send_message`; assert it's called with the channel from config.
- `test_regression_rollup_groups_by_module`.

**Acceptance**
- A `/manual-qa-execute` against a throwaway ticket produces a Slack DM with the right shape; clicking the dashboard link opens the live artifact.

**Risk**
- Slack MCP token may not have permission for the configured channel — script returns a clear error pointing to the OAuth scope to add.

---

### GAP-7 · First live Optimus write · HIGH

**Why this is its own gap:** Every Optimus payload builder (`optimus_move_task.py`, `optimus_build_verdict_comment.py`) has unit tests but never executed against real Optimus. The first run will tell us if (a) the status literals match, (b) the verdict-comment renders correctly in Optimus's renderer, (c) the move triggers any side-effects we didn't anticipate.

**Procedure (not code)**

1. **Create a throwaway test ticket** in Optimus with status `code_review` (the input lane this plugin reads from). Mark it clearly as a test (description prefix `[QA-AUTOMATION-TEST]`).
2. **Run `/manual-qa-execute --ticket <test-ticket-id> --dry-run`** — confirms the plan executes through Phase 2 and produces a verdict. No writes.
3. **Run without `--dry-run`** with phase still `shadow` — confirm the audit log records the intended write but doesn't execute.
4. **Flip phase to `writes-on`** via config. Re-run. Observe the live move.
5. **Verify** in Optimus UI that the ticket landed in the expected lane (`qa2` for pass; `needs_changes` for fail).
6. **Re-fetch the task** via `get_task` and assert the description contains the verdict pointer block.

**Files**
- Likely no script changes IF the live test passes. The plan assumes our literals are right.
- IF status literal is wrong (e.g., Optimus expects `qa_2` instead of `qa2`), update `DEFAULT_LANES` in `optimus_move_task.py`.

**Tests (live, not unit)**
- One round-trip against the throwaway ticket; the audit log entry's `outcome` field is `success`.
- Cleanup step: delete the throwaway ticket after the test.

**Acceptance**
- Live round-trip succeeds.
- The audit log shows the move with timestamps.
- Re-running the same ticket within 5 minutes hits the Mem dedup gate and does NOT re-move.

**Risk**
- Optimus status literals don't match — easy fix once observed.
- Move triggers an unwanted notification to the ticket's assignee — mitigation: do the live test outside business hours.

---

### GAP-8 · Pointer-block round-trip · MEDIUM

**Why now:** The pointer-block markers (`<!-- qa-automation:pointer:start -->` / `:end`) may get stripped by Optimus's Markdown renderer. We've never confirmed they survive.

**Combined with GAP-7's live test.** After step 6 above, do the following:

1. **Inspect** the re-fetched description. Does it still contain the HTML comment markers? Or just the inner content?
2. **Re-run `find_pointer_block.py --upsert`** on the same task with a new verdict. Confirm the existing block is replaced in place, not duplicated.

**Files (conditional)**
- IF comments are stripped: switch to text-based delimiters in `skills/qa-checklist-reader/templates/pointer-block.md`. Candidate: `---qa-automation-pointer-start---` / `---qa-automation-pointer-end---` on their own lines.
- Update `skills/qa-checklist-reader/scripts/find_pointer_block.py` to look for whichever delimiter we chose.

**Tests**
- `test_upsert_replaces_existing_block_in_place` — given a description with one pointer block, upsert produces a description with one pointer block (count == 1).
- `test_upsert_appends_when_block_absent`.

**Acceptance**
- After two runs of the same ticket with different verdicts, the Optimus description has exactly one pointer block, holding the latest verdict.

**Risk**
- If comments get stripped, the v0.12 acceptance gate is "must re-run with new delimiter" — adds a day.

---

### GAP-18 · qa-ui-observer redaction-aware checks · MEDIUM

**Why now:** Three of the six checks rely on JS introspection that Chrome MCP redacts. The audit run showed `[BLOCKED]` for those queries on Medtrics deploys. Two of them can be rewritten via `find`; one can't be done deterministically and should be dropped.

**Files (modified)**
- `skills/qa-ui-observer/scripts/check_observations.py`.
- `skills/qa-ui-observer/SKILL.md`.
- `skills/qa-ui-observer/tests/test_observations.py`.

**Per-check disposition**

| Check | Today | New |
|---|---|---|
| `console_warning` | Reads `trace.during.console`. | No change — console isn't redacted. |
| `deprecated_api_warning` | Same. | No change. |
| `asset_load_error` | Reads `trace.during.network` filtered by status. | No change — network URLs visible. |
| `broken_image` | Raw JS `document.querySelectorAll('img')` then check `naturalWidth === 0`. | Rewrite with `find("img elements that failed to load")`. Falls back to network 4xx/5xx for image URLs. |
| `missing_alt_text` | Raw JS `document.querySelectorAll('img:not([alt])')`. | Rewrite with `find("images missing alt attribute")`. |
| `layout_overflow` | Raw JS measuring `scrollWidth > clientWidth`. | **Dropped** — can't be done deterministically on redacted pages. Replaced by surfacing any console message matching `/layout|overflow|reflow/` via `console_warning`. |

**Tests**
- `test_broken_image_finds_via_find_first` — patch `find` to return matches; assert no JS introspection call.
- `test_broken_image_falls_back_to_network` — patch `find` to return empty; assert the network 4xx check runs.
- `test_layout_overflow_removed` — assert the kind is no longer in `ALLOWED_OBSERVATION_KINDS`.

**Acceptance**
- Re-run on a Medtrics deploy page produces observation findings without any `[BLOCKED]` markers in the audit log.

**Risk**
- Dropping `layout_overflow` loses a useful UX check. Mitigation: log as a known gap; revisit if/when Chrome MCP exposes a redaction-safe way to measure layout.

---

## Phase-wide acceptance test

**One full pass on M1-1190 (or a throwaway ticket)** end-to-end:
1. The run produces a real verdict (Phase 2 guarantees this).
2. Optimus ticket moves to the correct lane (`qa2` or `needs_changes`).
3. Optimus description gets the verdict pointer block (one, not two).
4. Slack staging card posts to the configured channel.
5. qa-ui-observer findings appear in the run with no `[BLOCKED]` markers.

## Risks

- **First live Optimus write surfaces an unexpected error.** Mitigation: phased rollout via `shadow` → `writes-on`; we observe the intent before executing.
- **Slack channel permissions block the post.** Mitigation: setup step verifies token has write scope.
- **Pointer-block delimiters get rewritten by Optimus.** Mitigation: live test reveals it before we ship; v0.12 acceptance gates on round-trip success.

## Out of scope

- The bi-weekly regression schedule itself — Phase 4.
- Scheduled-task creation against the live Cowork — Phase 4.
- Authoring of regression module checklists — Phase 4.
- Phase-transition metrics — Phase 5.

## Effort

- **Code:** ~200 LOC, mostly in `qa-slack-bridge` (new skill).
- **Tests:** ~8 new test cases + one live round-trip per integration.
- **Live testing:** ~1–2 hours per integration on the first run; cleanup matters.
- **Time:** 2–3 days, including the throwaway-ticket round trip.

## Decisions to confirm before starting

1. Slack channel — DM the QA Lead, or post to a dedicated `#qa-automation-staging` channel?
2. Regression roll-up cadence — bi-weekly (current proposal) or weekly?
3. Throwaway-ticket policy — create one per test, or maintain a single permanent test ticket?
4. If comments-as-delimiters are stripped — switch to text delimiters, or push back on Optimus to render HTML comments?
