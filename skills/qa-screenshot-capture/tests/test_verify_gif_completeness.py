"""Unit tests for verify_gif_completeness.py.

Covers:

  - GIF frame counter against fixtures we construct byte-by-byte (no Pillow).
  - The evaluate() judgment: ok / under_recorded / skipped_no_trace.
  - count_expected_actions() over execution_trace.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from verify_gif_completeness import (  # noqa: E402
    count_expected_actions,
    count_gif_frames,
    evaluate,
)


def _build_gif(frame_count: int) -> bytes:
    """Build a minimal valid GIF89a with the requested frame count.

    - 1×1 canvas, no global color table, no local color table.
    - Each frame is: graphic control extension (5 bytes payload) +
      image descriptor (10 bytes) + LZW min code size (1 byte) + one
      data sub-block of length 1 (the pixel) + terminator (0x00).
    - Trailer 0x3B ends the file.

    The frame counter walks the GIF byte structure; it does not decode
    pixels, so this synthetic file is enough to exercise it.
    """
    header = b"GIF89a"
    # Logical Screen Descriptor: W=1 H=1, packed=0, bg=0, aspect=0
    lsd = b"\x01\x00\x01\x00\x00\x00\x00"

    frame_bytes = b""
    for _ in range(frame_count):
        # Graphic Control Extension
        gce = b"\x21\xf9\x04\x00\x00\x00\x00\x00"
        # Image Descriptor: separator 0x2c, x=0, y=0, w=1, h=1, packed=0
        img = b"\x2c" + b"\x00\x00\x00\x00\x01\x00\x01\x00\x00"
        # LZW min code size + sub-block + terminator
        img_data = b"\x02\x01\x00\x00"
        frame_bytes += gce + img + img_data

    trailer = b"\x3b"
    return header + lsd + frame_bytes + trailer


class TestCountGifFrames:
    def test_single_frame(self, tmp_path):
        p = tmp_path / "one.gif"
        p.write_bytes(_build_gif(1))
        assert count_gif_frames(p) == 1

    def test_seven_frames(self, tmp_path):
        p = tmp_path / "seven.gif"
        p.write_bytes(_build_gif(7))
        assert count_gif_frames(p) == 7

    def test_twenty_two_frames(self, tmp_path):
        p = tmp_path / "big.gif"
        p.write_bytes(_build_gif(22))
        assert count_gif_frames(p) == 22

    def test_zero_frames(self, tmp_path):
        p = tmp_path / "empty.gif"
        p.write_bytes(_build_gif(0))
        assert count_gif_frames(p) == 0

    def test_non_gif_raises(self, tmp_path):
        p = tmp_path / "notgif.txt"
        p.write_bytes(b"not a gif")
        with pytest.raises(ValueError, match="is not a GIF"):
            count_gif_frames(p)


class TestCountExpectedActions:
    def test_missing_trace_returns_none(self, tmp_path):
        assert count_expected_actions(tmp_path) is None

    def test_list_shape(self, tmp_path):
        (tmp_path / "execution_trace.json").write_text(
            json.dumps([{"n": 1}, {"n": 2}, {"n": 3}])
        )
        assert count_expected_actions(tmp_path) == 3

    def test_dict_shape_with_steps(self, tmp_path):
        (tmp_path / "execution_trace.json").write_text(
            json.dumps({"steps": [{"n": 1}, {"n": 2}], "meta": {}})
        )
        assert count_expected_actions(tmp_path) == 2

    def test_bad_json_returns_none(self, tmp_path):
        (tmp_path / "execution_trace.json").write_text("not json")
        assert count_expected_actions(tmp_path) is None


class TestEvaluate:
    def test_ok_at_full_frames(self):
        v = evaluate(frames=10, expected=10, threshold=0.80)
        assert v["verdict"] == "ok"
        assert v["ratio"] == 1.0

    def test_ok_at_threshold(self):
        v = evaluate(frames=8, expected=10, threshold=0.80)
        assert v["verdict"] == "ok"

    def test_under_recorded_below_threshold(self):
        v = evaluate(frames=7, expected=14, threshold=0.80)
        assert v["verdict"] == "under_recorded"
        assert v["ratio"] == 0.5
        assert "UNDER-RECORDED" in v["message"]
        assert "qa_action_with_marker" in v["message"]

    def test_under_recorded_m1_1309_reproduction(self):
        """Regression check: the exact M1-1309 shape must flag under-recorded."""
        v = evaluate(frames=7, expected=14, threshold=0.80)
        assert v["verdict"] == "under_recorded"

    def test_skipped_no_trace(self):
        v = evaluate(frames=7, expected=None, threshold=0.80)
        assert v["verdict"] == "skipped_no_trace"

    def test_skipped_zero_expected(self):
        v = evaluate(frames=0, expected=0, threshold=0.80)
        assert v["verdict"] == "skipped_no_trace"
