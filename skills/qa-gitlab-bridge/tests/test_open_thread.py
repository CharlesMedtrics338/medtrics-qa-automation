"""Unit tests for gitlab_open_thread._build_thread_url (GAP-19).

The bug: the prior implementation built the URL from the numeric
GITLAB_PROJECT_ID, which 404s when the project is reached via its
namespace path (https://gitlab.com/medtrics/medtrics/...). We now prefer
the mr.web_url field, which always carries the namespace path.

These tests don't touch the network.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "gitlab_open_thread.py"
)


@pytest.fixture(scope="module")
def open_thread():
    """Load gitlab_open_thread.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("gitlab_open_thread", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_thread_url_uses_namespace_path_when_web_url_present(open_thread):
    mr = {"web_url": "https://gitlab.com/medtrics/medtrics/-/merge_requests/6865"}
    env = {"GITLAB_URL": "https://gitlab.com", "GITLAB_PROJECT_ID": "1496872"}
    url = open_thread._build_thread_url(mr, env, "6865", 3426507991)
    assert url == "https://gitlab.com/medtrics/medtrics/-/merge_requests/6865#note_3426507991"
    # Sanity: namespace path is present, numeric id is NOT.
    assert "medtrics/medtrics" in url
    assert "1496872" not in url


def test_thread_url_none_when_note_id_missing(open_thread):
    mr = {"web_url": "https://gitlab.com/medtrics/medtrics/-/merge_requests/6865"}
    env = {"GITLAB_URL": "https://gitlab.com", "GITLAB_PROJECT_ID": "1496872"}
    assert open_thread._build_thread_url(mr, env, "6865", None) is None


def test_thread_url_falls_back_to_numeric_when_web_url_missing(open_thread):
    """If the MR fetch came back without web_url, log a warning and fall back."""
    mr = {"state": "opened"}  # no web_url field
    env = {"GITLAB_URL": "https://gitlab.com", "GITLAB_PROJECT_ID": "1496872"}
    url = open_thread._build_thread_url(mr, env, "6865", 3426507991)
    assert url is not None
    # Fallback IS the legacy construction — we accept it as degraded.
    assert "1496872" in url
    assert "#note_3426507991" in url


def test_thread_url_handles_none_mr(open_thread):
    """If get_mr returned None / non-dict, still fall back rather than crash."""
    env = {"GITLAB_URL": "https://gitlab.com", "GITLAB_PROJECT_ID": "1496872"}
    url = open_thread._build_thread_url(None, env, "6865", 3426507991)
    assert url is not None
    assert "#note_3426507991" in url
