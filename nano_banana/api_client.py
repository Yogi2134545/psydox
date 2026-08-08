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
import traceback

import requests

from .settings import GOOGLE_API_KEY

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="[NanoBanana] %(levelname)s %(message)s")
_log = logging.getLogger("nano_banana.api_client")

# ── Fallback hint list — NOT the source of truth for model discovery ──────────
# Actual discovery is done dynamically via diagnostics.discover_image_models().
_IMAGE_MODELS_OFFICIAL = [
    "gemini-3.1-flash-image",    # latest GA (hint only)
    "gemini-2.5-flash-image",    # current GA (hint only)
]

# ── Packshot angle definitions (8 views) ─────────────────────────────────────
# Each entry defines one photographic angle for AI-based packshot generation.
# The "desc" is embedded directly in the generation prompt.
ANGLE_VIEWS = [
    {
        "name":  "Front View",
        "label": "Front",
        "key":   "front",
        "desc":  "straight-on front view, product centered, camera at eye level facing directly toward the product",
    },
    {
        "name":  "Back View",
        "label": "Back",
        "key":   "back",
        "desc":  "straight-on rear view, product centered, camera at eye level facing directly at the back of the product",
    },
    {
        "name":  "Left Side",
        "label": "Left",
        "key":   "left",
        "desc":  "direct left-side profile, camera at exactly 90 degrees to the left of center, eye level",
    },
    {
        "name":  "Right Side",
        "label": "Right",
        "key":   "right",
        "desc":  "direct right-side profile, camera at exactly 90 degrees to the right of center, eye level",
    },
    {
        "name":  "45° Front-Left",
        "label": "45°L",
        "key":   "45_front_left",
        "desc":  "45-degree front-left three-quarter angle, camera slightly elevated, showing front and left side simultaneously",
    },
    {
        "name":  "45° Front-Right",
        "label": "45°R",
        "key":   "45_front_right",
        "desc":  "45-degree front-right three-quarter angle, camera slightly elevated, showing front and right side simultaneously",
    },
    {
        "name":  "Top / Flat Lay",
        "label": "Top",
        "key":   "top",
        "desc":  "overhead top-down flat lay, camera directly above looking straight down at the product on a flat surface",
    },
    {
        "name":  "Three-Quarter",
        "label": "3/4",
        "key":   "three_quarter",
        "desc":  "classic three-quarter angle, 45 degrees horizontal and 30 degrees elevated, dynamic hero composition",
    },
]

# ── Angle prompt builder ──────────────────────────────────────────────────────

def _build_angle_prompt(product_desc: str, angle: dict) -> str:
    """Build an angle-specific generation prompt that preserves all product attributes."""
    desc_clause = f" of the {product_desc.strip()}" if product_desc.strip() else ""
    return (
        f"Create a photorealistic commercial product photograph{desc_clause}. "
        f"Camera position: {angle['desc']}. "
        "Preserve exactly from the reference image: same product design, same colorway, "
        "same materials and textures, same logos and branding, same proportions and scale. "
        "Studio: pure white background (#FFFFFF), soft diffused studio lighting from above, "
        "natural drop shadow beneath the product, no props, no reflections, "
        "product fills approximately 80% of the frame. "
        "Quality: 8K commercial product photography, razor-sharp focus, "
        "shot on a professional medium-format camera."
    )


# PIL-based background colours (kept for background replacement tab, n=1 path)
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
        "os":                  platform.system() + " " + platform.release(),
        "google-genai":        _pkg_version("google-genai"),
        "google-generativeai": _pkg_version("google-generativeai"),
        "requests":            _pkg_version("requests"),
        "Pillow":              _pkg_version("Pillow"),
        "rembg":               _pkg_version("rembg"),
    }


# ── GeminiClient ─────────────────────────────────────────────────────────────

