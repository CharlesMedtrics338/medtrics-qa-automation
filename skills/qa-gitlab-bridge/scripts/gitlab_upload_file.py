#!/usr/bin/env python3
"""
gitlab_upload_file.py — upload one file (typically a step screenshot) to a
project's uploads endpoint.

POST /api/v4/projects/:id/uploads (multipart/form-data: file=@<path>)

Used by qa-fail-reporter to attach before/after screenshots to the fail
thread it posts on the MR.

Phase gating is enforced by qa-guardrails.gate_write("gitlab", phase) in
the caller — this script does NOT consult the phase flag. Callers MUST
refuse to invoke this script in shadow.

Output JSON (stdout):
  { "ok": true, "alt": <str>, "url": <str>, "full_path": <str>,
    "markdown": <str>, "id": <int|null> }

The `markdown` field is the markdown image link qa-fail-reporter splices
into the thread body.

Exit codes:
  0 — uploaded
  1 — env/config error
  2 — file not found
  3 — upload failed (lib logged the reason to stderr)

Usage:
  python3 gitlab_upload_file.py --path outputs/qa/M1-1190/step-2.png
  python3 gitlab_upload_file.py --path outputs/qa/M1-1190/step-2.png --project-id 1496872
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from gitlab_client import load_env, upload_file, log  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", required=True, type=Path,
                   help="Absolute or cwd-relative path to the file to upload.")
    p.add_argument("--project-id", help="Override env GITLAB_PROJECT_ID")
    p.add_argument("--env-file", help="Explicit path to a .env file.")
    args = p.parse_args()

    if not args.path.exists():
        log(f"ERROR: file not found: {args.path}")
        return 2

    env = load_env(args.env_file)
    result = upload_file(env, args.path, project_id=args.project_id)
    if result is None:
        return 3
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
