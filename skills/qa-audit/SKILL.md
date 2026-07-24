---
name: qa-audit
description: Append-only audit trail for medtrics-qa-automation. Records every queue read, checklist generation, verdict, Slack card post, Optimus write, GitLab thread, override, and failure. PII is scrubbed before any write. Triggered automatically by every command and skill; never invoked directly.
---

# qa-audit

## What this skill owns
- The audit-log file at `~/.medtrics-qa-automation/audit.jsonl`.
- The PII scrub call site (shared with `qa-memory` so the same regexes are applied everywhere).
- The entry shape: every action emits one append.

## Entry shape (v0.1)
```json
{
  "ts": "2026-05-27T15:42:00Z",
  "command": "manual-qa-execute",
  "skill": "qa-chrome-executor",
  "ticket": "M1-1168",
  "mr_id": "12345",
  "action": "step_executed",     // or: queue_added, checklist_uploaded, verdict_posted, optimus_moved, gitlab_thread_opened, guardrail_blocked, override
  "result": "pass",              // or: fail, skip, error
  "evidence_ref": "mem:run-2026-05-27T15:40:00Z/step-3",
  "duration_ms": 4210,
  "notes": null
}
```

## Reads
- `/weekly-review` (future) consumes this for the improvement-loop pattern (mirrors `client-ops-audit`).

## Writes
- Every skill in this plugin appends one entry per externally-visible action.
- Append is best-effort; failure to append never blocks the parent flow.

## PII scrub
- Strip emails, names, MRNs, and tokens from `notes` and `evidence_ref` before append.
- Use the same regex bank as `qa-memory`.
