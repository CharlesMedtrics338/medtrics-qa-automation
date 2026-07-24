#!/usr/bin/env python3
"""
gitlab_get_mr.py — fetch one MR's metadata + changes + deployment summary.

Aggregates four GitLab calls into one stable MrFetch payload that
qa-checklist-reader's resolve_mr_via_gitlab.md consumes:

  1. GET /merge_requests/:iid                 — title, branch, state, sha, web_url
  2. GET /merge_requests/:iid/changes         — changed files
  3. GET /merge_requests/:iid/pipelines       — head pipeline status (gate)
  4. GET /deployments?ref=<head_sha>          — pulled lazily on demand

Output JSON (stdout):
{
  "ok": true,
  "mr_iid": <int>, "title": <str>, "state": <str>, "web_url": <str>,
  "source_branch": <str>, "target_branch": <str>,
  "head_sha": <str>, "base_sha": <str>, "start_sha": <str>,
  "changed_files": [<path>, ...],
  "pipeline_status": "success" | "running" | "failed" | "skipped" | "unknown",
  "deploy_url": <str|null>, "deploy_status": <str|null>
}

Exit codes:
  0 — fetched; deploy may still be unresolved (caller decides)
  1 — env/config error
  3 — MR not found / GitLab error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from gitlab_client import (  # noqa: E402
    load_env, get_mr, get_mr_changes, get_pipeline_status, gitlab_api, log,
    get_environment_by_name, list_deployments_for_environment,
)

# Medtrics deploys ephemeral preview environments named '{mr_iid}.medtrics.dev'.
# Override in config: `gitlab.deploy_environment_pattern`.
DEFAULT_DEPLOY_ENV_PATTERN = "{mr_iid}.medtrics.dev"


def _resolve_deploy(env, mr_iid: str, head_sha: str, project_id: str | None,
                    deploy_env_pattern: str = DEFAULT_DEPLOY_ENV_PATTERN):
    """Resolve a deploy URL + status for the MR.

    Tries three strategies in order — the first one that succeeds wins:

      A. **Environment-name lookup** (most reliable for Medtrics).
         Builds the environment name from `deploy_env_pattern` (default
         `{mr_iid}.medtrics.dev`) and queries `/environments?name=<name>`.
         If the environment exists and is `available`, use its
         `external_url`. Status defaults to `success` here — the env is
         live and serving the URL regardless of the most recent deployment's
         result code.

      B. **Deployments filtered by environment-name.** Same name as A, but
         queried against `/deployments?environment=<name>`. Picks up the
         most recent deployment's status (`success` / `running` / `skipped`
         / `failed`) when A returned no environment or no `external_url`.

      C. **Legacy SHA-prefix scan** (last resort). Walks recent project
         deployments looking for one whose SHA matches `head_sha[:12]`.
         This was the v0.5–v0.9.1 behavior; kept as a fallback for
         projects that don't follow the `{mr_iid}.medtrics.dev` convention.

    Returns (url, status, strategy) on hit, (None, None, "no_match") on miss.
    """
    if not mr_iid and not head_sha:
        return None, None, "no_inputs"

    env_name = deploy_env_pattern.format(mr_iid=mr_iid) if mr_iid else None

    # --- Strategy A: environment lookup by name -----------------------------
    if env_name:
        env_obj = get_environment_by_name(env, env_name, project_id=project_id)
        if isinstance(env_obj, dict) and env_obj.get("external_url"):
            state = (env_obj.get("state") or "").lower()
            if state == "available":
                # The env is live. Try to get the most recent deployment's
                # status for a richer signal, but don't refuse the URL if
                # the deployment list is empty/stale.
                deps = list_deployments_for_environment(env, env_name, project_id=project_id)
                most_recent = deps[0] if deps and isinstance(deps[0], dict) else {}
                status = most_recent.get("status") or "success"
                return env_obj["external_url"], status, "environment_lookup"
            # env exists but is stopped/stopping → treat as no URL
            return None, state or "stopped", "environment_unavailable"

    # --- Strategy B: deployments filtered by environment-name --------------
    if env_name:
        deps = list_deployments_for_environment(env, env_name, project_id=project_id)
        for d in deps:
            if not isinstance(d, dict):
                continue
            env_obj = d.get("environment") or {}
            url = env_obj.get("external_url")
            if url:
                return url, d.get("status"), "deployments_by_environment"

    # --- Strategy C: legacy SHA-prefix scan --------------------------------
    if head_sha:
        data, _ = gitlab_api(
            env, "deployments",
            params={"order_by": "created_at", "sort": "desc", "per_page": 20},
            project_id=project_id,
        )
        if isinstance(data, list):
            for d in data:
                if not isinstance(d, dict):
                    continue
                deployable = d.get("deployable") or {}
                commit = (d.get("sha") or deployable.get("sha") or "")
                if commit and commit.startswith(head_sha[:12]):
                    env_obj = d.get("environment") or {}
                    url = env_obj.get("external_url")
                    if url:
                        return url, d.get("status"), "sha_prefix_scan"

    return None, None, "no_match"


# qa-cache lives in a sibling skill; add its scripts to the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "qa-cache" / "scripts"))
import cache  # noqa: E402

CACHE_NAMESPACE = "gitlab.get_mr"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--iid", required=True, help="MR internal ID, e.g. 6865")
    p.add_argument("--project-id", help="Override env GITLAB_PROJECT_ID")
    p.add_argument("--env-file", help="Explicit path to a .env file.")
    p.add_argument("--no-deploy", action="store_true",
                   help="Skip the deploy-lookup roundtrip (faster).")
    p.add_argument("--deploy-env-pattern", default=DEFAULT_DEPLOY_ENV_PATTERN,
                   help=f"Environment-name pattern. Default {DEFAULT_DEPLOY_ENV_PATTERN!r}. "
                        f"Override per-install via config.gitlab.deploy_environment_pattern.")
    p.add_argument("--cache-ttl", type=int, default=300,
                   help="qa-cache TTL in seconds (GAP-11: default 300, cache-on by "
                        "default). Pass 0 or --no-cache to bypass.")
    p.add_argument("--no-cache", action="store_true",
                   help="Force a live GitLab fetch even if cache has a fresh entry.")
    args = p.parse_args()

    env = load_env(args.env_file)
    project_id = args.project_id or env.get("GITLAB_PROJECT_ID")
    cache_key = f"{project_id}:{args.iid}:{int(bool(args.no_deploy))}"

    # Cache read path.
    if args.cache_ttl > 0 and not args.no_cache:
        hit = cache.get(CACHE_NAMESPACE, cache_key)
        if hit is not None:
            hit["cache"] = "hit"
            print(json.dumps(hit, indent=2))
            return 0

    mr = get_mr(env, args.iid, project_id=args.project_id)
    if not isinstance(mr, dict):
        log(f"ERROR: MR {args.iid} not found or fetch failed.")
        return 3

    changes = get_mr_changes(env, args.iid, project_id=args.project_id) or {}
    changed_files = []
    for c in (changes.get("changes") or []):
        path = c.get("new_path") or c.get("old_path")
        if path:
            changed_files.append(path)

    pipeline_status = get_pipeline_status(env, args.iid, project_id=args.project_id)

    deploy_url, deploy_status, deploy_strategy = (None, None, "skipped")
    if not args.no_deploy:
        deploy_url, deploy_status, deploy_strategy = _resolve_deploy(
            env,
            mr_iid=str(mr.get("iid") or args.iid),
            head_sha=mr.get("sha") or "",
            project_id=args.project_id,
            deploy_env_pattern=args.deploy_env_pattern,
        )

    out = {
        "ok": True,
        "mr_iid": mr.get("iid"),
        "title": mr.get("title"),
        "state": mr.get("state"),
        "web_url": mr.get("web_url"),
        "source_branch": mr.get("source_branch"),
        "target_branch": mr.get("target_branch"),
        "head_sha": mr.get("sha"),
        "base_sha": (mr.get("diff_refs") or {}).get("base_sha"),
        "start_sha": (mr.get("diff_refs") or {}).get("start_sha"),
        "changed_files": changed_files,
        "pipeline_status": pipeline_status,
        "deploy_url": deploy_url,
        "deploy_status": deploy_status,
        "deploy_strategy": deploy_strategy,
        "deploy_env_name": args.deploy_env_pattern.format(mr_iid=mr.get("iid") or args.iid),
        "cache": "miss",
    }

    # Cache write path — only memoize successful responses.
    if args.cache_ttl > 0 and not args.no_cache:
        cache.put(CACHE_NAMESPACE, cache_key, out, ttl_seconds=args.cache_ttl)

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