class GeminiClient:

    def __init__(self):
        self.api_key = GOOGLE_API_KEY
        self._sdk = None
        self._types = None
        self._sdk_ok = False
        self._active_model: str | None = None
        self._perf: dict = {
            "requests":   0,
            "errors":     0,
            "retries":    0,
            "total_time": 0.0,
            "timings":    [],
        }
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
        from .diagnostics import _api_get
        try:
            resp = _api_get("/v1beta/models", self.api_key, timeout=30)
            resp.raise_for_status()
            return resp.json().get("models", [])
        except Exception as e:
            _log.warning("list_models failed: %s", e)
            return []

    def find_image_model(self) -> str | None:
        """
        Dynamically discover image-capable models for this API key via the
        diagnostics module, then confirm the first one responds 200.
        Falls back to the hint list if dynamic discovery returns nothing.
        Caches the result in self._active_model.
        """
        if self._active_model:
            return self._active_model

        if not self.api_key:
            return None

        from .diagnostics import discover_image_models

        candidates = discover_image_models(self.api_key)

        if not candidates:
            _log.warning(
                "Dynamic discovery found no image models — "
                "falling back to hint list: %s",
                _IMAGE_MODELS_OFFICIAL,
            )
            candidates = _IMAGE_MODELS_OFFICIAL

        from .diagnostics import _api_get
        for name in candidates:
            try:
                resp = _api_get(f"/v1beta/models/{name}", self.api_key, timeout=15)
                if resp.ok:
                    _log.info("Image model confirmed available: %s", name)
                    self._active_model = name
                    return name
                _log.info("Model %s → HTTP %s", name, resp.status_code)
            except Exception as e:
                _log.warning("Model probe %s failed: %s", name, e)

        _log.error(
            "No image generation model is available for this API key.\n"
            "Dynamic discovery returned: %s\n"
            "Hint list checked: %s\n"
            "Ensure image generation is enabled at https://aistudio.google.com",
            candidates,
            _IMAGE_MODELS_OFFICIAL,
        )
        raise RuntimeError(
            "No image-generation model is available for this API key.\n"
            f"Dynamic discovery checked: {candidates}\n"
            "Ensure image generation is enabled at https://aistudio.google.com"
        )

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
        model = None
        try:
            model = self.find_image_model()
        except RuntimeError as _model_err:
            report["errors"].append(str(_model_err))

        report["image_model_found"] = model
        report["model_compatible"] = model is not None

        if model is None:
            return report

        # Check whether the model endpoint says it supports generateContent
        from .diagnostics import _api_get
        try:
            r = _api_get(f"/v1beta/models/{model}", self.api_key, timeout=15)
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
        if not model:
            try:
                model = self.find_image_model()
            except RuntimeError as _e:
                return {"success": False, "model": None, "error": str(_e)}
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

        # SDK not available — try REST (dual auth: query param + x-goog-api-key header)
        from .diagnostics import _api_post
        payload = {
            "contents": [{"parts": [{"text": "Generate a small red circle on white background"}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        _log.info("TEST REST  model=%s", model)
        try:
            resp = _api_post(f"/v1beta/models/{model}:generateContent",
                             self.api_key, payload, timeout=60)
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
                        "response_body": body}
            for part in (body.get("candidates", [{}])[0]
                             .get("content", {}).get("parts", [])):
                if "inlineData" in part:
                    return {"success": True, "model": model, "error": None}
            return {"success": False, "model": model,
                    "error": "No image data in response", "response_body": body}
        except Exception as e:
            return {"success": False, "model": model, "error": str(e), "url": url}

    # ── Public generate API ───────────────────────────────────────────────────

    def get_perf_metrics(self) -> dict:
        """Return current performance statistics."""
        reqs = self._perf["requests"]
        errs = self._perf["errors"]
        timings = self._perf["timings"]
        avg_time = (sum(timings) / len(timings)) if timings else 0.0
        return {
            "requests":   reqs,
            "errors":     errs,
            "retries":    self._perf["retries"],
            "error_rate": round((errs / reqs * 100) if reqs else 0.0, 1),
            "avg_time":   round(avg_time, 2),
            "total_time": round(self._perf["total_time"], 2),
        }

    def generate_image(self, prompt: str, reference_image_bytes: bytes = None) -> bytes:
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY not set.")
        if not self._sdk_ok:
            raise RuntimeError(
                "google-genai SDK not installed. Add 'google-genai>=0.8.0' to requirements.txt"
            )

        model = self.find_image_model()

        _log.info("generate_image  model=%s  prompt=%r  has_ref=%s",
                  model, prompt[:80], reference_image_bytes is not None)

        parts = []
        if reference_image_bytes:
            from PIL import Image as _PIL
            pil_img = _PIL.open(io.BytesIO(reference_image_bytes)).convert("RGB")
            parts.append(pil_img)
        parts.append(prompt)

        self._perf["requests"] += 1
        t_start = time.time()

        try:
            response = self._sdk.models.generate_content(
                model=model,
                contents=parts,
                config=self._types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"]
                ),
            )
        except Exception as e:
            elapsed = time.time() - t_start
            self._perf["errors"] += 1
            self._perf["total_time"] += elapsed
            self._perf["timings"].append(elapsed)
            err = str(e)
            tb = traceback.format_exc()
            _log.error(
                "generate_content failed\n  model=%s\n  prompt=%r\n  error=%s",
                model, prompt[:80], err,
            )
            from .diagnostics import get_error_log
            get_error_log().add(
                operation="generate_image",
                model=model,
                endpoint=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                method="SDK generate_content",
                request_summary=f"prompt={prompt[:120]} has_ref={reference_image_bytes is not None}",
                response_status=None,
                response_body=err[:500],
                error_msg=err,
                stack_trace=tb,
                fix_suggestion=(
                    "Check PERMISSION_DENIED / 404 → enable image generation at "
                    "https://aistudio.google.com. Check model name is still active."
                ),
            )
            raise RuntimeError(
                f"Image generation failed.\n"
                f"Model    : {model}\n"
                f"Error    : {err}\n\n"
                f"If you see PERMISSION_DENIED or 404: image generation is not enabled "
                f"for your API key. Visit https://aistudio.google.com"
            ) from e

        elapsed = time.time() - t_start
        self._perf["total_time"] += elapsed
        self._perf["timings"].append(elapsed)

        for candidate in (response.candidates or []):
            for part in candidate.content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    _log.info("generate_image succeeded  model=%s  elapsed=%.2fs", model, elapsed)
                    return part.inline_data.data

        self._perf["errors"] += 1
        no_data_err = (
            f"Gemini returned no image data.\n"
            f"Model: {model}\n"
            f"Response candidates: {len(response.candidates or [])}\n"
            f"Full response: {response}"
        )
        from .diagnostics import get_error_log
        get_error_log().add(
            operation="generate_image",
            model=model,
            endpoint=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            method="SDK generate_content",
            request_summary=f"prompt={prompt[:120]}",
            response_status=None,
            response_body=str(response)[:500],
            error_msg="No image data in response",
            stack_trace="",
            fix_suggestion="Response had no inline_data parts. Check model supports IMAGE modality.",
        )
        raise RuntimeError(no_data_err)

    def edit_image(self, image_bytes: bytes, instruction: str) -> bytes:
        # generate_image handles perf tracking and error logging
        return self.generate_image(instruction, reference_image_bytes=image_bytes)

    def generate_packshot_angles(
        self,
        product_desc: str,
        reference_image_bytes: bytes,
        count: int = 7,
    ) -> list:
        """
        Generate `count` distinct photographic angle views of the product via AI.

        Makes `count` independent API calls — one per angle — each with its own
        angle-specific prompt that instructs the model to render the product from
        Front, Back, Left, Right, 45°L, 45°R, Top, 3/4 (in order).

        Returns a list of dicts, one per angle, in the same order as ANGLE_VIEWS:
            {"name": str, "label": str, "key": str,
             "bytes": bytes | None, "error": str | None}

        Never raises — individual angle failures are captured in "error".

        Debug instrumentation: every generated image is written to
        /tmp/debug_angles/<key>.jpg immediately after each API call.
        A summary ZIP is written to /tmp/debug_angles/debug_packshot.zip.
        All SHA256 hashes are logged so identical images can be detected.
        """
        import hashlib, os, zipfile as _zf

        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY not set — cannot generate angles.")
        if not self._sdk_ok:
            raise RuntimeError(
                "google-genai SDK not installed — add 'google-genai' to requirements.txt."
            )

        # ── Debug output directory ────────────────────────────────────────────
        debug_dir = "/tmp/debug_angles"
        try:
            os.makedirs(debug_dir, exist_ok=True)
        except Exception as _de:
            _log.warning("Could not create debug dir %s: %s", debug_dir, _de)
            debug_dir = None

        selected = ANGLE_VIEWS[:min(count, len(ANGLE_VIEWS))]
        results  = []
        hashes   = []

        _log.info(
            "generate_packshot_angles START  count=%d  selected=%d  angles=%s",
            count, len(selected), [a["name"] for a in selected],
        )
        print(
            f"\n{'='*60}\n"
            f"generate_packshot_angles START\n"
            f"  count requested : {count}\n"
            f"  angles selected : {len(selected)}\n"
            f"  angle names     : {[a['name'] for a in selected]}\n"
            f"{'='*60}"
        )

        for i, angle in enumerate(selected):
            prompt = _build_angle_prompt(product_desc, angle)

            _log.info(
                "packshot_angle [%d/%d]  name=%s  prompt=%r",
                i + 1, len(selected), angle["name"], prompt[:80],
            )
            print(
                f"\n--- API Call #{i+1}/{len(selected)} ---\n"
                f"  Angle  : {angle['name']}\n"
                f"  Prompt : {prompt[:200]}…"
            )

            try:
                img_bytes = self.generate_image(prompt, reference_image_bytes)

                sha = hashlib.sha256(img_bytes).hexdigest()
                hashes.append(sha)
                nb    = len(img_bytes)
                fname = f"{angle['key']}.jpg"

                # Write to disk immediately
                saved_path = None
                if debug_dir:
                    try:
                        saved_path = os.path.join(debug_dir, fname)
                        with open(saved_path, "wb") as _f:
                            _f.write(img_bytes)
                    except Exception as _we:
                        _log.warning("Could not write debug file %s: %s", saved_path, _we)
                        saved_path = None

                _log.info(
                    "packshot_angle OK [%d/%d]  name=%s  bytes=%d  sha256=%s  saved=%s",
                    i + 1, len(selected), angle["name"], nb, sha[:16], saved_path,
                )
                print(
                    f"  Response #{i+1}  : SUCCESS\n"
                    f"  Bytes    : {nb:,}\n"
                    f"  SHA256   : {sha}\n"
                    f"  Saved    : {saved_path or 'NOT SAVED'}"
                )

                results.append({
                    "name":  angle["name"],
                    "label": angle["label"],
                    "key":   angle["key"],
                    "bytes": img_bytes,
                    "error": None,
                })

            except Exception as exc:
                err = str(exc)
                _log.error(
                    "packshot_angle FAILED [%d/%d]  name=%s  error=%s",
                    i + 1, len(selected), angle["name"], err,
                )
                print(
                    f"  Response #{i+1}  : FAILED\n"
                    f"  Error    : {err[:300]}"
                )
                results.append({
                    "name":  angle["name"],
                    "label": angle["label"],
                    "key":   angle["key"],
                    "bytes": None,
                    "error": err,
                })

        # ── Summary ───────────────────────────────────────────────────────────
        total_calls   = len(selected)
        total_ok      = sum(1 for r in results if r.get("bytes"))
        total_failed  = total_calls - total_ok
        unique_hashes = len(set(hashes))

        summary = (
            f"\n{'='*60}\n"
            f"generate_packshot_angles COMPLETE\n"
            f"  Total API Calls          : {total_calls}\n"
            f"  Successful Responses     : {total_ok}\n"
            f"  Failed Responses         : {total_failed}\n"
            f"  Images Saved to Disk     : {total_ok}\n"
            f"  Unique SHA256 Hashes     : {unique_hashes}\n"
            f"  Duplicate images?        : {'YES — same image returned for all calls' if unique_hashes == 1 and total_ok > 1 else 'No'}\n"
            f"  SHA256 list              : {hashes}\n"
            f"{'='*60}\n"
        )
        _log.info(summary)
        print(summary)

        # ── Write debug ZIP ───────────────────────────────────────────────────
        if debug_dir and total_ok > 0:
            try:
                zip_path = os.path.join(debug_dir, "debug_packshot.zip")
                with _zf.ZipFile(zip_path, "w", _zf.ZIP_DEFLATED) as _zout:
                    for r in results:
                        if r.get("bytes"):
                            _zout.writestr(f"{r['key']}.jpg", r["bytes"])
                _log.info("Debug ZIP written: %s  (%d files)", zip_path, total_ok)
                print(f"  Debug ZIP : {zip_path}  ({total_ok} files)")
            except Exception as _ze:
                _log.warning("Could not write debug ZIP: %s", _ze)

        return results

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
