"""Tests for derive_filename.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import derive_filename as M  # noqa: E402


def test_basic_filename():
    out = M.derive_screenshot_filename("M1-1206", "2026-06-17T03:15:50.123Z", 3)
    # ticket preserved, run_id short, step embedded, gif extension
    assert out.startswith("qa-M1-1206-")
    assert out.endswith("-step-3.gif")


def test_run_id_short_is_alnum_only():
    rid = M.short_run_id("2026-06-17T03:15:50.123Z")
    assert rid.isalnum()
    assert rid == rid.lower()
    assert len(rid) == 12


def test_run_id_short_when_already_short():
    rid = M.short_run_id("ab12")
    assert rid == "ab12"


def test_run_id_short_when_empty():
    assert M.short_run_id("") == "run"
    assert M.short_run_id("!!!") == "run"


def test_step_n_coerced_from_string():
    out = M.derive_screenshot_filename("M1-1206", "rid", "7")
    assert out.endswith("-step-7.gif")


def test_step_n_invalid_defaults_to_zero():
    out = M.derive_screenshot_filename("M1-1206", "rid", "not-a-number")
    assert out.endswith("-step-0.gif")


def test_ticket_unsafe_chars_replaced():
    out = M.derive_screenshot_filename("M1/1206 weird!", "rid", 1)
    # slashes and spaces removed, internal punctuation collapsed to hyphens
    assert "/" not in out
    assert " " not in out
    assert "!" not in out


def test_extension_overridable():
    out = M.derive_screenshot_filename("M1-1206", "rid", 1, ext="png")
    assert out.endswith(".png")


def test_no_ticket_uses_unknown():
    out = M.derive_screenshot_filename("", "rid", 1)
    assert out.startswith("qa-unknown-")
