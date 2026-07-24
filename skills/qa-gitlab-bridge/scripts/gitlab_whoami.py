#!/usr/bin/env python3
"""
gitlab_whoami.py — pre-flight token check.

GET /api/v4/user — verifies the token is valid and prints the authenticated
GitLab user. Used by /setup-medtrics-qa-automation as the first verification
step before persisting config.

Exit codes:
  0 — token valid; user JSON printed to stdout
  1 — token missing or env load failed (lib prints diagnostics to stderr)
  2 — token present but the API rejected it (401/403)

Usage:
  python3 gitlab_whoami.py                          # use discovered .env
  python3 gitlab_whoami.py --env-file /path/.env
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from gitlab_client import load_env, whoami, log  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file", help="Explicit path to a .env file.")
    args = p.parse_args()

    env = load_env(args.env_file, require=("GITLAB_TOKEN",))
    user = whoami(env)
    if user is None:
        log("ERROR: GitLab rejected the token (401/403) or network failed.")
        return 2
    print(json.dumps({
        "ok": True,
        "username": user.get("username"),
        "name": user.get("name"),
        "id": user.get("id"),
        "gitlab_url": env.get("GITLAB_URL"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
