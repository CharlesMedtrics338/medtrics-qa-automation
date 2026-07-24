"""Unit tests for qa-cache/scripts/cache.py. Pure-Python; uses QA_CACHE_ROOT
to redirect the cache directory into a tmp_path so tests don't touch the
real ~/.cache/.

    pytest skills/qa-cache/tests/test_cache.py
"""
import time

import cache as C


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("QA_CACHE_ROOT", str(tmp_path))


# ---- get / put basics ----

def test_put_and_get_roundtrip(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert C.put("gitlab.get_mr", "1496872:6865", {"title": "fix x"}, ttl_seconds=60)
    assert C.get("gitlab.get_mr", "1496872:6865") == {"title": "fix x"}


def test_get_returns_default_on_miss(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert C.get("gitlab.get_mr", "no-such-key") is None
    assert C.get("gitlab.get_mr", "no-such-key", default="sentinel") == "sentinel"


def test_put_zero_ttl_is_rejected(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert C.put("ns", "k", "v", ttl_seconds=0) is False
    assert C.put("ns", "k", "v", ttl_seconds=-1) is False
    assert C.get("ns", "k") is None


# ---- TTL expiration ----

def test_expired_entry_returns_default(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.put("ns", "k", "v", ttl_seconds=1)
    assert C.get("ns", "k") == "v"
    time.sleep(1.5)
    assert C.get("ns", "k") is None


def test_expired_entry_is_pruned_on_read(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.put("ns", "k", "v", ttl_seconds=1)
    path = C._entry_path("ns", "k")
    assert path.exists()
    time.sleep(1.5)
    _ = C.get("ns", "k")  # triggers prune
    assert not path.exists()


# ---- namespace isolation ----

def test_namespaces_do_not_collide(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.put("gitlab.get_mr", "1:2", {"a": 1}, ttl_seconds=60)
    C.put("optimus.get_task", "1:2", {"b": 2}, ttl_seconds=60)
    assert C.get("gitlab.get_mr", "1:2") == {"a": 1}
    assert C.get("optimus.get_task", "1:2") == {"b": 2}


# ---- invalidate ----

def test_invalidate_single_key(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.put("ns", "a", 1, ttl_seconds=60)
    C.put("ns", "b", 2, ttl_seconds=60)
    removed = C.invalidate("ns", "a")
    assert removed == 1
    assert C.get("ns", "a") is None
    assert C.get("ns", "b") == 2


def test_invalidate_whole_namespace(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.put("ns", "a", 1, ttl_seconds=60)
    C.put("ns", "b", 2, ttl_seconds=60)
    C.put("other", "c", 3, ttl_seconds=60)
    removed = C.invalidate("ns")
    assert removed == 2
    assert C.get("ns", "a") is None
    assert C.get("ns", "b") is None
    assert C.get("other", "c") == 3


def test_invalidate_missing_key_is_zero(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert C.invalidate("ns", "no-such") == 0
    assert C.invalidate("no-such-ns") == 0


# ---- cleanup_expired ----

def test_cleanup_expired_sweeps_only_expired(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.put("ns", "fresh", 1, ttl_seconds=60)
    C.put("ns", "stale", 2, ttl_seconds=1)
    time.sleep(1.5)
    removed = C.cleanup_expired("ns")
    assert removed == 1
    assert C.get("ns", "fresh") == 1
    assert C.get("ns", "stale") is None


def test_cleanup_expired_all_namespaces(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.put("a", "k", "v", ttl_seconds=1)
    C.put("b", "k", "v", ttl_seconds=1)
    time.sleep(1.5)
    removed = C.cleanup_expired()
    assert removed == 2


# ---- stats ----

def test_stats_reports_entries(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    C.put("ns", "a", "v", ttl_seconds=60)
    C.put("ns", "b", "v", ttl_seconds=60)
    s = C.stats()
    assert "ns" in s
    assert s["ns"]["entries"] == 2
    assert s["ns"]["expired"] == 0
    assert s["ns"]["total_bytes"] > 0
