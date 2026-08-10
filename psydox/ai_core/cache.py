"""
Psydox AI Cache

Deterministic disk-based cache for AI generations.

Cache key is SHA256 of:
  input_hash + product_version + feature_id + operation + config_hash + model + prompt_fingerprint

Cache is stored as flat files under <PSYDOX_CACHE_DIR>/ai_cache/<key[:2]>/<key>.bin
TTL: configurable (default 24h).  Eviction: LRU by file mtime (max 500 entries by default).

The cache prevents re-generating identical work, which is important for cost.
It is disabled when DEBUG_MODE=true (mock results are cheap).
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Optional

_log = logging.getLogger("psydox.ai_core.cache")

_DEFAULT_TTL_S = 86400       # 24 hours
_MAX_ENTRIES   = 500
_CACHE_ENABLED = os.environ.get("PSYDOX_AI_CACHE", "true").lower() not in ("0", "false", "no")


def _cache_dir() -> Path:
    base = os.environ.get("PSYDOX_CACHE_DIR", str(Path.home() / ".psydox_cache"))
    p = Path(base) / "ai_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


class AICache:
    """
    Disk-based AI result cache.
    get/put are thread-safe (atomic file writes via temp file rename).
    """

    def __init__(self, ttl_s: int = _DEFAULT_TTL_S, max_entries: int = _MAX_ENTRIES):
        self._ttl       = ttl_s
        self._max       = max_entries
        self._enabled   = _CACHE_ENABLED
        self._hits      = 0
        self._misses    = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def make_key(
        self,
        input_hash:       str,
        feature_id:       str,
        operation:        str,
        prompt_fingerprint: str,
        model:            str = "",
        product_version:  str = "",
        config_hash:      str = "",
    ) -> str:
        raw = "|".join([
            input_hash, feature_id, operation, prompt_fingerprint,
            model, product_version, config_hash,
        ])
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Optional[bytes]:
        if not self._enabled:
            return None
        path = self._key_path(key)
        if not path.exists():
            self._misses += 1
            return None
        if time.time() - path.stat().st_mtime > self._ttl:
            path.unlink(missing_ok=True)
            self._misses += 1
            return None
        try:
            data = path.read_bytes()
            self._hits += 1
            _log.debug("AI cache HIT: %s", key[:16])
            return data
        except OSError:
            self._misses += 1
            return None

    def put(self, key: str, data: bytes) -> bool:
        if not self._enabled or not data:
            return False
        try:
            path = self._key_path(key)
            # Atomic write
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            _log.debug("AI cache PUT: %s (%d bytes)", key[:16], len(data))
            self._maybe_evict()
            return True
        except OSError as exc:
            _log.debug("AI cache PUT failed: %s", exc)
            return False

    def invalidate(self, key: str) -> None:
        self._key_path(key).unlink(missing_ok=True)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits":      self._hits,
            "misses":    self._misses,
            "hit_rate":  round(self._hits / total, 3) if total else 0.0,
            "enabled":   self._enabled,
        }

    # ── Internal ───────────────────────────────────────────────────────────────

    def _key_path(self, key: str) -> Path:
        shard = key[:2]
        d = _cache_dir() / shard
        d.mkdir(exist_ok=True)
        return d / f"{key}.bin"

    def _maybe_evict(self) -> None:
        try:
            root = _cache_dir()
            files = sorted(root.rglob("*.bin"), key=lambda f: f.stat().st_mtime)
            if len(files) > self._max:
                for old in files[:len(files) - self._max]:
                    old.unlink(missing_ok=True)
        except Exception:
            pass


# Module-level singleton
_cache: Optional[AICache] = None

def get_ai_cache() -> AICache:
    global _cache
    if _cache is None:
        _cache = AICache()
    return _cache
