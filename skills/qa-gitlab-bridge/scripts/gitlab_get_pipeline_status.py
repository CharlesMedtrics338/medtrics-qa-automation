#!/usr/bin/env python3
"""
gitlab_get_pipeline_status.py — green-pipeline gate.

Returns the status of the most recent pipeline for an MR's head SHA.
Used by qa-checklist-reader before kicking off any execution: per the QA
Process v2.2 contract, an automated QA1 run waits for the MR pipeline to
go green before continuing.

Output JSON (stdout):
  { "ok": true, "mr_iid": <int>, "status": "<status>" }

GitLab statuses: "success", "running", "pending", "failed", "skipped",
"canceled", "manual", "unknown" (when no pipelines exist).

Exit codes:
  0 — status fetched (regardless of value)
  1 — env/config error
  3 — fetch failed

Usage:
  python3 gitlab_get_pipeline_status.py --iid 6865
  python3 gitlab_get_pipeline_status.py --iid 6865 --project-id 1496872
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from gitlab_client import load_env, get_pipeline_status, log  # noqa: E402

# qa-cache lives in a sibling skill; add its scripts to the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "qa-cache" / "scripts"))
import cache  # noqa: E402

CACHE_NAMESPACE = "gitlab.pipeline"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--iid", required=True)
    p.add_argument("--project-id", help="Override env GITLAB_PROJECT_ID")
    p.add_argument("--env-file", help="Explicit path to a .env file.")
    p.add_argument("--cache-ttl", type=int, default=120,
                   help="qa-cache TTL in seconds (GAP-11: default 120, cache-on by "
                        "default). Pass 0 or --no-cache to bypass.")
    p.add_argument("--no-cache", action="store_true",
                   help="Force a live GitLab fetch even if cache has a fresh entry.")
    args = p.parse_args()

    env = load_env(args.env_file)
    project_id = args.project_id or env.get("GITLAB_PROJECT_ID")
    cache_key = f"{project_id}:{args.iid}"

    # Cache read path.
    if args.cache_ttl > 0 and not args.no_cache:
        hit = cache.get(CACHE_NAMESPACE, cache_key)
        if hit is not None:
            hit["cache"] = "hit"
            print(json.dumps(hit))
            return 0 if hit.get("status") != "unknown" else 3

    status = get_pipeline_status(env, args.iid, project_id=args.project_id)
    if status == "unknown":
        log(f"WARNING: No pipelines found for MR {args.iid} (or fetch failed).")

    payload = {"ok": status != "unknown", "mr_iid": int(args.iid), "status": status, "cache": "miss"}

    # Cache write path — only memoize successful responses.
    if args.cache_ttl > 0 and not args.no_cache and status != "unknown":
        cache.put(CACHE_NAMESPACE, cache_key, payload, ttl_seconds=args.cache_ttl)

    print(json.dumps(payload))
    return 0 if status != "unknown" else 3


if __name__ == "__main__":
    sys.exit(main())
