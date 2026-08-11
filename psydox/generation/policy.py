"""
Psydox Generation Policy

Central quality thresholds and provider pricing.
All thresholds MUST come from here — no magic numbers in pipeline code.

Business rule: ₹0.50 per APPROVED angle (hard limit).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_INR_PER_USD = 83.0  # Approximate exchange rate — update as needed


@dataclass
class AIQualityPolicy:
    """Single source of truth for all quality thresholds."""
    quality_threshold: int          = 85    # QualityEngine score (0-100)
    fidelity_threshold: float       = 0.65  # FidelityEngine overall_score (0.0-1.0)
    angle_accuracy_threshold: float = 0.70  # AngleValidator confidence (0.0-1.0)
    max_cost_inr_per_angle: float   = 0.50  # HARD business limit
    max_attempts_per_angle: int     = 2     # Default retry ceiling


_DEFAULT_POLICY = AIQualityPolicy()


def get_policy() -> AIQualityPolicy:
    return _DEFAULT_POLICY


# ── Provider pricing in INR ───────────────────────────────────────────────────
# Per-generation costs. None = pricing unknown → CostGuard will BLOCK.
#
# Sources (approximate, verify before production):
#   Gemini 2.0 Flash image gen: ~$0.001 → ₹0.08
#   DALL-E 3 standard:          ~$0.040 → ₹3.32  (OVER LIMIT)
#   OpenRouter free models:      $0.000 → ₹0.00
#   Replicate Flux Schnell:     ~$0.003 → ₹0.25
#   Stability AI Core:          ~$0.004 → ₹0.33
#   Mock (debug):                $0.000 → ₹0.00

_PRICING: dict[str, dict[str, Optional[float]]] = {
    "gemini": {
        "gemini-2.0-flash-preview-image-generation": 0.08,
        "gemini-2.0-flash-exp":                      0.08,
        "default":                                   0.08,
    },
    "openai": {
        "dall-e-3":  3.32,   # OVER ₹0.50 per call — will be blocked
        "dall-e-2":  1.66,
        "default":   3.32,
    },
    "openrouter": {
        "google/gemini-2.0-flash-exp:free": 0.00,
        "anthropic/claude-3-haiku":         0.08,
        "default":                          0.25,
    },
    "replicate": {
        "black-forest-labs/flux-schnell":  0.25,
        "black-forest-labs/flux-dev":      0.42,
        "stability-ai/sdxl":               0.33,
        "default":                         0.33,
    },
    "stability": {
        "stable-image-core":       0.33,
        "stable-image-ultra":      0.50,
        "default":                 0.33,
    },
    "mock": {
        "mock-v1":   0.00,
        "default":   0.00,
    },
}


def get_cost_inr(provider_id: str, model: str) -> Optional[float]:
    """
    Return the estimated INR cost for one generation call.
    Returns None if pricing is unknown → CostGuard will BLOCK.
    """
    provider_table = _PRICING.get(provider_id.lower())
    if provider_table is None:
        return None  # unknown provider — pricing unavailable
    cost = provider_table.get(model)
    if cost is None:
        cost = provider_table.get("default")
    return cost
