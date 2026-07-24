"""GitLab REST client — stdlib only.

Vendored into medtrics-qa-automation from medtrics-code-review's
`gitlab-write/scripts/lib/gitlab_client.py`, with two additions:

  - upload_file()         — POST /projects/:id/uploads (multipart/form-data).
                            Used by qa-fail-reporter for screenshot attachments.
  - get_pipeline_status() — GET /projects/:id/merge_requests/:iid/pipelines.
                            Used by qa-checklist-reader for the green-pipeline gate.

Convention (shared with code-review and release-notes): `urllib.request` +
`PRIVATE-TOKEN` header + .env-driven config, same retry / rate-limit semantics
so all three plugins behave the same way against the same GitLab instance.

.env discovery order (earliest wins):
  1. explicit --env-file argument
  2. ./.env (cwd)
  3. ~/.cowork/medtrics-qa-automation/.env
  4. {plugin_root}/.env
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# --- Constants (mirror release-notes/gather_notes_data_optimus.py) -----------

GITLAB_MAX_RETRIES = 5
GITLAB_INITIAL_BACKOFF = 2  # seconds
GITLAB_MIN_REMAINING = 5  # proactively pause when remaining requests drop below this
DEFAULT_GITLAB_URL = "https://gitlab.com"

# Required keys for any GitLab call. OPTIMUS_API_KEY is read here for
# convenience (callers that also hit Optimus get a single env dict).
REQUIRED_GITLAB_KEYS = ("GITLAB_TOKEN", "GITLAB_PROJECT_ID")
OPTIONAL_KEYS = ("GITLAB_URL", "OPTIMUS_API_KEY", "GITLAB_PAT")


def log(msg: str) -> None:
    """Stderr log — mirrors release-notes convention."""
    print(msg, file=sys.stderr)


# --- .env discovery ----------------------------------------------------------

def _read_env_file(path: Path) -> dict[str, str]:
    """Read a single .env file into a dict. Returns {} on missing file."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key in REQUIRED_GITLAB_KEYS or key in OPTIONAL_KEYS:
                    out[key] = value
    except OSError as e:
        log(f"WARNING: could not read {path}: {e}")
    return out


def _candidate_env_paths(explicit: str | None) -> list[Path]:
    """Discovery order (earliest wins):
      1. explicit --env-file argument (if given)
      2. ./.env (cwd)                           — matches release-notes
      3. ~/.cowork/medtrics-code-review/.env    — Cowork plugin home
      4. {plugin_root}/.env                     — last resort

    Plugin root is resolved via CLAUDE_PLUGIN_ROOT or by walking up
    from this file's location until we hit a `.claude-plugin/` directory.
    """
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit).expanduser())
    paths.append(Path.cwd() / ".env")
    paths.append(Path.home() / ".cowork" / "medtrics-qa-automation" / ".env")
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        paths.append(Path(plugin_root) / ".env")
    else:
        # Walk up looking for `.claude-plugin/`
        here = Path(__file__).resolve()
        for parent in [here, *here.parents]:
            if (parent / ".claude-plugin").is_dir():
                paths.append(parent / ".env")
                break
    # de-dupe preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def load_env(env_file: str | None = None, *, require: tuple[str, ...] = REQUIRED_GITLAB_KEYS) -> dict[str, str]:
    """Load env vars from process env + discovered .env files.

    Process env wins over file-derived values (matches release-notes'
    slack_upload.py behavior). Missing required keys → exit code 1.
    """
    env: dict[str, str] = {}

    # Layer file-derived values (later files lose to earlier ones)
    for path in _candidate_env_paths(env_file):
        for k, v in _read_env_file(path).items():
            env.setdefault(k, v)

    # Process env overrides everything
    for key in REQUIRED_GITLAB_KEYS + OPTIONAL_KEYS:
        v = os.environ.get(key)
        if v:
            env[key] = v

    # GITLAB_PAT alias for GITLAB_TOKEN (some setups use the older name)
    if "GITLAB_TOKEN" not in env and "GITLAB_PAT" in env:
        env["GITLAB_TOKEN"] = env["GITLAB_PAT"]

    env.setdefault("GITLAB_URL", DEFAULT_GITLAB_URL)

    missing = [k for k in require if k not in env]
    if missing:
        log(f"ERROR: missing required env keys: {', '.join(missing)}")
        log("Search order:")
        for p in _candidate_env_paths(env_file):
            log(f"  - {p}{' (exists)' if p.is_file() else ''}")
        log("Populate one of those .env files with:")
        log("  GITLAB_TOKEN=glpat-...")
        log("  GITLAB_PROJECT_ID=<numeric_id_or_path%2Fwith%2Fnamespace>")
        log("  GITLAB_URL=https://gitlab.com    # optional, defaults to gitlab.com")
        sys.exit(1)
    return env


