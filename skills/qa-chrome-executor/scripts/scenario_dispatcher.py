#!/usr/bin/env python3
"""
scenario_dispatcher.py

Deterministic execution layer for medtrics-qa-automation. Replaces the
LLM-fallback path in resolve_step_action.py.

Pipeline:
  1. load_matrix(path)            -> Matrix
  2. match_rule(matrix, ticket)   -> Rule | None
  3. run_negative_tests(rule)     -> bool   (must pass before scoring; if a
                                            known-bad fixture is scored as
                                            pass, the scanner is broken and
                                            the whole run is unreliable)
  4. expand_scenarios(rule)       -> list[ResolvedScenario]
                                    (cartesian over `for_each`)
  5. execute_scenario(rs, ctx)    -> ScenarioResult
                                    (drives Chrome MCP via the caller — this
                                    module returns the *plan*, the SKILL.md
                                    procedure dispatches the actual MCP calls)
  6. aggregate(results, criteria) -> Verdict
                                    (100% P0, >=90% P1; P2 informational)

The dispatcher is pure-Python with no side effects. It returns structured
plans the orchestrating skill executes. This keeps the test surface tiny
and lets unit tests cover the rule-matching + assertion logic with no
network.

Action verb whitelist (closed vocabulary):
  fetch              GET/POST a URL, return body + headers + status
  navigate           Chrome MCP navigate to a route
  upload_and_verify  Chrome MCP file_upload + assertion

Assertion kinds: utf8_bom_present, no_mojibake, status_2xx, status_eq,
header_eq, body_contains, body_not_contains, schema_matches,
byte_length_gte.

Steps whose action.kind is outside the whitelist mark the scenario as
`needs_human` and the run verdict is `partial`, never `pass`/`fail`.
"""

from __future__ import annotations

import fnmatch
import itertools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml  # PyYAML; vendored at runtime if missing
except ImportError:  # pragma: no cover
    yaml = None


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #

ALLOWED_ACTION_KINDS = {"fetch", "navigate", "upload_and_verify"}

# Assertions that judge an HTTP response (deterministic API lane).
ALLOWED_HTTP_ASSERTION_KINDS = {
    "utf8_bom_present",
    "no_mojibake",
    "status_2xx",
    "status_eq",
    "header_eq",
    "body_contains",
    "body_not_contains",
    "schema_matches",
    "byte_length_gte",
}

# Assertions that judge a captured page projection (agentic UI lane). The
# agent DRIVES the browser (interprets the step, finds the element), but the
# per-step PASS/FAIL verdict is decided here, deterministically, against a
# structured projection of what the page looked like after the action. This
# keeps the judgment out of the agent's opinion — same trust property as the
# negative-test self-check on the API lane.
ALLOWED_UI_ASSERTION_KINDS = {
    "element_visible",       # args: selector
    "element_absent",        # args: selector
    "text_present",          # args: patterns[], ignore_case?
    "text_absent",           # args: patterns[], ignore_case?
    "value_eq",              # args: selector, value
    "console_clean",         # args: ignore?[] (substrings to ignore)
    "url_matches",           # args: pattern (regex)
    "download_filename_eq",  # args: value | pattern
}

ALLOWED_ASSERTION_KINDS = ALLOWED_HTTP_ASSERTION_KINDS | ALLOWED_UI_ASSERTION_KINDS
PRIORITIES = {"P0", "P1", "P2"}


@dataclass
class Assertion:
    kind: str
    args: dict = field(default_factory=dict)


@dataclass
class Scenario:
    id: str
    priority: str
    action: dict
    assertions: list[Assertion]


@dataclass
class NegativeTest:
    id: str
    fixture: str
    apply: list[str]
    expected_verdict: str  # always "fail" in practice


@dataclass
class Rule:
    name: str
    description: str
    match: dict
    scenarios: list[Scenario]
    negative_tests: list[NegativeTest]
    disabled: bool = False  # GAP-3: opt-out flag for stub rules.


@dataclass
class Matrix:
    version: int
    rules: list[Rule]


