#!/usr/bin/env python3
"""
build_dashboard_widget.py — compose the Cowork Live Artifact widget_code for
qa1-queue-dashboard.

Reads templates/dashboard.html and substitutes six {{PLACEHOLDERS}} with
config-time values (Optimus + Mem MCP tool names, the Mem QA Run Logs
collection UUID, Optimus product + lane, dashboard title). Emits the
fully-composed HTML to stdout (or to --out).

The result is the `widget_code` argument to mcp__cowork__create_artifact /
update_artifact. Idempotent — running this twice with the same inputs
produces byte-identical output.

Placeholders (exact, case-sensitive):
    {{OPTIMUS_LIST_LANE_TASKS_TOOL}}
    {{MEM_LIST_NOTES_TOOL}}
    {{MEM_RUN_LOGS_COLLECTION_ID}}
    {{OPTIMUS_PRODUCT}}
    {{OPTIMUS_QA1_LANE}}
    {{COWORK_DASHBOARD_TITLE}}

Usage:
    python3 build_dashboard_widget.py \
        --optimus-tool "mcp__904fdec1-...__list_lane_tasks" \
        --mem-tool     "mcp__34ae805e-...__list_notes" \
        --mem-collection-id "<uuid-from-config.mem.run_logs_collection_id>" \
        --optimus-product medtrics \
        --qa1-lane qa1

Or, drive it directly from a config file (preferred):
    python3 build_dashboard_widget.py --config ~/.medtrics-qa-automation/config.json

GAP-2 (v0.10.0): the example UUID that was hardcoded here has been removed.
Always source the collection UUID from `config.mem.run_logs_collection_id` —
the live UUID is provisioned per-install by /setup-medtrics-qa-automation.

Exit codes:
    0 — widget composed
    1 — input error (missing config, unknown placeholder leftover)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dashboard.html"
DEFAULT_TITLE = "Automated QA1 — Queue"

# Canonical placeholders. Anything else in the template that looks like
# {{NAME}} is an error caught by the unknown-leftover guard below.
PLACEHOLDERS = (
    "OPTIMUS_LIST_LANE_TASKS_TOOL",
    "MEM_LIST_NOTES_TOOL",
    "MEM_RUN_LOGS_COLLECTION_ID",
    "OPTIMUS_PRODUCT",
    "OPTIMUS_QA1_LANE",
    "COWORK_DASHBOARD_TITLE",
)


def build(template: str, values: dict) -> str:
    """Substitute every {{KEY}} in `template` with the matching value.

    Raises ValueError on:
      - a required placeholder missing from `values`
      - an unknown {{KEY}} left in the output (typo or new placeholder
        added to the template without updating PLACEHOLDERS)
    """
    out = template
    for key in PLACEHOLDERS:
        token = "{{" + key + "}}"
        if token not in out:
            # Template doesn't use this placeholder — that's fine, skip.
            continue
        if key not in values or values[key] is None:
            raise ValueError(f"missing required value for placeholder {key}")
        out = out.replace(token, str(values[key]))

    # Guard: no {{...}} left in the final widget code.
    import re
    leftovers = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if leftovers:
        raise ValueError(
            "unknown placeholders left in widget output: " + ", ".join(sorted(set(leftovers)))
        )
    return out


def values_from_config(cfg: dict) -> dict:
    """Pull placeholder values out of the user's config.json shape."""
    optimus = cfg.get("optimus") or {}
    mem = cfg.get("mem") or {}
    cowork = cfg.get("cowork") or {}
    # The MCP tool names are environment-dependent. Default to the medtrics
    # MCP server UUIDs documented in the plugin's substrate skills; allow
    # override via config.mcp.* if the user has remapped them.
    mcp = cfg.get("mcp") or {}
    return {
        "OPTIMUS_LIST_LANE_TASKS_TOOL": mcp.get("optimus_list_lane_tasks_tool")
            or "mcp__904fdec1-f755-42c5-a32e-a3a9eb8ba1da__list_lane_tasks",
        "MEM_LIST_NOTES_TOOL": mcp.get("mem_list_notes_tool")
            or "mcp__34ae805e-29a6-4131-894e-fddbf3723a2d__list_notes",
        "MEM_RUN_LOGS_COLLECTION_ID": mem.get("run_logs_collection_id"),
        "OPTIMUS_PRODUCT": optimus.get("product") or "medtrics",
        "OPTIMUS_QA1_LANE": optimus.get("qa1_lane") or "qa1",
        "COWORK_DASHBOARD_TITLE": cowork.get("dashboard_title") or DEFAULT_TITLE,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE,
                   help="Path to dashboard.html template.")
    p.add_argument("--config", type=Path,
                   help="Path to ~/.medtrics-qa-automation/config.json. "
                        "If passed, values are derived from it.")
    p.add_argument("--optimus-tool", help="MCP tool name for Optimus list_lane_tasks.")
    p.add_argument("--mem-tool", help="MCP tool name for Mem list_notes.")
    p.add_argument("--mem-collection-id", help="UUID of the QA Run Logs Mem collection.")
    p.add_argument("--optimus-product", default="medtrics")
    p.add_argument("--qa1-lane", default="qa1")
    p.add_argument("--title", default=DEFAULT_TITLE)
    p.add_argument("--out", type=Path, help="Write to file instead of stdout.")
    args = p.parse_args()

    if args.config:
        if not args.config.exists():
            print(json.dumps({"error": "config_not_found", "path": str(args.config)}),
                  file=sys.stderr)
            return 1
        values = values_from_config(json.loads(args.config.read_text(encoding="utf-8")))
    else:
        values = {
            "OPTIMUS_LIST_LANE_TASKS_TOOL": args.optimus_tool,
            "MEM_LIST_NOTES_TOOL": args.mem_tool,
            "MEM_RUN_LOGS_COLLECTION_ID": args.mem_collection_id,
            "OPTIMUS_PRODUCT": args.optimus_product,
            "OPTIMUS_QA1_LANE": args.qa1_lane,
            "COWORK_DASHBOARD_TITLE": args.title,
        }

    # GAP-2: refuse to render with a null collection UUID. The widget would
    # silently call list_notes with collection_id=null and return zero rows,
    # masking the real failure mode (setup not run / Mem provisioning skipped).
    if not values.get("MEM_RUN_LOGS_COLLECTION_ID"):
        print(json.dumps({
            "error": "mem_collection_missing",
            "reason": "config.mem.run_logs_collection_id is null. Run "
                      "/setup-medtrics-qa-automation (step 4) to provision the "
                      "Mem QA Run Logs collection, then re-run /qa-dashboard.",
        }), file=sys.stderr)
        return 1

    if not args.template.exists():
        print(json.dumps({"error": "template_not_found", "path": str(args.template)}),
              file=sys.stderr)
        return 1

    try:
        widget = build(args.template.read_text(encoding="utf-8"), values)
    except ValueError as e:
        print(json.dumps({"error": "build_failed", "reason": str(e)}), file=sys.stderr)
        return 1

    if args.out:
        args.out.write_text(widget, encoding="utf-8")
    else:
        sys.stdout.write(widget)
    return 0


if __name__ == "__main__":
    sys.exit(main())