# --- HTTP -------------------------------------------------------------------

def _project_path(env: dict[str, str], project_id: str | None) -> str:
    """Resolve the URL-safe project ID segment.

    GitLab accepts both numeric IDs (e.g. `1496872`) and URL-encoded
    path-with-namespace (e.g. `medtrics-org%2Fmedtrics-legacy`). If the
    caller passes a path containing `/`, we URL-encode it.
    """
    pid = project_id or env["GITLAB_PROJECT_ID"]
    if "/" in pid and "%2F" not in pid:
        pid = urllib.parse.quote(pid, safe="")
    return pid


def gitlab_api(
    env: dict[str, str],
    path: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    project_id: str | None = None,
    relative_to_project: bool = True,
    timeout: int = 30,
) -> tuple[Any | None, dict[str, str]]:
    """Execute a GitLab REST call with rate-limit handling.

    Args:
      env: dict from load_env(). Must include GITLAB_TOKEN, GITLAB_URL.
      path: API path. If relative_to_project=True, prefixed with
        `/api/v4/projects/<project_id>/`. Otherwise prefixed with `/api/v4/`.
      method: HTTP verb.
      params: query-string params.
      body: JSON body for POST/PUT. Will be serialized.
      project_id: override env["GITLAB_PROJECT_ID"] (e.g. for cross-project search).
      relative_to_project: if False, treat `path` as an absolute API path under /api/v4/.
      timeout: per-request timeout in seconds.

    Returns:
      (parsed_json_or_None, response_headers_lowercased).

    Failure modes (return None, {}):
      - HTTPError with non-429 status (logged, no retry)
      - 429 exhausted after GITLAB_MAX_RETRIES
      - URLError (network)
    """
    base = env["GITLAB_URL"].rstrip("/")
    if relative_to_project:
        url = f"{base}/api/v4/projects/{_project_path(env, project_id)}/{path.lstrip('/')}"
    else:
        url = f"{base}/api/v4/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data_bytes: bytes | None = None
    headers: dict[str, str] = {"PRIVATE-TOKEN": env["GITLAB_TOKEN"]}
    if body is not None:
        data_bytes = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    for attempt in range(1, GITLAB_MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_headers = {k.lower(): v for k, v in resp.getheaders()}
                raw = resp.read()
                parsed: Any = None
                if raw:
                    try:
                        parsed = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        parsed = raw.decode("utf-8", errors="replace")
                # Proactive throttle
                remaining = resp_headers.get("ratelimit-remaining", "")
                if remaining.isdigit() and int(remaining) < GITLAB_MIN_REMAINING:
                    reset_at = resp_headers.get("ratelimit-reset", "")
                    if reset_at.isdigit():
                        wait = max(0, int(reset_at) - int(time.time())) + 1
                    else:
                        wait = GITLAB_INITIAL_BACKOFF
                    log(f"  Rate limit low ({remaining} remaining), pausing {wait}s...")
                    time.sleep(wait)
                return parsed, resp_headers
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            if e.code == 429:
                retry_after = e.headers.get("Retry-After", "") if e.headers else ""
                if retry_after and retry_after.strip().isdigit():
                    wait = int(retry_after.strip())
                else:
                    wait = GITLAB_INITIAL_BACKOFF * (2 ** (attempt - 1))
                if attempt < GITLAB_MAX_RETRIES:
                    log(
                        f"  Rate limited (429) on {method} {path}, "
                        f"retrying in {wait}s (attempt {attempt}/{GITLAB_MAX_RETRIES})..."
                    )
                    time.sleep(wait)
                    continue
                else:
                    log(
                        f"  Rate limited (429) on {method} {path}, "
                        f"exhausted all {GITLAB_MAX_RETRIES} retries"
                    )
                    return None, {}
            else:
                log(f"WARNING: GitLab API {e.code} for {method} {path}: {body_text[:200]}")
                return None, {}
        except urllib.error.URLError as e:
            log(f"WARNING: GitLab API URLError for {method} {path}: {e}")
            return None, {}
    return None, {}


# --- Convenience wrappers ---------------------------------------------------

def get_mr(env: dict[str, str], iid: int | str, *, project_id: str | None = None) -> Any | None:
    """GET /projects/:id/merge_requests/:iid"""
    data, _ = gitlab_api(env, f"merge_requests/{iid}", project_id=project_id)
    return data


def get_mr_changes(env: dict[str, str], iid: int | str, *, project_id: str | None = None) -> Any | None:
    """GET /projects/:id/merge_requests/:iid/changes"""
    data, _ = gitlab_api(env, f"merge_requests/{iid}/changes", project_id=project_id)
    return data


def get_mr_commits(env: dict[str, str], iid: int | str, *, project_id: str | None = None) -> Any | None:
    """GET /projects/:id/merge_requests/:iid/commits"""
    data, _ = gitlab_api(env, f"merge_requests/{iid}/commits", project_id=project_id)
    return data


def search_branches(env: dict[str, str], query: str, *, project_id: str | None = None) -> list[dict[str, Any]]:
    """GET /projects/:id/repository/branches?search=..."""
    data, _ = gitlab_api(env, "repository/branches", params={"search": query}, project_id=project_id)
    return data if isinstance(data, list) else []


def list_mrs(
    env: dict[str, str],
    *,
    source_branch: str | None = None,
    state: str = "opened",
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """GET /projects/:id/merge_requests?source_branch=...&state=..."""
    params: dict[str, Any] = {"state": state}
    if source_branch:
        params["source_branch"] = source_branch
    data, _ = gitlab_api(env, "merge_requests", params=params, project_id=project_id)
    return data if isinstance(data, list) else []


def search_mrs_by_title(
    env: dict[str, str],
    query: str,
    *,
    state: str = "opened",
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """GET /projects/:id/search?scope=merge_requests&search=..."""
    data, _ = gitlab_api(
        env,
        "search",
        params={"scope": "merge_requests", "search": query, "state": state},
        project_id=project_id,
    )
    return data if isinstance(data, list) else []


def search_blobs(env: dict[str, str], query: str, *, project_id: str | None = None) -> list[dict[str, Any]]:
    """GET /projects/:id/search?scope=blobs&search=..."""
    data, _ = gitlab_api(
        env,
        "search",
        params={"scope": "blobs", "search": query},
        project_id=project_id,
    )
    return data if isinstance(data, list) else []


def post_mr_discussion(
    env: dict[str, str],
    iid: int | str,
    body: str,
    *,
    position: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> tuple[Any | None, dict[str, str]]:
    """POST /projects/:id/merge_requests/:iid/discussions"""
    payload: dict[str, Any] = {"body": body}
    if position is not None:
        payload["position"] = position
    return gitlab_api(
        env,
        f"merge_requests/{iid}/discussions",
        method="POST",
        body=payload,
        project_id=project_id,
    )


def post_discussion_note(
    env: dict[str, str],
    iid: int | str,
    discussion_id: str,
    body: str,
    *,
    project_id: str | None = None,
) -> tuple[Any | None, dict[str, str]]:
    """POST /projects/:id/merge_requests/:iid/discussions/:discussion_id/notes"""
    return gitlab_api(
        env,
        f"merge_requests/{iid}/discussions/{discussion_id}/notes",
        method="POST",
        body={"body": body},
        project_id=project_id,
    )


def resolve_discussion(
    env: dict[str, str],
    iid: int | str,
    discussion_id: str,
    *,
    resolved: bool = True,
    project_id: str | None = None,
) -> tuple[Any | None, dict[str, str]]:
    """PUT /projects/:id/merge_requests/:iid/discussions/:discussion_id?resolved=..."""
    return gitlab_api(
        env,
        f"merge_requests/{iid}/discussions/{discussion_id}",
        method="PUT",
        params={"resolved": "true" if resolved else "false"},
        project_id=project_id,
    )


def update_mr_note(
    env: dict[str, str],
    iid: int | str,
    note_id: int | str,
    body: str,
    *,
    project_id: str | None = None,
) -> tuple[Any | None, dict[str, str]]:
    """PUT /projects/:id/merge_requests/:iid/notes/:note_id — edit a note body.

    Used by v0.3.0 auto-post to edit-in-place the summary thread when re-running
    against a new head_sha. Verified against gitlab.com Notes API docs (v0.2.7 review).
    """
    return gitlab_api(
        env,
        f"merge_requests/{iid}/notes/{note_id}",
        method="PUT",
        body={"body": body},
        project_id=project_id,
    )


def get_mr_discussions(
    env: dict[str, str],
    iid: int | str,
    *,
    per_page: int = 100,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """GET /projects/:id/merge_requests/:iid/discussions — list every discussion.

    Used by v0.3.0 finding-dedup to find existing plugin-posted threads (looks
    for the canonical `— posted by medtrics-code-review v…` footer in note bodies).
    Paginates automatically up to a soft cap of 10 pages (1000 discussions).
    """
    out: list[dict[str, Any]] = []
    for page in range(1, 11):
        data, _ = gitlab_api(
            env,
            f"merge_requests/{iid}/discussions",
            params={"per_page": per_page, "page": page},
            project_id=project_id,
        )
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < per_page:
            break
    return out


def get_discussion(
    env: dict[str, str],
    iid: int | str,
    discussion_id: str,
    *,
    project_id: str | None = None,
) -> Any | None:
    """GET /projects/:id/merge_requests/:iid/discussions/:discussion_id — fetch one."""
    data, _ = gitlab_api(
        env,
        f"merge_requests/{iid}/discussions/{discussion_id}",
        project_id=project_id,
    )
    return data


def whoami(env: dict[str, str]) -> Any | None:
    """GET /user — pre-flight token check (not project-scoped)."""
    data, _ = gitlab_api(env, "user", relative_to_project=False)
    return data


def get_project(env: dict[str, str], *, project_id: str | None = None) -> Any | None:
    """GET /projects/:id — pre-flight project check."""
    data, _ = gitlab_api(env, "", project_id=project_id)
    return data


# --- v0.5 additions for medtrics-qa-automation -----------------------------

def get_pipeline_status(
    env: dict[str, str],
    iid: int | str,
    *,
    project_id: str | None = None,
) -> str:
    """Return the status of the most recent pipeline for an MR.

    GET /projects/:id/merge_requests/:iid/pipelines

    GitLab returns a list ordered most-recent-first; we return the .status of
    the first entry. Falls back to "unknown" if the list is empty or the API
    call failed. Possible statuses: "success", "running", "failed", "skipped",
    "pending", "canceled", "manual".

    Used by qa-checklist-reader as the green-pipeline pre-execution gate.
    """
    data, _ = gitlab_api(
        env,
        f"merge_requests/{iid}/pipelines",
        params={"per_page": 1},
        project_id=project_id,
    )
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return str(first.get("status") or "unknown")
    return "unknown"


def upload_file(
    env: dict[str, str],
    file_path: str | Path,
    *,
    project_id: str | None = None,
    timeout: int = 60,
) -> dict[str, Any] | None:
    """Upload a file to a project's uploads endpoint.

    POST /projects/:id/uploads
    multipart/form-data: file=@<file_path>

    GitLab returns:
      {
        "id": <int>,
        "alt": "<filename>",
        "url": "/uploads/<hash>/<filename>",
        "full_path": "/<namespace>/uploads/<hash>/<filename>",
        "markdown": "![<filename>](/uploads/<hash>/<filename>)"
      }

    Used by qa-fail-reporter for screenshot attachments.

    Returns the parsed JSON on success, None on failure. Honors the same
    retry / 429 / rate-limit semantics as gitlab_api() — we re-implement
    the request loop here because urllib doesn't ship multipart helpers.
    """
    import uuid

    p = Path(file_path)
    if not p.exists():
        log(f"ERROR: upload_file: missing {p}")
        return None

    base = env["GITLAB_URL"].rstrip("/")
    url = f"{base}/api/v4/projects/{_project_path(env, project_id)}/uploads"

    boundary = f"----qa-upload-{uuid.uuid4().hex}"
    filename = p.name
    content_type = _guess_content_type(filename)
    file_bytes = p.read_bytes()

    body_parts = [
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"),
        f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
        file_bytes,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    data_bytes = b"".join(body_parts)

    headers = {
        "PRIVATE-TOKEN": env["GITLAB_TOKEN"],
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(data_bytes)),
    }

    for attempt in range(1, GITLAB_MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if not raw:
                    return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    log(f"WARNING: upload_file: non-JSON response: {raw[:200]!r}")
                    return None
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            if e.code == 429 and attempt < GITLAB_MAX_RETRIES:
                wait = GITLAB_INITIAL_BACKOFF * (2 ** (attempt - 1))
                log(f"  upload_file rate-limited (429), retrying in {wait}s "
                    f"(attempt {attempt}/{GITLAB_MAX_RETRIES})...")
                time.sleep(wait)
                continue
            log(f"WARNING: upload_file HTTP {e.code} for {filename}: {body_text[:200]}")
            return None
        except urllib.error.URLError as e:
            log(f"WARNING: upload_file URLError for {filename}: {e}")
            return None
    return None


def _guess_content_type(filename: str) -> str:
    """Minimal extension → content-type map for the file types qa-automation uploads."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png":  "image/png",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "gif":  "image/gif",
        "webp": "image/webp",
        "svg":  "image/svg+xml",
        "html": "text/html",
        "txt":  "text/plain",
        "md":   "text/markdown",
        "json": "application/json",
        "pdf":  "application/pdf",
    }.get(ext, "application/octet-stream")


# ---- v0.9: download project uploads + extract upload refs from note bodies ----

import re as _re

# Matches GitLab project-upload markdown in a note body:
#   [filename.txt](/uploads/<32-hex-secret>/<filename>)
# Both the link text (alt) and the URL captured.
_UPLOAD_REF_RE = _re.compile(
    r"\[([^\]]+)\]\((/uploads/([0-9a-f]{8,64})/([^)\s]+))\)"
)


def extract_upload_refs(note_body: str) -> list[dict[str, str]]:
    """Find every project-upload reference in a discussion-note body.

    Returns a list of {alt, url, secret, filename} dicts in source order.
    The `secret` is the per-upload hex token GitLab assigns; pair it with
    the `filename` to fetch via `get_project_upload()`.

    The match is permissive on filename (any non-space / non-`)` characters)
    so files with dots, hyphens, underscores all round-trip cleanly.
    """
    if not note_body:
        return []
    out: list[dict[str, str]] = []
    for m in _UPLOAD_REF_RE.finditer(note_body):
        out.append({
            "alt":      m.group(1),
            "url":      m.group(2),
            "secret":   m.group(3),
            "filename": m.group(4),
        })
    return out


def get_environment_by_name(
    env: dict[str, str],
    name: str,
    *,
    project_id: str | None = None,
) -> dict[str, Any] | None:
    """GET /projects/:id/environments?name=<name> — find an environment by exact name.

    Returns the first matching environment dict (with `external_url` + `state`)
    or None when no environment matches. The environment object includes:
      - id            int
      - name          str
      - state         'available' | 'stopping' | 'stopped'
      - external_url  str | None
      - tier          'production' | 'staging' | 'development' | 'testing' | 'other'

    Used by the deploy resolver as the most reliable lookup path — Medtrics
    uses an environment-name convention `{mr_iid}.medtrics.dev`, so a direct
    lookup beats walking the deployments list.
    """
    if not name:
        return None
    data, _ = gitlab_api(env, "environments",
                        params={"name": name, "per_page": 5},
                        project_id=project_id)
    if isinstance(data, list) and data:
        # GitLab name filter is exact for the single name= param.
        return data[0] if isinstance(data[0], dict) else None
    return None


def list_deployments_for_environment(
    env: dict[str, str],
    environment_name: str,
    *,
    project_id: str | None = None,
    per_page: int = 5,
) -> list[dict[str, Any]]:
    """GET /projects/:id/deployments?environment=<name>&order_by=created_at&sort=desc

    Returns the most recent deployments to that environment. Used to recover
    deployment status (success / running / skipped / failed) after we've
    located the environment via name.
    """
    if not environment_name:
        return []
    data, _ = gitlab_api(env, "deployments",
                        params={"environment": environment_name,
                                "order_by": "created_at", "sort": "desc",
                                "per_page": per_page},
                        project_id=project_id)
    return data if isinstance(data, list) else []


def get_project_upload(
    env: dict[str, str],
    secret: str,
    filename: str,
    *,
    project_id: str | None = None,
    timeout: int = 30,
) -> bytes | None:
    """Download a project upload that was attached to a discussion comment.

    GET /api/v4/projects/:id/uploads/:secret/:filename  (PRIVATE-TOKEN header)

    Returns the raw bytes on success, None on failure (HTTPError logged).

    IMPORTANT: do NOT fetch the raw `gitlab.com/<namespace>/<repo>/uploads/...`
    URL — gitlab.com proxies that path through Cloudflare which returns a
    bot-check 403 to any non-browser request. The /api/v4/ path is the
    correct download surface for automation.
    """
    if not secret or not filename:
        log("get_project_upload: missing secret or filename")
        return None
    base = env["GITLAB_URL"].rstrip("/")
    pid = _project_path(env, project_id)
    # `filename` may contain characters that need URL-encoding (spaces, etc.).
    # GitLab path segments accept most safe chars without encoding; we encode
    # defensively for the filename only.
    safe_filename = urllib.parse.quote(filename, safe="")
    url = f"{base}/api/v4/projects/{pid}/uploads/{secret}/{safe_filename}"

    headers = {
        "PRIVATE-TOKEN": env["GITLAB_TOKEN"],
        "Accept": "*/*",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body_text = e.read()[:200].decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        log(f"WARNING: get_project_upload HTTP {e.code} for {filename}: {body_text}")
        return None
    except urllib.error.URLError as e:
        log(f"WARNING: get_project_upload URLError for {filename}: {e}")
        return None


__all__ = [
    "GITLAB_MAX_RETRIES",
    "GITLAB_INITIAL_BACKOFF",
    "GITLAB_MIN_REMAINING",
    "DEFAULT_GITLAB_URL",
    "load_env",
    "log",
    "gitlab_api",
    "get_mr",
    "get_mr_changes",
    "get_mr_commits",
    "search_branches",
    "list_mrs",
    "search_mrs_by_title",
    "search_blobs",
    "post_mr_discussion",
    "post_discussion_note",
    "resolve_discussion",
    "update_mr_note",
    "get_mr_discussions",
    "get_discussion",
    "whoami",
    "get_project",
    # v0.5 additions for qa-automation
    "get_pipeline_status",
    "upload_file",
    # v0.9 additions for fetching MR-thread checklist attachments
    "extract_upload_refs",
    "get_project_upload",
]
