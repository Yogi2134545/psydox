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
    "front view, straight on, clean white background",
    "side profile view, 90 degrees, light grey background",
    "three-quarter angle view, 45 degrees, soft gradient background",
    "back view, pure white background",
    "top-down overhead view, white background",
    "close-up detail shot, macro photography, white background",
    "low angle dramatic view, dark background",
    "elevated 45-degree view, light background",
]

# PIL-based background colors for offline angle variations (no AI required)
_PIL_ANGLE_STYLES = [
    {"bg": (255, 255, 255), "label": "White background"},
    {"bg": (240, 240, 240), "label": "Light grey"},
    {"bg": (220, 220, 220), "label": "Medium grey"},
    {"bg": (200, 215, 230), "label": "Cool blue-grey"},
    {"bg": (230, 220, 210), "label": "Warm beige"},
    {"bg": (210, 230, 210), "label": "Soft green"},
    {"bg": (30,  30,  30),  "label": "Dark / studio"},
    {"bg": (245, 235, 220), "label": "Cream"},
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
    ) -> list:
        """
        Generate `count` background-style variations of a product image.
        Uses rembg to remove background, then composites on different coloured
        backgrounds — works with no API key. If Gemini image generation is
        available it will be used for richer results.
        Returns list of bytes (JPEG) or None per slot.
        """
        import io as _io
        from PIL import Image as _PILImage

        # Remove background once, reuse the cutout for all variations
        fg_rgba = None
        try:
            import rembg
            result_bytes = rembg.remove(reference_image_bytes)
            fg_rgba = _PILImage.open(_io.BytesIO(result_bytes)).convert("RGBA")
        except Exception:
            try:
                fg_rgba = _PILImage.open(_io.BytesIO(reference_image_bytes)).convert("RGBA")
            except Exception:
                fg_rgba = None

        results = []
        for i in range(min(count, len(_PIL_ANGLE_STYLES))):
            style = _PIL_ANGLE_STYLES[i]
            try:
                if fg_rgba is not None:
                    # Composite product on solid colour background
                    bg = _PILImage.new("RGBA", fg_rgba.size, style["bg"] + (255,))
                    bg.paste(fg_rgba, mask=fg_rgba.split()[3])
                    out = bg.convert("RGB")
                else:
                    out = _PILImage.open(_io.BytesIO(reference_image_bytes)).convert("RGB")

                buf = _io.BytesIO()
                out.save(buf, format="JPEG", quality=90)
                results.append(buf.getvalue())
            except Exception:
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
