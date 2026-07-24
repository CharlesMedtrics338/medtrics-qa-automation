"""Tests for build_attachment_record.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_attachment_record as M  # noqa: E402


def test_successful_upload_record():
    r = M.build_record(
        step_n=3, label="screenshot",
        path="outputs/qa/M1-1206/abc/step3/screenshot.gif",
        upload_result={
            "ok": True, "id": 999, "url": "/uploads/xyz/screenshot.gif",
            "markdown": "![screenshot](/uploads/xyz/screenshot.gif)",
        },
    )
    assert r["step_n"] == 3
    assert r["label"] == "screenshot"
    assert r["kind"] == "image"
    assert r["gitlab_url"] == "/uploads/xyz/screenshot.gif"
    assert r["gitlab_markdown"].startswith("!")
    assert r["gitlab_id"] == 999


def test_failed_upload_record():
    r = M.build_record(
        step_n=3, label="screenshot",
        path="outputs/qa/.../step3/screenshot.gif",
        upload_result={"ok": False, "error": "413 file too large"},
    )
    assert "gitlab_markdown" not in r
    assert r["upload_error"] == "413 file too large"
    assert r["kind"] == "image"


def test_console_label_kind():
    r = M.build_record(
        step_n=1, label="console", path="...", upload_result={"ok": True},
    )
    assert r["kind"] == "log"


def test_network_label_kind():
    r = M.build_record(
        step_n=1, label="network", path="...", upload_result={"ok": True},
    )
    assert r["kind"] == "log"


def test_dom_label_kind():
    r = M.build_record(
        step_n=1, label="dom", path="...", upload_result={"ok": True},
    )
    assert r["kind"] == "html"


def test_step_n_coerced_from_string():
    r = M.build_record(
        step_n="7", label="screenshot", path="...",
        upload_result={"ok": True, "markdown": ""},
    )
    assert r["step_n"] == 7
