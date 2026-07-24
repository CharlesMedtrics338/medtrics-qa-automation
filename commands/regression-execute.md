---
description: Run the bi-weekly regression pack across the active modules (Scheduling, Evaluations in Phase 2; Forms, Reports added in Phase 3). For each module, reads the module regression checklist from qa/regression, runs it against the develop deploy, and posts per-module reports and a roll-up to the dream-team Slack channel.
argument-hint: "[--module name] [--dry-run]"
---

# /regression-execute

You are running the Medtrics bi-weekly regression suite. Unlike per-MR runs, regression checklists live **in this plugin**, not on a ticket — they are the canonical "this module still works" suite curated by QA.

## What to do

1. **Resolve config.** Invoke `qa-config`. Refuse if missing.

2. **Resolve the module list.**
   - If the user passed `--module <name>`, run just that module.
   - Otherwise, default to the phase-active set:
     - **Phase 2.** `scheduling`, `evaluations`.
     - **Phase 3.** `scheduling`, `evaluations`, `forms`, `reports`.

3. **For each module, in sequence** (regression runs sequentially in v0.4 — true parallelism needs multiple Cowork sessions):

   a. **Load the checklist.** Read `qa/regression/<module>/checklist.md` (same `## QA Checklist` + numbered-steps format as the per-ticket checklists). Parse via `python3 skills/qa-checklist-reader/scripts/parse_checklist_steps.py <file>`. If the file is missing → audit-log `regression_module_skipped`, continue.

   b. **Resolve the develop deploy.** `qa-gitlab-bridge` returns the latest `develop` deploy URL. If the deploy is not `success` → mark the module `blocked, deploy_not_ready`, continue.

   c. **Pre-execution setup.** Read `qa-guardrails.HARD_TIMEOUT_S` (600s) and set the module deadline. (v0.9.3 — the persona allowlist gate was removed; login is declared inside each module's checklist.)

   d. **Execute** via the UI lane (`skills/qa-ui-executor/SKILL.md`). The API lane is per-MR-bug-class and not used for regression. Same per-step guardrails + assertion judging.

   e. **Aggregate** with `scenario_dispatcher.aggregate`. Persist to a Mem `Regression Run Logs` note keyed on `<run_id>/<module>`.

   f. **Per-module report.** Render `outputs/qa/regression/<run_id>/<module>.md` summarizing pass rates, failed items, and screenshot links.

4. **Roll-up.** After all modules complete, build a single Slack post to `config.slack.regression_channel` (default `#dream-team`):
   - One line per module: `<emoji> <module> — P0 <rate> · P1 <rate> · failed: <n>`
   - Link to each per-module report.
   - Overall verdict: `pass` if every module passed; otherwise `partial` or `fail`.
   - If any P0 failed in any module: include `@oncall` mention (configurable).

5. **Phase-gated writes** (writes-on only): if the overall verdict is `fail`, optionally open a GitLab thread on the develop pipeline. Optimus lane moves do not apply to regression runs.

6. **Audit.** One row per module (`regression_module_executed`) and one summary row (`regression_completed`) with totals.

## Failure handling
- Module checklist file missing → audit, skip module, continue.
- Develop deploy not ready → mark module `blocked`, continue.
- Chrome MCP timeout during a module → mark module `blocked, timeout`, continue to next module.
- `--dry-run` stops after step 3a for each module — prints the parsed plan; does not drive Chrome.

## Cadence
- Default scheduled task: every Wednesday at 9am ET, the operator manually disables on alternate weeks.
- Manual invocation: `/regression-execute` (all modules) or `/regression-execute --module scheduling` (single module).

## Notes
- Regression checklists are version-controlled in `qa/regression/<module>/checklist.md`. Edits go through code review like any other plugin change.
- "P0 across all four modules in one business day" is the target. Sequential execution + per-module screenshots usually finishes in <3 hours.
