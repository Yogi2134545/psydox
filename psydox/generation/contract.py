"""
Psydox Generation Contract + Angle Specifications

A GenerationContract is created before every AI call.
It encodes the full specification: product, angle, quality requirements, budget.

AngleSpec defines each of the 8 standard angles with:
  - camera description (used in prompt)
  - validation keywords (used by AngleValidator)
  - display name
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Standard product angles ───────────────────────────────────────────────────

@dataclass(frozen=True)
class AngleSpec:
    angle_id:            str        # e.g. "FRONT", "FRONT_45"
    display_name:        str        # e.g. "Front View"
    camera_description:  str        # natural language for prompt
    validation_keywords: list[str]  # keywords expected in vision analysis
    is_45_degree:        bool = False

    def to_dict(self) -> dict:
        return {
            "angle_id":           self.angle_id,
            "display_name":       self.display_name,
            "camera_description": self.camera_description,
            "is_45_degree":       self.is_45_degree,
        }


ANGLES: dict[str, AngleSpec] = {
    "FRONT": AngleSpec(
        angle_id="FRONT",
        display_name="Front View",
        camera_description="straight front view, camera at product eye level, product centered",
        validation_keywords=["front", "facing", "forward", "direct"],
    ),
    "FRONT_45": AngleSpec(
        angle_id="FRONT_45",
        display_name="Front 45°",
        camera_description="front three-quarter view, camera 45 degrees to the left-front",
        validation_keywords=["front", "three-quarter", "45", "angle", "diagonal"],
        is_45_degree=True,
    ),
    "LEFT": AngleSpec(
        angle_id="LEFT",
        display_name="Left Side View",
        camera_description="left side profile view, camera perpendicular to the left side",
        validation_keywords=["left", "side", "profile", "lateral"],
    ),
    "LEFT_45": AngleSpec(
        angle_id="LEFT_45",
        display_name="Left 45°",
        camera_description="left rear three-quarter view, camera 45 degrees to the left-rear",
        validation_keywords=["left", "rear", "three-quarter", "45"],
        is_45_degree=True,
    ),
    "RIGHT": AngleSpec(
        angle_id="RIGHT",
        display_name="Right Side View",
        camera_description="right side profile view, camera perpendicular to the right side",
        validation_keywords=["right", "side", "profile", "lateral"],
    ),
    "RIGHT_45": AngleSpec(
        angle_id="RIGHT_45",
        display_name="Right 45°",
        camera_description="right rear three-quarter view, camera 45 degrees to the right-rear",
        validation_keywords=["right", "rear", "three-quarter", "45"],
        is_45_degree=True,
    ),
    "BACK": AngleSpec(
        angle_id="BACK",
        display_name="Back View",
        camera_description="straight back/rear view, camera directly behind the product",
        validation_keywords=["back", "rear", "behind", "reverse"],
    ),
    "BACK_45": AngleSpec(
        angle_id="BACK_45",
        display_name="Back 45°",
        camera_description="rear three-quarter view, camera 45 degrees to the rear",
        validation_keywords=["back", "rear", "three-quarter", "45"],
        is_45_degree=True,
    ),
}


def get_angle(angle_id: str) -> Optional[AngleSpec]:
    return ANGLES.get(angle_id.upper())


def list_angles() -> list[AngleSpec]:
    return list(ANGLES.values())


# ── Generation Contract ───────────────────────────────────────────────────────

@dataclass
class GenerationContract:
    """
    Full specification for one AI generation attempt.
    Created before every API call — never modified after creation.
    """
    product_id:          str
    product_description: str
    angle_spec:          AngleSpec
    provider_id:         str    = "gemini"
    model:               str    = ""
    background_type:     str    = "pure white studio"
    lighting:            str    = "soft diffused studio lighting"
    quality_threshold:   int    = 85
    fidelity_threshold:  float  = 0.65
    angle_threshold:     float  = 0.70
    max_cost_inr:        float  = 0.50
    max_attempts:        int    = 2
    attempt_number:      int    = 1
    resolution:          str    = "1024x1024"
    retry_reason:        str    = ""  # set on retries to strengthen prompt

    def to_dict(self) -> dict:
        return {
            "product_id":          self.product_id,
            "product_description": self.product_description,
            "angle_id":            self.angle_spec.angle_id,
            "provider_id":         self.provider_id,
            "model":               self.model,
            "background_type":     self.background_type,
            "quality_threshold":   self.quality_threshold,
            "fidelity_threshold":  self.fidelity_threshold,
            "max_cost_inr":        self.max_cost_inr,
            "attempt_number":      self.attempt_number,
            "resolution":          self.resolution,
        }
