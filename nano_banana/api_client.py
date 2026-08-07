"""Nano Banana — Google AI / Gemini API client."""
import io
import time
import base64
import requests
from typing import Optional

from .settings import GOOGLE_API_KEY

# Ordered list of models to try — first available one wins
_GEMINI_IMG_MODELS = [
    "gemini-2.0-flash-preview-image-generation",
    "gemini-2.0-flash-exp-image-generation",
    "gemini-2.0-flash",
]
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_ANGLE_PROMPTS = [
    "front view, straight on",
    "side profile view, 90 degrees",
    "three-quarter angle view, 45 degrees",
    "back view",
    "top-down overhead view",
    "close-up detail shot, macro",
    "low angle dramatic upward view",
    "elevated 45-degree view",
]


class GeminiClient:
    """Wraps Google Generative AI for image generation and editing."""

    def __init__(self):
        self.api_key = GOOGLE_API_KEY

    def _is_configured(self) -> bool:
        return bool(self.api_key)

    def _retry(self, fn, attempts: int = 3):
        last_err = None
        for i in range(attempts):
            try:
                return fn()
            except Exception as e:
                last_err = e
                if i < attempts - 1:
                    time.sleep(2 ** i)
        raise last_err

    # ── core REST helper ──────────────────────────────────────────────────────

    def _generate_image_rest(self, parts: list) -> bytes:
        """Try each Gemini image model in order and return image bytes from the first that works."""
        if not self.api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY not configured. Set it as an environment variable."
            )
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        last_err = None
        for model in _GEMINI_IMG_MODELS:
            url = f"{_GEMINI_BASE}/{model}:generateContent?key={self.api_key}"
            try:
                resp = requests.post(url, json=payload, timeout=120)
                if resp.status_code == 404:
                    last_err = RuntimeError(f"Model {model} not found (404)")
                    continue
                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    last_err = RuntimeError(f"No candidates from {model}: {data}")
                    continue
                for part in candidates[0]["content"]["parts"]:
                    if "inlineData" in part:
                        return base64.b64decode(part["inlineData"]["data"])
                last_err = RuntimeError(f"No image data in response from {model}")
            except requests.HTTPError as e:
                last_err = e
                if e.response is not None and e.response.status_code == 404:
                    continue
                raise
        raise last_err or RuntimeError("All Gemini image models failed")

    # ── public API ────────────────────────────────────────────────────────────

    def generate_image(self, prompt: str, reference_image_bytes: bytes = None) -> bytes:
        """Generate an image from a text prompt, optionally using a reference image."""
        if not self.api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY not configured. Set it as an environment variable."
            )
        parts = []
        if reference_image_bytes:
            img_b64 = base64.b64encode(reference_image_bytes).decode()
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": img_b64}})
        parts.append({"text": prompt})
        return self._generate_image_rest(parts)

    def generate_angles(
        self,
        prompt_base: str,
        reference_image_bytes: bytes,
        count: int = 4,
    ) -> list[bytes]:
        """Generate `count` angle variations of a product image. Returns list of image bytes."""
        results = []
        for i in range(min(count, len(_ANGLE_PROMPTS))):
            angle_prompt = f"{prompt_base}, {_ANGLE_PROMPTS[i]}, product photography"
            try:
                img_bytes = self.generate_image(angle_prompt, reference_image_bytes)
                results.append(img_bytes)
            except Exception as e:
                results.append(None)
        return results

    def edit_image(self, image_bytes: bytes, instruction: str) -> bytes:
        """Edit an existing image using a text instruction. Returns edited image bytes."""
        if not self.api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY not configured. Set it as an environment variable."
            )
        img_b64 = base64.b64encode(image_bytes).decode()
        parts = [
            {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
            {"text": f"{instruction}. Return only the edited image."},
        ]
        return self._generate_image_rest(parts)
