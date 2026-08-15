"""
Psydox AI Core — AI Model Router

Decides WHICH provider and model to use for a given task.
This prevents every feature from blindly using the most expensive model.

Routing considers: task type, quality requirement, cost, provider availability.
"""
import os
import logging
from enum import Enum
from typing import Optional

from .providers.base import ImageGenerationProvider, VisionProvider

_log = logging.getLogger("psydox.ai_core.router")


class TaskType(str, Enum):
    # Deterministic — no AI needed
    SOLID_BACKGROUND  = "solid_background"
    GRADIENT          = "gradient"
    RESIZE            = "resize"
    ENHANCE_CLASSIC   = "enhance_classic"

    # AI generation
    CREATIVE_BACKGROUND = "creative_background"
    LIFESTYLE           = "lifestyle"
    MODEL_GENERATION    = "model_generation"
    SCENE_GENERATION    = "scene_generation"
    ANGLE_GENERATION    = "angle_generation"
    LIGHTING_AI         = "lighting_ai"
    SHADOW_AI           = "shadow_ai"
    CREATIVE_EDIT       = "creative_edit"

    # Vision analysis
    PRODUCT_ANALYSIS  = "product_analysis"
    QUALITY_ANALYSIS  = "quality_analysis"


class TaskRequirement(str, Enum):
    DETERMINISTIC = "deterministic"  # no AI call
    FAST_AI       = "fast_ai"
    STANDARD_AI   = "standard_ai"
    PREMIUM_AI    = "premium_ai"


# Routing table: task → requirement
_ROUTING: dict[TaskType, TaskRequirement] = {
    TaskType.SOLID_BACKGROUND:    TaskRequirement.DETERMINISTIC,
    TaskType.GRADIENT:            TaskRequirement.DETERMINISTIC,
    TaskType.RESIZE:              TaskRequirement.DETERMINISTIC,
    TaskType.ENHANCE_CLASSIC:     TaskRequirement.DETERMINISTIC,
    TaskType.PRODUCT_ANALYSIS:    TaskRequirement.FAST_AI,
    TaskType.QUALITY_ANALYSIS:    TaskRequirement.FAST_AI,
    TaskType.LIGHTING_AI:         TaskRequirement.FAST_AI,
    TaskType.SHADOW_AI:           TaskRequirement.FAST_AI,
    TaskType.CREATIVE_BACKGROUND: TaskRequirement.STANDARD_AI,
    TaskType.ANGLE_GENERATION:    TaskRequirement.STANDARD_AI,
    TaskType.SCENE_GENERATION:    TaskRequirement.STANDARD_AI,
    TaskType.CREATIVE_EDIT:       TaskRequirement.STANDARD_AI,
    TaskType.LIFESTYLE:           TaskRequirement.PREMIUM_AI,
    TaskType.MODEL_GENERATION:    TaskRequirement.PREMIUM_AI,
}


class AIModelRouter:
    """
    Routes tasks to the appropriate provider.
    Supports primary provider + fallback provider.
    """

    def __init__(
        self,
        image_provider: ImageGenerationProvider | None = None,
        vision_provider: VisionProvider | None = None,
        fallback_image: ImageGenerationProvider | None = None,
    ):
        self._image    = image_provider
        self._vision   = vision_provider
        self._fallback = fallback_image

    def is_deterministic(self, task: TaskType) -> bool:
        return _ROUTING.get(task) == TaskRequirement.DETERMINISTIC

    def get_image_provider(self, task: TaskType) -> Optional[ImageGenerationProvider]:
        """Return the best available image provider for this task."""
        req = _ROUTING.get(task, TaskRequirement.STANDARD_AI)

        if req == TaskRequirement.DETERMINISTIC:
            return None  # signal: use classic processing

        if self._image and self._image.is_available():
            return self._image

        if self._fallback and self._fallback.is_available():
            _log.info("Primary provider unavailable — using fallback for task=%s", task)
            return self._fallback

        _log.warning("No image provider available for task=%s", task)
        return None

    def get_vision_provider(self) -> Optional[VisionProvider]:
        """Return the vision analysis provider."""
        if self._vision and self._vision.is_available():
            return self._vision
        return None

    def can_handle(self, task: TaskType) -> bool:
        """Return True if this task can be executed (deterministic OR provider available)."""
        if self.is_deterministic(task):
            return True
        return self.get_image_provider(task) is not None

    def explain(self, task: TaskType) -> str:
        req = _ROUTING.get(task, TaskRequirement.STANDARD_AI)
        if req == TaskRequirement.DETERMINISTIC:
            return f"⚡ Classic (instant, no AI cost)"
        prov = self.get_image_provider(task)
        if prov:
            return f"✨ AI via {prov.name} ({req.value})"
        return f"✗ Not available (no provider configured)"


def build_router() -> AIModelRouter:
    """Build the default router using all configured providers via ProviderRegistry.

    Delegates to ProviderRegistry.build_router() so that any configured provider
    (Gemini, Ideogram, OpenAI, etc.) is used — not just Gemini.
    """
    from .provider_registry import get_provider_registry
    return get_provider_registry().build_router()
