# medtrics-qa-automation — install / use

A Claude Code / Cowork & Cursor plugin: automated QA1 against per-MR deploys. The plugin
**reads** a human-authored `## QA Checklist` section from the Optimus ticket,
matches against a deterministic scenario matrix, falls back to driving Claude
in Chrome through the checklist steps when no matrix rule fires, and judges
every step by code (not by the agent's opinion). Enforceable guardrails layer
gates destructive actions, PII writes, and phase transitions.

## Python dependencies

Almost everything is stdlib. The only third-party runtime import is `PyYAML`
(used by the deterministic API-lane dispatcher to load
`qa/scenario-matrix.yaml`):

```bash
pip install -r requirements.txt
# or, on systems that reject pip without it:
pip install -r requirements.txt --break-system-packages
```

`requirements-dev.txt` adds `pytest` for running the suite.

`/setup-medtrics-qa-automation` checks for `PyYAML` at step 0 and stops with a
prompt to install if absent. Skipping the install is supported but disables
the API lane — the UI lane still works.

Tested on Python 3.10+.

## Install (Claude Code CLI)

1. Unzip this archive somewhere, e.g. `~/plugins/`.
2. `cd` into it and `pip install -r requirements.txt` (see above).
3. One-off, for a single session:

       claude --plugin-dir "/full/path/to/medtrics-qa-automation"

4. Or install it persistently from a local marketplace:

       # point at the FOLDER that contains medtrics-qa-automation/
       claude plugin marketplace add "/full/path/to"
       claude plugin install medtrics-qa-automation@<marketplace-name>
       claude plugin list

Verify it loaded: `claude plugin list` (or type `/` to see the slash commands).

## Install (Cowork desktop)

Save the `.plugin` file from this archive's parent dir and click the install
button presented by the chat interface, or drop the file into your Cowork
plugins folder. Then `pip install -r requirements.txt` from wherever the
plugin unpacks (Cowork shows the path in the install confirmation).

## Install (Cursor)

1. In Cursor, open **Settings → Plugins / Extensions**.
2. Select **Install from local directory** or upload package pointing to the repository containing `.cursor-plugin/` and `manifest.json`.
3. Verify slash commands and skills load from `./commands/` and `./skills/`.

## First-run setup

Run `/setup-medtrics-qa-automation`. It collects:
- Optimus product slug (default `medtrics`)
- GitLab project ID
- Slack staging channel (where verdict cards land)
- Slack regression channel (default `#dream-team`)
- Polling interval (default 5 min; `0` disables)
- Phase flag (`shadow` recommended for first install)

Writes `~/.medtrics-qa-automation/config.json` and optionally creates the
5-minute polling task and the bi-weekly regression task.

## Connectors required

The full pipeline uses these MCPs:
- **Optimus** (`mcp__904fdec1-…`) — task reads and writes
- **GitLab MCP** — MR resolution, fail-thread writes
- **Mem** (`mcp__34ae805e-…`) — `QA Run Logs` and `Regression Run Logs`
- **Claude in Chrome** — the browser driver for both lanes
- **Slack** — verdict staging cards and regression roll-ups

Configure these in your Claude Code / Cowork environment before running. The
pure-logic pieces (scenario dispatcher, guardrails, checklist parser, diff
helper) run with no MCP and are unit-testable in isolation.

## Slash commands

| Command | Purpose |
|---|---|
| `/setup-medtrics-qa-automation` | First-run config + optional scheduled tasks |
| `/qa1-poll` | Single poll of the Optimus qa1 lane (read-only) |
| `/manual-qa-execute [ticket]` | Per-ticket executor; picks the lane automatically |
| `/ui-qa-execute <ticket>` | Forces the agentic UI lane on one ticket |
| `/regression-execute` | Bi-weekly module-pack runner |

## What's inside

```
.claude-plugin/plugin.json
commands/                       # five slash-command files
skills/
  qa-config                     # config schema + bootstrap
  qa-memory                     # Mem warm-tier (QA Run Logs)
  qa-audit                      # append-only audit JSONL
  qa-queue                      # Cowork Live Artifact dashboard
  qa-checklist-reader           # reads '## QA Checklist' from Optimus description
  qa-chrome-executor            # API lane — scenario-matrix + Chrome MCP
  qa-ui-executor                # UI lane — drives Chrome, judges by code
  qa-guardrails                 # enforced safety (guardrails.py)
  qa-optimus-bridge             # Optimus MCP wrapper
  qa-gitlab-bridge              # GitLab MCP wrapper
  qa-poller                     # the 5-min trigger
qa/scenario-matrix.yaml         # deterministic rules
conftest.py + pytest.ini        # shared pytest setup (plugin root)
requirements.txt                # runtime deps (PyYAML)
requirements-dev.txt            # adds pytest
# Each skill is self-contained: SKILL.md + scripts/ + templates/ + tests/.
# Tests live next to the skill they exercise, fixtures sit alongside.
```

## Author your checklist (the human input)

Put this in the Optimus ticket description, under a stable heading:

```markdown
## QA Checklist

Tester role: coordinator
Branch: feat/m1-1234/csv-encoding-fix

1. [P0] Navigate to /curriculum/imports and click "Download CSV template"
   Expected: A CSV file downloads; UTF-8 punctuation, no mojibake.

2. [P1] Visit /curriculum/courses
   Expected: Table shows 8 rows.
```

A ticket without this section blocks with `blocked_reason: checklist_missing`.
**The plugin will not auto-generate a checklist.**
