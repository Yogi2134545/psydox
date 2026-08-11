"""
Psydox AI Core — Stability AI Provider

Uses the Stability AI REST API for image generation.
Requires: STABILITY_API_KEY environment variable.
No special SDK required — uses standard HTTP requests.
"""
import io
import os
import time
import logging
import base64
from .base import ImageGenerationProvider, ProviderResult, ProviderCapability

_log = logging.getLogger("psydox.ai_core.stability")

_API_URL       = "https://api.stability.ai/v2beta/stable-image/generate/core"
_COST_PER_IMAGE = 0.065  # ~6.5 credits at $0.01/credit


class StabilityImageProvider(ImageGenerationProvider):
    """Image generation via Stability AI REST API."""

    def __init__(self):
        self._api_key = os.environ.get("STABILITY_API_KEY", "").strip()

    @property
    def name(self) -> str:
        return "stability"

    @property
    def capabilities(self) -> list[ProviderCapability]:
        return [ProviderCapability.IMAGE_GENERATION, ProviderCapability.IMAGE_EDITING]

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
                error="STABILITY_API_KEY is not configured.",
            )

        t0 = time.monotonic()

        try:
            img_bytes = self._call_api(prompt, reference_bytes)
            latency = int((time.monotonic() - t0) * 1000)
            return ProviderResult(
                success=True,
                image_bytes=img_bytes,
                provider=self.name,
                model="stable-image-core",
                latency_ms=latency,
                cost_estimate=self._COST_PER_IMAGE,
            )
        except Exception as e:
            latency = int((time.monotonic() - t0) * 1000)
            _log.warning("Stability AI generation failed: %s", e)
            return ProviderResult(
                success=False, provider=self.name,
                model="stable-image-core", latency_ms=latency, error=str(e),
            )

    def _call_api(self, prompt: str, reference_bytes: bytes | None) -> bytes:
        import requests

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "image/*",
        }

        files: dict = {
            "prompt":       (None, prompt),
            "output_format": (None, "jpeg"),
        }

        if reference_bytes:
            files["image"] = ("reference.jpg", reference_bytes, "image/jpeg")
            files["mode"]  = (None, "image-to-image")
            files["strength"] = (None, "0.75")
            url = "https://api.stability.ai/v2beta/stable-image/generate/sd3"
        else:
            url = _API_URL

        resp = requests.post(url, headers=headers, files=files, timeout=90)

        if resp.status_code == 200:
            # API returns raw image bytes
            return resp.content
        else:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise RuntimeError(f"Stability API error {resp.status_code}: {detail}")

    def estimate_cost(self, prompt: str, reference_bytes: bytes | None = None) -> float:
        return self._COST_PER_IMAGE
