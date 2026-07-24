# resolve_mr_via_gitlab — procedure reference

Sub-procedure of `qa-checklist-reader`. Resolves an Optimus ticket's
title + description into a concrete `MrResolution` (MR + deploy URL +
changed files + pipeline status) using the GitLab REST API directly via
the bridge scripts under `qa-gitlab-bridge/scripts/`.

**Does not write anywhere.** Only reads.

The parsing half is in `scripts/extract_mr_link.py` (pure Python regex).
The HTTP half is in `qa-gitlab-bridge/scripts/gitlab_get_mr.py` (stdlib
urllib via `lib/gitlab_client.py`). This document is the orchestration —
how the calling skill chains the two together.

## Inputs

| Input | Source |
|---|---|
| `ticket_title` | `task.title` from `mcp__904fdec1...__get_task` |
| `ticket_description` | `task.description` from same |
| `project_id` | From `~/.medtrics-qa-automation/config.json` (e.g. `medtrics/medtrics`) |

## Outputs

A single `MrResolution` object:

```json
{
  "resolved": true,
  "via": "explicit_mr_url" | "branch_exact" | "ticket_id_search",
  "confidence": 1.0,
  "mr_iid": "6848",
  "mr_url": "https://gitlab.com/medtrics/medtrics/-/merge_requests/6848",
  "source_branch": "fix/m1-1129/bug-curriculum-a-import-encoded",
  "target_branch": "develop",
  "title": "Draft: Fix/m1 1129/bug curriculum a import encoded",
  "state": "opened",
  "draft": true,
  "deploy_url": "https://6848.medtrics.dev",
  "deploy_status": "success",
  "deploy_environment_slug": "env-6848-medtrics-...",
  "changed_files": ["src/apps/data_import/services/csv_template.py", ...]
}
```

On failure:

```json
{
  "resolved": false,
  "blocked_reason": "no_candidates" | "no_open_mr_found" |
                    "deploy_not_ready" | "gitlab_error",
  "details": "..."
}
```

## Procedure

### Step 1 — Extract hints

```bash
python3 scripts/extract_mr_link.py \
  --title "<task.title>" \
  --description "<task.description>"
```

Returns `{ticket_ids, mr_urls, branches, candidates, resolved}`. If
`resolved` is `false`, return `MrResolution{resolved: false,
blocked_reason: "no_candidates"}` and stop.

Otherwise iterate `candidates` in declared order (highest confidence
first). For each candidate, try the matching MCP strategy below. The
first one that returns a usable MR wins.

### Step 2 — Strategy: `explicit_mr_url` (confidence 1.0)

```bash
python3 ../qa-gitlab-bridge/scripts/gitlab_get_mr.py \
  --iid <candidate.value.iid>
```

Returns the consolidated MR payload (title, state, branches, SHAs,
`changed_files`, `pipeline_status`, `deploy_url`, `deploy_status`).
If `state` is `closed` or `merged`, log and continue to the next candidate
— we only want open MRs in qa1. If state is `opened` (draft or not),
proceed to Step 5.

### Step 3 — Strategy: `branch_exact` (confidence 0.8–0.9)

```python
# Direct via the lib (one-liner — list_mrs filtered by branch).
from gitlab_client import load_env, list_mrs
env = load_env()
mrs = list_mrs(env, source_branch=candidate.value, state="opened")
```

Pick the single open MR (refuse if multiple — branch convention should be
1:1 in medtrics-legacy). Then re-fetch via `gitlab_get_mr.py --iid <iid>`
to get the consolidated payload.

### Step 4 — Strategy: `ticket_id_search` (confidence 0.6)

The ticket ID was found but no full branch slug. Search for any open MR
whose title or branch contains the lowercase ticket ID via the lib:

```python
from gitlab_client import load_env, search_mrs_by_title
env = load_env()
mrs = search_mrs_by_title(env, candidate.value, state="opened")
```

From the returned list, pick the MR whose `source_branch` contains the
lowercase ticket ID as a substring. If more than one matches, pick the
most recently updated. Then re-fetch via `gitlab_get_mr.py --iid <iid>`
to get the consolidated payload.

