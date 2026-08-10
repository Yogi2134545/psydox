"""Tests for AI Cache."""
import sys
import os
import tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def test_cache_put_and_get(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PSYDOX_AI_CACHE", "true")
    from psydox.ai_core import cache as _m
    import importlib; importlib.reload(_m)
    c = _m.AICache()
    key = c.make_key("abc", "bg", "solid", "fp123")
    assert c.get(key) is None
    c.put(key, b"hello")
    assert c.get(key) == b"hello"


def test_cache_miss_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_CACHE_DIR", str(tmp_path))
    from psydox.ai_core import cache as _m
    import importlib; importlib.reload(_m)
    c = _m.AICache()
    assert c.get("nonexistent_key_xyz") is None


def test_cache_key_deterministic(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_CACHE_DIR", str(tmp_path))
    from psydox.ai_core import cache as _m
    import importlib; importlib.reload(_m)
    c = _m.AICache()
    k1 = c.make_key("h1", "bg", "solid", "fp")
    k2 = c.make_key("h1", "bg", "solid", "fp")
    assert k1 == k2


def test_different_inputs_different_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_CACHE_DIR", str(tmp_path))
    from psydox.ai_core import cache as _m
    import importlib; importlib.reload(_m)
    c = _m.AICache()
    k1 = c.make_key("h1", "bg",        "solid", "fp")
    k2 = c.make_key("h1", "lifestyle", "ai",    "fp")
    assert k1 != k2


def test_cache_disabled_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PSYDOX_AI_CACHE", "false")
    from psydox.ai_core import cache as _m
    import importlib; importlib.reload(_m)
    c = _m.AICache(ttl_s=3600)
    c._enabled = False
    key = c.make_key("x", "f", "op", "fp")
    c.put(key, b"data")
    assert c.get(key) is None


def test_cache_stats_tracks_hits(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PSYDOX_AI_CACHE", "true")
    from psydox.ai_core import cache as _m
    import importlib; importlib.reload(_m)
    c = _m.AICache()
    key = c.make_key("y", "f", "op", "fp")
    c.put(key, b"x")
    c.get(key)
    stats = c.stats()
    assert stats["hits"] >= 1
    assert stats["enabled"] is True
