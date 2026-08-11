"""
Psydox AI Core — OpenAI Provider

Supports DALL-E 3 image generation.
Requires: OPENAI_API_KEY environment variable.
Optionally uses the openai Python package; falls back to raw HTTP if unavailable.
"""
import io
import os
import time
import logging
from .base import ImageGenerationProvider, ProviderResult, ProviderCapability

_log = logging.getLogger("psydox.ai_core.openai_provider")

_DEFAULT_MODEL = "dall-e-3"
_COST_PER_IMAGE = 0.040  # DALL-E 3 standard 1024×1024


class OpenAIImageProvider(ImageGenerationProvider):
    """DALL-E 3 image generation via OpenAI API."""

    def __init__(self, model: str = _DEFAULT_MODEL):
        self._model  = model
        self._api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    @property
    def name(self) -> str:
        return "openai"

    @property
    def capabilities(self) -> list[ProviderCapability]:
        return [ProviderCapability.IMAGE_GENERATION]

    def is_available(self) -> bool:
        return bool(self._api_key)

    def generate(
        self,
        prompt: str,
        reference_bytes: bytes | None = None,
        model: str | None = None,
        **kwargs,
    ) -> ProviderResult:
        if not self._api_key:
            return ProviderResult(
                success=False, provider=self.name,
                error="OPENAI_API_KEY is not configured.",
            )

        model_used = model or self._model
        t0 = time.monotonic()

        try:
            img_bytes = self._call_api(prompt, model_used)
            latency = int((time.monotonic() - t0) * 1000)
            return ProviderResult(
                success=True,
                image_bytes=img_bytes,
                provider=self.name,
                model=model_used,
                latency_ms=latency,
                cost_estimate=self._COST_PER_IMAGE,
            )
        except Exception as e:
            latency = int((time.monotonic() - t0) * 1000)
            _log.warning("OpenAI generation failed: %s", e)
            return ProviderResult(
                success=False, provider=self.name,
                model=model_used, latency_ms=latency, error=str(e),
            )

    def _call_api(self, prompt: str, model: str) -> bytes:
        """Call OpenAI Images API — tries openai SDK, falls back to requests."""
        try:
            import openai
            client = openai.OpenAI(api_key=self._api_key)
            response = client.images.generate(
                model=model, prompt=prompt,
                n=1, size="1024x1024", response_format="b64_json",
            )
            import base64
            b64 = response.data[0].b64_json
            return base64.b64decode(b64)
        except ImportError:
            pass  # fall through to HTTP

        import requests, base64
        payload = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
            "response_format": "b64_json",
        }
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"},
            json=payload, timeout=90,
        )
        resp.raise_for_status()
        b64 = resp.json()["data"][0]["b64_json"]
        return base64.b64decode(b64)

    def estimate_cost(self, prompt: str, reference_bytes: bytes | None = None) -> float:
        return self._COST_PER_IMAGE
