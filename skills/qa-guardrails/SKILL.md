---
name: qa-guardrails
description: Enforceable safety layer for medtrics-qa-automation. Use whenever driving a browser action, filing a verdict, moving an Optimus task, opening a GitLab thread, posting Slack, or persisting evidence. Backed by scripts/guardrails.py — deterministic, dependency-free, unit-tested. Covers destructive-action blocking, phase-gated writes, PII/PHI redaction, and timeouts. (v0.9.3 — persona allowlist removed; login is owned by the checklist.)
---

# qa-guardrails

The safety decisions in this pipeline come from **code, not the agent's
judgment** — the same trust property the assertion layer has. Everything below
is implemented and tested in `scripts/guardrails.py`; this SKILL.md is the
procedural wrapper that says *when* to call each function.

A `Decision` is `{allowed, severity, reason}` where `severity ∈ {ok, warn, block}`.
Callers MUST refuse on `block`; on `warn` they proceed but record `reason` in
the audit row / Mem note.

## The four enforcement surfaces

### 1. `screen_action(action, phase)` — before every browser action
Call it in `qa-ui-executor` step 2, before driving any verb.

- Read-only verbs (`navigate`, `screenshot`, `capture`, `wait_for_text`, `find`,
  `noop`) → always `ok`.
- Destructive controls (label/selector matches delete/remove/deactivate/purge/
  drop/wipe/erase/reset/revoke/archive/disenroll/terminate, inflections
  included; `dropdown` is NOT destructive) →
  - `shadow` → **block** (`destructive_action_in_shadow`).
  - `writes-on` → allowed (`warn`) **only if the step's `expected` text is
    itself testing that destructive behavior**; otherwise **block**
    (`destructive_action_not_under_test`).
- Mutating verbs (`fill`, `upload`, `submit_form`) → `warn` (run mutated state;
  fine on an ephemeral MR deploy, but recorded).
- Plain `click` → `ok`. Unrecognized kind → **block** (held for a human).

### 2. `gate_write(system, phase)` — before any write-back
- `shadow` → only `slack` (staging card) and `mem` (our run-log evidence) are
  allowed; `optimus` and `gitlab` are **blocked**.
- `writes-on` → all allowed.

### 3. `redact_pii(text)` / `assert_evidence_clean(text)` — before any write
Scrub evidence (captured page text, step `observed` strings, screenshots'
OCR/labels) before it lands in Mem, Slack, Optimus, or GitLab. Redacts EMAIL,
SSN, PHONE, BEARER, APIKEY, MRN, CSRF, DOB → `[REDACTED:KIND]`. Idempotent.
`assert_evidence_clean` returns `block` if anything would remain — use it as a
final pre-write gate.

## Timeouts
`HARD_TIMEOUT_S = 600` (per run), `STEP_TIMEOUT_S = 30` (per step). The executor
enforces these on the clock; on breach → `state=blocked, reason=timeout`.

## How a run uses it (the call sequence)

```
each step:      screen_action(action, phase)                                -> block? mark step needs_human/blocked, skip
before Mem write: text = redact_pii(observed); assert_evidence_clean(text)  -> block? drop the offending field
writes-on only: gate_write("optimus"/"gitlab"/"slack", phase)               -> block? skip that write
```

Login is owned by the checklist itself (v0.9.3): the checklist's first
steps are explicit `Login as <whoever the test needs>` lines, and the
executor follows them as normal step verbs. The guardrails layer has no
persona allowlist — `screen_action` still gates destructive verbs, and
`gate_write` still phase-gates writes, regardless of who is logged in.

## Reads
- `scripts/guardrails.py` (the implementation).
- Callers: `qa-ui-executor`, `qa-chrome-executor`, the writes-back paths.

## Writes
- None. Pure validator. (It tells callers what they may do; it never acts.)

## Tested by
- `tests/test_guardrails.py` — 24 cases (destructive blocking, phase gates,
  PII redaction, idempotence, edge cases like `dropdown`).
