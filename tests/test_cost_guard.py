"""
Tests for CostGuard — the ₹0.50 per-angle hard limit.

All tests are offline (no API calls).

Coverage:
  - ₹0.49 → ALLOW
  - ₹0.50 → ALLOW
  - ₹0.51 → BLOCK
  - Unknown pricing → BLOCK
  - Batch budget enforcement
  - Cost per approved angle metric
  - AutoFix / retry budget gate
"""
import pytest

from psydox.generation.cost_guard import CostGuard, CostCheckResult
from psydox.generation.policy import AIQualityPolicy, get_cost_inr


POLICY = AIQualityPolicy()


# ── Per-call limit ────────────────────────────────────────────────────────────

class TestPerCallLimit:
    def setup_method(self):
        self.guard = CostGuard(POLICY)

    def test_049_is_allowed(self):
        result = self.guard.check_with_cost(0.49)
        assert result.allowed is True
        assert result.action == "ALLOW"

    def test_050_is_allowed(self):
        result = self.guard.check_with_cost(0.50)
        assert result.allowed is True

    def test_051_is_blocked(self):
        result = self.guard.check_with_cost(0.51)
        assert result.allowed is False
        assert result.action == "BLOCK_OVER_LIMIT"

    def test_zero_cost_is_allowed(self):
        result = self.guard.check_with_cost(0.00)
        assert result.allowed is True

    def test_large_cost_blocked(self):
        result = self.guard.check_with_cost(3.32)  # DALL-E 3
        assert result.allowed is False

    def test_negative_cost_blocked(self):
        result = self.guard.check_with_cost(-1.0)
        assert result.allowed is False
        assert result.action == "BLOCK_UNKNOWN"


# ── Provider name + model lookup ──────────────────────────────────────────────

class TestProviderModelLookup:
    def setup_method(self):
        self.guard = CostGuard(POLICY)

    def test_gemini_is_within_limit(self):
        result = self.guard.check_call("gemini", "gemini-2.0-flash-preview-image-generation")
        assert result.allowed is True

    def test_openai_dalle3_blocked(self):
        result = self.guard.check_call("openai", "dall-e-3")
        assert result.allowed is False
        assert "3.32" in result.reason or "exceeds" in result.reason

    def test_replicate_flux_allowed(self):
        result = self.guard.check_call("replicate", "black-forest-labs/flux-schnell")
        assert result.allowed is True

    def test_stability_core_allowed(self):
        result = self.guard.check_call("stability", "stable-image-core")
        assert result.allowed is True

    def test_stability_ultra_blocked_at_exactly_limit(self):
        # stable-image-ultra = ₹0.50 → should be ALLOWED (≤ not <)
        result = self.guard.check_call("stability", "stable-image-ultra")
        assert result.allowed is True  # 0.50 == limit → allowed

    def test_mock_provider_allowed(self):
        result = self.guard.check_call("mock", "mock-v1")
        assert result.allowed is True

    def test_unknown_provider_blocked(self):
        result = self.guard.check_call("somerandomprovider", "unknown-model-xyz")
        assert result.allowed is False
        assert result.action == "BLOCK_UNKNOWN"

    def test_known_provider_unknown_model_uses_default(self):
        # "gemini" with unknown model → falls back to default price
        result = self.guard.check_call("gemini", "gemini-99-ultra-mega")
        assert result.allowed is True  # default for gemini is ₹0.08

    def test_openai_unknown_model_uses_default(self):
        # openai default is ₹3.32 → blocked
        result = self.guard.check_call("openai", "some-future-model")
        assert result.allowed is False


# ── Unknown pricing ───────────────────────────────────────────────────────────

class TestUnknownPricing:
    def test_get_cost_inr_unknown_provider_returns_none(self):
        cost = get_cost_inr("doesnotexist", "somemodel")
        assert cost is None

    def test_cost_guard_blocks_unknown_pricing(self):
        guard = CostGuard(POLICY)
        result = guard.check_call("doesnotexist", "somemodel")
        assert result.allowed is False
        assert result.action == "BLOCK_UNKNOWN"

    def test_reason_mentions_cost_cannot_be_verified(self):
        guard = CostGuard(POLICY)
        result = guard.check_call("mysteryai", "mysterymodel")
        assert "cannot be verified" in result.reason.lower() or "unknown" in result.reason.lower()


