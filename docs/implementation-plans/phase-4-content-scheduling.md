# Phase 4 — v0.13.0 · Content + scheduling

## Goal

Stand up two operational capabilities the plugin spec promised but never delivered: a bi-weekly regression suite (which needs authored module checklists) and 5-minute Optimus polling (which needs scheduled tasks created against the live Cowork environment).

After this phase, the plugin operates on its own without manual `/manual-qa-execute` calls — polling picks tickets up, regression runs on a cadence.

## Why this lands AFTER Phase 3

Polling triggers `/manual-qa-execute --all`, which writes verdicts to Optimus and Slack. If we scheduled polling before Phase 3's write paths were proven, the automation would either no-op or fail loudly. After Phase 3 we know the loop is closed; only then is it safe to put it on a timer.

## Gaps closed

### GAP-4 · Regression module checklists · MEDIUM

**Files (new — authored, not generated)**
- `qa/regression/scheduling/checklist.md`
- `qa/regression/evaluations/checklist.md`
- `qa/regression/forms/checklist.md` (Phase 3 enablement of the broader regression suite)
- `qa/regression/reports/checklist.md` (Phase 3 enablement)
- `qa/regression/README.md` — explains the regression model.

**This is authoring work, not code work.** The plugin already reads `## QA Checklist` blocks from arbitrary Markdown files; these files just have to exist with the right shape.

**Per-checklist shape** (same as per-ticket checklists)
```markdown
# {Module} regression — vN

## Context
Three sentences on what this module owns and why these specific paths regress.

## QA Checklist

### P1 · {scenario name}
- Step: {action}
- Expected: {outcome}
- ...

### P2 · {scenario name}
...
```

**Authoring brief per module**

| Module | Recommended scenarios | Sourced from |
|---|---|---|
| `scheduling` | Block-schedule create / edit / delete; collision detection; multi-block templates; manage-blocks form roundtrip | M1-1190 area; Karen's QA notes |
| `evaluations` | Evaluation form submit; partial-save; due-date logic; learner visibility rules | Optimus archive — last 6 months of evaluations bugs |
| `forms` | Required-field validation; conditional logic; image upload; file upload size limits | The four most recent forms-related bug closes |
| `reports` | Report generation under each known role; date-range filtering; export-to-CSV | Reports lane in Optimus |

**Ownership question (for the user):** Do these get authored by you, Karen, or a QA Lead? The plugin can't author them — it can read and execute them.

**Tests**
- `test_regression_checklists_parse` — call `extract_checklist_block.py` on each file; assert it returns a non-empty list of steps.

**Acceptance**
- `/regression-execute --module scheduling` runs the scheduling checklist end-to-end against the latest deployed `staging` build and produces a verdict report.

**Risk**
- Authoring lag — if checklists take longer than expected, `/regression-execute` ships in v0.13 with only the modules that are ready; the others wait for v0.13.1.

---

### GAP-9 · Live scheduled tasks · HIGH

**Why now:** The plugin's setup procedure has Step 5 ("offer to create scheduled tasks") but has never been run with the user confirming yes. We don't know if our cron expressions parse correctly in Cowork's scheduler, if the command chains work, or if anything subtle breaks.

**Procedure (not code)**

1. **Audit the proposed schedules** in `commands/setup-medtrics-qa-automation.md` Step 5. Today:
   - `*/5 * * * *` → `/qa1-poll && /manual-qa-execute --all` (Optimus polling)
   - `0 9 * * MON-FRI` → `/regression-execute --rollup` (bi-weekly should be `0 9 * * MON-FRI/14` or two distinct entries — confirm exact cron syntax)
2. **Run `/setup-medtrics-qa-automation`** in a live Cowork session, confirming both task creations.
3. **Verify** via `mcp__scheduled-tasks__list_scheduled_tasks` that both tasks appear.
4. **Wait one polling cycle (5 min)** and inspect `~/.medtrics-qa-automation/audit.jsonl` for a `poll_completed` row.
5. **Wait one regression cycle** OR manually trigger via `mcp__scheduled-tasks__update_scheduled_task` to fire next minute.

**Files (conditional on what we learn)**
- If cron syntax is wrong: fix in `commands/setup-medtrics-qa-automation.md`.
- If the command chain doesn't work (e.g., `&&` isn't supported in Cowork's task runner): split into two scheduled tasks OR have the polling task call `/manual-qa-execute --all` directly without a wrapper.
- If anything else surfaces: document in `engineering-gaps.md` and fix in v0.13.1.

**Tests**
- None at unit level — this is a live integration test against Cowork's scheduler.

**Acceptance**
- Both scheduled tasks exist in `list_scheduled_tasks`.
- Polling task fires once and logs `poll_completed` in audit.jsonl.
- Regression task fires on its cadence and posts a Slack roll-up.

**Risk**
- **Polling under-runs** if a previous invocation is still in flight when the next 5-minute tick fires. Mitigation: setup runbook documents the "guard against re-entry" — first thing the polling command does is check for an in-flight lock file in `~/.medtrics-qa-automation/`. Add this to the setup script if it's missing.
- **Polling over-runs** if Optimus returns many tickets at once. Mitigation: `/manual-qa-execute --all` already serializes; the polling task should also pass a `--max=N` cap.
- **Regression runs on a wrong deploy** — the user might have multiple staging deploys. Mitigation: the regression command needs a `deploy_url` config field with a default + override flag.

---

## Phase-wide acceptance test

**Two-week observation window** after enabling:
1. The polling task has fired ~4000 times (5 min × 24h × 14d).
2. Every tick produced an audit row.
3. Tickets that landed in `code_review` were picked up and processed within 10 minutes (one polling cycle plus one execution window).
4. The regression task fired once on its bi-weekly cadence and posted a roll-up to Slack.
5. No alert fired (alerting itself is Phase 5; Phase 4 just needs no broken runs).

## Risks

- **Cowork scheduler quirks** — cron format, chained commands, retry-on-failure semantics. Mitigation: live-test before announcing.
- **Module checklists drift** — once authored, regression checklists must be kept in sync with feature changes. Mitigation: include "review/refresh regression checklist" as a step in the deploy checklist for the modules covered.
- **The polling cron interval is wrong** — 5 min might be too aggressive (rate-limiting Optimus) or too lax (slow turnaround on hot tickets). Mitigation: config field `polling.interval_minutes`; start at 5, tune after observation.

## Out of scope

- Phase-transition metrics — Phase 5.
- Authoring `forms` and `reports` regression checklists if the team isn't ready (push to v0.13.1).
- Adding new schedule kinds beyond polling + regression rollup.

## Effort

- **Code:** Near zero. Conditional patches in `commands/setup-medtrics-qa-automation.md` if cron syntax needs adjustment.
- **Authoring:** 4 module checklists at ~30 minutes each = ~2 hours, plus reviewer rounds.
- **Live testing:** ~1 day of observation after the schedule turns on.
- **Time:** 1–2 days plus a 14-day silent observation window.

## Decisions to confirm before starting

1. Who authors the regression checklists — you, Karen, or QA Lead?
2. Polling cadence — start at 5 minutes, or wider to be conservative?
3. Regression cadence — bi-weekly Monday 9am, or different?
4. Ship v0.13 with all 4 modules, or ship with scheduling+evaluations only and follow up?
