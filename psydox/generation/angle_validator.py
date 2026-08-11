"""
Psydox Angle Validator

Checks whether a generated image matches the requested angle.

Two modes:
  1. Vision AI available → ask provider to classify the angle
  2. No vision AI → return APPROXIMATION verdict (never hard-fail on angle alone)

An angle FAIL means:
  - Vision AI says the angle doesn't match AND confidence is high
  - Example: asked BACK, got FRONT
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .contract import AngleSpec

_log = logging.getLogger("psydox.generation.angle_validator")

_ANGLE_PROMPT_TEMPLATE = """You are a product photography expert.
I will show you a product image.
Tell me: from which angle is this product photographed?

Choose ONE of these angles:
- FRONT: straight front view
- FRONT_45: front three-quarter view (45 degrees)
- LEFT: left side profile
- LEFT_45: left rear three-quarter view
- RIGHT: right side profile
- RIGHT_45: right rear three-quarter view
- BACK: straight rear view
- BACK_45: rear three-quarter view

Respond with JSON only:
{
  "detected_angle": "FRONT",
  "confidence": 0.85,
  "description": "The product faces directly toward the camera"
}

Confidence: 0.0 = complete uncertainty, 1.0 = certain.
Return ONLY valid JSON, no commentary."""


@dataclass
class AngleValidationResult:
    passed:          bool
    detected_angle:  str   = ""
    requested_angle: str   = ""
    confidence:      float = 0.0
    verdict:         str   = ""   # "PASS" | "FAIL" | "REVIEW" | "APPROXIMATION"
    reason:          str   = ""
    used_vision_ai:  bool  = False

    def to_dict(self) -> dict:
        return {
            "passed":          self.passed,
            "detected_angle":  self.detected_angle,
            "requested_angle": self.requested_angle,
            "confidence":      round(self.confidence, 3),
            "verdict":         self.verdict,
            "reason":          self.reason,
            "used_vision_ai":  self.used_vision_ai,
        }


class AngleValidator:
    """
    Validates that a generated image shows the requested product angle.
    Never raises — returns AngleValidationResult with appropriate verdict.
    """

    def validate(
        self,
        generated_bytes: bytes,
        angle_spec: AngleSpec,
        vision_provider=None,       # Optional VisionProvider
        threshold: float = 0.70,
    ) -> AngleValidationResult:
        """
        Validate that generated_bytes shows the angle described by angle_spec.

        If vision_provider is available: use AI to classify angle.
        If not: return APPROXIMATION (never hard-fail without AI confirmation).
        """
        if not generated_bytes:
            return AngleValidationResult(
                passed=False,
                requested_angle=angle_spec.angle_id,
                verdict="FAIL",
                reason="No image bytes to validate.",
            )

        if vision_provider and vision_provider.is_available():
            return self._validate_with_vision(generated_bytes, angle_spec, vision_provider, threshold)

        return self._validate_without_vision(angle_spec)

    def _validate_with_vision(
        self,
        generated_bytes: bytes,
        angle_spec: AngleSpec,
        vision_provider,
        threshold: float,
    ) -> AngleValidationResult:
        import json
        import re

        try:
            result = vision_provider.analyze(generated_bytes, _ANGLE_PROMPT_TEMPLATE)

            # Handle both ProviderResult and raw string returns
            text = getattr(result, "text", None) or (result if isinstance(result, str) else "")
            if not text:
                raise ValueError("Empty vision response")

            # Parse JSON
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                m = re.search(r'\{.*\}', text, re.DOTALL)
                data = json.loads(m.group()) if m else {}

            detected = str(data.get("detected_angle", "")).upper()
            confidence = float(data.get("confidence", 0.0))
            description = str(data.get("description", ""))

            requested = angle_spec.angle_id
            matches = (detected == requested)

            if matches and confidence >= threshold:
                return AngleValidationResult(
                    passed=True,
                    detected_angle=detected,
                    requested_angle=requested,
                    confidence=confidence,
                    verdict="PASS",
                    reason=f"Angle {detected} detected with confidence {confidence:.2f}.",
                    used_vision_ai=True,
                )

            if not matches and confidence >= threshold:
                return AngleValidationResult(
                    passed=False,
                    detected_angle=detected,
                    requested_angle=requested,
                    confidence=confidence,
                    verdict="FAIL",
                    reason=f"Expected {requested}, detected {detected} (confidence {confidence:.2f}).",
                    used_vision_ai=True,
                )

            # Low confidence — send to REVIEW
            return AngleValidationResult(
                passed=False,
                detected_angle=detected or "UNKNOWN",
                requested_angle=requested,
                confidence=confidence,
                verdict="REVIEW",
                reason=f"Angle detection low confidence ({confidence:.2f}) — manual review needed.",
                used_vision_ai=True,
            )

        except Exception as exc:
            _log.warning("AngleValidator vision check failed: %s", exc)
            return self._validate_without_vision(angle_spec)

    def _validate_without_vision(self, angle_spec: AngleSpec) -> AngleValidationResult:
        """No vision provider — cannot verify angle algorithmically."""
        return AngleValidationResult(
            passed=False,
            requested_angle=angle_spec.angle_id,
            detected_angle="UNKNOWN",
            confidence=0.0,
            verdict="APPROXIMATION",
            reason="No vision provider — angle cannot be verified automatically. Manual review recommended.",
            used_vision_ai=False,
        )
