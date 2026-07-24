#!/usr/bin/env python3
"""
build_attachment_record.py

Compose the attachment record(s) qa-fail-reporter's build_verdict_thread.py
consumes. Takes the result of gitlab_upload_file.py (JSON on stdin) plus the
step metadata as flags, emits an attachment record on stdout.

Pure-Python. No I/O beyond stdin/stdout. Splitting this out keeps the orchestration
shell-script simple — every upload becomes a one-liner that pipes the upload
result into this script.

Input on stdin (JSON):

    {
      "ok": true,
      "id": 1138110302,
      "alt": "screenshot",
      "url": "/uploads/abc.../screenshot.gif",
      "full_path": "...",
      "markdown": "![screenshot](/uploads/abc.../screenshot.gif)"
    }

Or for a failed upload:

    {"ok": false, "error": "..."}

Output on stdout (JSON, one record):

    {
      "step_n": 3,
      "label": "screenshot",
      "kind": "image",
      "path": "outputs/qa/M1-1206/.../step3/screenshot.gif",
      "gitlab_url": "/uploads/abc.../screenshot.gif",
      "gitlab_markdown": "![screenshot](/uploads/abc.../screenshot.gif)"
    }
"""

from __future__ import annotations

import argparse
import json
import sys


KIND_BY_LABEL = {
    "screenshot": "image",
    "console":    "log",
    "network":    "log",
    "dom":        "html",
}


def build_record(*, step_n: int, label: str, path: str, upload_result: dict) -> dict:
    """Compose one attachment record from an upload result.

    Always emits a record — when upload failed, `gitlab_markdown` is absent and
    the verdict-thread renderer falls back to a local-path reference.
    """
    record = {
        "step_n": int(step_n),
        "label": label,
        "kind": KIND_BY_LABEL.get(label, "file"),
        "path": path,
    }
    if upload_result.get("ok"):
        record["gitlab_url"] = upload_result.get("url", "")
        record["gitlab_markdown"] = upload_result.get("markdown", "")
        record["gitlab_id"] = upload_result.get("id")
    else:
        record["upload_error"] = upload_result.get("error", "unknown")
    return record


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--step-n", type=int, required=True)
    p.add_argument("--label", required=True,
                   choices=["screenshot", "console", "network", "dom"])
    p.add_argument("--path", required=True,
                   help="Outputs-relative path of the artifact on disk.")
    args = p.parse_args()

    raw = sys.stdin.read()
    try:
        upload_result = json.loads(raw) if raw.strip() else {"ok": False, "error": "empty_stdin"}
    except json.JSONDecodeError as e:
        upload_result = {"ok": False, "error": f"invalid_json: {e}"}

    record = build_record(
        step_n=args.step_n,
        label=args.label,
        path=args.path,
        upload_result=upload_result,
    )
    sys.stdout.write(json.dumps(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
