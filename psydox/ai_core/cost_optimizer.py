"""
Psydox AI Cost Optimizer

Before invoking the AI, the optimizer decides:
  1. Can this be done with Classic (PIL) processing? → free
  2. Is there a valid cached result? → free
  3. Which model tier is appropriate? (don't always use premium)

Decision table:
  Solid color background  → CLASSIC
  Gradient background     → CLASSIC
  Resize / crop           → CLASSIC
  Transparent BG (rembg)  → CLASSIC
  Product analysis        → FAST_AI (cheap vision model)
  Quality analysis        → CLASSIC (algorithmic)
  Lighting adjustment     → FAST_AI
  Shadow generation       → FAST_AI
  Creative background     → STANDARD_AI
  Scene generation        → STANDARD_AI
  Angle generation        → STANDARD_AI
  Creative edit           → STANDARD_AI
  Lifestyle               → PREMIUM_AI
  Model generation        → PREMIUM_AI

Cost estimates (USD, approximate):
  CLASSIC      $0.00
  FAST_AI      $0.01 per generation
  STANDARD_AI  $0.02 per generation
  PREMIUM_AI   $0.04 per generation
"""
from __future__ import annotations

import hashlib
import logging
from enum import Enum
from typing import Optional

_log = logging.getLogger("psydox.ai_core.cost_optimizer")

_COST_TABLE = {
    "CLASSIC":     0.00,
    "FAST_AI":     0.01,
    "STANDARD_AI": 0.02,
    "PREMIUM_AI":  0.04,
}


class ProcessingStrategy(str, Enum):
    CLASSIC      = "CLASSIC"      # PIL / algorithmic, no AI cost
    FAST_AI      = "FAST_AI"      # lightweight AI model
    STANDARD_AI  = "STANDARD_AI"  # mid-tier AI model
    PREMIUM_AI   = "PREMIUM_AI"   # highest quality AI model
    CACHE_HIT    = "CACHE_HIT"    # return cached result, $0


class OptimizationDecision:
    def __init__(
        self,
        strategy:      ProcessingStrategy,
        estimated_cost: float,
        cache_key:     Optional[str] = None,
        reason:        str = "",
    ):
        self.strategy       = strategy
        self.estimated_cost = estimated_cost
        self.cache_key      = cache_key
        self.reason         = reason

    def __repr__(self) -> str:
        return f"OptimizationDecision(strategy={self.strategy}, cost=${self.estimated_cost:.3f})"


class CostOptimizer:
    """
    Decides the optimal processing strategy for a given request.
    Used by the AIOrchestrator before dispatching to a provider.
    """

    def __init__(self):
        try:
            from psydox.ai_core.cache import get_ai_cache
            self._cache = get_ai_cache()
        except Exception:
            self._cache = None

    def decide(
        self,
        task_type_value: str,     # TaskType.value string
        prompt_fingerprint: str,
        input_hash: str,
        feature_id: str = "",
        force_ai: bool = False,
    ) -> OptimizationDecision:
        """
        Decide how to process this request.
        Returns an OptimizationDecision with strategy, cost, and optional cache_key.
        """
        from psydox.ai_core.router import TaskType, TaskRequirement, _ROUTING

        # Look up routing
        try:
            task = TaskType(task_type_value)
            requirement = _ROUTING.get(task)
        except ValueError:
            requirement = None

        # CLASSIC path
        if requirement and requirement.value == "deterministic" and not force_ai:
            return OptimizationDecision(
                strategy=ProcessingStrategy.CLASSIC,
                estimated_cost=0.0,
                reason=f"Task '{task_type_value}' uses classic processing (free)",
            )

        # Check cache
        if self._cache:
            cache_key = self._make_key(input_hash, feature_id, task_type_value, prompt_fingerprint)
            if self._cache.get(cache_key) is not None:
                return OptimizationDecision(
                    strategy=ProcessingStrategy.CACHE_HIT,
                    estimated_cost=0.0,
                    cache_key=cache_key,
                    reason="Cache hit — reusing existing result",
                )

        # Determine AI tier
        if requirement:
            strategy_map = {
                "fast_ai":     ProcessingStrategy.FAST_AI,
                "standard_ai": ProcessingStrategy.STANDARD_AI,
                "premium_ai":  ProcessingStrategy.PREMIUM_AI,
            }
            strategy = strategy_map.get(requirement.value, ProcessingStrategy.STANDARD_AI)
        else:
            strategy = ProcessingStrategy.STANDARD_AI

        cost = _COST_TABLE.get(strategy.value, 0.02)
        cache_key = self._make_key(input_hash, feature_id, task_type_value, prompt_fingerprint) if self._cache else None

        return OptimizationDecision(
            strategy=strategy,
            estimated_cost=cost,
            cache_key=cache_key,
            reason=f"AI generation required ({strategy.value})",
        )

    def _make_key(self, input_hash: str, feature_id: str, task: str, prompt_fp: str) -> str:
        raw = f"{input_hash}|{feature_id}|{task}|{prompt_fp}"
        return hashlib.sha256(raw.encode()).hexdigest()


_optimizer: Optional[CostOptimizer] = None

def get_cost_optimizer() -> CostOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = CostOptimizer()
    return _optimizer
