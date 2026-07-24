#!/usr/bin/env python3
"""
gitlab_download_upload.py — download a project upload (attached file from an
MR discussion).

Hits `GET /api/v4/projects/:id/uploads/:secret/:filename` with PRIVATE-TOKEN.
This is the **API** path; the raw `gitlab.com/<namespace>/<repo>/uploads/...`
URL that appears in markdown notes is Cloudflare-gated and returns a 403
"Just a moment" bot challenge to non-browser clients. Use this script
instead.

Pair with `gitlab_find_mr_attachment.py` to locate the right secret +
filename from the MR's discussions.

Usage:
    # write to stdout (binary-safe):
    python3 gitlab_download_upload.py \\
        --secret 0e2a605a3146a2db9ae2b6d78761114d \\
        --filename fix-m1-1190-...-manual-qa-checklist.txt

    # write to a file:
    python3 gitlab_download_upload.py --secret ... --filename ... \\
        --out /tmp/checklist.txt

Output:
    On success: file bytes go to --out or stdout; stderr gets a one-line
    success message with the byte count.

Exit codes:
    0 — downloaded
    1 — env / input error
    3 — download failed (HTTP error, network, etc.; gitlab_client logged the reason)
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from gitlab_client import load_env, get_project_upload, log  # noqa: E402

# qa-cache lives under the qa-cache skill.
_QA_CACHE = (
    Path(__file__).resolve().parent.parent.parent / "qa-cache" / "scripts"
)
if _QA_CACHE.exists():
    sys.path.insert(0, str(_QA_CACHE))
    try:
        import cache  # noqa: E402
    except ImportError:
        cache = None
else:
    cache = None

CACHE_NAMESPACE = "gitlab.download_upload"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--secret", required=True, help="GitLab upload secret (hex token).")
    p.add_argument("--filename", required=True, help="Upload filename (as it appears in the URL).")
    p.add_argument("--project-id", help="Override env GITLAB_PROJECT_ID.")
    p.add_argument("--env-file", help="Explicit .env path.")
    p.add_argument("--out", type=Path,
                   help="Write the bytes to this file. Default: stdout.")
    p.add_argument("--cache-ttl", type=int, default=600,
                   help="qa-cache TTL in seconds (GAP-11: default 600 — uploads are "
                        "immutable per secret/filename). Pass 0 or --no-cache to bypass.")
    p.add_argument("--no-cache", action="store_true",
                   help="Force a live download even if cache has a fresh entry.")
    args = p.parse_args()

    env = load_env(args.env_file)
    project_id = args.project_id or env.get("GITLAB_PROJECT_ID")
    cache_key = f"{project_id}:{args.secret}:{args.filename}"
    use_cache = (cache is not None) and (args.cache_ttl > 0) and (not args.no_cache)

    # Cache read path. Bytes are stored as base64 since qa-cache is JSON-backed.
    data: bytes | None = None
    if use_cache:
        hit = cache.get(CACHE_NAMESPACE, cache_key)
        if hit is not None and isinstance(hit, dict) and "b64" in hit:
            data = base64.b64decode(hit["b64"])
            log(f"qa-cache HIT {CACHE_NAMESPACE} {cache_key} ({len(data)} bytes)")

    if data is None:
        data = get_project_upload(env, args.secret, args.filename, project_id=args.project_id)
        if data is None:
            return 3
        if use_cache:
            cache.put(
                CACHE_NAMESPACE,
                cache_key,
                {"b64": base64.b64encode(data).decode("ascii")},
                ttl_seconds=args.cache_ttl,
            )

    if args.out:
        args.out.write_bytes(data)
        log(f"Wrote {len(data)} bytes to {args.out}")
    else:
        sys.stdout.buffer.write(data)
        log(f"Streamed {len(data)} bytes to stdout for {args.filename}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
