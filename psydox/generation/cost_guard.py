"""
Psydox CostGuard

Every AI API call MUST pass through CostGuard before executing.

Flow:  UI → AI Orchestrator → CostGuard.check() → Provider (or BLOCK)

Rules:
  1. Per-call cost ≤ ₹0.50 → ALLOW
  2. Per-call cost > ₹0.50 → BLOCK
  3. Pricing unknown      → BLOCK ("Cost cannot be verified")
  4. Retries also checked → total budget for angle set enforced

CostGuard NEVER bypasses its own checks.
CostGuard NEVER assumes ₹0 for unknown pricing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .policy import AIQualityPolicy, get_cost_inr, get_policy

_log = logging.getLogger("psydox.generation.cost_guard")


@dataclass
class CostCheckResult:
    allowed:        bool
    reason:         str         = ""
    estimated_inr:  float       = 0.0
    action:         str         = ""  # "ALLOW" | "BLOCK_OVER_LIMIT" | "BLOCK_UNKNOWN"


class CostGuard:
    """
    Enforces the ₹0.50 per-angle hard limit and total batch budget.
    Stateless — instantiate once or call check_call() as a static helper.
    """

    def __init__(self, policy: Optional[AIQualityPolicy] = None):
        self._policy = policy or get_policy()

    # ── Per-call check (the primary gate) ────────────────────────────────────

    def check_call(self, provider_id: str, model: str) -> CostCheckResult:
        """
        Check a single API call.
        Returns CostCheckResult.allowed = False → do NOT call the API.
        """
        cost = get_cost_inr(provider_id, model)

        if cost is None:
            _log.warning(
                "CostGuard: unknown pricing for provider=%s model=%s — BLOCKED",
                provider_id, model,
            )
            return CostCheckResult(
                allowed=False,
                reason=f"Cost cannot be verified for {provider_id}/{model}.",
                estimated_inr=0.0,
                action="BLOCK_UNKNOWN",
            )

        limit = self._policy.max_cost_inr_per_angle
        if cost > limit:
            _log.warning(
                "CostGuard: cost ₹%.2f > limit ₹%.2f for provider=%s model=%s — BLOCKED",
                cost, limit, provider_id, model,
            )
            return CostCheckResult(
                allowed=False,
                reason=f"₹{cost:.2f} exceeds per-angle limit ₹{limit:.2f} for {provider_id}/{model}.",
                estimated_inr=cost,
                action="BLOCK_OVER_LIMIT",
            )

        _log.debug("CostGuard: ₹%.2f ALLOWED for provider=%s model=%s", cost, provider_id, model)
        return CostCheckResult(
            allowed=True,
            reason=f"₹{cost:.2f} within limit ₹{limit:.2f}.",
            estimated_inr=cost,
            action="ALLOW",
        )

    def check_with_cost(self, estimated_cost_inr: float) -> CostCheckResult:
        """
        Check a call where you already know the cost (e.g. from provider.estimate_cost()).
        estimated_cost_inr = -1 means unknown → BLOCK.
        """
        if estimated_cost_inr < 0:
            return CostCheckResult(
                allowed=False,
                reason="Cost cannot be verified (negative cost).",
                estimated_inr=0.0,
                action="BLOCK_UNKNOWN",
            )

        limit = self._policy.max_cost_inr_per_angle
        if estimated_cost_inr > limit:
            return CostCheckResult(
                allowed=False,
                reason=f"₹{estimated_cost_inr:.2f} exceeds limit ₹{limit:.2f}.",
                estimated_inr=estimated_cost_inr,
                action="BLOCK_OVER_LIMIT",
            )

        return CostCheckResult(
            allowed=True,
            reason=f"₹{estimated_cost_inr:.2f} within limit ₹{limit:.2f}.",
            estimated_inr=estimated_cost_inr,
            action="ALLOW",
        )

    # ── Batch budget check ────────────────────────────────────────────────────

    def check_batch_budget(
        self,
        total_requested_angles: int,
        approved_so_far: int,
        spent_inr: float,
        next_call_cost_inr: float,
    ) -> CostCheckResult:
        """
        Check whether the next API call is within the remaining batch budget.

        Total batch budget = total_requested_angles × ₹0.50
        Remaining = budget - spent_so_far
        """
        limit = self._policy.max_cost_inr_per_angle
        total_budget = total_requested_angles * limit
        remaining    = total_budget - spent_inr

        if next_call_cost_inr > remaining:
            return CostCheckResult(
                allowed=False,
                reason=(
                    f"Batch budget exhausted: spent ₹{spent_inr:.2f} of "
                    f"₹{total_budget:.2f} ({total_requested_angles} angles × ₹{limit:.2f}). "
                    f"Next call ₹{next_call_cost_inr:.2f} > remaining ₹{remaining:.2f}."
                ),
                estimated_inr=next_call_cost_inr,
                action="BLOCK_OVER_LIMIT",
            )

        return CostCheckResult(
            allowed=True,
            reason=f"₹{remaining:.2f} remaining in batch budget.",
            estimated_inr=next_call_cost_inr,
            action="ALLOW",
        )

    # ── Business metric ───────────────────────────────────────────────────────

    @staticmethod
    def cost_per_approved_angle(total_spent_inr: float, approved_count: int) -> float:
        """The primary business metric: total cost / approved angles."""
        if approved_count <= 0:
            return float("inf")
        return round(total_spent_inr / approved_count, 4)


_guard: Optional[CostGuard] = None


def get_cost_guard() -> CostGuard:
    global _guard
    if _guard is None:
        _guard = CostGuard()
    return _guard
