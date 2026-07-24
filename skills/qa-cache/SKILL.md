---
name: qa-cache
description: Hot-tier (local filesystem) cache with TTL semantics for medtrics-qa-automation. Stops the plugin from re-doing expensive read work — GitLab MR fetches, pipeline status, Optimus get_task, Mem search_notes — within a short window. Stdlib only. Namespaced, prune-on-read. Complements qa-memory (warm cloud tier); see qa-memory/SKILL.md for how the two-tier memory layers fit together.
---

# qa-cache

The plugin reads from GitLab, Optimus, and Mem on every poll tick, every
ticket execution, every dashboard load. Most of that data is stable for
minutes at a time. This skill provides a per-machine cache so we don't burn
API calls (or rate-limit budget) re-fetching the same answer twice in a row.

The cache is **never authoritative**. Writers always treat their own writes
as fresh and bypass the cache. Reads consult it first; misses fall through
to the underlying source and write the response back with a TTL.

## Storage

```
~/.cache/medtrics-qa-automation/
├── gitlab.get_mr/
│   └── <sha1-of-key>.json
├── gitlab.pipeline/
│   └── <sha1-of-key>.json
├── optimus.get_task/
│   └── <sha1-of-key>.json
└── mem.search_notes/
    └── <sha1-of-key>.json
```

Each file:

```json
{
  "namespace": "gitlab.get_mr",
  "key": "1496872:6865",
  "value": { ... whatever the underlying source returned ... },
  "written_at": "2026-06-03T03:00:00Z",
  "expires_at": "2026-06-03T03:05:00Z"
}
```

Namespace + key are hashed together (SHA-1) so the on-disk filename is
fixed-length regardless of key shape. The plaintext key is stored inside
the JSON body for debuggability.

## API

`skills/qa-cache/scripts/cache.py`:

```python
get(namespace: str, key: str, default=None) -> Any        # None on miss / expired
put(namespace: str, key: str, value, ttl_seconds: int) -> None
invalidate(namespace: str, key: str | None = None) -> int # ret # entries removed
cleanup_expired(namespace: str | None = None) -> int      # housekeeping
stats() -> dict                                            # debug: counts per ns
```

The `key` argument is free-form text — typically a colon-joined tuple of
the inputs (e.g. `"1496872:6865"` for a (project_id, mr_iid) lookup, or
`"medtrics:qa1"` for a (product, lane) Optimus list).

## TTL recommendations

| Read | Namespace | TTL | Why |
|---|---|---|---|
| `gitlab_get_mr.py` | `gitlab.get_mr` | **300s (5 min)** | MR metadata + changed files change slowly within a polling cycle. |
| `gitlab_get_pipeline_status.py` | `gitlab.pipeline` | **120s (2 min)** | Pipeline transitions matter for the green-pipeline gate; 2 min is the floor where freshness still matches reality. |
| `mcp__optimus__get_task` (caller-level) | `optimus.get_task` | **120s** | Task descriptions change on human edit; 2 min covers polling without missing edits. |
| `mcp__mem__search_notes` | `mem.search_notes` | **300s** | Mem search results are stable across short windows; useful for find-related-notes lookups in fail-reporter. |
| `mcp__optimus__list_lane_tasks` | `optimus.list_lane_tasks` | **60s** | Polling cadence is 5 min; a 60s cache catches manual /qa1-poll runs without missing new arrivals on the next scheduled tick. |

Callers pick their own TTL — qa-cache enforces no policy. The numbers above
are documented defaults that other skills' SKILL.md files reference.

## When to bypass

`qa-cache` is opt-in. Callers that need authoritative reads (e.g.
verdict-time pipeline check) pass `--no-cache` to the wrapper script or
call the underlying API directly.

Bypass is also automatic on writes — `qa-fail-reporter` doesn't read
its own thread back from cache after posting; it consults GitLab directly
if it needs to confirm the post landed.

## What this skill does NOT do

- Not a queue. The poller's enqueue logic stays in `qa-poller`.
- Not a Mem replacement. Mem is the durable run-log archive; this cache
  exists to reduce redundant reads on a fast path.
- Not a circuit breaker. Failures from underlying APIs are not memoized as
  cache hits — only successful responses go into the cache.
- Not encrypted. The cache files have user-mode 0600 perms and live under
  `~/.cache/`, but they contain whatever the underlying API returned. PII
  scrubbing is the responsibility of the caller before any cache write.

## Tested by

`skills/qa-cache/tests/test_cache.py` — 12 tests covering TTL expiration,
namespace isolation, invalidate-one + invalidate-namespace,
cleanup_expired, the `default` fallback on miss, and prune-on-read.

## Reads / Writes

Reads: local filesystem only — `~/.cache/medtrics-qa-automation/`.
Writes: same. Failures never block the parent flow (cache failures degrade
to "always miss"; the caller still gets a correct answer from the
underlying source).