If `search_mrs_by_title` returns zero results, also try with the search
term lowercased and with the prefix-digit hyphen ("m1-1129"). If still
nothing, continue to the next candidate.

### Step 5 — Resolve the deploy URL

The MR object returned by `get_merge_request` includes a
`deployment_summary.records[]` array. Each record has:

```json
{
  "status": "success" | "running" | "skipped" | "failed",
  "environment": {
    "name": "6848.medtrics.dev",
    "slug": "env-6848-medtrics-...",
    "external_url": "https://6848.medtrics.dev"
  },
  "ref": "refs/merge-requests/6848/head",
  "created_at": "..."
}
```

Filter to records whose `ref` is `refs/merge-requests/<mr_iid>/head` and
whose `environment.name` starts with `<mr_iid>.medtrics.dev`. Of those,
pick the most recent by `created_at`.

If the picked record's `status` is **not** `success`, return:

```json
{"resolved": false, "blocked_reason": "deploy_not_ready", "details": "<status>"}
```

The poller will retry the ticket on its next cycle once the pipeline
finishes. Do NOT fall back to constructing the URL from the convention
`<mr_iid>.medtrics.dev` — that URL might exist as DNS but serve stale
or broken assets if the deploy job didn't succeed.

**Important — `deployment_summary` is project-wide, not MR-scoped.**
GitLab returns the 10 most recent deploys across the whole project, so a
slightly-older MR's `deploy instance` job often won't appear here. When
the filter above produces zero records, fall back to:

```text
call mcp__gitlab__list_commit_statuses(
  project_id = config.gitlab.project_id,
  sha = mr.diff_refs.head_sha,
  per_page = 30,
)
```

Filter statuses to `name == "deploy instance"` (the Medtrics-legacy
pipeline job name) AND `ref == "refs/merge-requests/<mr_iid>/head"`. Of
those, pick the most recent successful one. The deploy URL is
constructed from the MR IID using the project convention
`https://<mr_iid>.medtrics.dev` — this fallback path uses the URL
pattern, but only AFTER confirming an actual `deploy instance` job
succeeded against the MR's head SHA. No success status → return
`blocked_reason: "deploy_not_ready"`.

### Step 6 — Pull the changed files

```text
call mcp__gitlab__list_merge_request_changed_files(
  project_id = config.gitlab.project_id,
  merge_request_iid = mr.iid,
)
```

This is the input the scenario-matrix dispatcher needs for the
`files_changed_glob` clause. Cache it in the `MrResolution` object so
the dispatcher doesn't have to call GitLab again.

### Step 7 — Assemble and return

Build the `MrResolution` object from the fields gathered above and
return it to the caller (`qa-checklist-uploader` SKILL.md Step 3).

## Failure handling

| GitLab failure | Behavior |
|---|---|
| `get_merge_request` returns 404 | Continue to next candidate. |
| `get_merge_request` returns 5xx | Retry once after 5s. On second failure, return `blocked_reason: "gitlab_error"`. |
| `list_merge_requests` returns empty | Continue to next candidate. |
| No candidate resolves | Return `blocked_reason: "no_open_mr_found"`. |
| MR resolved but no deploy in `deployment_summary` | Return `blocked_reason: "deploy_not_ready"`. |
| Deploy status `failed` or `skipped` | Same — `deploy_not_ready`. |

## Idempotence

Pure reads against GitLab. Safe to retry indefinitely. The
`qa-checklist-uploader` SKILL.md is the one that decides whether to
write a Mem note based on the resolution result.

## Caching considerations

If the same MR is resolved multiple times within a single
`qa1-poll-every-5min` cycle (e.g. once during the poll, once during
executor), cache the `MrResolution` in memory keyed by `(ticket_id,
mr_iid)`. Do not cache across cycles — deploy state changes between runs.

## Reads

- `mcp__gitlab__get_merge_request`
- `mcp__gitlab__list_merge_requests`
- `mcp__gitlab__list_merge_request_changed_files`
- `mcp__gitlab__list_commit_statuses` (rarely)

## Writes

None. This sub-procedure is read-only.
