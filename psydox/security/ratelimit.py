"""
Psydox Rate Limiter — token bucket per user per action.

Limits:
  ai_generation   10 / hour
  classic_batch   30 / hour
  upload          50 / hour
  login           5 / 10 minutes

Uses in-memory buckets backed by st.cache_resource (Railway-safe).
Not distributed — suitable for single-process deployments.
"""
from __future__ import annotations

import time
import logging
from typing import Optional

try:
    import streamlit as st
    _HAS_ST = True
except ImportError:
    st = None  # type: ignore
    _HAS_ST = False

_log = logging.getLogger("psydox.security.ratelimit")


class _Bucket:
    def __init__(self, capacity: int, refill_per_second: float):
        self.capacity         = capacity
        self.refill_per_second = refill_per_second
        self.tokens           = float(capacity)
        self.last_refill      = time.time()

    def consume(self, n: int = 1) -> bool:
        now    = time.time()
        delta  = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + delta * self.refill_per_second)
        self.last_refill = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


# Default limits: (capacity, refill_per_second)
_LIMITS: dict[str, tuple[int, float]] = {
    "ai_generation": (10,  10 / 3600),      # 10/hour
    "classic_batch": (30,  30 / 3600),      # 30/hour
    "upload":        (50,  50 / 3600),      # 50/hour
    "login":         (5,   5  / 600),       # 5 per 10min
}


class RateLimiter:
    def __init__(self, store: dict):
        self._store = store  # keyed by "email:action"

    def check(self, user_email: str, action: str, n: int = 1) -> bool:
        """Return True if request is allowed; False if rate-limited."""
        key = f"{user_email}:{action}"
        if key not in self._store:
            capacity, rate = _LIMITS.get(action, (100, 1.0))
            self._store[key] = _Bucket(capacity, rate)
        return self._store[key].consume(n)

    def remaining(self, user_email: str, action: str) -> int:
        key = f"{user_email}:{action}"
        bucket = self._store.get(key)
        if bucket is None:
            capacity, _ = _LIMITS.get(action, (100, 1.0))
            return capacity
        return int(bucket.tokens)


_FALLBACK_STORE: dict = {}


def _rl_store() -> dict:
    if _HAS_ST:
        @st.cache_resource
        def _store():
            return {}
        return _store()
    return _FALLBACK_STORE


def get_rate_limiter() -> RateLimiter:
    return RateLimiter(_rl_store())
