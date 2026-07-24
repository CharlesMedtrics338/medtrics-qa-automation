"""Unit tests for qa-optimus-bridge/scripts/optimus_move_task.py.

Pure-Python. Covers the verdict → lane mapping, the four `decision` paths
(move / blocked / shadow / unknown verdict), per-install lane overrides via
config, and input validation.

    pytest skills/qa-optimus-bridge/tests/test_optimus_move_task.py
"""
import pytest

import optimus_move_task as M


# ---------- happy paths ----------

def test_pass_writes_on_targets_qa2():
    out = M.build_payload("M1-1190", "pass", "writes-on", {})
    assert out["decision"] == "move"
    assert out["target_lane"] == "qa2"
    assert out["args"] == {"task": "M1-1190", "status": "qa2"}
    assert out["mcp_tool"] == M.OPTIMUS_MOVE_TOOL
    assert out["audit_action"] == "optimus_moved_to_qa2"


def test_fail_writes_on_targets_needs_changes():
    out = M.build_payload("M1-1190", "fail", "writes-on", {})
    assert out["decision"] == "move"
    assert out["target_lane"] == "needs_changes"
    assert out["args"]["status"] == "needs_changes"
    assert out["audit_action"] == "optimus_moved_to_needs_changes"


def test_partial_no_cause_targets_needs_changes():
    """v0.10.1: partial without an explicit cause routes to needs_changes
    (non-data-related is the safer default — surface to dev)."""
    out = M.build_payload("M1-1190", "partial", "writes-on", {})
    assert out["decision"] == "move"
    assert out["target_lane"] == "needs_changes"


def test_partial_data_related_intends_needs_review_falls_back_on_hold():
    """v0.10.2: partial + data-related cause INTENDS needs_review but
    transitionally substitutes on_hold until Optimus releases the lane."""
    for cause in ("blocked_by_seed_data", "no_seed_data",
                  "missing_test_data", "environment_not_seeded"):
        out = M.build_payload("M1-1190", "partial", "writes-on", {},
                              partial_cause=cause)
        assert out["decision"] == "move"
        # Effective lane is on_hold (the fallback that exists in Optimus today).
        assert out["target_lane"] == "on_hold", (
            f"cause={cause!r} should fall back to on_hold")
        # pending_release records the intended destination for the operator.
        assert out["pending_release"]["intended_lane"] == "needs_review"
        assert out["pending_release"]["effective_lane"] == "on_hold"
        # The args going to the MCP move_task call use the fallback.
        assert out["args"]["status"] == "on_hold"


def test_pending_release_substitution_removable():
    """When needs_review lands in Optimus, removing it from
    PENDING_RELEASE_LANES should make data-related partials route there
    natively — no other code changes needed."""
    # Simulate the post-release state.
    saved = M.PENDING_RELEASE_LANES.copy()
    try:
        M.PENDING_RELEASE_LANES.clear()
        out = M.build_payload("M1-1190", "partial", "writes-on", {},
                              partial_cause="blocked_by_seed_data")
        assert out["target_lane"] == "needs_review"
        assert "pending_release" not in out
        assert out["args"]["status"] == "needs_review"
    finally:
        M.PENDING_RELEASE_LANES.update(saved)


def test_partial_non_data_cause_targets_needs_changes():
    """v0.10.1: any non-data-related cause routes to needs_changes."""
    for cause in ("code_defect", "plugin_tooling", "missing_step",
                  "submit_blocker", "vue_reactivity"):
        out = M.build_payload("M1-1190", "partial", "writes-on", {},
                              partial_cause=cause)
        assert out["decision"] == "move"
        assert out["target_lane"] == "needs_changes", (
            f"cause={cause!r} should route to needs_changes")


def test_blocked_never_moves_regardless_of_phase():
    out = M.build_payload("M1-1190", "blocked", "writes-on", {})
    assert out["decision"] == "no_move_blocked"
    assert out["target_lane"] is None
    assert "args" not in out
    out_shadow = M.build_payload("M1-1190", "blocked", "shadow", {})
    assert out_shadow["decision"] == "no_move_blocked"


# ---------- phase gate ----------

def test_shadow_refuses_pass():
    out = M.build_payload("M1-1190", "pass", "shadow", {})
    assert out["decision"] == "no_move_phase_shadow"
    assert "args" not in out
    assert out["audit_action"] == "would_have_moved_to_qa2"


def test_shadow_refuses_fail():
    out = M.build_payload("M1-1190", "fail", "shadow", {})
    assert out["decision"] == "no_move_phase_shadow"
    assert out["target_lane"] == "needs_changes"
    assert out["audit_action"] == "would_have_moved_to_needs_changes"


