---
name: qa-gitlab-bridge
description: Read/write wrapper around the GitLab API for medtrics-qa-automation. Reads MR metadata + deployment status + pipeline status during checklist resolution; in Phase 2+ uploads screenshot attachments and opens fail-threads on the MR with structured per-step evidence. Writes are blocked during Phase 1 shadow. Backed by stdlib urllib scripts under scripts/ — one script per action, identical pattern to medtrics-code-review and medtrics-release-notes.
---

# qa-gitlab-bridge

Thin wrapper around the GitLab REST API. Owns the HTTP calls; never owns
content composition. Content composition lives in
`qa-checklist-reader/resolve_mr_via_gitlab.md` (reads) and `qa-fail-reporter`
(writes).

## Layout

```
scripts/
  lib/
    __init__.py
    gitlab_client.py        # vendored stdlib client — urllib + .env discovery
                            # + retry/rate-limit, matching code-review/release-notes
  gitlab_whoami.py          # pre-flight token check (GET /user)
  gitlab_get_mr.py          # GET /merge_requests/:iid + changes + pipeline + deploy
  gitlab_get_pipeline_status.py   # GET /merge_requests/:iid/pipelines (green gate)
  gitlab_upload_file.py     # POST /uploads (multipart) — screenshots
  gitlab_open_thread.py     # POST /merge_requests/:iid/discussions
```

Each script is a self-contained CLI — argparse, JSON stdout, sane exit codes.
The SKILL.md procedures elsewhere invoke them by path.

## .env contract

The lib auto-discovers `.env` in this order:
  1. explicit `--env-file <path>` arg on any script
  2. `./.env` (cwd)
  3. `~/.cowork/medtrics-qa-automation/.env` ← **canonical location for Cowork installs**
  4. `<plugin_root>/.env`

Required keys:
```env
GITLAB_TOKEN=glpat-...
GITLAB_PROJECT_ID=1496872              # or namespace%2Frepo
GITLAB_URL=https://gitlab.com           # optional; defaults to gitlab.com
```

`/setup-medtrics-qa-automation` walks the user through writing this file and
runs `gitlab_whoami.py` as the verification step.

## Reads

- **MR metadata** (description, source branch, deployment_summary, changed
  files) — consumed by `qa-checklist-reader/resolve_mr_via_gitlab.md` to
  produce the `MrResolution` object.
- **Latest pipeline status** — gates execution behind a green pipeline, per
  QA Process v2.2 ("the agent waits for the MR pipeline to go green before
  continuing").

## Writes (Phase 2+ only)

### `upload_file(project_id, path) → AttachmentRef`

Uploads a local file (typically a step screenshot) to the project's uploads
endpoint:

    POST /api/v4/projects/:project_id/uploads
    multipart/form-data: file=@<path>

GitLab returns:

```json
{
  "id": 17,
  "alt": "step-3.png",
  "url": "/uploads/abc123.../step-3.png",
  "full_path": "/medtrics-legacy/uploads/abc123.../step-3.png",
  "markdown": "![step-3.png](/uploads/abc123.../step-3.png)"
}
```

We return:

```python
AttachmentRef = {
  "alt": str,
  "url": str,         # GitLab-relative
  "markdown": str,    # to embed in thread body
}
```

The `.markdown` field is what `qa-fail-reporter` splices into the thread.

### `open_thread(project_id, mr_iid, body) → ThreadRef`

Opens a non-diff-positioned discussion on the MR:

    POST /api/v4/projects/:project_id/merge_requests/:iid/discussions
    json: { "body": "<rendered markdown>" }

Returns:

```python
ThreadRef = {
  "id": str,            # GitLab discussion id
  "url": str,           # MR URL with #note_<id> anchor
}
```

Restrictions:
- `body` must already be PII-redacted (caller's responsibility).
- Threads on closed/merged MRs are refused.
- No automated replies on existing threads. Resolution is human.

### `get_pipeline_status(project_id, mr_iid) → str`

Read-only. Returns the latest pipeline status (`success` / `running` /
`failed` / `skipped`) for the MR's head SHA. Used by `qa-checklist-reader` to
gate the run on green pipeline.

## Authentication

- Personal access token discovered by `lib/gitlab_client.load_env()` in this
  order:
  1. `GITLAB_TOKEN` environment variable
  2. `./.env` (cwd)
  3. `~/.cowork/medtrics-qa-automation/.env`
  4. `<plugin_root>/.env`
  5. Refuse — `load_env()` exits with diagnostics listing every path tried.
- Required scopes on the PAT: `api` (read + write).
- Token is masked in all logs and audit rows. The redactor in `qa-guardrails`
  treats `glpat-` prefixed strings as `BEARER` and redacts on the way to Mem
  / Slack / audit.
- Verify the token end-to-end with `python3 scripts/gitlab_whoami.py` — used
  by `/setup-medtrics-qa-automation` as the pre-flight gate.

## Phase gating

Every write goes through `qa-guardrails.gate_write("gitlab", phase)`:
- `shadow` → blocked. Bridge raises and the caller falls back to local-only
  evidence (Mem run log + Slack staging card).
- `writes-on` → allowed.

## Failure handling

| Failure | Behavior |
|---|---|
| 401 / 403 | Token invalid or missing scope. Audit, surface, refuse. |
| 404 on project | Wrong project ID. Audit and refuse — config issue. |
| 5xx on upload | Retry once after 5 s. On second failure, return `AttachmentRef` with `markdown` set to a plain-text fallback (`_(screenshot upload failed)_`) so the thread can still post. |
| 5xx on thread post | Retry once. On second failure, audit `gitlab_thread_post_failed` and propagate to the caller; the Slack staging card still went out. |
| Rate-limit (429) | Honor `Retry-After`. Cap the wait at 60 s; beyond that, fail-fast and audit. |

## What this skill does NOT do
- Compose thread bodies. That's `qa-fail-reporter`.
- Compose attachment markdown. The bridge returns what GitLab gives; the
  reporter splices it into the template.
- Reply to existing threads (v0.5 scope).
- Post diff-positioned discussions. We post non-positioned threads on the
  MR. Inline-on-diff posts are a v0.6 option.

## Reads / writes table

| Operation | Script | Endpoint | Phase 1 | Phase 2+ |
|---|---|---|---|---|
| Token check | `gitlab_whoami.py` | `GET /api/v4/user` | ✅ | ✅ |
| Resolve MR | `gitlab_get_mr.py` | `GET /merge_requests/:iid` (+ changes + pipeline + deploy) | ✅ | ✅ |
| Pipeline status | `gitlab_get_pipeline_status.py` | `GET /merge_requests/:iid/pipelines` | ✅ | ✅ |
| Upload file | `gitlab_upload_file.py` | `POST /uploads` (multipart) | ❌ blocked | ✅ |
| Open thread | `gitlab_open_thread.py` | `POST /merge_requests/:iid/discussions` | ❌ blocked | ✅ |

Phase 1 blocks are enforced upstream by `qa-guardrails.gate_write("gitlab", phase)` — the write scripts themselves do not consult the phase flag, by design. The caller is responsible for refusing to invoke them in shadow.
