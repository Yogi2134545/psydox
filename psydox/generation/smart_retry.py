"""
Psydox Smart Retry Engine

When a generation fails, do NOT simply re-run the same prompt.
Diagnose the failure and strengthen the specific instruction that failed.

Failure → hint → adjusted StructuredPrompt

Retry hints:
  "quality"   → simplify background, change model if possible
  "fidelity"  → add stronger product-lock constraints
  "angle"     → reinforce camera/angle specification
  "cost"      → should not retry (blocked by CostGuard)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from psydox.ai_core.prompt_engine import StructuredPrompt

_log = logging.getLogger("psydox.generation.smart_retry")


@dataclass
class RetryContext:
    original_prompt:  StructuredPrompt
    retry_hint:       str    # "quality" | "fidelity" | "angle"
    attempt_number:   int    = 2
    product_desc:     str    = ""
    angle_desc:       str    = ""
    fidelity_warnings: list  = None   # type: ignore

    def __post_init__(self):
        if self.fidelity_warnings is None:
            self.fidelity_warnings = []


class SmartRetryEngine:
    """
    Builds a modified prompt for a retry attempt.
    Each retry has a specific reason — not a blind re-run.
    """

    def build_retry_prompt(self, ctx: RetryContext) -> StructuredPrompt:
        hint = ctx.retry_hint.lower()

        if hint == "quality":
            return self._strengthen_quality(ctx)
        if hint == "fidelity":
            return self._strengthen_fidelity(ctx)
        if hint == "angle":
            return self._strengthen_angle(ctx)

        # Unknown hint — strengthen everything
        return self._strengthen_all(ctx)

    # ── Specific strengthening strategies ─────────────────────────────────────

    def _strengthen_quality(self, ctx: RetryContext) -> StructuredPrompt:
        """Quality failure: simplify background, use quality-focused suffix."""
        p = ctx.original_prompt
        _log.info("SmartRetry: strengthening quality for attempt %d", ctx.attempt_number)
        return StructuredPrompt(
            subject     = p.subject,
            environment = "pure white studio background (#FFFFFF), no gradients",
            lighting    = "soft even studio lighting, avoid harsh shadows",
            camera      = p.camera,
            composition = "product perfectly centered, sharp focus, clean edges",
            style       = "ultra-sharp commercial product photography, 8K detail",
            output_format = p.output_format,
            constraints = p.constraints + [
                "maximum sharpness and clarity",
                "no blur, no artifacts, no distortion",
            ],
            negatives   = p.negatives + ["blurry", "overexposed", "underexposed", "artifacts"],
            fidelity_lock = p.fidelity_lock,
            template_id = p.template_id,
            version     = f"{p.version}-quality-retry",
        )

    def _strengthen_fidelity(self, ctx: RetryContext) -> StructuredPrompt:
        """Fidelity failure: add hard product-lock constraints."""
        p = ctx.original_prompt
        _log.info("SmartRetry: strengthening fidelity for attempt %d", ctx.attempt_number)

        extra = [
            "CRITICAL: do NOT change any product property",
            "preserve EXACT product color, shape, logo, brand text",
            "only background changes — product must be pixel-perfect identical",
        ]
        if ctx.fidelity_warnings:
            for w in ctx.fidelity_warnings[:2]:
                if "color" in w.lower():
                    extra.append("color must remain UNCHANGED from reference")
                if "shape" in w.lower():
                    extra.append("product shape and silhouette must match reference exactly")

        return StructuredPrompt(
            subject     = p.subject,
            environment = p.environment,
            lighting    = p.lighting,
            camera      = p.camera,
            composition = p.composition,
            style       = p.style,
            output_format = p.output_format,
            constraints = p.constraints + extra,
            negatives   = p.negatives + ["different product", "color change", "shape change"],
            fidelity_lock = p.fidelity_lock,
            template_id = p.template_id,
            version     = f"{p.version}-fidelity-retry",
        )

    def _strengthen_angle(self, ctx: RetryContext) -> StructuredPrompt:
        """Angle failure: reinforce camera/angle instructions."""
        p = ctx.original_prompt
        _log.info("SmartRetry: strengthening angle for attempt %d", ctx.attempt_number)

        camera_instruction = p.camera
        if ctx.angle_desc:
            camera_instruction = (
                f"EXACTLY: {ctx.angle_desc}. "
                "The camera angle is the PRIMARY requirement of this image."
            )

        return StructuredPrompt(
            subject     = p.subject,
            environment = p.environment,
            lighting    = p.lighting,
            camera      = camera_instruction,
            composition = "product fully visible from the EXACT angle specified",
            style       = p.style,
            output_format = p.output_format,
            constraints = p.constraints + [
                f"camera angle MUST be: {ctx.angle_desc or 'as specified'}",
                "do not substitute a different viewpoint",
            ],
            negatives   = p.negatives + ["wrong angle", "incorrect viewpoint"],
            fidelity_lock = p.fidelity_lock,
            template_id = p.template_id,
            version     = f"{p.version}-angle-retry",
        )

    def _strengthen_all(self, ctx: RetryContext) -> StructuredPrompt:
        p = ctx.original_prompt
        return StructuredPrompt(
            subject     = p.subject,
            environment = "pure white studio, no distractions",
            lighting    = "perfect soft studio lighting",
            camera      = p.camera,
            composition = "product perfectly centered and sharp",
            style       = "professional commercial product photography",
            output_format = p.output_format,
            constraints = p.constraints + ["preserve ALL product properties exactly"],
            negatives   = p.negatives + ["anything that changes the product"],
            fidelity_lock = p.fidelity_lock,
            template_id = p.template_id,
            version     = f"{p.version}-full-retry",
        )