def test_shadow_refuses_partial():
    """v0.10.1: shadow still computes the would-have-moved lane —
    needs_changes by default for partial without cause."""
    out = M.build_payload("M1-1190", "partial", "shadow", {})
    assert out["decision"] == "no_move_phase_shadow"
    assert out["target_lane"] == "needs_changes"
    assert out["audit_action"] == "would_have_moved_to_needs_changes"


def test_shadow_refuses_partial_data_blocked():
    """v0.10.2: shadow + data-blocked partial → would-have-moved to the
    fallback lane (on_hold), with pending_release noting the intended
    lane (needs_review)."""
    out = M.build_payload("M1-1190", "partial", "shadow", {},
                          partial_cause="blocked_by_seed_data")
    assert out["decision"] == "no_move_phase_shadow"
    assert out["target_lane"] == "on_hold"
    assert out["audit_action"] == "would_have_moved_to_on_hold"
    assert out["pending_release"]["intended_lane"] == "needs_review"


# ---------- config overrides ----------

def test_lane_names_can_be_overridden_via_config():
    """v0.10.2: overrides span qa2 / needs_changes / on_hold / needs_review.
    needs_review is the intended lane for data-related partials but still
    falls back to on_hold (PENDING_RELEASE_LANES) until Optimus releases it."""
    cfg = {"optimus": {
        "qa2_lane": "qa-stage-2",
        "needs_changes_lane": "rework",
        "on_hold_lane": "parking-lot",
        "needs_review_lane": "ops-review",
    }}
    assert M.build_payload("X", "pass",    "writes-on", cfg)["target_lane"] == "qa-stage-2"
    assert M.build_payload("X", "fail",    "writes-on", cfg)["target_lane"] == "rework"
    # partial without cause → needs_changes override
    assert M.build_payload("X", "partial", "writes-on", cfg)["target_lane"] == "rework"
    # partial + data-related cause: resolves to "ops-review" but isn't in
    # PENDING_RELEASE_LANES (only the canonical "needs_review" is), so the
    # override flows through cleanly.
    out_override = M.build_payload("X", "partial", "writes-on", cfg,
                                   partial_cause="blocked_by_seed_data")
    assert out_override["target_lane"] == "ops-review"
    assert "pending_release" not in out_override


def test_partial_override_falls_back_to_default_for_unset_keys():
    cfg = {"optimus": {"qa2_lane": "qa-stage-2"}}
    # qa2 is overridden, the rest fall back to defaults
    assert M.build_payload("X", "pass", "writes-on", cfg)["target_lane"] == "qa-stage-2"
    assert M.build_payload("X", "fail", "writes-on", cfg)["target_lane"] == "needs_changes"
    assert M.build_payload("X", "partial", "writes-on", cfg)["target_lane"] == "needs_changes"
    # Data-related: defaults route to needs_review, substituted to on_hold.
    out = M.build_payload("X", "partial", "writes-on", cfg,
                          partial_cause="no_seed_data")
    assert out["target_lane"] == "on_hold"
    assert out["pending_release"]["intended_lane"] == "needs_review"


def test_from_lane_uses_config_qa1_lane_when_set():
    out = M.build_payload("X", "pass", "writes-on",
                          {"optimus": {"qa1_lane": "qa1_review"}})
    assert out["from_lane"] == "qa1_review"


# ---------- validation ----------

def test_unknown_verdict_raises():
    with pytest.raises(ValueError, match="unknown verdict"):
        M.build_payload("M1-1190", "needs_human", "writes-on", {})


def test_unknown_phase_raises():
    with pytest.raises(ValueError, match="unknown phase"):
        M.build_payload("M1-1190", "pass", "broken-phase", {})


def test_missing_ticket_raises():
    with pytest.raises(ValueError, match="ticket is required"):
        M.build_payload("", "pass", "writes-on", {})


# ---------- resolve_target_lane direct ----------

def test_resolve_target_lane_uses_defaults():
    """v0.10.2: resolve_target_lane returns the INTENDED lane (does NOT
    apply the PENDING_RELEASE_LANES substitution — that happens in
    build_payload). Data-related partial resolves to needs_review."""
    assert M.resolve_target_lane("pass",    None, {}) == "qa2"
    assert M.resolve_target_lane("fail",    None, {}) == "needs_changes"
    # partial without a cause → needs_changes (safer default)
    assert M.resolve_target_lane("partial", None, {}) == "needs_changes"
    # partial + data-related cause → needs_review (intended; falls back at
    # payload-build time via PENDING_RELEASE_LANES)
    assert M.resolve_target_lane("partial", "blocked_by_seed_data", {}) == "needs_review"
    # partial + non-data-related cause → needs_changes
    assert M.resolve_target_lane("partial", "code_defect", {}) == "needs_changes"
    assert M.resolve_target_lane("blocked", None, {}) is None
    assert M.resolve_target_lane("unknown", None, {}) is None
