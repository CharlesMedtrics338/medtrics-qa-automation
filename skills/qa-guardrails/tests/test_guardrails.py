"""Unit tests for the enforceable guardrails. Pure-Python, no network."""
import guardrails as G


# ---- screen_action ----

def test_destructive_blocked_in_shadow():
    d = G.screen_action({"kind": "click", "label": "Delete block"}, "shadow")
    assert not d.allowed and d.severity == "block" and "destructive" in d.reason


def test_destructive_blocked_in_writeson_when_not_under_test():
    d = G.screen_action({"kind": "click", "label": "Remove user", "expected": "user is saved"}, "writes-on")
    assert not d.allowed and d.reason == "destructive_action_not_under_test"


def test_destructive_allowed_in_writeson_when_under_test():
    d = G.screen_action(
        {"kind": "click", "label": "Delete block", "expected": "the block is deleted and gone from the list"},
        "writes-on")
    assert d.allowed and d.severity == "warn"


def test_readonly_verbs_always_ok():
    for kind in ("navigate", "screenshot", "capture", "wait_for_text", "find"):
        d = G.screen_action({"kind": kind, "label": "Delete"}, "shadow")
        # navigate/etc is OK even if label has a scary word, because no action fires
        assert d.allowed and d.severity == "ok"


def test_mutating_verbs_warn():
    assert G.screen_action({"kind": "fill", "selector": "#start"}, "shadow").severity == "warn"
    assert G.screen_action({"kind": "upload", "selector": "#f"}, "shadow").severity == "warn"


def test_plain_click_ok():
    assert G.screen_action({"kind": "click", "label": "Edit"}, "shadow").allowed


def test_unknown_phase_blocks():
    assert not G.screen_action({"kind": "click"}, "prod").allowed


def test_unrecognized_kind_blocks():
    d = G.screen_action({"kind": "teleport"}, "shadow")
    assert not d.allowed and "unrecognized" in d.reason


# ---- gate_write ----

def test_optimus_blocked_in_shadow():
    assert not G.gate_write("optimus", "shadow").allowed
    assert not G.gate_write("gitlab", "shadow").allowed


def test_slack_and_mem_allowed_in_shadow():
    assert G.gate_write("slack", "shadow").allowed
    assert G.gate_write("mem", "shadow").allowed


def test_all_writes_allowed_in_writeson():
    for s in ("optimus", "gitlab", "slack", "mem"):
        assert G.gate_write(s, "writes-on").allowed


def test_unknown_write_system_blocks():
    assert not G.gate_write("twitter", "writes-on").allowed


# ---- redact_pii ----

def test_redacts_email_and_mrn():
    text = "Email qa-admin@test.medtrics.invalid for patient MRN: 99123"
    clean, kinds = G.redact_pii(text)
    assert "qa-admin@test.medtrics.invalid" not in clean
    assert "99123" not in clean
    assert "EMAIL" in kinds and "MRN" in kinds


def test_redacts_ssn_phone_token():
    text = "SSN 123-45-6789 call 313-555-1212 Bearer abc.def-123"
    clean, kinds = G.redact_pii(text)
    assert "123-45-6789" not in clean
    assert "313-555-1212" not in clean
    assert "abc.def-123" not in clean
    assert {"SSN", "PHONE", "BEARER"} <= set(kinds)


def test_redact_idempotent():
    text = "x@y.com"
    once, _ = G.redact_pii(text)
    twice, _ = G.redact_pii(once)
    assert once == twice


def test_clean_text_untouched():
    text = "Block 1 03 Mar 2025 07 Mar 2025 no PII here"
    clean, kinds = G.redact_pii(text)
    assert clean == text and kinds == []


def test_assert_evidence_clean_blocks_on_pii():
    assert not G.assert_evidence_clean("reach me at a@b.com").allowed
    assert G.assert_evidence_clean("dates 03 Mar 2025 match").allowed


# ---- timeouts present ----

def test_timeout_constants():
    assert G.HARD_TIMEOUT_S == 600 and G.STEP_TIMEOUT_S == 30
