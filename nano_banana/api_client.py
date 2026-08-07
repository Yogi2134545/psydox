"""
Nano Banana — Google AI client.

ROOT CAUSE (fixed 2026-08-07):
- Bug 1: `google-generativeai` v0.8.x has NO support for image generation OUTPUT.
  It only supports text + vision INPUT. Sending `responseModalities: ["IMAGE"]`
  to any text model returns 400; to image models via the old SDK returns 404.
  Fix: use `google-genai` (the new unified SDK) which has first-class image
  generation support via `response_modalities=['IMAGE', 'TEXT']`.

- Bug 2: `gemini-2.0-flash` was in the fallback model list. That model is
  text-only. Sending `responseModalities: ["IMAGE"]` to it always returns 400.
  Fix: removed entirely. Only image-capable model IDs are tried.

- Bug 3: HTTPError for non-404 status codes was re-raised immediately, stopping
  the fallback chain and surfacing a bare "400 Bad Request" with no body.
  Fix: all HTTP errors are caught, response body is logged and included in the
  exception message.

Correct model for Gemini image generation (as of 2025):
  gemini-2.0-flash-preview-image-generation
  accessed via google-genai SDK with response_modalities=['IMAGE', 'TEXT'].
"""
import io
import sys
import time
import base64
import json
import logging
import requests
from typing import Optional

from .settings import GOOGLE_API_KEY

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="[NanoBanana] %(levelname)s: %(message)s")
_log = logging.getLogger("nano_banana.api_client")

# Image-capable models only. gemini-2.0-flash is TEXT-ONLY — never put it here.
_IMAGE_MODELS = [
    "gemini-2.0-flash-preview-image-generation",  # current name (2025)
    "gemini-2.0-flash-exp-image-generation",       # prior experimental name
]
_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# PIL-based background colours for angle/variation generation (no API required)
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


def _log_request(url: str, payload: dict):
    safe_payload = json.loads(json.dumps(payload))
    # Truncate base64 blobs so logs stay readable
    for content in safe_payload.get("contents", []):
        for part in content.get("parts", []):
            if "inlineData" in part and "data" in part["inlineData"]:
                part["inlineData"]["data"] = part["inlineData"]["data"][:40] + "...[truncated]"
    _log.info("REQUEST  url=%s  payload=%s", url, json.dumps(safe_payload, indent=2))


def _log_response(model: str, status: int, body: dict | str):
    _log.info("RESPONSE model=%s  status=%s  body=%s",
              model, status, json.dumps(body, indent=2) if isinstance(body, dict) else body)


