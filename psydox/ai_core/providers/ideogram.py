"""
Psydox AI Core — Ideogram Provider

Wraps jadu_ka_ghar.client.IdeogramClient as a Psydox ImageGenerationProvider
so it appears in the provider selector alongside Gemini/OpenAI/etc.

Capability mapped: IMAGE_GENERATION (remix) + BACKGROUND_REMOVAL.
"""
from __future__ import annotations

import logging

from ..providers.base import (
    ImageGenerationProvider,
    ProviderCapability,
    ProviderResult,
)

_log = logging.getLogger("psydox.ai_core.providers.ideogram")


class IdeogramImageProvider(ImageGenerationProvider):
    """Ideogram V3 via jadu_ka_ghar client — remix mode as primary generate."""

    def __init__(self):
        from jadu_ka_ghar.client import IdeogramClient
        self._client = IdeogramClient()

    @property
    def name(self) -> str:
        return "ideogram"

    @property
    def capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability.IMAGE_GENERATION,
            ProviderCapability.IMAGE_EDITING,
            ProviderCapability.BACKGROUND_REMOVAL,
        ]

    def is_available(self) -> bool:
        return self._client.is_available()

    def generate(
        self,
        prompt: str,
        reference_bytes: bytes | None = None,
        model: str | None = None,
        **kwargs,
    ) -> ProviderResult:
        """
        Generate an image. When reference_bytes is provided, uses V3 remix
        (preferred for product shots). Otherwise uses V3 generate.
        """
        import time
        t0 = time.time()
        try:
            if reference_bytes:
                result_bytes = self._client.remix(
                    image_bytes=reference_bytes,
                    prompt=prompt,
                    style_type=kwargs.get("style_type", "GENERAL"),
                    aspect_ratio=kwargs.get("aspect_ratio", "AUTO"),
                    magic_prompt=kwargs.get("magic_prompt", "AUTO"),
                    image_weight=int(kwargs.get("image_weight", 50)),
                    rendering_speed=kwargs.get("rendering_speed", "STANDARD"),
                )
            else:
                result_bytes = self._client.generate(
                    prompt=prompt,
                    style_type=kwargs.get("style_type", "REALISTIC"),
                    style_preset=kwargs.get("style_preset", "PRODUCT_PHOTOGRAPHY"),
                    aspect_ratio=kwargs.get("aspect_ratio", "1x1"),
                    magic_prompt=kwargs.get("magic_prompt", "AUTO"),
                    rendering_speed=kwargs.get("rendering_speed", "STANDARD"),
                )
            return ProviderResult(
                success=True,
                image_bytes=result_bytes,
                model="ideogram-v3",
                provider=self.name,
                latency_ms=int((time.time() - t0) * 1000),
            )
        except RuntimeError as e:
            _log.warning("IdeogramImageProvider.generate failed: %s", e)
            return ProviderResult(
                success=False,
                model="ideogram-v3",
                provider=self.name,
                latency_ms=int((time.time() - t0) * 1000),
                error=str(e),
            )
        except Exception as e:
            _log.exception("IdeogramImageProvider.generate unexpected error")
            return ProviderResult(
                success=False,
                model="ideogram-v3",
                provider=self.name,
                latency_ms=int((time.time() - t0) * 1000),
                error=f"Unexpected error: {e}",
            )

    def estimate_cost(self, prompt: str, reference_bytes: bytes | None = None) -> float:
        return 0.08  # ~₹7 per generation — Ideogram V3 standard speed
