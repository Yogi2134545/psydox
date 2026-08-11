"""
Psydox AI Core — OpenRouter Provider

OpenRouter aggregates many AI providers under one OpenAI-compatible API.
Requires: OPENROUTER_API_KEY environment variable.
Uses the openai SDK with a custom base_url, or falls back to raw HTTP.
"""
import os
import time
import logging
import base64
from .base import ImageGenerationProvider, ProviderResult, ProviderCapability

_log = logging.getLogger("psydox.ai_core.openrouter")

_BASE_URL      = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "google/gemini-2.0-flash-exp:free"
_COST_PER_IMAGE = 0.02  # approximate; varies by model


class OpenRouterImageProvider(ImageGenerationProvider):
    """Image generation via OpenRouter (multi-model aggregator)."""

    def __init__(self, model: str = _DEFAULT_MODEL):
        self._model   = model
        self._api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()

    @property
    def name(self) -> str:
        return "openrouter"

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
                error="OPENROUTER_API_KEY is not configured.",
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
            _log.warning("OpenRouter generation failed: %s", e)
            return ProviderResult(
                success=False, provider=self.name,
                model=model_used, latency_ms=latency, error=str(e),
            )

    def _call_api(self, prompt: str, model: str) -> bytes:
        """Call OpenRouter via openai SDK (custom base_url) or direct HTTP."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://psydox-production.up.railway.app",
            "X-Title": "Psydox Studio",
        }

        try:
            import openai
            client = openai.OpenAI(api_key=self._api_key, base_url=_BASE_URL)
            response = client.images.generate(
                model=model, prompt=prompt,
                n=1, size="1024x1024", response_format="b64_json",
            )
            b64 = response.data[0].b64_json
            return base64.b64decode(b64)
        except ImportError:
            pass  # fall through to direct HTTP

        import requests
        payload = {
            "model": model, "prompt": prompt,
            "n": 1, "size": "1024x1024", "response_format": "b64_json",
        }
        resp = requests.post(
            f"{_BASE_URL}/images/generations",
            headers=headers, json=payload, timeout=90,
        )
        resp.raise_for_status()
        b64 = resp.json()["data"][0]["b64_json"]
        return base64.b64decode(b64)

    def estimate_cost(self, prompt: str, reference_bytes: bytes | None = None) -> float:
        return self._COST_PER_IMAGE
