"""
Psydox AI Core — Replicate Provider

Replicate runs open-source AI models in the cloud.
Requires: REPLICATE_API_TOKEN environment variable.
Uses direct HTTP (replicate package optional).
"""
import io
import os
import time
import logging
from .base import ImageGenerationProvider, ProviderResult, ProviderCapability

_log = logging.getLogger("psydox.ai_core.replicate_provider")

_DEFAULT_MODEL = "black-forest-labs/flux-schnell"
_COST_PER_IMAGE = 0.003  # Flux Schnell ~$0.003 per image


class ReplicateImageProvider(ImageGenerationProvider):
    """Image generation via Replicate API."""

    def __init__(self, model: str = _DEFAULT_MODEL):
        self._model   = model
        self._api_key = os.environ.get("REPLICATE_API_TOKEN", "").strip()

    @property
    def name(self) -> str:
        return "replicate"

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
                error="REPLICATE_API_TOKEN is not configured.",
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
            _log.warning("Replicate generation failed: %s", e)
            return ProviderResult(
                success=False, provider=self.name,
                model=model_used, latency_ms=latency, error=str(e),
            )

    def _call_api(self, prompt: str, model: str) -> bytes:
        """Run a Replicate prediction and poll until complete."""
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/json",
        }

        # Try replicate package first
        try:
            import replicate
            client = replicate.Client(api_token=self._api_key)
            output = client.run(model, input={"prompt": prompt})
            # output is a list of URLs or a single URL
            url = output[0] if isinstance(output, list) else output
            return self._download(str(url))
        except ImportError:
            pass

        # Fall back to HTTP API
        import requests

        # 1. Create prediction
        resp = requests.post(
            f"https://api.replicate.com/v1/models/{model}/predictions",
            headers=headers,
            json={"input": {"prompt": prompt}},
            timeout=30,
        )
        resp.raise_for_status()
        prediction = resp.json()
        prediction_id = prediction["id"]

        # 2. Poll until complete (max 120s)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            time.sleep(2)
            poll = requests.get(
                f"https://api.replicate.com/v1/predictions/{prediction_id}",
                headers=headers, timeout=15,
            )
            poll.raise_for_status()
            data = poll.json()
            status = data.get("status")
            if status == "succeeded":
                output = data.get("output", [])
                url = output[0] if isinstance(output, list) else output
                return self._download(str(url))
            if status in ("failed", "canceled"):
                raise RuntimeError(f"Replicate prediction {status}: {data.get('error')}")

        raise TimeoutError("Replicate prediction timed out after 120s")

    def _download(self, url: str) -> bytes:
        import requests
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content

    def estimate_cost(self, prompt: str, reference_bytes: bytes | None = None) -> float:
        return self._COST_PER_IMAGE