class GeminiClient:

    def __init__(self):
        self.api_key = GOOGLE_API_KEY
        self._sdk_client = None
        self._sdk_available = False
        self._init_sdk()

    # ── SDK initialisation ────────────────────────────────────────────────────

    def _init_sdk(self):
        """Try to initialise the new google-genai SDK (preferred for image generation)."""
        if not self.api_key:
            return
        try:
            from google import genai as _genai
            from google.genai import types as _types
            self._sdk_client = _genai.Client(api_key=self.api_key)
            self._genai_types = _types
            self._sdk_available = True
            _log.info("google-genai SDK initialised successfully")
        except ImportError:
            _log.warning(
                "google-genai package not installed — falling back to REST. "
                "Add 'google-genai>=0.8.0' to requirements.txt for full image generation support."
            )
        except Exception as e:
            _log.warning("google-genai SDK init failed: %s", e)

    # ── public API ────────────────────────────────────────────────────────────

    def generate_image(self, prompt: str, reference_image_bytes: bytes = None) -> bytes:
        """Generate an image from a text prompt, optionally using a reference image."""
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY not set in environment variables.")

        _log.info("generate_image called — prompt=%r  has_reference=%s",
                  prompt[:80], reference_image_bytes is not None)

        # --- Try new SDK first (correct implementation for image generation) ---
        if self._sdk_available:
            try:
                return self._sdk_generate(prompt, reference_image_bytes)
            except Exception as e:
                _log.warning("SDK generate failed (%s), trying REST fallback", e)

        # --- Fallback: REST API ---
        parts = []
        if reference_image_bytes:
            img_b64 = base64.b64encode(reference_image_bytes).decode()
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": img_b64}})
        parts.append({"text": prompt})
        return self._rest_generate(parts)

    def edit_image(self, image_bytes: bytes, instruction: str) -> bytes:
        """Edit an image with a text instruction."""
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY not set in environment variables.")

        _log.info("edit_image called — instruction=%r", instruction[:80])

        if self._sdk_available:
            try:
                return self._sdk_generate(instruction, image_bytes)
            except Exception as e:
                _log.warning("SDK edit failed (%s), trying REST fallback", e)

        img_b64 = base64.b64encode(image_bytes).decode()
        parts = [
            {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
            {"text": f"{instruction}. Return only the edited image."},
        ]
        return self._rest_generate(parts)

    def generate_angles(self, prompt_base: str, reference_image_bytes: bytes, count: int = 4) -> list:
        """
        Generate `count` background-colour variations using rembg + PIL.
        No API call required — works offline.
        """
        import io as _io
        from PIL import Image as _PIL

        fg_rgba = None
        try:
            import rembg
            fg_rgba = _PIL.open(_io.BytesIO(rembg.remove(reference_image_bytes))).convert("RGBA")
        except Exception as e:
            _log.warning("rembg failed (%s) — using original image", e)
            try:
                fg_rgba = _PIL.open(_io.BytesIO(reference_image_bytes)).convert("RGBA")
            except Exception:
                fg_rgba = None

        results = []
        for i in range(min(count, len(_PIL_ANGLE_STYLES))):
            style = _PIL_ANGLE_STYLES[i]
            try:
                if fg_rgba is not None:
                    bg = _PIL.new("RGBA", fg_rgba.size, style["bg"] + (255,))
                    bg.paste(fg_rgba, mask=fg_rgba.split()[3])
                    out = bg.convert("RGB")
                else:
                    out = _PIL.open(_io.BytesIO(reference_image_bytes)).convert("RGB")
                buf = _io.BytesIO()
                out.save(buf, format="JPEG", quality=90)
                results.append(buf.getvalue())
            except Exception as e:
                _log.error("angle %d failed: %s", i, e)
                results.append(None)
        return results

    # ── SDK implementation (google-genai) ────────────────────────────────────

    def _sdk_generate(self, prompt: str, image_bytes: bytes = None) -> bytes:
        """
        Use the google-genai SDK to generate an image.
        This is the CORRECT way to call Gemini image generation —
        the old google-generativeai SDK does not support image output.
        """
        types = self._genai_types
        parts = []

        if image_bytes:
            from PIL import Image as _PIL
            pil_img = _PIL.open(io.BytesIO(image_bytes)).convert("RGB")
            parts.append(pil_img)

        parts.append(prompt)

        model = _IMAGE_MODELS[0]
        _log.info("SDK generate — model=%s  parts=%d", model, len(parts))

        try:
            response = self._sdk_client.models.generate_content(
                model=model,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"]
                ),
            )
        except Exception as e:
            # Extract and log the full error detail from Google
            err_str = str(e)
            _log.error(
                "SDK generate_content failed:\n"
                "  model     : %s\n"
                "  error     : %s",
                model, err_str,
            )
            raise RuntimeError(
                f"Gemini image generation failed.\n"
                f"Model: {model}\n"
                f"Error: {err_str}\n\n"
                f"If you see 'PERMISSION_DENIED' or '404': image generation is not enabled "
                f"for your API key. Go to https://aistudio.google.com and enable Imagen 3."
            ) from e

        # Extract image bytes from response
        for candidate in response.candidates or []:
            for part in candidate.content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    _log.info("SDK generate succeeded — got image bytes")
                    return part.inline_data.data

        raise RuntimeError(
            f"Gemini returned no image data.\n"
            f"Full response: {response}"
        )

    # ── REST fallback (with full logging) ────────────────────────────────────

    def _rest_generate(self, parts: list) -> bytes:
        """
        REST fallback for image generation.
        Logs full request + response body for every attempt.
        Raises a detailed error showing exactly what Google returned.
        """
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        errors = []

        for model in _IMAGE_MODELS:
            url = f"{_BASE}/{model}:generateContent?key={self.api_key}"
            _log_request(url, payload)

            try:
                resp = requests.post(url, json=payload, timeout=120,
                                     headers={"Content-Type": "application/json"})
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text

                _log_response(model, resp.status_code, body)

                if resp.status_code == 404:
                    google_msg = (body.get("error", {}).get("message", "not found")
                                  if isinstance(body, dict) else body)
                    errors.append(f"[{model}] 404 — {google_msg}")
                    continue

                if not resp.ok:
                    google_msg = (body.get("error", {}).get("message", str(body))
                                  if isinstance(body, dict) else body)
                    errors.append(
                        f"[{model}] {resp.status_code} — {google_msg}"
                    )
                    # 400 on an image model = wrong request format; 403 = no permission.
                    # Both are fatal for this model — try next.
                    continue

                candidates = body.get("candidates", []) if isinstance(body, dict) else []
                if not candidates:
                    errors.append(f"[{model}] 200 but no candidates: {body}")
                    continue

                for part in candidates[0]["content"]["parts"]:
                    if "inlineData" in part:
                        _log.info("REST generate succeeded — model=%s", model)
                        return base64.b64decode(part["inlineData"]["data"])

                errors.append(f"[{model}] 200 but no image data in parts")

            except requests.RequestException as e:
                errors.append(f"[{model}] network error: {e}")

        # All models failed — raise with full detail
        raise RuntimeError(
            "Gemini image generation failed for all models.\n\n"
            + "\n".join(errors)
            + "\n\nTo enable image generation:\n"
            "1. Your GOOGLE_API_KEY must have Imagen 3 access enabled.\n"
            "2. Go to https://aistudio.google.com → enable Imagen 3 (requires billing).\n"
            "3. Standard free-tier keys do NOT include image generation output."
        )
