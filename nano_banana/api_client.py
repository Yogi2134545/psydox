"""
Nano Banana — Google AI client.

VERIFIED OFFICIAL MODEL SUPPORT (checked 2026-08-07):
  - gemini-2.0-flash-preview-image-generation → SHUT DOWN Nov 14, 2025
  - gemini-2.0-flash-exp-image-generation     → never official, always 404
  - gemini-2.0-flash                          → TEXT-ONLY, always 400 for image output
  - imagen-3.0-*                              → Vertex AI only, NOT AI Studio keys
  - gemini-2.5-flash-image                   → CURRENT official image model
  - gemini-3.1-flash-image                   → CURRENT official image model (latest)

Correct SDK: google-genai (NOT google-generativeai)
Correct call: client.models.generate_content(
    model=MODEL,
    contents=...,
    config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])
)
"""
import io
import sys
import time
import base64
import json
import logging
import platform
import importlib.metadata

import requests

from .settings import GOOGLE_API_KEY

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="[NanoBanana] %(levelname)s %(message)s")
_log = logging.getLogger("nano_banana.api_client")

# ── Official image-capable model list (newest first) ─────────────────────────
# Source: https://ai.google.dev/gemini-api/docs/image-generation (checked 2026-08-07)
_IMAGE_MODELS_OFFICIAL = [
    "gemini-3.1-flash-image",    # latest GA
    "gemini-2.5-flash-image",    # current GA
]

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


# ── Version helpers ───────────────────────────────────────────────────────────

def _pkg_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except Exception:
        return "not installed"


def get_versions() -> dict:
    return {
        "python":              platform.python_version(),
        "google-genai":        _pkg_version("google-genai"),
        "google-generativeai": _pkg_version("google-generativeai"),
        "requests":            _pkg_version("requests"),
        "Pillow":              _pkg_version("Pillow"),
    }


# ── GeminiClient ─────────────────────────────────────────────────────────────

