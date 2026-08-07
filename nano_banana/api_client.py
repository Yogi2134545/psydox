"""Nano Banana — Google AI / Gemini API client."""
import io
import time
import base64
import requests
from typing import Optional

from .settings import GOOGLE_API_KEY


class GeminiClient:
    """Wraps Google Generative AI for image generation and editing."""

    def __init__(self):
        self.api_key = GOOGLE_API_KEY
        self._genai = None
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._genai = genai
            except ImportError:
                pass

    # ── internal helpers ──────────────────────────────────────────────────────

    def _is_configured(self) -> bool:
        return bool(self.api_key and self._genai)

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

    # ── image generation via Imagen REST ─────────────────────────────────────

    def generate_image(self, prompt: str, reference_image_bytes: bytes = None) -> bytes:
        """
        Generate an image from a text prompt (and optionally a reference image).
        Returns raw image bytes (JPEG/PNG).
        """
        if not self.api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY not configured. Set it as an environment variable."
            )

        # If reference image provided, use Gemini vision for guided generation
        if reference_image_bytes and self._genai:
            return self._guided_generation(prompt, reference_image_bytes)

        # Otherwise use Imagen 3 for pure text-to-image
        return self._imagen_generate(prompt)

    def _imagen_generate(self, prompt: str) -> bytes:
        """Call Imagen 3 REST endpoint."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/imagen-3.0-generate-001:predict?key={self.api_key}"
        )
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1},
        }

        def _call():
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            b64 = data["predictions"][0]["bytesBase64Encoded"]
            return base64.b64decode(b64)

        return self._retry(_call)

    def _guided_generation(self, prompt: str, reference_image_bytes: bytes) -> bytes:
        """Use Gemini vision model with reference image as context."""
        import google.generativeai as genai
        from PIL import Image as PILImage

        ref_img = PILImage.open(io.BytesIO(reference_image_bytes))

        model = genai.GenerativeModel("gemini-1.5-pro-vision")

        def _call():
            response = model.generate_content(
                [prompt, ref_img],
                generation_config={"response_mime_type": "image/png"},
            )
            # Extract image bytes from response
            for part in response.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    return part.inline_data.data
            # Fallback: try Imagen without reference
            return self._imagen_generate(prompt)

        try:
            return self._retry(_call)
        except Exception:
            # Graceful fallback to Imagen without the reference
            return self._imagen_generate(prompt)

    # ── image editing via Gemini ──────────────────────────────────────────────

    def edit_image(self, image_bytes: bytes, instruction: str) -> bytes:
        """
        Edit an existing image using a text instruction.
        Returns edited image bytes.
        """
        if not self.api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY not configured. Set it as an environment variable."
            )

        if not self._genai:
            raise RuntimeError(
                "google-generativeai package not installed. "
                "Run: pip install google-generativeai"
            )

        import google.generativeai as genai
        from PIL import Image as PILImage

        pil_img = PILImage.open(io.BytesIO(image_bytes))
        model = genai.GenerativeModel("gemini-1.5-pro-vision")

        full_instruction = (
            f"{instruction}. Return only the edited image, no explanations."
        )

        def _call():
            response = model.generate_content(
                [full_instruction, pil_img],
                generation_config={"response_mime_type": "image/png"},
            )
            for part in response.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    return part.inline_data.data
            raise RuntimeError("No image data in Gemini response")

        return self._retry(_call)
