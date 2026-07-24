"""GAP-3: rules with `disabled: true` must be skipped by match_rule even
when their match clauses would otherwise fire.

Today the matrix has `missing_required_field` and `role_permission_regression`
flagged disabled until populated with real scenarios.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scenario_dispatcher import (
    Matrix,
    Rule,
    Scenario,
    match_rule,
    load_matrix,
)


def _scenario(rule_name: str) -> Scenario:
    """Minimal scenario so a rule isn't stub-empty."""
    return Scenario(
        id=f"scenario-{rule_name}",
        priority="P1",
        action={"kind": "fetch", "url_template": "/", "method": "GET"},
        assertions=[],
    )


def test_disabled_rule_is_skipped_even_when_match_succeeds():
    enabled = Rule(
        name="real_rule",
        description="",
        match={"title_contains": ["other-title-marker"]},
        scenarios=[_scenario("real_rule")],
        negative_tests=[],
        disabled=False,
    )
    disabled = Rule(
        name="stub_rule",
        description="",
        match={"title_contains": ["permission"]},
        scenarios=[_scenario("stub_rule")],
        negative_tests=[],
        disabled=True,
    )
    matrix = Matrix(version=1, rules=[disabled, enabled])

    # Title only matches the disabled rule. match_rule must NOT return it.
    result = match_rule(
        matrix,
        ticket_title="permission regression on foo",
        ticket_type="bug",
        files_changed=["src/foo.py"],
    )
    assert result is None, "disabled rule must not be returned as a match"


def test_disabled_field_defaults_to_false_for_back_compat():
    """Rules that don't carry the field still load as enabled."""
    r = Rule(
        name="legacy",
        description="",
        match={"title_contains": ["x"]},
        scenarios=[_scenario("legacy")],
        negative_tests=[],
    )
    assert r.disabled is False


def test_load_matrix_picks_up_disabled_field():
    """The shipped scenario-matrix.yaml flags two rules disabled per GAP-3."""
    matrix_path = (
        Path(__file__).resolve().parents[3]
        / "qa"
        / "scenario-matrix.yaml"
    )
    if not matrix_path.exists():
        pytest.skip("scenario-matrix.yaml not in expected location")
    matrix = load_matrix(matrix_path)
    by_name = {r.name: r for r in matrix.rules}
    assert by_name["missing_required_field"].disabled is True
    assert by_name["role_permission_regression"].disabled is True
    assert by_name["import_template_encoding"].disabled is False
