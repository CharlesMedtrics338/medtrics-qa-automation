"""Unit tests for the v0.12.2 auto-wrap helper (qa_action_with_marker.py).

The helper's contract:

  - Six banned MCP tools each map to a wrapped kind.
  - Every wrapped kind emits a 3-action plan: [underlying, marker JS, screenshot].
  - Invalid kinds / missing tab_id / negative step_n all raise ValueError.
  - Passing --kind javascript without --script raises ValueError.
  - since_last_seen is threaded through for read_console / read_network.

The tests do not exercise Chrome MCP — they only exercise the pure-Python
plan-building logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the sibling scripts/ importable.
SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from qa_action_with_marker import (  # noqa: E402  after sys.path juggling
    VALID_WRAPPED_KINDS,
    build_wrapped_plan,
)


class TestValidKinds:
    def test_all_six_kinds_present(self):
        assert set(VALID_WRAPPED_KINDS) == {
            "javascript",
            "read_page",
            "read_console",
            "read_network",
            "get_page_text",
            "find",
        }

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError, match="kind must be one of"):
            build_wrapped_plan(kind="click", step_n=1, tab_id=999)


class TestPlanShape:
    """Every wrapped kind returns a 3-action plan (underlying + marker + screenshot)."""

    @pytest.mark.parametrize(
        "kind, extra",
        [
            ("javascript", {"script": "return 1;"}),
            ("read_page", {}),
            ("read_console", {}),
            ("read_network", {}),
            ("get_page_text", {}),
            ("find", {}),
        ],
    )
    def test_plan_has_three_actions(self, kind, extra):
        plan = build_wrapped_plan(kind=kind, step_n=1, tab_id=42, **extra)
        assert len(plan["actions"]) == 3
        assert plan["wrapped_kind"] == kind
        assert plan["kind"] == f"wrapped_{kind}"
        assert plan["policy_version"] == 3

    def test_marker_second_action(self):
        plan = build_wrapped_plan(kind="read_page", step_n=2, tab_id=99)
        second = plan["actions"][1]
        assert second["name"] == "javascript_tool"
        assert second["purpose"] == "force_frame_marker"
        assert "qa-force-frame-marker" in second["input"]["text"]

    def test_screenshot_third_action(self):
        plan = build_wrapped_plan(kind="find", step_n=1, tab_id=99)
        third = plan["actions"][2]
        assert third["name"] == "computer"
        assert third["input"]["action"] == "screenshot"
        assert third["input"]["tabId"] == 99


class TestUnderlyingActions:
    def test_javascript_requires_script(self):
        with pytest.raises(ValueError, match="requires --script"):
            build_wrapped_plan(kind="javascript", step_n=1, tab_id=42)

    def test_javascript_action_carries_script(self):
        plan = build_wrapped_plan(
            kind="javascript",
            step_n=1,
            tab_id=42,
            script="return window.document.title;",
        )
        first = plan["actions"][0]
        assert first["name"] == "javascript_tool"
        assert first["input"]["action"] == "javascript_exec"
        assert first["input"]["text"] == "return window.document.title;"
        assert first["input"]["tabId"] == 42

    def test_read_page_action(self):
        plan = build_wrapped_plan(kind="read_page", step_n=1, tab_id=42)
        first = plan["actions"][0]
        assert first["name"] == "read_page"
        assert first["input"] == {"tabId": 42}

    def test_read_console_since_last_seen_true(self):
        plan = build_wrapped_plan(
            kind="read_console", step_n=1, tab_id=42, since_last_seen=True
        )
        first = plan["actions"][0]
        assert first["name"] == "read_console_messages"
        assert first["input"]["sinceLastSeen"] is True

    def test_read_console_since_last_seen_default_false(self):
        plan = build_wrapped_plan(kind="read_console", step_n=1, tab_id=42)
        first = plan["actions"][0]
        assert first["input"]["sinceLastSeen"] is False

    def test_read_network_action(self):
        plan = build_wrapped_plan(
            kind="read_network", step_n=1, tab_id=42, since_last_seen=True
        )
        first = plan["actions"][0]
        assert first["name"] == "read_network_requests"
        assert first["input"]["sinceLastSeen"] is True

    def test_get_page_text_action(self):
        plan = build_wrapped_plan(kind="get_page_text", step_n=1, tab_id=42)
        first = plan["actions"][0]
        assert first["name"] == "get_page_text"

    def test_find_action(self):
        plan = build_wrapped_plan(kind="find", step_n=1, tab_id=42)
        first = plan["actions"][0]
        assert first["name"] == "find"


class TestValidation:
    def test_negative_step_n_raises(self):
        with pytest.raises(ValueError, match="step_n must be >= 0"):
            build_wrapped_plan(kind="read_page", step_n=-1, tab_id=42)

    def test_zero_tab_id_raises(self):
        with pytest.raises(ValueError, match="tab_id must be a positive integer"):
            build_wrapped_plan(kind="read_page", step_n=1, tab_id=0)

    def test_negative_tab_id_raises(self):
        with pytest.raises(ValueError, match="tab_id must be a positive integer"):
            build_wrapped_plan(kind="read_page", step_n=1, tab_id=-1)


class TestMarkerRotation:
    """Marker JS reuses v0.12.1's HSL rotation — step_n * 36 mod 360."""

    def test_marker_step_1_is_hue_36(self):
        plan = build_wrapped_plan(kind="find", step_n=1, tab_id=42)
        marker_js = plan["actions"][1]["input"]["text"]
        # step_n * 36 = 36 — the marker script computes this at runtime,
        # so we check the step_n substitution is threaded correctly.
        assert "(1 * 36)" in marker_js

    def test_marker_step_10_wraps(self):
        plan = build_wrapped_plan(kind="find", step_n=10, tab_id=42)
        marker_js = plan["actions"][1]["input"]["text"]
        assert "(10 * 36)" in marker_js


class TestBannedToolsAreAllCovered:
    """Every tool banned in the v0.12.2 SKILL.md contract must have a wrapped kind."""

    BANNED_TOOLS = {
        "javascript_tool",
        "read_page",
        "read_console_messages",
        "read_network_requests",
        "get_page_text",
        "find",
    }

    def test_banned_tools_map_to_underlying_action_names(self):
        underlying_names = set()
        for kind in VALID_WRAPPED_KINDS:
            extra = {"script": "return 1;"} if kind == "javascript" else {}
            plan = build_wrapped_plan(kind=kind, step_n=1, tab_id=42, **extra)
            underlying_names.add(plan["actions"][0]["name"])
        assert underlying_names == self.BANNED_TOOLS
