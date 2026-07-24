"""Unit tests for the deploy resolver in gitlab_get_mr._resolve_deploy.

Three strategies, in priority order:
  A. environment-name lookup       — preferred (Medtrics convention)
  B. deployments filtered by env   — for status info
  C. legacy SHA-prefix scan        — last resort

Pure-Python; mocks `gitlab_client.gitlab_api` and the env-name helpers so
no network is required.

    pytest skills/qa-gitlab-bridge/tests/test_resolve_deploy.py
"""
from unittest import mock

import gitlab_get_mr as G


ENV = {"GITLAB_URL": "https://gitlab.com", "GITLAB_TOKEN": "x", "GITLAB_PROJECT_ID": "1"}


# ---- Strategy A: environment-name lookup ----

def test_strategy_A_environment_available_returns_url_and_success():
    fake_env = {"name": "6865.medtrics.dev", "state": "available",
                "external_url": "https://6865.medtrics.dev"}
    fake_deps = [{"status": "success", "environment": fake_env}]
    with mock.patch.object(G, "get_environment_by_name", return_value=fake_env), \
         mock.patch.object(G, "list_deployments_for_environment", return_value=fake_deps):
        url, status, strategy = G._resolve_deploy(ENV, mr_iid="6865", head_sha="abc", project_id=None)
    assert url == "https://6865.medtrics.dev"
    assert status == "success"
    assert strategy == "environment_lookup"


def test_strategy_A_falls_back_to_default_status_when_no_deployments():
    # Env is live but the deployment list returned empty (e.g. skipped).
    fake_env = {"name": "6865.medtrics.dev", "state": "available",
                "external_url": "https://6865.medtrics.dev"}
    with mock.patch.object(G, "get_environment_by_name", return_value=fake_env), \
         mock.patch.object(G, "list_deployments_for_environment", return_value=[]):
        url, status, strategy = G._resolve_deploy(ENV, mr_iid="6865", head_sha="abc", project_id=None)
    assert url == "https://6865.medtrics.dev"
    assert status == "success"   # default when env is available but no recent deploy
    assert strategy == "environment_lookup"


def test_strategy_A_returns_none_when_env_stopped():
    fake_env = {"name": "old.medtrics.dev", "state": "stopped",
                "external_url": "https://old.medtrics.dev"}
    with mock.patch.object(G, "get_environment_by_name", return_value=fake_env), \
         mock.patch.object(G, "list_deployments_for_environment", return_value=[]), \
         mock.patch.object(G, "gitlab_api", return_value=([], {})):
        url, status, strategy = G._resolve_deploy(ENV, mr_iid="9999", head_sha="abc", project_id=None)
    assert url is None
    assert strategy == "environment_unavailable"


# ---- Strategy B: deployments filtered by env-name ----

def test_strategy_B_used_when_env_lookup_returned_nothing():
    fake_env = {"name": "x.medtrics.dev", "external_url": ""}  # no URL on env
    fake_deps = [
        {"status": "running",
         "environment": {"name": "x.medtrics.dev",
                         "external_url": "https://x.medtrics.dev"}},
    ]
    with mock.patch.object(G, "get_environment_by_name", return_value=None), \
         mock.patch.object(G, "list_deployments_for_environment", return_value=fake_deps), \
         mock.patch.object(G, "gitlab_api", return_value=([], {})):
        url, status, strategy = G._resolve_deploy(ENV, mr_iid="6865", head_sha="abc", project_id=None)
    assert url == "https://x.medtrics.dev"
    assert status == "running"
    assert strategy == "deployments_by_environment"


# ---- Strategy C: legacy SHA-prefix scan ----

def test_strategy_C_used_as_last_resort_when_no_env_match():
    # No env name match, no env-filtered deployments. Fall back to SHA scan.
    project_deps = [
        {"sha": "48ec56abf4dc85acc62d478a820df66f12ee16e7",
         "status": "success",
         "environment": {"name": "6865.medtrics.dev",
                         "external_url": "https://6865.medtrics.dev"}},
        {"sha": "11111111111111111111111111111111",
         "status": "running", "environment": {}},
    ]
    with mock.patch.object(G, "get_environment_by_name", return_value=None), \
         mock.patch.object(G, "list_deployments_for_environment", return_value=[]), \
         mock.patch.object(G, "gitlab_api", return_value=(project_deps, {})):
        url, status, strategy = G._resolve_deploy(
            ENV, mr_iid="6865", head_sha="48ec56abf4dc85acc62d478a820df66f12ee16e7",
            project_id=None,
        )
    assert url == "https://6865.medtrics.dev"
    assert status == "success"
    assert strategy == "sha_prefix_scan"


def test_no_match_returns_none_match():
    with mock.patch.object(G, "get_environment_by_name", return_value=None), \
         mock.patch.object(G, "list_deployments_for_environment", return_value=[]), \
         mock.patch.object(G, "gitlab_api", return_value=([], {})):
        url, status, strategy = G._resolve_deploy(ENV, mr_iid="6865", head_sha="abc", project_id=None)
    assert url is None
    assert status is None
    assert strategy == "no_match"


# ---- env-name pattern override ----

def test_env_pattern_override_changes_lookup_name():
    fake_env = {"name": "staging-6865.example.org", "state": "available",
                "external_url": "https://staging-6865.example.org"}
    captured = {}

    def spy_get_env(env, name, *, project_id=None):
        captured["name"] = name
        return fake_env if name == "staging-6865.example.org" else None

    with mock.patch.object(G, "get_environment_by_name", side_effect=spy_get_env), \
         mock.patch.object(G, "list_deployments_for_environment", return_value=[]):
        url, status, strategy = G._resolve_deploy(
            ENV, mr_iid="6865", head_sha="abc", project_id=None,
            deploy_env_pattern="staging-{mr_iid}.example.org",
        )
    assert captured["name"] == "staging-6865.example.org"
    assert url == "https://staging-6865.example.org"
    assert strategy == "environment_lookup"


def test_empty_inputs_returns_no_inputs_strategy():
    url, status, strategy = G._resolve_deploy(ENV, mr_iid="", head_sha="", project_id=None)
    assert strategy == "no_inputs"
    assert url is None and status is None
