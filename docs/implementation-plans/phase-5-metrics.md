# Phase 5 — v0.14.0 · Phase-transition metrics

## Goal

Make the "shadow → writes-on" phase transition computable from audit data instead of vibes. After this phase, running `/qa-phase-readiness` answers the question "have we earned the right to flip writes-on?" with a number and a recommendation.

## Why this lands LAST

The metric depends on sustained audit data from Phase 4's live polling. Without ~3 weeks of real runs accumulated, the metric has nothing to compute over.

## Gaps closed

### GAP-10 · Phase-transition readiness command · LOW

**Files (new)**
- `commands/qa-phase-readiness.md` — the slash command.
- `skills/qa-audit/scripts/compute_fp_rate.py` — helper script.
- `skills/qa-audit/tests/test_fp_rate.py`.

**The metric**

False-positive rate over a sliding 21-day window:

```
FP rate = (verdicts overridden by QA Lead within 24h) / (total verdicts)
```

The denominator is every `verdict_emitted` event in the audit log over the window. The numerator is the subset of those where a `verdict_overridden` event followed within 24h.

**Go/no-go thresholds**

| Window FP rate | Recommendation |
|---|---|
| <5% for 3 consecutive weeks | ✅ Ready — flip to `writes-on` |
| 5–10% | ⚠️ Tune detectors first |
| >10% | ❌ Not ready — investigate the failure modes |

**Command output (text only — no widget needed)**

```
QA phase readiness — week of {date}

  Verdicts emitted (21d): 142
  Verdicts overridden within 24h: 6
  FP rate: 4.2%

  Per-week breakdown:
    Week -3:  3.8% (3 / 79)
    Week -2:  4.1% (4 / 97)
    Week -1:  4.2% (6 / 142)

  Recommendation: ✅ Ready to flip to writes-on
  (3 consecutive weeks under 5% threshold)
```

**Files (modified)**
- `skills/qa-audit/SKILL.md` — adds the override event type (`verdict_overridden`) that the metric depends on.
- `skills/qa-config/SKILL.md` — adds `phase.fp_rate_threshold` (default `0.05`) and `phase.consecutive_weeks_required` (default `3`).

**The override event**

For the metric to compute, an override has to be a distinct audit event. Where it comes from:
- A QA Lead reviewing a verdict in the dashboard sees it's wrong; they tag the ticket in Slack or click "override" on the staging card.
- The override fires `verdict_overridden` into the audit log with: `original_verdict`, `corrected_verdict`, `overrider`, `reason`.

If no override UI exists today (it doesn't), the v0.14 plan also adds:
- A Slack slash-command shortcut on the staging-card thread: `/qa-override fail → pass · reason`.
- A handler that writes the override event.

That widens v0.14's scope slightly. Alternative: defer the override path; for v0.14, compute FP rate from a simpler proxy — `verdict_emitted` events where the ticket later moved to a status inconsistent with the verdict (e.g., we said `fail`, but the ticket got moved to `qa2` anyway within 24h).

**Tests**
- `test_fp_rate_zero_when_no_overrides` — synthetic audit log with no override events; rate is 0.
- `test_fp_rate_counts_24h_window` — override at 23h59m counts; at 24h01m does not.
- `test_fp_rate_per_week_grouping` — given events across two weeks, returns separate counts.
- `test_recommendation_thresholds` — at 4.9% returns ✅; at 5.1% returns ⚠️; at 10.1% returns ❌.

**Acceptance**
- Run `/qa-phase-readiness` after 3 weeks of live polling. Output matches what a manual audit-log scan would produce.

**Risk**
- **The override event needs a producer.** Mitigation: either build the slash-command, or accept the proxy metric for v0.14 and add real overrides in v0.14.1.
- **3 weeks of data is a lot to wait for.** Mitigation: command supports `--window 7` for a short-window preview; useful for sanity-checking the math even before we have a real 3-week run.

---

## Phase-wide acceptance test

**End-to-end sanity check.**
1. Run `/qa-phase-readiness --window 7` after week 1 of Phase 4 polling. Output renders without errors. Numbers match a hand-count of the last 7 days of audit log.
2. After 3 weeks: re-run without `--window`. Recommendation aligns with how the QA Lead would have called it from gut feel alone.
3. Flip phase to `writes-on` via config. Plugin no longer needs the `shadow → writes-on` gate documentation; document the new "writes-on" steady-state in `README.md`.

## Risks

- **The metric is gameable** — if the QA Lead never overrides anything, FP rate is artificially zero. Mitigation: the metric is a recommendation, not an auto-flip. Human judgment still decides.
- **3-week threshold is arbitrary.** Mitigation: configurable. If the team wants a stricter or looser bar, they can change it.

## Out of scope

- A dashboard view of the FP rate over time. Text output is enough for v0.14.
- Slack notification when the threshold is crossed.
- Auto-flipping `writes-on` when the metric says so — always a human decision.

## Effort

- **Code:** ~80 LOC (compute_fp_rate.py) + ~30 LOC for the command + optional ~100 LOC for the Slack override slash-command.
- **Tests:** ~6 test cases.
- **Wait:** 3 weeks of accumulated audit data before the command can produce a meaningful recommendation.
- **Time:** 1 day of build + 3-week observation window.

## Decisions to confirm before starting

1. Build the Slack override slash-command in v0.14, or use the proxy metric and defer?
2. Default thresholds — 5% / 3 weeks. Different bar?
3. Window length — 21 days (3-week sliding) or 14 days (2-week)?
