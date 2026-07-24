#!/usr/bin/env python3
"""
poll_download.py

Wait for a Chrome MCP gif_creator export to finish writing into the mounted
~/Downloads folder.

Polls the target path every 250ms. A file is considered "ready" when it exists,
is non-empty, AND its size is stable for at least one polling interval (size
unchanged between consecutive polls — guarantees Chrome finished writing).

Exits 0 on success, 1 on timeout, 2 on empty file.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


DEFAULT_INTERVAL_MS = 250
DEFAULT_TIMEOUT_S = 15.0


def wait_for_file(path: Path, *, interval_ms: int = DEFAULT_INTERVAL_MS,
                  timeout_s: float = DEFAULT_TIMEOUT_S) -> tuple[str, int]:
    """Block until `path` exists with stable size, or timeout.

    Returns (status, exit_code).
    status ∈ {"ready", "timeout", "empty"}.
    """
    deadline = time.monotonic() + timeout_s
    last_size = -1
    while time.monotonic() < deadline:
        try:
            st = path.stat()
            size = st.st_size
        except FileNotFoundError:
            size = -1

        if size > 0 and size == last_size:
            return ("ready", 0)

        last_size = size
        time.sleep(interval_ms / 1000.0)

    if last_size == 0:
        return ("empty", 2)
    return ("timeout", 1)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", type=Path, required=True,
                   help="Absolute path of the file to wait for.")
    p.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--interval-ms", type=int, default=DEFAULT_INTERVAL_MS)
    args = p.parse_args()

    status, code = wait_for_file(args.path,
                                 interval_ms=args.interval_ms,
                                 timeout_s=args.timeout_s)
    sys.stdout.write(status + "\n")
    if status == "ready":
        try:
            sys.stdout.write(f"size_bytes={os.path.getsize(args.path)}\n")
        except OSError:
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
