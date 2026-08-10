"""
Nano Banana — Session-level API cost tracker.

Tracks image generation calls and product analysis calls, then estimates
USD cost based on published Gemini pricing (approximate — not a billing record).

All costs are ESTIMATES. Actual billing is managed by Google Cloud.

Usage:
    tracker = CostTracker()
    tracker.record_image_generation()
    print(tracker.get_summary())
"""
import time
import streamlit as st

# ── Pricing constants (USD, approximate as of 2025) ──────────────────────────
# Gemini image generation — per generated image
_COST_PER_IMAGE_USD = 0.04

# Gemini 2.0 Flash text+vision — per token
_COST_PER_1K_INPUT_TOKENS  = 0.0001
_COST_PER_1K_OUTPUT_TOKENS = 0.0004

# Estimated token usage per operation
_TOKENS_IMG_GEN_INPUT   = 500
_TOKENS_IMG_GEN_OUTPUT  = 200
_TOKENS_ANALYSIS_INPUT  = 800
_TOKENS_ANALYSIS_OUTPUT = 300

_COST_PER_ANALYSIS_USD = (
    (_TOKENS_ANALYSIS_INPUT  / 1000) * _COST_PER_1K_INPUT_TOKENS +
    (_TOKENS_ANALYSIS_OUTPUT / 1000) * _COST_PER_1K_OUTPUT_TOKENS
)


@st.cache_resource
def _store() -> dict:
    """Process-wide store, survives Streamlit reruns."""
    return {}


class CostTracker:
    """
    Per-session cost tracking. Uses st.cache_resource so the counter
    persists across reruns and resets when the server restarts.

    Pass a session_id to isolate multiple browser sessions on the same server.
    """

    def __init__(self, session_id: str = "default"):
        self._sid = session_id
        d = _store()
        if self._sid not in d:
            d[self._sid] = {
                "image_generations": 0,
                "product_analyses":  0,
                "total_calls":       0,
                "estimated_cost_usd": 0.0,
                "start_time":        time.time(),
            }

    @property
    def _data(self) -> dict:
        return _store()[self._sid]

    def record_image_generation(self, count: int = 1) -> None:
        """Call once per generate_image() invocation."""
        d = self._data
        d["image_generations"] += count
        d["total_calls"]       += count
        d["estimated_cost_usd"] += count * _COST_PER_IMAGE_USD

    def record_product_analysis(self, count: int = 1) -> None:
        """Call once per ProductAnalyzer.analyze() invocation."""
        d = self._data
        d["product_analyses"] += count
        d["total_calls"]      += count
        d["estimated_cost_usd"] += count * _COST_PER_ANALYSIS_USD

    def get_summary(self) -> dict:
        d = self._data
        elapsed = time.time() - d["start_time"]
        return {
            "image_generations":   d["image_generations"],
            "product_analyses":    d["product_analyses"],
            "total_calls":         d["total_calls"],
            "estimated_cost_usd":  round(d["estimated_cost_usd"], 4),
            "session_duration_mins": round(elapsed / 60, 1),
        }

    def reset(self) -> None:
        _store()[self._sid] = {
            "image_generations": 0,
            "product_analyses":  0,
            "total_calls":       0,
            "estimated_cost_usd": 0.0,
            "start_time":        time.time(),
        }