class GeminiClient:

    def __init__(self):
        self.api_key = GOOGLE_API_KEY
        self._sdk = None
        self._types = None
        self._sdk_ok = False
        self._active_model: str | None = None
        self._init_sdk()

    # ── SDK init ──────────────────────────────────────────────────────────────

    def _init_sdk(self):
        if not self.api_key:
            _log.warning("GOOGLE_API_KEY not set — image generation disabled")
            return
        try:
            from google import genai
            from google.genai import types
            self._sdk = genai.Client(api_key=self.api_key)
            self._types = types
            self._sdk_ok = True
            _log.info("google-genai SDK ready  version=%s", _pkg_version("google-genai"))
        except ImportError:
            _log.error(
                "google-genai package not installed. "
                "Add 'google-genai>=0.8.0' to requirements.txt"
            )
        except Exception as e:
            _log.error("google-genai init failed: %s", e)

    # ── Model discovery ───────────────────────────────────────────────────────

    def list_available_models(self) -> list[dict]:
        """Query the API and return every model the key can access."""
        if not self.api_key:
            return []
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json().get("models", [])
        except Exception as e:
            _log.warning("list_models failed: %s", e)
            return []

    def find_image_model(self) -> str | None:
        """
        Return the first model from the official list that exists for this key.
        Tries each name against the API; skips 404s.
        """
        if self._active_model:
            return self._active_model

        for name in _IMAGE_MODELS_OFFICIAL:
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/{name}"
                   f"?key={self.api_key}")
            try:
                resp = requests.get(url, timeout=15)
                if resp.ok:
                    _log.info("Image model confirmed available: %s", name)
                    self._active_model = name
                    return name
                _log.info("Model %s → %s", name, resp.status_code)
            except Exception as e:
                _log.warning("Model probe %s failed: %s", name, e)

        _log.error(
            "No official image generation model is available for this API key.\n"
            "Checked: %s\n"
            "Your key may not have image generation enabled. "
            "Visit https://aistudio.google.com to check model access.",
            _IMAGE_MODELS_OFFICIAL,
        )
        return None

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def run_diagnostics(self) -> dict:
        """
        Run full compatibility checks and return a structured report.
        Called by the Dashboard tab and 'Test Connection' button.
        """
        report = {
            "versions":           get_versions(),
            "api_key_loaded":     bool(self.api_key),
            "api_key_masked":     ("*" * (len(self.api_key) - 4) + self.api_key[-4:]
                                   if self.api_key and len(self.api_key) > 4 else "NOT SET"),
            "sdk_compatible":     self._sdk_ok,
            "available_models":   [],
            "image_model_found":  None,
            "model_compatible":   False,
            "endpoint":           "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            "auth_method":        "API key (query param)",
            "image_gen_supported": False,
            "image_edit_supported": False,
            "test_image_result":  None,
            "errors":             [],
            "warnings":           [],
        }

        if not self.api_key:
            report["errors"].append("GOOGLE_API_KEY not set")
            return report

        if not self._sdk_ok:
            report["errors"].append(
                "google-genai SDK not available — install it: pip install google-genai"
            )

        # List available models
        all_models = self.list_available_models()
        report["available_models"] = [m.get("name", "") for m in all_models]

        # Find image model
        model = self.find_image_model()
        report["image_model_found"] = model
        report["model_compatible"] = model is not None

        if model is None:
            report["errors"].append(
                f"No image-generation model available for this key. "
                f"Checked: {_IMAGE_MODELS_OFFICIAL}. "
                f"Ensure Imagen/image-generation is enabled at https://aistudio.google.com"
            )
            return report

        # Check whether the model endpoint says it supports generateContent
        model_info_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
            f"?key={self.api_key}"
        )
        try:
            r = requests.get(model_info_url, timeout=15)
            if r.ok:
                info = r.json()
                methods = info.get("supportedGenerationMethods", [])
                report["image_gen_supported"] = "generateContent" in methods
                report["image_edit_supported"] = "generateContent" in methods
                if "generateContent" not in methods:
                    report["errors"].append(
                        f"Model {model} does not list 'generateContent' in "
                        f"supportedGenerationMethods: {methods}"
                    )
            else:
                report["warnings"].append(
                    f"Could not fetch model info ({r.status_code}): {r.text[:200]}"
                )
        except Exception as e:
            report["warnings"].append(f"Model info probe failed: {e}")

        # Minimal generation test
        test_result = self.test_image_generation(model)
        report["test_image_result"] = test_result
        if test_result.get("success"):
            report["image_gen_supported"] = True
        else:
            report["errors"].append(
                f"Test image generation FAILED: {test_result.get('error')}"
            )

        return report

    def test_image_generation(self, model: str = None) -> dict:
        """
        Send a minimal image generation request and report pass/fail with full detail.
        Returns {"success": bool, "model": str, "error": str|None, "response_keys": list}
        """
        model = model or self.find_image_model()
        if not model:
            return {"success": False, "model": None,
                    "error": "No image-capable model found for this API key"}

        _log.info("TEST — model=%s  prompt='a red circle on white background'", model)

        if self._sdk_ok:
            try:
                response = self._sdk.models.generate_content(
                    model=model,
                    contents="Generate a small red circle on a white background",
                    config=self._types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"]
                    ),
                )
                for candidate in (response.candidates or []):
                    for part in candidate.content.parts:
                        if hasattr(part, "inline_data") and part.inline_data:
                            _log.info("TEST PASSED — model=%s  got image bytes", model)
                            return {"success": True, "model": model, "error": None,
                                    "response_keys": ["inline_data"]}
                return {"success": False, "model": model,
                        "error": "Response contained no image data",
                        "full_response": str(response)}
            except Exception as e:
                err = str(e)
                _log.error("TEST FAILED — model=%s  error=%s", model, err)
                return {"success": False, "model": model, "error": err}

        # SDK not available — try REST
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={self.api_key}")
        payload = {
            "contents": [{"parts": [{"text": "Generate a small red circle on white background"}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        _log.info("TEST REST  url=%s", url)
        try:
            resp = requests.post(url, json=payload, timeout=60)
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            _log.info("TEST REST  status=%s  body=%s",
                      resp.status_code,
                      json.dumps(body, indent=2) if isinstance(body, dict) else body[:500])
            if not resp.ok:
                google_err = (body.get("error", {}).get("message", str(body))
                              if isinstance(body, dict) else body)
                return {"success": False, "model": model,
                        "error": f"HTTP {resp.status_code}: {google_err}",
                        "url": url, "response_body": body}
            for part in (body.get("candidates", [{}])[0]
                             .get("content", {}).get("parts", [])):
                if "inlineData" in part:
                    return {"success": True, "model": model, "error": None}
            return {"success": False, "model": model,
                    "error": "No image data in response", "response_body": body}
        except Exception as e:
            return {"success": False, "model": model, "error": str(e), "url": url}

    # ── Public generate API ───────────────────────────────────────────────────

    def generate_image(self, prompt: str, reference_image_bytes: bytes = None) -> bytes:
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY not set.")
        if not self._sdk_ok:
            raise RuntimeError(
                "google-genai SDK not installed. Add 'google-genai>=0.8.0' to requirements.txt"
            )

        model = self.find_image_model()
        if not model:
            raise RuntimeError(
                f"No image-generation model available for this API key.\n"
                f"Checked official models: {_IMAGE_MODELS_OFFICIAL}\n"
                f"Your key may not have image generation enabled.\n"
                f"Visit https://aistudio.google.com to enable it."
            )

        _log.info("generate_image  model=%s  prompt=%r  has_ref=%s",
                  model, prompt[:80], reference_image_bytes is not None)

        parts = []
        if reference_image_bytes:
            from PIL import Image as _PIL
            pil_img = _PIL.open(io.BytesIO(reference_image_bytes)).convert("RGB")
            parts.append(pil_img)
        parts.append(prompt)

        try:
            response = self._sdk.models.generate_content(
                model=model,
                contents=parts,
                config=self._types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"]
                ),
            )
        except Exception as e:
            err = str(e)
            _log.error(
                "generate_content failed\n  model=%s\n  prompt=%r\n  error=%s",
                model, prompt[:80], err,
            )
            raise RuntimeError(
                f"Image generation failed.\n"
                f"Model    : {model}\n"
                f"Error    : {err}\n\n"
                f"If you see PERMISSION_DENIED or 404: image generation is not enabled "
                f"for your API key. Visit https://aistudio.google.com"
            ) from e

        for candidate in (response.candidates or []):
            for part in candidate.content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    _log.info("generate_image succeeded  model=%s", model)
                    return part.inline_data.data

        raise RuntimeError(
            f"Gemini returned no image data.\n"
            f"Model: {model}\n"
            f"Response candidates: {len(response.candidates or [])}\n"
            f"Full response: {response}"
        )

    def edit_image(self, image_bytes: bytes, instruction: str) -> bytes:
        return self.generate_image(instruction, reference_image_bytes=image_bytes)

    def generate_angles(self, prompt_base: str, reference_image_bytes: bytes,
                        count: int = 4) -> list:
        """PIL-based background variations — no API call, always works."""
        import io as _io
        from PIL import Image as _PIL

        fg_rgba = None
        try:
            import rembg
            fg_rgba = _PIL.open(_io.BytesIO(rembg.remove(reference_image_bytes))).convert("RGBA")
        except Exception as e:
            _log.warning("rembg failed (%s) — using original", e)
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
