#!/usr/bin/env python3
"""
guardrails.py — enforceable safety layer for medtrics-qa-automation.

P1-3. The executor (qa-ui-executor) and any writes-back path call these pure
functions BEFORE doing anything that touches the deploy or persists evidence.
They are deterministic, dependency-free, and unit-tested — the same trust
property as the assertion layer: safety decisions come from code, not from the
agent's judgment.

Four enforcement surfaces:

  screen_action(action, phase)   -> Decision   gate a browser action (block
                                                destructive clicks in shadow)
  gate_write(system, phase)      -> Decision   gate a write-back (Optimus /
                                                GitLab blocked in shadow; Slack
                                                staging card allowed)
  redact_pii(text)               -> (clean_text, kinds_found)
                                                scrub evidence before any write

Plus HARD_TIMEOUT_S / STEP_TIMEOUT_S the executor enforces on the clock.

A Decision is {allowed, severity, reason}. severity is "ok" | "warn" | "block".
Callers MUST refuse to proceed on severity == "block"; "warn" proceeds but the
reason is recorded in the audit row / Mem note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

HARD_TIMEOUT_S = 600        # 10 min per run
STEP_TIMEOUT_S = 30         # per step

VALID_PHASES = {"shadow", "writes-on"}

# (v0.9.3) check_persona removed — the 6-persona model was an aspirational
# spec built on top of a Django seed command that never shipped. Login
# behavior is now declared inside each checklist's own steps; the executor
# follows what the checklist says rather than consulting a schema.

# A control whose label/selector matches this is destructive: irreversible or
# data-mutating in a way QA must never trigger incidentally. Roots match common
# inflections (delete/deleted/deleting) via \w*, while short ambiguous words are
# whole-word only so e.g. "dropdown" is NOT treated as destructive.
DESTRUCTIVE_RE = re.compile(
    r"(?ix)"
    r"\b(?:delet\w*|remov\w*|deactivat\w*|deprovision\w*|purg\w*|wip\w*|"
    r"eras\w*|revok\w*|archiv\w*|disenroll\w*|terminat\w*|reset\w*)\b"
    r"|\bdrop\b"
)

# Writes that change something a human or other system sees. In shadow only the
# Slack staging card (a review surface, not a system-of-record write) is allowed.
WRITE_SYSTEMS = {"optimus", "gitlab", "slack", "mem"}
SHADOW_ALLOWED_WRITES = {"slack", "mem"}   # Mem run-log is our own evidence store


@dataclass
class Decision:
    allowed: bool
    severity: str   # "ok" | "warn" | "block"
    reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _block(reason: str) -> Decision:
    return Decision(allowed=False, severity="block", reason=reason)


def _warn(reason: str) -> Decision:
    return Decision(allowed=True, severity="warn", reason=reason)


def _ok(reason: str = "") -> Decision:
    return Decision(allowed=True, severity="ok", reason=reason)


# --------------------------------------------------------------------------- #
# 1. Action screening
# --------------------------------------------------------------------------- #


def screen_action(action: dict, phase: str) -> Decision:
    """Gate one browser action before it is driven.

    action keys (all optional except kind):
      kind     navigate | click | fill | upload | screenshot | capture | ...
      selector CSS selector / element reference, if any
      label    human label of the control (e.g. button text)
      expected the step's expected-result text (used to tell whether a
               destructive action is the thing under test)
    """
    if phase not in VALID_PHASES:
        return _block(f"unknown_phase:{phase}")

    kind = (action.get("kind") or "").lower()
    target = " ".join(str(action.get(k, "")) for k in ("selector", "label"))
    expected = action.get("expected", "") or ""

    # Read-only verbs are always safe.
    if kind in {"navigate", "screenshot", "capture", "wait_for_text", "noop", "find"}:
        return _ok()

    # Destructive controls.
    if DESTRUCTIVE_RE.search(target):
        if phase != "writes-on":
            return _block("destructive_action_in_shadow")
        # In writes-on, only allow if the STEP is explicitly testing that
        # destructive behavior (the expectation references it).
        if DESTRUCTIVE_RE.search(expected):
            return _warn("destructive_action_under_test")
        return _block("destructive_action_not_under_test")

    # Mutating verbs (fill/upload/click-submit) are fine against an ephemeral MR
    # deploy for QA, but flagged so the audit trail shows the run mutated state.
    if kind in {"fill", "upload", "submit_form"}:
        return _warn(f"mutating_action:{kind}")
    if kind == "click":
        # A plain click is usually navigation/expansion; allow.
        return _ok()

    # Anything unrecognized is held for a human rather than improvised.
    return _block(f"unrecognized_action_kind:{kind}")


# --------------------------------------------------------------------------- #
# 2. Write-back gating
# --------------------------------------------------------------------------- #


def gate_write(system: str, phase: str) -> Decision:
    system = (system or "").lower()
    if phase not in VALID_PHASES:
        return _block(f"unknown_phase:{phase}")
    if system not in WRITE_SYSTEMS:
        return _block(f"unknown_write_system:{system}")
    if phase == "writes-on":
        return _ok()
    # shadow
    if system in SHADOW_ALLOWED_WRITES:
        return _ok("shadow_allowed")
    return _block(f"write_blocked_in_shadow:{system}")


# --------------------------------------------------------------------------- #
# 3. PII / PHI redaction
# --------------------------------------------------------------------------- #

_PII_PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("PHONE", re.compile(r"\b(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")),
    ("BEARER", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+")),
    ("APIKEY", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9]{8,}\b")),
    ("MRN", re.compile(r"(?i)\bMRN[:#]?\s*\d{4,}\b")),
    ("CSRF", re.compile(r"(?i)\bcsrf(?:middleware)?token\b[\"'=:\s]+[A-Za-z0-9._\-]+")),
    ("DOB", re.compile(r"(?i)\bDOB[:#]?\s*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b")),
]


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Replace PII/PHI with [REDACTED:KIND]. Returns (clean_text, kinds_found).

    Order matters: EMAIL before PHONE so an email's digits aren't misread, etc.
    Idempotent — running it twice yields the same result.
    """
    if not text:
        return text, []
    found: list[str] = []
    out = text
    for kind, pat in _PII_PATTERNS:
        if pat.search(out):
            found.append(kind)
            out = pat.sub(f"[REDACTED:{kind}]", out)
    return out, found


def assert_evidence_clean(text: str) -> Decision:
    """Block a write if any PII/PHI remains after redaction would be applied."""
    _, kinds = redact_pii(text)
    if kinds:
        return _block("pii_present_in_evidence:" + ",".join(sorted(set(kinds))))
    return _ok()


# --------------------------------------------------------------------------- #
# CLI (smoke)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import json, sys
    demo = {
        "screen_delete_shadow": screen_action(
            {"kind": "click", "label": "Delete block"}, "shadow").as_dict(),
        "screen_save_shadow": screen_action(
            {"kind": "submit_form", "label": "Save"}, "shadow").as_dict(),
        "gate_optimus_shadow": gate_write("optimus", "shadow").as_dict(),
        "gate_slack_shadow": gate_write("slack", "shadow").as_dict(),
        "redact": redact_pii("contact qa-admin@test.medtrics.invalid MRN: 99123")[1],
    }
    json.dump(demo, sys.stdout, indent=2)
    print()
