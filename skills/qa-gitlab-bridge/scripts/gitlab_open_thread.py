#!/usr/bin/env python3
"""
gitlab_open_thread.py — post a discussion thread on a merge request.

POST /api/v4/projects/:id/merge_requests/:iid/discussions
json: { "body": "<markdown>" }

Used by qa-fail-reporter to post the structured fail-thread on the MR.
The body is composed upstream by build_fail_thread.py; this script is
the thin transport.

Phase gating is enforced by qa-guardrails.gate_write("gitlab", phase)
in the caller — this script does NOT consult the phase flag. Callers
MUST refuse to invoke this script in shadow.

PII redaction is the caller's responsibility — qa-fail-reporter runs the
rendered body through qa-guardrails.redact_pii + assert_evidence_clean
before invoking this script.

Body source:
  --body          inline string (small bodies)
  --body-file     path to a markdown file (typical for fail-threads)
  --body-stdin    read the body from stdin (pipeline-friendly)

Exit codes:
  0 — thread posted
  1 — env/config error
  2 — input error (no body provided / body file missing)
  3 — GitLab post failed (lib logged the reason)

Output JSON (stdout):
  { "ok": true, "discussion_id": <str>, "note_id": <int|null>,
    "thread_url": <str|null> }

Usage:
  python3 gitlab_open_thread.py --iid 6865 --body-file thread.md
  echo "Hello MR" | python3 gitlab_open_thread.py --iid 6865 --body-stdin
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from gitlab_client import load_env, post_mr_discussion, get_mr, log  # noqa: E402


def _build_thread_url(mr, env, iid, note_id):
    """Build the user-facing URL for a freshly-posted note.

    GAP-19: prefer mr.web_url (namespace-path-based, e.g.
    https://gitlab.com/medtrics/medtrics/-/merge_requests/6865) over the
    legacy numeric-project-id construction, which 404s when GITLAB_PROJECT_ID
    is the numeric form.
    """
    if not note_id:
        return None
    if isinstance(mr, dict) and mr.get("web_url"):
        return f"{mr['web_url']}#note_{note_id}"
    # Fallback: legacy construction. Logged so the caller can spot the
    # degraded case in the audit log.
    base_web = (env.get("GITLAB_URL") or "").rstrip("/")
    log("WARN: mr.web_url missing — falling back to numeric-id thread_url. "
        "URL may not resolve in the browser.")
    return f"{base_web}/{env.get('GITLAB_PROJECT_ID')}/-/merge_requests/{iid}#note_{note_id}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--iid", required=True, help="MR internal ID, e.g. 6865")
    p.add_argument("--project-id", help="Override env GITLAB_PROJECT_ID")
    p.add_argument("--env-file", help="Explicit path to a .env file.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--body", help="Inline body string.")
    g.add_argument("--body-file", type=Path, help="Path to a markdown file.")
    g.add_argument("--body-stdin", action="store_true", help="Read body from stdin.")
    p.add_argument("--no-refuse-on-closed", action="store_true",
                   help="Allow posting on closed/merged MRs (default: refuse).")
    args = p.parse_args()

    if args.body is not None:
        body = args.body
    elif args.body_file is not None:
        if not args.body_file.exists():
            log(f"ERROR: body file not found: {args.body_file}")
            return 2
        body = args.body_file.read_text(encoding="utf-8")
    else:
        body = sys.stdin.read()

    if not body.strip():
        log("ERROR: refusing to post empty body.")
        return 2

    env = load_env(args.env_file)

    # Fetch MR up front — needed for (a) the closed-state check and (b) the
    # web_url field that anchors the returned thread_url. The MR fetch is
    # cached by gitlab_client (GAP-11), so this is cheap on repeat calls.
    mr = get_mr(env, args.iid, project_id=args.project_id)

    # Refuse on closed/merged MRs by default — fail-threads on already-shipped
    # MRs are out of scope.
    if not args.no_refuse_on_closed:
        if isinstance(mr, dict) and mr.get("state") in ("closed", "merged"):
            log(f"ERROR: refusing to post on MR {args.iid} (state={mr['state']}). "
                "Pass --no-refuse-on-closed to override.")
            return 3

    data, _ = post_mr_discussion(env, args.iid, body, project_id=args.project_id)
    if not isinstance(data, dict):
        log("ERROR: post_mr_discussion returned no payload.")
        return 3

    notes = data.get("notes") or []
    first_note = notes[0] if notes else {}
    note_id = first_note.get("id")
    discussion_id = data.get("id") or ""
    thread_url = _build_thread_url(mr, env, args.iid, note_id)

    print(json.dumps({
        "ok": True,
        "discussion_id": discussion_id,
        "note_id": note_id,
        "thread_url": thread_url,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
