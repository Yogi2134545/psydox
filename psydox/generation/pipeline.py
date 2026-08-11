"""
Psydox Generation Pipeline

Implements the full product angle generation pipeline:

    Product Intelligence → Product Memory → Product Lock
    → Generation Contract → Provider Selection → CostGuard
    → Prompt Engine → AI Provider → Quality → Fidelity
    → Angle Validation → Decision Engine → APPROVED/RETRY/REVIEW

This is the single entry point for all AI angle generation.
Features never call providers directly.

Usage:
    pipeline = GenerationPipeline(user_email="yogeshwar@popclub.co")
    result = pipeline.generate_angle(image_bytes, "FRONT", provider_id="gemini")
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .policy       import AIQualityPolicy, get_policy, get_cost_inr
from .cost_guard   import CostGuard, CostCheckResult
from .contract     import GenerationContract, AngleSpec, get_angle, ANGLES
from .angle_validator import AngleValidator, AngleValidationResult
from .decision_engine import DecisionEngine, DecisionOutcome, GenerationDecision
from .smart_retry  import SmartRetryEngine, RetryContext

_log = logging.getLogger("psydox.generation.pipeline")


@dataclass
class AngleResult:
    """Result of generating one angle."""
    angle_id:       str
    display_name:   str
    outcome:        str             # APPROVED | REVIEW | HARD_FAIL | BUDGET_CONFLICT | FAILED
    image_bytes:    Optional[bytes] = None
    quality_score:  int             = 0
    fidelity_score: float           = 0.0
    angle_passed:   bool            = False
    cost_inr:       float           = 0.0
    attempts:       int             = 0
    provider:       str             = ""
    model:          str             = ""
    reason:         str             = ""
    validation_detail: dict         = field(default_factory=dict)

    def is_approved(self) -> bool:
        return self.outcome == "APPROVED"

    def to_dict(self) -> dict:
        return {
            "angle_id":      self.angle_id,
            "display_name":  self.display_name,
            "outcome":       self.outcome,
            "has_image":     self.image_bytes is not None,
            "quality_score": self.quality_score,
            "fidelity_score": round(self.fidelity_score, 3),
            "angle_passed":  self.angle_passed,
            "cost_inr":      round(self.cost_inr, 4),
            "attempts":      self.attempts,
            "provider":      self.provider,
            "model":         self.model,
            "reason":        self.reason,
        }


@dataclass
class MultiAngleResult:
    """Result of generating multiple angles for one product."""
    product_id:    str
    requested:     int
    approved:      int
    review:        int
    failed:        int
    total_cost_inr: float
    angle_results: list[AngleResult]
    is_complete:   bool  # True only when approved == requested

    @property
    def cost_per_approved_angle(self) -> float:
        return CostGuard.cost_per_approved_angle(self.total_cost_inr, self.approved)

    def to_dict(self) -> dict:
        return {
            "product_id":          self.product_id,
            "requested":           self.requested,
            "approved":            self.approved,
            "review":              self.review,
            "failed":              self.failed,
            "total_cost_inr":      round(self.total_cost_inr, 4),
            "cost_per_approved":   round(self.cost_per_approved_angle, 4),
            "is_complete":         self.is_complete,
            "angle_results":       [r.to_dict() for r in self.angle_results],
        }


class GenerationPipeline:
    """
    Full product-angle generation pipeline.
    Connects all subsystems — never bypasses CostGuard, quality, or fidelity.
    """

    def __init__(
        self,
        user_email: str = "",
        policy: Optional[AIQualityPolicy] = None,
    ):
        self._user_email = user_email
        self._policy     = policy or get_policy()
        self._cost_guard = CostGuard(self._policy)
        self._angle_val  = AngleValidator()
        self._decision   = DecisionEngine()
        self._retry_eng  = SmartRetryEngine()

    # ── Single angle generation ───────────────────────────────────────────────

    def generate_angle(
        self,
        image_bytes: bytes,
        angle_id: str,
        provider_id: str = "gemini",
        model: str = "",
        product_id: str = "",
    ) -> AngleResult:
        """Generate one angle for the given product image."""
        angle_spec = get_angle(angle_id)
        if not angle_spec:
            return AngleResult(
                angle_id=angle_id, display_name=angle_id,
                outcome="FAILED", reason=f"Unknown angle: {angle_id}",
            )

        # Resolve model from registry if not provided
        if not model:
            model = self._default_model(provider_id)

        # Cost guard: check before first attempt
        cost_check = self._cost_guard.check_call(provider_id, model)
        if not cost_check.allowed:
            return AngleResult(
                angle_id=angle_id, display_name=angle_spec.display_name,
                outcome="BUDGET_CONFLICT",
                reason=cost_check.reason,
                cost_inr=0.0, attempts=0,
            )

        # Product intelligence (use cache if available)
        product_desc = self._get_product_description(image_bytes, product_id)
        pid = product_id or self._image_hash(image_bytes)

        return self._run_attempts(
            image_bytes=image_bytes,
            angle_spec=angle_spec,
            product_desc=product_desc,
            product_id=pid,
            provider_id=provider_id,
            model=model,
        )

    def _run_attempts(
        self,
        image_bytes: bytes,
        angle_spec: AngleSpec,
        product_desc: str,
        product_id: str,
        provider_id: str,
        model: str,
    ) -> AngleResult:
        """Execute up to max_attempts for one angle, with smart retry."""
        from psydox.ai_core.prompt_engine import PromptEngine, PromptContext
        from psydox.quality.engine       import AIQualityEngine
        from psydox.quality.fidelity     import FidelityEngine

        pe      = PromptEngine()
        qe      = AIQualityEngine()
        fe      = FidelityEngine()
        context = self._build_prompt_context(product_desc, angle_spec)
        prompt  = pe.build_angle(context, angle_spec.camera_description)

        total_cost = 0.0
        last_result: Optional[AngleResult] = None

        for attempt in range(1, self._policy.max_attempts_per_angle + 1):
            cost_inr = get_cost_inr(provider_id, model) or 0.0

            # Per-attempt cost guard
            cost_check = self._cost_guard.check_call(provider_id, model)
            if not cost_check.allowed:
                return AngleResult(
                    angle_id=angle_spec.angle_id,
                    display_name=angle_spec.display_name,
                    outcome="BUDGET_CONFLICT",
                    reason=cost_check.reason,
                    cost_inr=total_cost,
                    attempts=attempt - 1,
                )

            # Generate
            gen_result = self._call_provider(
                provider_id=provider_id,
                model=model,
                prompt_text=prompt.to_text(),
                reference_bytes=image_bytes,
            )
            total_cost += cost_inr

            if not gen_result.get("success"):
                last_result = AngleResult(
                    angle_id=angle_spec.angle_id,
                    display_name=angle_spec.display_name,
                    outcome="FAILED",
                    reason=gen_result.get("error", "Provider generation failed"),
                    cost_inr=total_cost,
                    attempts=attempt,
                    provider=provider_id,
                    model=model,
                )
                continue

            gen_bytes = gen_result["image_bytes"]

            # Quality check
            qs = qe.score(gen_bytes, image_bytes)

            # Fidelity check
            fs = fe.score(image_bytes, gen_bytes)

            # Angle validation (uses vision AI if available)
            vision_prov = self._get_vision_provider(provider_id)
            ar = self._angle_val.validate(gen_bytes, angle_spec, vision_prov, self._policy.angle_accuracy_threshold)

            # Decision
            decision = self._decision.decide(
                quality_score=qs,
                fidelity_score=fs,
                angle_result=ar,
                cost_inr=total_cost,
                quality_threshold=self._policy.quality_threshold,
                fidelity_threshold=self._policy.fidelity_threshold,
                angle_threshold=self._policy.angle_accuracy_threshold,
            )

            result = AngleResult(
                angle_id=angle_spec.angle_id,
                display_name=angle_spec.display_name,
                outcome=decision.outcome.value,
                image_bytes=gen_bytes,
                quality_score=qs.score,
                fidelity_score=fs.overall_score,
                angle_passed=(ar.verdict == "PASS"),
                cost_inr=total_cost,
                attempts=attempt,
                provider=provider_id,
                model=model,
                reason=decision.reason,
                validation_detail={
                    "quality":  qs.score,
                    "fidelity": round(fs.overall_score, 3),
                    "angle":    ar.to_dict(),
                },
            )

            if decision.outcome == DecisionOutcome.APPROVED:
                return result

            if decision.outcome == DecisionOutcome.HARD_FAIL:
                result.can_retry = False
                return result

            if decision.outcome == DecisionOutcome.REVIEW:
                return result

            # RETRY — build adjusted prompt for next attempt
            last_result = result
            if attempt < self._policy.max_attempts_per_angle:
                retry_ctx = RetryContext(
                    original_prompt=prompt,
                    retry_hint=decision.retry_hint,
                    attempt_number=attempt + 1,
                    product_desc=product_desc,
                    angle_desc=angle_spec.camera_description,
                    fidelity_warnings=fs.warnings if fs else [],
                )
                prompt = self._retry_eng.build_retry_prompt(retry_ctx)
                _log.info(
                    "SmartRetry: attempt %d/%d, hint=%s",
                    attempt + 1, self._policy.max_attempts_per_angle, decision.retry_hint,
                )

        # Exhausted all attempts
        if last_result:
            last_result.outcome = "REVIEW"
            last_result.reason  = f"Max attempts ({self._policy.max_attempts_per_angle}) exhausted. " + last_result.reason
            return last_result

        return AngleResult(
            angle_id=angle_spec.angle_id,
            display_name=angle_spec.display_name,
            outcome="FAILED",
            reason="No attempts completed.",
            cost_inr=total_cost,
            attempts=0,
        )

    # ── Multi-angle generation ────────────────────────────────────────────────

    def generate_angles(
        self,
        image_bytes: bytes,
        angle_ids: list[str],
        provider_id: str = "gemini",
        model: str = "",
        product_id: str = "",
    ) -> MultiAngleResult:
        """Generate multiple product angles for one image."""
        if not model:
            model = self._default_model(provider_id)

        pid           = product_id or self._image_hash(image_bytes)
        results       = []
        total_cost    = 0.0
        approved      = 0
        review        = 0
        failed        = 0

        for angle_id in angle_ids:
            # Check remaining batch budget before each angle
            cost_inr = get_cost_inr(provider_id, model) or 0.0
            budget_check = self._cost_guard.check_batch_budget(
                total_requested_angles=len(angle_ids),
                approved_so_far=approved,
                spent_inr=total_cost,
                next_call_cost_inr=cost_inr,
            )
            if not budget_check.allowed:
                angle_spec = get_angle(angle_id)
                results.append(AngleResult(
                    angle_id=angle_id,
                    display_name=angle_spec.display_name if angle_spec else angle_id,
                    outcome="BUDGET_CONFLICT",
                    reason=budget_check.reason,
                    cost_inr=0.0, attempts=0,
                ))
                failed += 1
                continue

            ar = self.generate_angle(image_bytes, angle_id, provider_id, model, pid)
            results.append(ar)
            total_cost += ar.cost_inr

            if ar.is_approved():
                approved += 1
            elif ar.outcome == "REVIEW":
                review += 1
            else:
                failed += 1

        return MultiAngleResult(
            product_id=pid,
            requested=len(angle_ids),
            approved=approved,
            review=review,
            failed=failed,
            total_cost_inr=total_cost,
            angle_results=results,
            is_complete=(approved == len(angle_ids)),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _call_provider(
        self,
        provider_id: str,
        model: str,
        prompt_text: str,
        reference_bytes: bytes,
    ) -> dict:
        """Call the AI provider via the existing provider registry."""
        try:
            from psydox.ai_core.provider_registry import get_provider_registry
            registry = get_provider_registry()
            provider = registry.get_provider(provider_id)

            if not provider:
                return {"success": False, "error": f"Provider '{provider_id}' not configured."}

            result = provider.generate(
                prompt=prompt_text,
                reference_bytes=reference_bytes,
                model=model or None,
            )
            if result.success and result.image_bytes:
                return {"success": True, "image_bytes": result.image_bytes,
                        "provider": result.provider, "model": result.model}
            return {"success": False, "error": result.error or "Provider returned no image."}

        except Exception as exc:
            _log.exception("Pipeline._call_provider failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def _get_vision_provider(self, provider_id: str):
        """Return vision provider if available (Gemini only currently)."""
        if provider_id != "gemini":
            return None
        try:
            from psydox.ai_core.router import build_router
            router = build_router()
            return router.get_vision_provider()
        except Exception:
            return None

    def _get_product_description(self, image_bytes: bytes, product_id: str) -> str:
        """Get product description from memory or run intelligence analysis."""
        try:
            from psydox.product.memory import get_product_memory
            mem     = get_product_memory()
            profile = mem.get_or_create(image_bytes)

            if not profile.attributes.get("overall_confidence", 0):
                mem.analyze_and_enrich(profile, image_bytes)

            attrs = profile.attributes
            parts = []
            if attrs.get("category"):
                parts.append(attrs["category"]["value"])
            if attrs.get("primary_color"):
                parts.append(attrs["primary_color"]["value"])
            if attrs.get("material"):
                parts.append(attrs["material"]["value"])
            if attrs.get("brand_text"):
                parts.append("with " + ", ".join(b["value"] for b in attrs["brand_text"][:2]))
            return " ".join(parts) if parts else "product"
        except Exception as exc:
            _log.debug("Could not get product description: %s", exc)
            return "product"

    def _build_prompt_context(self, product_desc: str, angle_spec: AngleSpec):
        from psydox.ai_core.prompt_engine import PromptContext
        return PromptContext(
            product_desc=product_desc,
            environment="pure white studio background",
            lighting="soft diffused studio lighting",
            camera_angle=angle_spec.camera_description,
            aspect_ratio="1:1",
            resolution="1024x1024",
        )

    def _default_model(self, provider_id: str) -> str:
        try:
            from psydox.ai_core.provider_registry import get_provider_registry
            info = get_provider_registry().get_info(provider_id)
            return info.default_model if info else ""
        except Exception:
            return ""

    @staticmethod
    def _image_hash(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()[:16]