@dataclass
class ResolvedScenario:
    """A Scenario with `for_each` expanded into concrete URLs."""
    id: str            # e.g. scenario-import-template-encoding[content_type=curriculum.session]
    base_id: str
    priority: str
    action: dict       # action with template variables substituted
    assertions: list[Assertion]


@dataclass
class StepResult:
    scenario_id: str
    priority: str
    verdict: str       # pass | fail | needs_human
    failed_assertions: list[str]
    evidence: dict


@dataclass
class RunVerdict:
    overall: str       # pass | fail | partial | unreliable
    p0_pass_rate: float
    p1_pass_rate: float
    counts: dict
    reasons: list[str]


# --------------------------------------------------------------------------- #
# Load + validate
# --------------------------------------------------------------------------- #


def load_matrix(path: Path) -> Matrix:
    if yaml is None:
        raise RuntimeError(
            "PyYAML not available. Install with `pip install pyyaml "
            "--break-system-packages`."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules: list[Rule] = []
    for r in raw.get("rules", []):
        scenarios = [_load_scenario(s) for s in (r.get("scenarios") or [])]
        negatives = [
            NegativeTest(
                id=n["id"],
                fixture=n["fixture"],
                apply=list(n.get("apply", [])),
                expected_verdict=n.get("expected_verdict", "fail"),
            )
            for n in (r.get("negative_tests") or [])
        ]
        rules.append(
            Rule(
                name=r["name"],
                description=r.get("description", ""),
                match=r.get("match", {}),
                scenarios=scenarios,
                negative_tests=negatives,
                disabled=bool(r.get("disabled", False)),
            )
        )
    return Matrix(version=raw.get("version", 1), rules=rules)


def _load_scenario(s: dict) -> Scenario:
    if s["priority"] not in PRIORITIES:
        raise ValueError(f"bad priority on scenario {s['id']!r}: {s['priority']!r}")
    if s["action"]["kind"] not in ALLOWED_ACTION_KINDS:
        raise ValueError(
            f"scenario {s['id']!r} uses action kind {s['action']['kind']!r} "
            f"which is not in the whitelist {sorted(ALLOWED_ACTION_KINDS)}"
        )
    asserts: list[Assertion] = []
    for a in s.get("assertions", []):
        kind = a["kind"]
        if kind not in ALLOWED_ASSERTION_KINDS:
            raise ValueError(
                f"scenario {s['id']!r} uses assertion kind {kind!r} which is "
                f"not in the whitelist {sorted(ALLOWED_ASSERTION_KINDS)}"
            )
        args = {k: v for k, v in a.items() if k != "kind"}
        asserts.append(Assertion(kind=kind, args=args))
    return Scenario(
        id=s["id"],
        priority=s["priority"],
        action=s["action"],
        assertions=asserts,
    )


# --------------------------------------------------------------------------- #
# Rule matching
# --------------------------------------------------------------------------- #


def match_rule(
    matrix: Matrix,
    ticket_title: str,
    ticket_type: str | None,
    files_changed: list[str],
) -> Rule | None:
    """First rule whose match clauses ALL succeed wins. None = needs_human."""
    title_lower = (ticket_title or "").lower()
    for rule in matrix.rules:
        if rule.disabled:
            # GAP-3: rule explicitly opted out via `disabled: true`.
            continue
        if not _match_clauses(rule.match, title_lower, ticket_type, files_changed):
            continue
        if not rule.scenarios:
            # Rule is a stub — match but no executable plan.
            continue
        return rule
    return None


def _match_clauses(
    clauses: dict,
    title_lower: str,
    ticket_type: str | None,
    files_changed: list[str],
) -> bool:
    # title_contains: any-of
    titles = [t.lower() for t in (clauses.get("title_contains") or [])]
    if titles and not any(t in title_lower for t in titles):
        return False
    # title_regex: any-of
    regexes = clauses.get("title_regex") or []
    if regexes and not any(re.search(p, title_lower, re.IGNORECASE) for p in regexes):
        return False
    # ticket_type: any-of (when provided)
    tts = clauses.get("ticket_type") or []
    if tts and (ticket_type or "").lower() not in [t.lower() for t in tts]:
        return False
    # files_changed_glob: any-of
    globs = clauses.get("files_changed_glob") or []
    if globs:
        if not files_changed:
            return False
        if not any(
            fnmatch.fnmatch(f, g) for f in files_changed for g in globs
        ):
            return False
    return True


# --------------------------------------------------------------------------- #
# Scenario expansion
# --------------------------------------------------------------------------- #


def expand_scenarios(rule: Rule) -> list[ResolvedScenario]:
    out: list[ResolvedScenario] = []
    for sc in rule.scenarios:
        action = sc.action
        for_each = action.get("for_each") or {}
        keys = list(for_each.keys())
        if not keys:
            out.append(
                ResolvedScenario(
                    id=sc.id,
                    base_id=sc.id,
                    priority=sc.priority,
                    action={k: v for k, v in action.items() if k != "for_each"},
                    assertions=sc.assertions,
                )
            )
            continue
        for combo in itertools.product(*[for_each[k] for k in keys]):
            vars_ = dict(zip(keys, combo))
            resolved_url = action["url_template"].format(**vars_)
            sid = sc.id + "[" + ",".join(f"{k}={v}" for k, v in vars_.items()) + "]"
            new_action = {
                k: v for k, v in action.items()
                if k not in {"for_each", "url_template"}
            }
            new_action["url"] = resolved_url
            new_action["kind"] = action["kind"]
            out.append(
                ResolvedScenario(
                    id=sid,
                    base_id=sc.id,
                    priority=sc.priority,
                    action=new_action,
                    assertions=sc.assertions,
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Assertion runners (operate on a captured HTTP response or raw bytes)
# --------------------------------------------------------------------------- #


@dataclass
class CapturedResponse:
    status: int
    headers: dict[str, str]
    body_bytes: bytes


def run_assertions(
    response: CapturedResponse,
    assertions: list[Assertion],
) -> tuple[bool, list[str]]:
    """Returns (all_passed, list_of_failed_assertion_ids)."""
    failed: list[str] = []
    decoded: str | None = None
    for a in assertions:
        ok = _eval_one(a, response, decoded)
        if not ok:
            failed.append(a.kind + ":" + json.dumps(a.args, sort_keys=True))
    return (len(failed) == 0, failed)


def _eval_one(
    a: Assertion,
    response: CapturedResponse,
    decoded: str | None,
) -> bool:
    k = a.kind
    body = response.body_bytes
    if k == "utf8_bom_present":
        return body.startswith(b"\xef\xbb\xbf")
    if k == "no_mojibake":
        patterns = a.args.get("patterns") or []
        text = body.decode("utf-8", errors="replace")
        return not any(p in text for p in patterns)
    if k == "status_2xx":
        return 200 <= response.status < 300
    if k == "status_eq":
        return response.status == int(a.args["value"])
    if k == "header_eq":
        return response.headers.get(a.args["name"], "").lower() == a.args["value"].lower()
    if k == "body_contains":
        text = body.decode("utf-8", errors="replace")
        return all(p in text for p in (a.args.get("patterns") or []))
    if k == "body_not_contains":
        text = body.decode("utf-8", errors="replace")
        return not any(p in text for p in (a.args.get("patterns") or []))
    if k == "schema_matches":
        # First line of body must equal the expected ordered column list as CSV.
        text = body.decode("utf-8-sig", errors="replace").splitlines()
        if not text:
            return False
        expected = ",".join(a.args.get("columns") or [])
        return text[0].strip() == expected.strip()
    if k == "byte_length_gte":
        return len(body) >= int(a.args["value"])
    return False


# --------------------------------------------------------------------------- #
# UI assertion runners (operate on a captured page projection)
# --------------------------------------------------------------------------- #


@dataclass
class FoundElement:
    """One element the agent queried via Chrome MCP `find` / javascript_tool.

    The agent records the result of querying a specific selector; the
    assertion layer only reads this structured record, it never inspects the
    live DOM itself.
    """
    selector: str
    visible: bool = False
    text: str = ""
    value: str | None = None
    exists: bool = True


@dataclass
class ConsoleMessage:
    level: str          # "log" | "info" | "warning" | "error"
    text: str = ""


@dataclass
class CapturedPage:
    """Structured snapshot of the page after one agentic step.

    Populated by the executor from Chrome MCP outputs:
      url           -> mcp__Claude_in_Chrome__navigate / javascript_tool location
      title         -> get_page_text / document.title
      text          -> get_page_text (visible text)
      elements      -> one FoundElement per selector the step queried
      console       -> read_console_messages
      downloads     -> filenames observed (e.g. from a download event)
    """
    url: str = ""
    title: str = ""
    text: str = ""
    elements: list[FoundElement] = field(default_factory=list)
    console: list[ConsoleMessage] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)

    def element_for(self, selector: str) -> FoundElement | None:
        for e in self.elements:
            if e.selector == selector:
                return e
        return None


def run_ui_assertions(
    page: CapturedPage,
    assertions: list[Assertion],
) -> tuple[bool, list[str]]:
    """Returns (all_passed, list_of_failed_assertion_ids). Mirror of
    run_assertions() but for the agentic UI lane."""
    failed: list[str] = []
    for a in assertions:
        if not _eval_ui_one(a, page):
            failed.append(a.kind + ":" + json.dumps(a.args, sort_keys=True))
    return (len(failed) == 0, failed)


def _eval_ui_one(a: Assertion, page: CapturedPage) -> bool:
    k = a.kind

    if k == "element_visible":
        el = page.element_for(a.args["selector"])
        return bool(el and el.exists and el.visible)

    if k == "element_absent":
        el = page.element_for(a.args["selector"])
        # Absent = either never found, or found-but-not-visible is NOT enough;
        # require it to not exist (or to have been queried and reported gone).
        return el is None or not el.exists

    if k in ("text_present", "text_absent"):
        patterns = a.args.get("patterns") or []
        ignore_case = a.args.get("ignore_case", True)
        hay = page.text.lower() if ignore_case else page.text
        needles = [p.lower() if ignore_case else p for p in patterns]
        present = all(n in hay for n in needles) if needles else True
        return present if k == "text_present" else not any(n in hay for n in needles)

    if k == "value_eq":
        el = page.element_for(a.args["selector"])
        return bool(el and el.exists and (el.value or "") == a.args.get("value", ""))

    if k == "console_clean":
        ignore = a.args.get("ignore") or []
        for m in page.console:
            if m.level.lower() != "error":
                continue
            if any(sub in m.text for sub in ignore):
                continue
            return False
        return True

    if k == "url_matches":
        return re.search(a.args["pattern"], page.url or "") is not None

    if k == "download_filename_eq":
        if "value" in a.args:
            return a.args["value"] in page.downloads
        if "pattern" in a.args:
            pat = a.args["pattern"]
            return any(re.search(pat, fn) for fn in page.downloads)
        return False

    return False


# --------------------------------------------------------------------------- #
# Negative-test self-check
# --------------------------------------------------------------------------- #


def run_negative_tests(
    rule: Rule,
    plugin_root: Path,
) -> tuple[bool, list[str]]:
    """
    For each negative test, load the fixture and run the named assertions.
    A negative test PASSES when the assertions FAIL — that means the
    scanner correctly flags the known-bad input. If any negative test's
    assertions return pass, the scanner is broken and we return False.
    """
    broken: list[str] = []
    for nt in rule.negative_tests:
        fixture_path = plugin_root / nt.fixture
        if not fixture_path.exists():
            broken.append(f"{nt.id}: fixture missing at {fixture_path}")
            continue
        body = fixture_path.read_bytes()
        # Synthesize a 200 response so status assertions don't false-fail the
        # negative test for the wrong reason.
        fake_response = CapturedResponse(
            status=200,
            headers={"content-type": "text/csv; charset=utf-8"},
            body_bytes=body,
        )
        # Run only the assertions listed in `apply`, using any scenario's
        # assertion args for those kinds in this rule.
        applied = _collect_assertions_for_kinds(rule, nt.apply)
        all_passed, _ = run_assertions(fake_response, applied)
        if nt.expected_verdict == "fail" and all_passed:
            broken.append(
                f"{nt.id}: scanner passed a known-bad fixture "
                f"({nt.fixture}); marking run unreliable"
            )
    return (len(broken) == 0, broken)


def _collect_assertions_for_kinds(rule: Rule, kinds: list[str]) -> list[Assertion]:
    """Pull the first-seen Assertion of each kind from rule.scenarios."""
    out: list[Assertion] = []
    seen: set[str] = set()
    for sc in rule.scenarios:
        for a in sc.assertions:
            if a.kind in kinds and a.kind not in seen:
                out.append(a)
                seen.add(a.kind)
    return out


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def aggregate(
    results: list[StepResult],
    scanner_ok: bool,
) -> RunVerdict:
    if not scanner_ok:
        return RunVerdict(
            overall="unreliable",
            p0_pass_rate=0.0,
            p1_pass_rate=0.0,
            counts={"total": len(results)},
            reasons=["negative_test_self_check_failed"],
        )

    counts = {"P0": {"pass": 0, "fail": 0, "needs_human": 0},
              "P1": {"pass": 0, "fail": 0, "needs_human": 0},
              "P2": {"pass": 0, "fail": 0, "needs_human": 0}}
    for r in results:
        counts[r.priority][r.verdict] = counts[r.priority].get(r.verdict, 0) + 1

    reasons: list[str] = []
    p0_total = sum(counts["P0"].values())
    p1_total = sum(counts["P1"].values())
    p0_rate = counts["P0"]["pass"] / p0_total if p0_total else 1.0
    p1_rate = counts["P1"]["pass"] / p1_total if p1_total else 1.0

    has_needs_human = any(
        counts[p]["needs_human"] > 0 for p in ("P0", "P1", "P2")
    )

    if counts["P0"]["fail"] > 0:
        overall = "fail"
        reasons.append("p0_failure")
    elif p0_total and p0_rate < 1.0:
        overall = "partial"
        reasons.append("p0_incomplete")
    elif p1_total and p1_rate < 0.90:
        overall = "fail"
        reasons.append("p1_below_threshold")
    elif has_needs_human:
        overall = "partial"
        reasons.append("steps_outside_verb_vocabulary")
    else:
        overall = "pass"

    return RunVerdict(
        overall=overall,
        p0_pass_rate=round(p0_rate, 3),
        p1_pass_rate=round(p1_rate, 3),
        counts=counts,
        reasons=reasons,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _cli() -> int:
    import argparse, sys
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--matrix", required=True, help="Path to scenario-matrix.yaml")
    ap.add_argument("--ticket-title", required=True)
    ap.add_argument("--ticket-type", default="bug")
    ap.add_argument("--files-changed", default="",
                    help="Comma-separated list of changed file paths")
    ap.add_argument("--plan-only", action="store_true",
                    help="Print the resolved scenarios JSON and exit "
                         "(no network, no assertions).")
    ap.add_argument("--plugin-root", default=".",
                    help="Path to plugin root (for resolving fixture paths)")
    args = ap.parse_args()

    matrix = load_matrix(Path(args.matrix))
    files = [f.strip() for f in args.files_changed.split(",") if f.strip()]
    rule = match_rule(matrix, args.ticket_title, args.ticket_type, files)
    if rule is None:
        print(json.dumps({"matched": False, "verdict": "needs_human"}))
        return 0
    resolved = expand_scenarios(rule)
    scanner_ok, broken = run_negative_tests(rule, Path(args.plugin_root))
    out = {
        "matched": True,
        "rule": rule.name,
        "scanner_ok": scanner_ok,
        "negative_test_failures": broken,
        "scenarios": [
            {
                "id": rs.id,
                "priority": rs.priority,
                "action": rs.action,
                "assertions": [{"kind": a.kind, "args": a.args} for a in rs.assertions],
            }
            for rs in resolved
        ],
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
