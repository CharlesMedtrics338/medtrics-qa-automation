# Implementation plans — index

One doc per release. Each closes a defined slice of `engineering-gaps.md`.

| File | Version | Gaps closed | Status |
|---|---|---|---|
| [`phase-1-quick-wins.md`](phase-1-quick-wins.md) | v0.10.0 | GAP-2, 3, 11, 13, 14, 19 | **shipped** |
| [`phase-2-inner-loop.md`](phase-2-inner-loop.md) | v0.11.0 | GAP-6 (×9), 12, 15, 16, 17 | planning |
| [`phase-3-write-paths.md`](phase-3-write-paths.md) | v0.12.0 | GAP-5, 7, 8, 18 | planning |
| [`phase-4-content-scheduling.md`](phase-4-content-scheduling.md) | v0.13.0 | GAP-4, 9 | planning |
| [`phase-5-metrics.md`](phase-5-metrics.md) | v0.14.0 | GAP-10 | planning |

Read order:
1. `../fix-roadmap.md` — strategic view, dependency graph, sizing.
2. `../engineering-gaps.md` — the gap inventory each plan closes.
3. This folder — the *how* per phase.

Each doc follows the same shape:
- **Goal** — one sentence on what shipping this phase makes possible.
- **Per-gap entry** — files touched, change shape (pseudocode, not actual code), tests, acceptance criteria.
- **Phase-wide acceptance test** — what success looks like end-to-end.
- **Risks** — what could break or delay.
- **Out of scope** — explicit non-goals so we don't scope-creep mid-phase.

Implementation work doesn't start until a plan is reviewed + approved.
