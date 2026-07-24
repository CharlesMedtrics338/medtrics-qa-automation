"""Unit tests for the vendored gitlab_client.py — pure-Python checks that
don't hit the network. Covers:

  - .env discovery + parsing
  - content-type guessing for upload_file
  - upload_file multipart body construction (no actual POST)
  - URL building inside gitlab_api (no actual call)

Run with: pytest tests/test_gitlab_client.py
"""
from pathlib import Path
from unittest import mock

import gitlab_client as G


# ---------- .env discovery ----------

def test_env_loaded_from_explicit_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_PROJECT_ID", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("GITLAB_TOKEN=glpat-aaaa\nGITLAB_PROJECT_ID=12345\n")
    env = G.load_env(str(env_file))
    assert env["GITLAB_TOKEN"] == "glpat-aaaa"
    assert env["GITLAB_PROJECT_ID"] == "12345"
    assert env["GITLAB_URL"] == G.DEFAULT_GITLAB_URL


def test_env_process_overrides_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GITLAB_TOKEN=from-file\nGITLAB_PROJECT_ID=999\n")
    monkeypatch.setenv("GITLAB_TOKEN", "from-process")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "999")
    env = G.load_env(str(env_file))
    assert env["GITLAB_TOKEN"] == "from-process"


def test_env_gitlab_pat_alias(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("GITLAB_PAT=glpat-xyz\nGITLAB_PROJECT_ID=1\n")
    env = G.load_env(str(env_file))
    assert env["GITLAB_TOKEN"] == "glpat-xyz"


def test_env_missing_required_exits(tmp_path, monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_PROJECT_ID", raising=False)
    monkeypatch.delenv("GITLAB_PAT", raising=False)
    # Point all discovery paths at empty dirs
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # noqa: ARG005
    try:
        G.load_env()
    except SystemExit as e:
        assert e.code == 1
        return
    raise AssertionError("expected SystemExit on missing required keys")


def test_env_comments_and_quotes_handled(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# this is a comment\n"
        '  GITLAB_TOKEN = "glpat-quoted"  \n'
        "GITLAB_PROJECT_ID='42'\n"
        "\n"
    )
    env = G.load_env(str(env_file))
    assert env["GITLAB_TOKEN"] == "glpat-quoted"
    assert env["GITLAB_PROJECT_ID"] == "42"


# ---------- content type guessing ----------

def test_guess_content_type_known_extensions():
    assert G._guess_content_type("step.png") == "image/png"
    assert G._guess_content_type("foo.JPG") == "image/jpeg"
    assert G._guess_content_type("a.svg") == "image/svg+xml"
    assert G._guess_content_type("doc.pdf") == "application/pdf"


def test_guess_content_type_unknown():
    assert G._guess_content_type("blob.bin") == "application/octet-stream"
    assert G._guess_content_type("noext") == "application/octet-stream"


# ---------- upload_file multipart body ----------

def test_upload_file_constructs_correct_multipart(tmp_path):
    """Verify the body bytes upload_file sends — without actually doing the POST.
    We mock urllib.request.urlopen to capture the Request object."""
    f = tmp_path / "step-2.png"
    f.write_bytes(b"\x89PNG\r\nfake png bytes\r\n")
    env = {"GITLAB_TOKEN": "glpat-test", "GITLAB_PROJECT_ID": "42",
           "GITLAB_URL": "https://gitlab.com"}

    captured = {}

    class FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'{"id": 7, "alt": "step-2.png", "url": "/uploads/abc/step-2.png", "markdown": "![step-2.png](/uploads/abc/step-2.png)"}'

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data
        return FakeResp()

    with mock.patch.object(G.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = G.upload_file(env, f)

    assert result is not None
    assert result["markdown"].startswith("![step-2.png]")
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/v4/projects/42/uploads")
    # Multipart boundary in Content-Type
    ct = next(v for k, v in captured["headers"].items() if k.lower() == "content-type")
    assert ct.startswith("multipart/form-data; boundary=----qa-upload-")
    # Body contains the file bytes verbatim
    assert b"\x89PNG" in captured["data"]
    assert b'filename="step-2.png"' in captured["data"]
    assert b"Content-Type: image/png" in captured["data"]


def test_upload_file_missing_path_returns_none(tmp_path):
    env = {"GITLAB_TOKEN": "x", "GITLAB_PROJECT_ID": "1",
           "GITLAB_URL": "https://gitlab.com"}
    assert G.upload_file(env, tmp_path / "nope.png") is None


# ---------- get_pipeline_status ----------

def test_get_pipeline_status_returns_first_pipeline_status():
    env = {"GITLAB_TOKEN": "x", "GITLAB_PROJECT_ID": "1",
           "GITLAB_URL": "https://gitlab.com"}
    with mock.patch.object(G, "gitlab_api",
                           return_value=([{"status": "success", "id": 1}], {})):
        assert G.get_pipeline_status(env, 6865) == "success"


def test_get_pipeline_status_unknown_on_empty():
    env = {"GITLAB_TOKEN": "x", "GITLAB_PROJECT_ID": "1",
           "GITLAB_URL": "https://gitlab.com"}
    with mock.patch.object(G, "gitlab_api", return_value=([], {})):
        assert G.get_pipeline_status(env, 6865) == "unknown"


def test_get_pipeline_status_unknown_on_api_failure():
    env = {"GITLAB_TOKEN": "x", "GITLAB_PROJECT_ID": "1",
           "GITLAB_URL": "https://gitlab.com"}
    with mock.patch.object(G, "gitlab_api", return_value=(None, {})):
        assert G.get_pipeline_status(env, 6865) == "unknown"


# ---------- project ID URL-encoding ----------

def test_project_path_numeric_passes_through():
    env = {"GITLAB_PROJECT_ID": "1496872"}
    assert G._project_path(env, None) == "1496872"


def test_project_path_namespace_gets_encoded():
    env = {"GITLAB_PROJECT_ID": "medtrics-org/medtrics-legacy"}
    assert G._project_path(env, None) == "medtrics-org%2Fmedtrics-legacy"


def test_project_path_override_arg_wins():
    env = {"GITLAB_PROJECT_ID": "1"}
    assert G._project_path(env, "999") == "999"
