#!/usr/bin/env python3
"""
merge_attachments.py

Merge per-step attachment records into the run-wide attachments index that
build_verdict_thread.py consumes.

Reads any number of attachment-record files (one per artifact) and writes the
aggregated index to --out (or stdout). Optionally applies a per-step cap.

Aggregated shape:

    {
      "attachments": [<record>, <record>, ...],
      "truncated": false,
      "truncated_count": 0,
      "total_count": <n>
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--records-dir", type=Path, required=True,
                   help="Directory containing one .json record per artifact.")
    p.add_argument("--per-step-cap", type=int, default=0,
                   help="If >0, keep at most this many records per step_n.")
    p.add_argument("--out", type=Path, help="Write the index here; stdout if omitted.")
    args = p.parse_args()

    records: list[dict] = []
    if args.records_dir.exists():
        for f in sorted(args.records_dir.glob("*.json")):
            try:
                records.append(json.loads(f.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue

    truncated = False
    truncated_count = 0
    if args.per_step_cap > 0:
        per_step: dict[int, int] = {}
        kept: list[dict] = []
        for r in records:
            n = r.get("step_n", 0)
            per_step[n] = per_step.get(n, 0) + 1
            if per_step[n] <= args.per_step_cap:
                kept.append(r)
            else:
                truncated_count += 1
        truncated = truncated_count > 0
        records = kept

    index = {
        "attachments": records,
        "truncated": truncated,
        "truncated_count": truncated_count,
        "total_count": len(records) + truncated_count,
    }

    out_text = json.dumps(index, indent=2)
    if args.out:
        args.out.write_text(out_text, encoding="utf-8")
    else:
        sys.stdout.write(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
