"""Unit tests for the v0.12.1 force-frame helper (three modes)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "force_frame_step.py"


def _import_module():
    spec = importlib.util.spec_from_file_location("force_frame_step", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# CLICK MODE — the preferred path.
# ---------------------------------------------------------------------------


class TestClickMode:
    def test_emits_single_left_click_action(self):
        mod = _import_module()
        plan = mod.build_action_plan(kind="click", step_n=3, tab_id=42, x=100, y=200)
        assert plan["kind"] == "click"
        assert plan["policy_version"] == 2
        actions = plan["actions"]
        assert len(actions) == 1
        act = actions[0]
        assert act["name"] == "computer"
        assert act["purpose"] == "force_frame_click"
        assert act["input"]["action"] == "left_click"
        assert act["input"]["coordinate"] == [100, 200]
        assert act["input"]["tabId"] == 42

    def test_requires_x_and_y(self):
        mod = _import_module()
        with pytest.raises(ValueError):
            mod.build_action_plan(kind="click", step_n=1, tab_id=1, x=None, y=200)
        with pytest.raises(ValueError):
            mod.build_action_plan(kind="click", step_n=1, tab_id=1, x=100, y=None)

    def test_step_label_kept(self):
        mod = _import_module()
        plan = mod.build_action_plan(
            kind="click", step_n=1, tab_id=1, step_label="Open Sites", x=1, y=1
        )
        assert plan["step_label"] == "Open Sites"


# ---------------------------------------------------------------------------
# SCROLL MODE.
# ---------------------------------------------------------------------------


class TestScrollMode:
    def test_emits_single_scroll_action(self):
        mod = _import_module()
        plan = mod.build_action_plan(kind="scroll", step_n=1, tab_id=42, dx=0, dy=400)
        actions = plan["actions"]
        assert len(actions) == 1
        act = actions[0]
        assert act["input"]["action"] == "scroll"
        assert act["input"]["coordinate"] == [0, 400]

    def test_requires_dx_and_dy(self):
        mod = _import_module()
        with pytest.raises(ValueError):
            mod.build_action_plan(kind="scroll", step_n=1, tab_id=1, dx=None, dy=0)


# ---------------------------------------------------------------------------
# MARKER MODE (fallback).
# ---------------------------------------------------------------------------


class TestMarkerMode:
    def test_emits_two_action_sequence(self):
        mod = _import_module()
        plan = mod.build_action_plan(kind="marker", step_n=5, tab_id=42)
        actions = plan["actions"]
        assert len(actions) == 2
        assert actions[0]["name"] == "javascript_tool"
        assert actions[0]["purpose"] == "force_frame_marker"
        assert actions[1]["name"] == "computer"
        assert actions[1]["input"]["action"] == "screenshot"

    def test_marker_js_contains_load_bearing_pieces(self):
        mod = _import_module()
        plan = mod.build_action_plan(kind="marker", step_n=5, tab_id=42)
        js = plan["marker_js"]
        # Load-bearing pieces:
        # 1. Creates or reuses the marker div with the fixed id.
        assert "qa-force-frame-marker" in js
        # 2. Sets absolute/fixed positioning + 4x4 px size.
        assert "position = 'fixed'" in js
        assert "width = '4px'" in js
        assert "height = '4px'" in js
        # 3. Sets a per-step HSL background so the pixel content differs.
        assert "backgroundColor = 'hsl(' + hue + ', 100%, 50%)'" in js
        # 4. Interpolates the step number into the hue (5*36 = 180 → cyan for step 5).
        assert "(5 * 36) % 360" in js
        # 5. Persists a data attribute (audit trail — invisible to pixel dedup on its own,
        # but useful when correlating frames with steps).
        assert "dataset.qaFrame = String((5))" in js
        # 6. Ends with a settle delay so the paint completes before the screenshot fires.
        assert "await new Promise(r => setTimeout(r, 60))" in js

    def test_hue_rotates_per_step(self):
        mod = _import_module()
        plan_step_1 = mod.build_action_plan(kind="marker", step_n=1, tab_id=42)
        plan_step_2 = mod.build_action_plan(kind="marker", step_n=2, tab_id=42)
        # Step 1 = 36°, step 2 = 72° — different hue, distinct pixel content.
        assert "(1 * 36) % 360" in plan_step_1["marker_js"]
        assert "(2 * 36) % 360" in plan_step_2["marker_js"]

    def test_marker_does_not_scroll(self):
        # Regression guard: v0.12.0's scroll-and-scroll-back was useless.
        # The v0.12.1 marker must NOT emit any scroll instruction.
        mod = _import_module()
        plan = mod.build_action_plan(kind="marker", step_n=1, tab_id=42)
        js = plan["marker_js"]
        assert "scrollBy" not in js
        assert "scroll(" not in js


# ---------------------------------------------------------------------------
# SHARED VALIDATION.
# ---------------------------------------------------------------------------


class TestSharedValidation:
    def test_bad_kind_rejected(self):
        mod = _import_module()
        with pytest.raises(ValueError):
            mod.build_action_plan(kind="teleport", step_n=1, tab_id=1)

    def test_negative_step_rejected(self):
        mod = _import_module()
        with pytest.raises(ValueError):
            mod.build_action_plan(kind="marker", step_n=-1, tab_id=1)

    def test_zero_tab_rejected(self):
        mod = _import_module()
        with pytest.raises(ValueError):
            mod.build_action_plan(kind="marker", step_n=1, tab_id=0)

    def test_step_zero_ok(self):
        mod = _import_module()
        plan = mod.build_action_plan(kind="marker", step_n=0, tab_id=1)
        assert plan["step_n"] == 0


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


class TestCli:
    def test_cli_click_output(self):
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--kind",
                "click",
                "--step-n",
                "3",
                "--tab-id",
                "123",
                "--x",
                "775",
                "--y",
                "284",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(r.stdout)
        assert payload["kind"] == "click"
        assert payload["actions"][0]["input"]["coordinate"] == [775, 284]

    def test_cli_scroll_output(self):
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--kind",
                "scroll",
                "--step-n",
                "1",
                "--tab-id",
                "1",
                "--dx",
                "0",
                "--dy",
                "400",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(r.stdout)
        assert payload["kind"] == "scroll"
        assert payload["actions"][0]["input"]["coordinate"] == [0, 400]

    def test_cli_marker_raw_mode(self):
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--kind",
                "marker",
                "--step-n",
                "5",
                "--tab-id",
                "9",
                "--raw",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "qa-force-frame-marker" in r.stdout
        assert "backgroundColor" in r.stdout
        assert not r.stdout.lstrip().startswith("{")

    def test_cli_click_raw_dumps_action(self):
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--kind",
                "click",
                "--step-n",
                "1",
                "--tab-id",
                "1",
                "--x",
                "10",
                "--y",
                "20",
                "--raw",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        # Click has no JS — --raw for click dumps the single action object.
        obj = json.loads(r.stdout)
        assert obj["name"] == "computer"
        assert obj["input"]["coordinate"] == [10, 20]

    def test_cli_rejects_missing_coordinates(self):
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--kind",
                "click",
                "--step-n",
                "1",
                "--tab-id",
                "1",
            ],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2
        assert "requires --x and --y" in r.stderr

    def test_cli_rejects_bad_kind(self):
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--kind",
                "teleport",
                "--step-n",
                "1",
                "--tab-id",
                "1",
            ],
            capture_output=True,
            text=True,
        )
        # argparse rejects invalid --kind values with exit code 2.
        assert r.returncode != 0
