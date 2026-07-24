---
name: qa-ui-observer
description: Deterministic UI/UX inconsistency detector for medtrics-qa-automation. Consumes the CapturedPage projection that qa-ui-executor already builds per step and runs a fixed catalog of advisory checks — console warnings at level warn, 4xx and 5xx asset loads, broken img elements, missing alt text on P0 pages, layout overflow signals. Returns ui_observations that flow into the Mem run log and the GitLab fail-thread. Observations are ADVISORY — they never affect the run verdict, the same way P2 steps do not. Pure-Python, unit-tested, no LLM.
---

# qa-ui-observer

The verdict layer says pass/fail. This skill says *also worth mentioning to the
author*. Same trust property as the assertion layer: all checks come from code,
all results are deterministic, none of them flip the run's pass/fail decision.

The observer runs alongside the assertion pass, not after. For each step in
the UI lane, qa-ui-executor builds a `CapturedPage`; this skill takes that
projection plus the step's metadata and returns zero or more observations.

## The observation kinds (v0.5 catalog)

| Kind | Trigger | Severity |
|---|---|---|
| `console_warning` | A `ConsoleMessage` with `level == "warn"` was captured during the step. Errors at `level == "error"` are already covered by the `console_clean` assertion. | info |
| `asset_load_error` | The network log contains a request to a static asset (`.js`, `.css`, `.svg`, `.png`, `.jpg`, `.webp`, `.woff*`) with `status >= 400`. | warn |
| `broken_image` | A captured `<img>` element exists in the DOM but `naturalWidth == 0` (image failed to load). | warn |
| `missing_alt_text` | An `<img>` element on a P0 step's page has empty or missing `alt`. Accessibility check. | info |
| `layout_overflow` | A captured element has `scrollWidth > clientWidth + 1` or `scrollHeight > clientHeight + 1` while not declared scrollable — text or content clipped. | warn |
| `deprecated_api_warning` | A `ConsoleMessage` at `level == "warn"` whose text matches the deprecated-API regex bank (`/deprecated/i`, `/will be removed/i`, `/since version/i`). | info |

The catalog is closed and unit-tested. New kinds require a new check function
+ tests; observers never improvise.

## Inputs

| Input | Required | Source |
|---|---|---|
| `step` | Yes | The structured step `{n, step_id, priority, action, expected}` from the parsed checklist |
| `captured_page` | Yes | The `CapturedPage` projection qa-ui-executor built for this step |
| `config` | Yes | `~/.medtrics-qa-automation/config.json` — for the deprecated-API regex bank |

## Outputs

A list of zero or more observation records:

```json
{
  "kind": "broken_image",
  "severity": "warn" | "info",
  "step_id": "step-3",
  "step_n": 3,
  "step_priority": "P0",
  "location": "img[src='/static/icons/calendar.svg']",
  "evidence": "<img src='/static/icons/calendar.svg'> has naturalWidth=0 (file 404)"
}
```

Observations are collected across all steps into a single `ui_observations[]`
array on the Mem run log.

## Procedure

For each step:

1. **Walk the captured `console` messages** and emit `console_warning` for any
   `level == "warn"`. Cross-reference against the deprecated-API regex bank
   to upgrade matches to `deprecated_api_warning`.
2. **Walk the captured `network` requests** and emit `asset_load_error` for
   any request whose URL matches the static-asset extension list AND whose
   status is `>= 400`.
3. **Walk the captured `elements`**: for each element where the executor
   recorded an `<img>` selector, emit `broken_image` if `naturalWidth == 0`.
   If `step.priority == "P0"`, also emit `missing_alt_text` for any `<img>`
   with empty `alt`.
4. **Walk the captured `elements`** for any with `scrollWidth > clientWidth + 1`
   or `scrollHeight > clientHeight + 1` (and not declared scrollable), emit
   `layout_overflow`.

The order observations are emitted is stable per step (kinds in the catalog
order above) so the GitLab thread renders consistently across runs.

## What this skill does NOT do
- Does not affect the pass/fail verdict. P0 + P1 pass criteria are
  unchanged. Observations are advisory.
- Does not author fix advice. Each observation carries evidence; the MR
  author triages.
- Does not capture extra pages. Reads only what qa-ui-executor already built.
- Does not do visual baseline diffing. That's a v0.6+ option per the v0.5 FRD.
- Does not flag stylistic issues subjectively. Pure deterministic checks only.

## Integration

`qa-ui-executor` calls this skill once per step, immediately after
`run_ui_assertions()`. The returned list is appended to a per-run
`ui_observations[]` array which is written to the Mem run log. `qa-fail-reporter`
reads the array and includes it in the GitLab thread under the "UI/UX
observations" section.

## Reads
- The step record and the CapturedPage in memory (no I/O).
- `config.ui_observer.deprecated_api_patterns` (optional; falls back to
  built-in regex bank).

## Writes
- None directly. Returns observations; the caller persists them.

## Tested by
`tests/test_ui_observations.py` covers one positive + one negative case per
catalog kind, plus stable ordering across multiple kinds firing in one step.
