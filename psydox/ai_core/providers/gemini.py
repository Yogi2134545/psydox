"""
Psydox AI Core — Gemini Provider

Wraps the existing GeminiClient (nano_banana/api_client.py) through the
provider interface. The rest of the AI Core knows nothing about Gemini internals.
"""
import time
import logging
from .base import ImageGenerationProvider, VisionProvider, ProviderResult, ProviderCapability

_log = logging.getLogger("psydox.ai_core.gemini")


class GeminiImageProvider(ImageGenerationProvider):
    """Gemini image generation via google-genai SDK."""

    _COST_PER_IMAGE = 0.04

    def __init__(self):
        self._client = None
        self._init_client()

    def _init_client(self):
        try:
            from nano_banana.api_client import GeminiClient
            self._client = GeminiClient()
        except Exception as e:
            _log.warning("GeminiImageProvider: could not init client: %s", e)
            self._client = None

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def capabilities(self) -> list[ProviderCapability]:
        return [ProviderCapability.IMAGE_GENERATION, ProviderCapability.IMAGE_EDITING]

    def is_available(self) -> bool:
        if not self._client:
            return False
        return bool(self._client.api_key) and self._client._sdk_ok

    def generate(
        self,
        prompt: str,
        reference_bytes: bytes | None = None,
        model: str | None = None,
        **kwargs,
    ) -> ProviderResult:
        if not self._client:
            return ProviderResult(
                success=False, provider=self.name,
                error="Gemini client not initialized. Check GOOGLE_API_KEY.",
            )

        t0 = time.monotonic()
        try:
            img_bytes = self._client.generate_image(prompt, reference_image_bytes=reference_bytes)
            latency = int((time.monotonic() - t0) * 1000)
            model_used = self._client._active_model or "unknown"
            return ProviderResult(
                success=True,
                image_bytes=img_bytes,
                provider=self.name,
                model=model_used,
                latency_ms=latency,
                cost_estimate=self._COST_PER_IMAGE,
                retry_count=self._client._perf.get("retries", 0),
            )
        except Exception as e:
            latency = int((time.monotonic() - t0) * 1000)
            return ProviderResult(
                success=False,
                provider=self.name,
                latency_ms=latency,
                error=str(e),
            )

    def estimate_cost(self, prompt: str, reference_bytes: bytes | None = None) -> float:
        return self._COST_PER_IMAGE


class GeminiVisionProvider(VisionProvider):
    """Gemini vision analysis via google-genai SDK (text model, no image output)."""

    _COST_PER_ANALYSIS = 0.0001  # negligible

    def __init__(self):
        self._client = None
        self._init_client()

    def _init_client(self):
        try:
            from nano_banana.api_client import GeminiClient
            self._client = GeminiClient()
        except Exception as e:
            _log.warning("GeminiVisionProvider: could not init client: %s", e)
            self._client = None

    @property
    def name(self) -> str:
        return "gemini_vision"

    def is_available(self) -> bool:
        if not self._client:
            return False
        return bool(self._client.api_key) and self._client._sdk_ok

    def analyze(
        self,
        image_bytes: bytes,
        prompt: str,
        model: str | None = None,
    ) -> ProviderResult:
        if not self._client or not self.is_available():
            return ProviderResult(
                success=False, provider=self.name,
                error="Gemini vision provider not available.",
            )

        t0 = time.monotonic()
        try:
            import io
            from PIL import Image as _PIL
            from psydox.core.config import get_config
            cfg = get_config()
            text_model = model or cfg.ai_text_model

            pil_img = _PIL.open(io.BytesIO(image_bytes)).convert("RGB")
            response = self._client._sdk.models.generate_content(
                model=text_model,
                contents=[pil_img, prompt],
            )
            text = ""
            for candidate in (response.candidates or []):
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        text += part.text

            return ProviderResult(
                success=True,
                text=text.strip(),
                provider=self.name,
                model=text_model,
                latency_ms=int((time.monotonic() - t0) * 1000),
                cost_estimate=self._COST_PER_ANALYSIS,
            )
        except Exception as e:
            return ProviderResult(
                success=False, provider=self.name,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(e),
            )
