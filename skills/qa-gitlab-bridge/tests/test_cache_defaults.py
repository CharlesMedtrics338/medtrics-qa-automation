"""GAP-11: confirm the read-script defaults for --cache-ttl.

These scripts went from cache-off-by-default to cache-on-by-default in
v0.10.0. The test parses the script's argparse arguments without running
main() and asserts the default value.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
DOWNLOAD_UPLOAD = SCRIPTS_DIR / "gitlab_download_upload.py"
GET_MR = SCRIPTS_DIR / "gitlab_get_mr.py"
GET_PIPELINE = SCRIPTS_DIR / "gitlab_get_pipeline_status.py"


def _argparse_defaults(script_path: Path) -> dict[str, object]:
    """Run the script with --help redirected, then introspect its parser."""
    src = script_path.read_text(encoding="utf-8")
    # Extract just the function definitions / parser setup is hard without
    # executing module-level code. Easier path: run argparse via subprocess
    # OR import and call main() once with --help and grab the parser. We use
    # a simpler probe — call argparse-default via regex against the source.
    # That's brittle, so instead we import the module and inspect.
    spec = importlib.util.spec_from_file_location(script_path.stem, script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # main() builds the parser inline; call it via mock so it doesn't execute.
    captured: dict[str, object] = {}

    def fake_parse_args(self):  # noqa: ANN001
        captured.update({a.dest: a.default for a in self._actions})

        class _Args:
            pass
        for k, v in captured.items():
            setattr(_Args, k, v)
        # main() will error past parse_args; raise to abort.
        raise SystemExit(0)

    with mock.patch("argparse.ArgumentParser.parse_args", fake_parse_args):
        try:
            mod.main()
        except SystemExit:
            pass
    return captured


@pytest.mark.parametrize(
    "script,expected_ttl",
    [
        (GET_MR, 300),
        (GET_PIPELINE, 120),
        (DOWNLOAD_UPLOAD, 600),
    ],
)
def test_cache_ttl_defaults_to_non_zero(script, expected_ttl):
    defaults = _argparse_defaults(script)
    assert "cache_ttl" in defaults, f"{script.name} should accept --cache-ttl"
    assert defaults["cache_ttl"] == expected_ttl, (
        f"{script.name} default --cache-ttl should be {expected_ttl} (GAP-11), "
        f"got {defaults['cache_ttl']}"
    )


@pytest.mark.parametrize("script", [GET_MR, GET_PIPELINE, DOWNLOAD_UPLOAD])
def test_no_cache_flag_still_present(script):
    """--no-cache is the documented bypass for the new cache-on defaults."""
    defaults = _argparse_defaults(script)
    assert "no_cache" in defaults
    assert defaults["no_cache"] is False
