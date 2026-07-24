#!/usr/bin/env python3
"""
cache.py — hot-tier filesystem cache with TTL semantics for medtrics-qa-automation.

Stdlib only. Stores each entry as a JSON file at:

    {CACHE_ROOT}/{namespace}/{sha1(namespace + ':' + key)}.json

Entry shape:

    {
      "namespace": "gitlab.get_mr",
      "key":       "<plaintext key>",
      "value":     <whatever the underlying source returned>,
      "written_at": "2026-06-03T03:00:00Z",
      "expires_at": "2026-06-03T03:05:00Z"
    }

CACHE_ROOT defaults to `~/.cache/medtrics-qa-automation/`. Override via the
`QA_CACHE_ROOT` env var (useful for tests). Files are written 0600 to keep
any API-response data out of other-user view.

Failure model: every helper here is best-effort. Read failures (parse error,
missing file, stale value, permission denied) return the `default` argument
to `get()` and never raise. Write failures log to stderr but do not raise —
the cache existing to speed things up, not to be load-bearing.

Public API:
    get(namespace, key, default=None) -> Any
    put(namespace, key, value, ttl_seconds) -> bool
    invalidate(namespace, key=None) -> int           # ret # entries removed
    cleanup_expired(namespace=None) -> int           # housekeeping
    stats() -> dict                                  # debug summary
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def _root() -> Path:
    """Resolve the cache root from env or home cache directory."""
    env = os.environ.get("QA_CACHE_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cache" / "medtrics-qa-automation"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    # second-precision ISO-8601 with trailing Z; matches the rest of the plugin
    return t.replace(microsecond=0).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _from_iso(s: str) -> dt.datetime:
    """Parse an ISO timestamp. Tolerates the Z suffix; returns UTC-aware dt."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s)


def _entry_path(namespace: str, key: str) -> Path:
    digest = hashlib.sha1(f"{namespace}:{key}".encode("utf-8")).hexdigest()
    return _root() / namespace / f"{digest}.json"


def _log(msg: str) -> None:
    print(f"[qa-cache] {msg}", file=sys.stderr)


def _read_entry(path: Path) -> dict | None:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _is_expired(entry: dict) -> bool:
    try:
        return _from_iso(entry.get("expires_at", "")) <= _now()
    except (ValueError, TypeError):
        # Corrupt timestamp → treat as expired.
        return True


# ---- public API ------------------------------------------------------------

def get(namespace: str, key: str, default: Any = None) -> Any:
    """Look up a cached value. Returns `default` on miss or expiry.

    Prunes the entry on the way out if it's expired so the directory
    doesn't accumulate stale files. Best-effort — any error returns
    `default`.
    """
    path = _entry_path(namespace, key)
    entry = _read_entry(path)
    if entry is None:
        return default
    if _is_expired(entry):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return default
    return entry.get("value", default)


def put(namespace: str, key: str, value: Any, ttl_seconds: int) -> bool:
    """Store `value` under (namespace, key) with TTL in seconds. Returns True
    on successful write, False on failure (logged to stderr, never raised).
    """
    if ttl_seconds <= 0:
        return False
    path = _entry_path(namespace, key)
    expires = _now() + dt.timedelta(seconds=ttl_seconds)
    entry = {
        "namespace": namespace,
        "key": key,
        "value": value,
        "written_at": _iso(_now()),
        "expires_at": _iso(expires),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Write to a temp file then rename — atomic on POSIX.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, separators=(",", ":")), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
        return True
    except OSError as e:
        _log(f"put failed for {namespace}:{key}: {e}")
        return False


def invalidate(namespace: str, key: str | None = None) -> int:
    """Delete cache entries. When `key` is None, clears the whole namespace.
    Returns the number of files removed. Never raises.
    """
    removed = 0
    if key is not None:
        path = _entry_path(namespace, key)
        try:
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError as e:
            _log(f"invalidate failed for {namespace}:{key}: {e}")
        return removed

    ns_dir = _root() / namespace
    if not ns_dir.is_dir():
        return 0
    for f in ns_dir.glob("*.json"):
        try:
            f.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def cleanup_expired(namespace: str | None = None) -> int:
    """Delete every expired entry. When `namespace` is None, sweep every
    namespace. Returns the number of files removed.
    """
    removed = 0
    root = _root()
    if not root.is_dir():
        return 0
    namespaces = [namespace] if namespace else [p.name for p in root.iterdir() if p.is_dir()]
    for ns in namespaces:
        ns_dir = root / ns
        if not ns_dir.is_dir():
            continue
        for f in ns_dir.glob("*.json"):
            entry = _read_entry(f)
            if entry is None or _is_expired(entry):
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    continue
    return removed


def stats() -> dict:
    """Return per-namespace { entries, expired, total_bytes } for debugging."""
    out: dict = {}
    root = _root()
    if not root.is_dir():
        return out
    for ns_dir in root.iterdir():
        if not ns_dir.is_dir():
            continue
        entries = 0
        expired = 0
        total_bytes = 0
        for f in ns_dir.glob("*.json"):
            try:
                total_bytes += f.stat().st_size
            except OSError:
                continue
            entry = _read_entry(f)
            if entry is None:
                continue
            entries += 1
            if _is_expired(entry):
                expired += 1
        out[ns_dir.name] = {
            "entries": entries,
            "expired": expired,
            "total_bytes": total_bytes,
        }
    return out


def main() -> int:
    """Tiny CLI so the cache is inspectable from the shell."""
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("stats")
    c1 = sub.add_parser("cleanup")
    c1.add_argument("--namespace", default=None)
    c2 = sub.add_parser("invalidate")
    c2.add_argument("--namespace", required=True)
    c2.add_argument("--key", default=None)
    args = p.parse_args()
    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.cmd == "cleanup":
        print(json.dumps({"removed": cleanup_expired(args.namespace)}))
    elif args.cmd == "invalidate":
        print(json.dumps({"removed": invalidate(args.namespace, args.key)}))
    else:
        p.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