# ── Batch budget ──────────────────────────────────────────────────────────────

class TestBatchBudget:
    def setup_method(self):
        self.guard = CostGuard(POLICY)

    def test_empty_batch_allows_first_call(self):
        result = self.guard.check_batch_budget(
            total_requested_angles=8,
            approved_so_far=0,
            spent_inr=0.0,
            next_call_cost_inr=0.08,
        )
        assert result.allowed is True

    def test_batch_at_exactly_budget_blocks(self):
        # spent = 8 × 0.50 = ₹4.00 (entire budget gone)
        result = self.guard.check_batch_budget(
            total_requested_angles=8,
            approved_so_far=6,
            spent_inr=4.00,
            next_call_cost_inr=0.08,
        )
        assert result.allowed is False

    def test_batch_almost_at_limit_allows_cheap_call(self):
        # spent = ₹3.92, budget = ₹4.00, next = ₹0.08 → exactly fits
        result = self.guard.check_batch_budget(
            total_requested_angles=8,
            approved_so_far=7,
            spent_inr=3.92,
            next_call_cost_inr=0.08,
        )
        assert result.allowed is True

    def test_single_angle_budget(self):
        # 1 angle → budget = ₹0.50
        result = self.guard.check_batch_budget(
            total_requested_angles=1,
            approved_so_far=0,
            spent_inr=0.40,
            next_call_cost_inr=0.08,
        )
        assert result.allowed is True

    def test_single_angle_retry_over_budget(self):
        # 1 angle, first attempt ₹0.48, retry ₹0.08 → total ₹0.56 > ₹0.50
        result = self.guard.check_batch_budget(
            total_requested_angles=1,
            approved_so_far=0,
            spent_inr=0.48,
            next_call_cost_inr=0.08,
        )
        assert result.allowed is False


# ── Cost per approved angle metric ───────────────────────────────────────────

class TestCostPerApprovedAngle:
    def test_basic_metric(self):
        # 10 attempts, 8 approved, total ₹3.20 → ₹0.40 per angle
        metric = CostGuard.cost_per_approved_angle(3.20, 8)
        assert abs(metric - 0.40) < 0.01

    def test_perfect_run(self):
        # 8 attempts, 8 approved, ₹0.64 → ₹0.08 per angle
        metric = CostGuard.cost_per_approved_angle(0.64, 8)
        assert abs(metric - 0.08) < 0.01

    def test_zero_approved_returns_inf(self):
        metric = CostGuard.cost_per_approved_angle(1.00, 0)
        assert metric == float("inf")

    def test_within_business_limit(self):
        # 5 approved, ₹1.80 total → ₹0.36 per angle (within ₹0.50)
        metric = CostGuard.cost_per_approved_angle(1.80, 5)
        assert metric <= 0.50


# ── Retry / AutoFix budget gate ───────────────────────────────────────────────

class TestRetryBudget:
    def setup_method(self):
        self.guard = CostGuard(POLICY)

    def test_retry_within_budget_allowed(self):
        # First attempt ₹0.08, retry ₹0.08 → total ₹0.16 for 1 angle (₹0.50 budget)
        result = self.guard.check_batch_budget(
            total_requested_angles=1,
            approved_so_far=0,
            spent_inr=0.08,
            next_call_cost_inr=0.08,
        )
        assert result.allowed is True

    def test_autofix_over_budget_blocked(self):
        # After 2 attempts for 1 angle, total ₹0.48, autofix costs ₹0.08 → ₹0.56 > ₹0.50
        result = self.guard.check_batch_budget(
            total_requested_angles=1,
            approved_so_far=0,
            spent_inr=0.48,
            next_call_cost_inr=0.08,
        )
        assert result.allowed is False
