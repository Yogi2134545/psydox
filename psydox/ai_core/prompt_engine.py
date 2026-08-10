"""
Psydox AI Core — Prompt Engine

Prompts are structured objects, not concatenated strings.
Build prompts from context → convert to provider-specific text.
Versioning ensures every generation can be reproduced.
"""
import json
import hashlib
from dataclasses import dataclass, field
from typing import Optional


# ── Structured prompt ─────────────────────────────────────────────────────────

@dataclass
class StructuredPrompt:
    """
    Provider-independent prompt representation.
    All fields are optional — only set what's relevant.
    """
    subject:       str = ""           # what is being photographed
    environment:   str = ""           # where (studio, beach, etc.)
    lighting:      str = ""           # lighting description
    camera:        str = ""           # camera angle/lens
    composition:   str = ""           # compositional instruction
    style:         str = ""           # overall aesthetic
    output_format: str = ""           # aspect ratio / resolution
    constraints:   list = field(default_factory=list)   # things that MUST be preserved
    negatives:     list = field(default_factory=list)   # things to AVOID
    fidelity_lock: dict = field(default_factory=dict)   # locked product attributes

    # Versioning
    template_id:   str = ""
    version:       str = "1.0"

    def to_text(self) -> str:
        """
        Convert to a provider-compatible prompt string.
        Constraints and negatives are appended as emphatic clauses.
        """
        parts = []

        if self.subject:
            parts.append(self.subject)
        if self.environment:
            parts.append(f"Setting: {self.environment}.")
        if self.lighting:
            parts.append(f"Lighting: {self.lighting}.")
        if self.camera:
            parts.append(f"Camera: {self.camera}.")
        if self.composition:
            parts.append(f"Composition: {self.composition}.")
        if self.style:
            parts.append(f"Style: {self.style}.")
        if self.output_format:
            parts.append(self.output_format)

        if self.constraints:
            parts.append(
                "CRITICAL — preserve exactly: " + "; ".join(self.constraints) + "."
            )

        if self.fidelity_lock:
            lock_parts = [f"{k}={v}" for k, v in self.fidelity_lock.items()]
            parts.append(
                "LOCKED product attributes (do NOT change): "
                + ", ".join(lock_parts) + "."
            )

        if self.negatives:
            parts.append("AVOID: " + ", ".join(self.negatives) + ".")

        return " ".join(p for p in parts if p)

    def fingerprint(self) -> str:
        """SHA256 fingerprint for caching / deduplication."""
        content = json.dumps(self.__dict__, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# ── Templates ─────────────────────────────────────────────────────────────────

@dataclass
class PromptTemplate:
    """
    Reusable template for a specific generation task.
    Templates are versioned so prompt changes are tracked.
    """
    id:        str
    version:   str
    build:     callable  # (context: dict) -> StructuredPrompt


# ── Context ───────────────────────────────────────────────────────────────────

@dataclass
class PromptContext:
    """Input context for prompt construction."""
    product_desc:       str = ""
    product_type:       str = ""
    product_colors:     list = field(default_factory=list)
    product_pattern:    str = ""
    product_brand:      list = field(default_factory=list)
    product_features:   list = field(default_factory=list)
    target_platform:    str = ""
    style:              str = ""
    environment:        str = ""
    lighting:           str = ""
    camera_angle:       str = ""
    aspect_ratio:       str = ""
    resolution:         str = ""
    custom_instructions: str = ""
    brand_profile:      dict = field(default_factory=dict)


# ── Engine ────────────────────────────────────────────────────────────────────

class PromptEngine:
    """
    Central prompt construction service.
    Build prompts from PromptContext using registered templates.
    """

    _QUALITY_SUFFIX = (
        "Ultra-high resolution, photorealistic, commercial product photography quality, "
        "shot on a professional medium-format camera, 8K."
    )

    def build_background(self, ctx: PromptContext) -> StructuredPrompt:
        constraints = self._base_constraints(ctx)
        return StructuredPrompt(
            subject=f"Professional product photography of {ctx.product_desc or 'a product'}",
            environment=ctx.environment or "clean studio background",
            lighting=ctx.lighting or "soft diffused studio lighting",
            camera="eye level, product centered, filling 80% of frame",
            style=ctx.style or "clean, minimal, e-commerce",
            output_format=self._ratio_clause(ctx),
            constraints=constraints,
            negatives=["text overlay", "watermark", "people", "extra products"],
            template_id="background_v1",
            version="1.0",
        )

    def build_lifestyle(self, ctx: PromptContext) -> StructuredPrompt:
        constraints = self._base_constraints(ctx)
        constraints.append("product visible and prominent in frame")
        return StructuredPrompt(
            subject=f"Product lifestyle photography featuring {ctx.product_desc or 'the product'}",
            environment=ctx.environment or "authentic lifestyle setting",
            lighting=ctx.lighting or "natural, cinematic",
            camera="medium shot, slightly elevated angle",
            style=ctx.style or "candid lifestyle, authentic",
            output_format=self._ratio_clause(ctx),
            constraints=constraints,
            negatives=["studio backdrop", "artificial look"],
            template_id="lifestyle_v1",
            version="1.0",
        )

    def build_model(self, ctx: PromptContext) -> StructuredPrompt:
        constraints = self._base_constraints(ctx)
        constraints.append("product worn/held exactly as in reference — no substitutions")
        return StructuredPrompt(
            subject=f"Fashion model wearing/using {ctx.product_desc or 'the product'}",
            environment=ctx.environment or "clean studio or lifestyle background",
            lighting=ctx.lighting or "professional fashion lighting",
            camera="3/4 shot, slightly elevated",
            style=ctx.style or "commercial fashion catalog",
            output_format=self._ratio_clause(ctx),
            constraints=constraints,
            negatives=["product color change", "wrong product", "mannequin"],
            template_id="model_v1",
            version="1.0",
        )

    def build_angle(self, ctx: PromptContext, angle_desc: str) -> StructuredPrompt:
        constraints = self._base_constraints(ctx)
        constraints.append("only camera angle changes — product identical to reference")
        return StructuredPrompt(
            subject=f"Photorealistic product photo of {ctx.product_desc or 'the product'}",
            environment="pure white studio background (#FFFFFF)",
            lighting="soft diffused studio lighting, natural drop shadow",
            camera=angle_desc,
            style="commercial product photography, e-commerce",
            output_format=self._ratio_clause(ctx),
            constraints=constraints,
            negatives=["props", "reflections", "background elements", "color shift"],
            template_id="angle_v1",
            version="1.0",
        )

    def build_scene(self, ctx: PromptContext) -> StructuredPrompt:
        constraints = self._base_constraints(ctx)
        return StructuredPrompt(
            subject=f"Product scene composition featuring {ctx.product_desc or 'the product'}",
            environment=ctx.environment or "styled scene",
            lighting=ctx.lighting or "professional product lighting",
            camera=ctx.camera_angle or "hero angle",
            style=ctx.style or "editorial product scene",
            output_format=self._ratio_clause(ctx),
            constraints=constraints,
            template_id="scene_v1",
            version="1.0",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _base_constraints(self, ctx: PromptContext) -> list[str]:
        constraints = []
        if ctx.product_desc:
            constraints.append(f"this exact {ctx.product_desc}")
        if ctx.product_colors:
            constraints.append(f"colors: {', '.join(ctx.product_colors)}")
        if ctx.product_pattern and ctx.product_pattern not in ("solid", "other", ""):
            constraints.append(f"pattern: {ctx.product_pattern}")
        if ctx.product_brand:
            constraints.append(f"branding: {', '.join(ctx.product_brand)} — reproduce exactly")
        return constraints

    def _ratio_clause(self, ctx: PromptContext) -> str:
        if ctx.aspect_ratio and ctx.resolution:
            return f"Aspect ratio {ctx.aspect_ratio}. Resolution {ctx.resolution}."
        if ctx.aspect_ratio:
            return f"Aspect ratio {ctx.aspect_ratio}."
        return ""

    def from_context(self, task: str, ctx: PromptContext) -> StructuredPrompt:
        """Build a prompt for any task by name."""
        builders = {
            "background": self.build_background,
            "lifestyle":  self.build_lifestyle,
            "model":      self.build_model,
            "scene":      self.build_scene,
        }
        build_fn = builders.get(task, self.build_background)
        return build_fn(ctx)
