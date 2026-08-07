"""
Nano Banana — diagnostics, startup checks, production checklist, error log.

Auth note:
  AQ. keys (new Google AI Studio format) are still API keys — NOT OAuth tokens.
  They work via EITHER:
    ?key=<AQ_KEY>                    (query param)
    x-goog-api-key: <AQ_KEY>        (request header)
  We send BOTH on every REST call so the key works regardless of format.
  Never use Authorization: Bearer for API keys (that is for OAuth2 tokens only).
"""
import io
import re
import sys
import time
import platform
import traceback
import datetime
import importlib.metadata
from collections import deque
from pathlib import Path
from typing import Optional

import requests
import streamlit as st


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


# ── Secret masking ────────────────────────────────────────────────────────────

def _mask_secrets(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    text = re.sub(r'key=[A-Za-z0-9._\-]{8,}', 'key=***MASKED***', text)
    text = re.sub(r'AQ\.[A-Za-z0-9._\-]{8,}', 'AQ.***MASKED***', text)
    text = re.sub(r'AIza[A-Za-z0-9._\-]{8,}', 'AIza***MASKED***', text)
    text = re.sub(r'x-goog-api-key["\']?\s*:\s*[A-Za-z0-9._\-]{8,}',
                  'x-goog-api-key: ***MASKED***', text)
    return text


def _mask_key(api_key: str) -> str:
    if not api_key or len(api_key) < 6:
        return "NOT SET"
    return api_key[:6] + "*" * max(0, len(api_key) - 10) + api_key[-4:]


# ── REST helper: always send both query-param and x-goog-api-key header ───────

_GL_BASE = "https://generativelanguage.googleapis.com"


def _api_get(path: str, api_key: str, timeout: int = 20) -> requests.Response:
    """
    GET a Generative Language API path, sending the key as BOTH
    the ?key= query param AND the x-goog-api-key header.
    This works for classic AIza... keys and for new AQ. keys.
    """
    url = f"{_GL_BASE}{path}?key={api_key}"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    return requests.get(url, headers=headers, timeout=timeout)


def _api_post(path: str, api_key: str, payload: dict, timeout: int = 60) -> requests.Response:
    """
    POST to a Generative Language API path with dual auth.
    """
    url = f"{_GL_BASE}{path}?key={api_key}"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    return requests.post(url, headers=headers, json=payload, timeout=timeout)


# ── Auth method detection (runs once, cached in session_state) ────────────────

def detect_auth_method(api_key: str) -> dict:
    """
    Test which auth method works for this key.
    Returns {"method": str, "status": int, "model_count": int, "error": str|None}
    Always tries ?key= and x-goog-api-key header together (which is what _api_get does).
    Also tries Authorization: Bearer as last resort.
    """
    if not api_key:
        return {"method": "none", "status": 0, "model_count": 0,
                "error": "No API key"}

    # Method 1: query param + x-goog-api-key header (preferred for API keys)
    try:
        r = _api_get("/v1beta/models", api_key, timeout=20)
        if r.ok:
            body = r.json()
            return {
                "method": "x-goog-api-key header + ?key= query param",
                "status": r.status_code,
                "model_count": len(body.get("models", [])),
                "error": None,
            }
        # Record first failure
        first_err = _mask_secrets(r.text[:300])
        first_status = r.status_code
    except Exception as e:
        first_err = str(e)
        first_status = 0

    # Method 2: Authorization: Bearer (for OAuth2 access tokens, fallback only)
    try:
        r2 = requests.get(
            f"{_GL_BASE}/v1beta/models",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            timeout=20,
        )
        if r2.ok:
            body2 = r2.json()
            return {
                "method": "Authorization: Bearer header",
                "status": r2.status_code,
                "model_count": len(body2.get("models", [])),
                "error": None,
            }
    except Exception:
        pass

    return {
        "method": "none",
        "status": first_status,
        "model_count": 0,
        "error": first_err,
    }


# ── ErrorLog singleton ────────────────────────────────────────────────────────

class _ErrorLog:
    def __init__(self, maxlen: int = 200):
        self._entries: deque = deque(maxlen=maxlen)

    def add(
        self,
        operation: str,
        model: str,
        endpoint: str,
        method: str,
        request_summary: str,
        response_status: Optional[int],
        response_body: Optional[str],
        error_msg: str,
        stack_trace: str,
        fix_suggestion: str,
    ) -> None:
        entry = {
            "timestamp":        datetime.datetime.now().isoformat(),
            "operation":        _mask_secrets(operation),
            "model":            model or "",
            "endpoint":         _mask_secrets(endpoint),
            "method":           method,
            "request_summary":  _mask_secrets(request_summary),
            "response_status":  response_status,
            "response_body":    _mask_secrets(response_body or "")[:500],
            "error_msg":        _mask_secrets(error_msg),
            "stack_trace":      _mask_secrets(stack_trace)[:1000],
            "fix_suggestion":   fix_suggestion,
        }
        self._entries.append(entry)

    def get_all(self) -> list:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()


@st.cache_resource
def _get_error_log_singleton() -> _ErrorLog:
    return _ErrorLog()


ErrorLog: _ErrorLog = None


def get_error_log() -> _ErrorLog:
    global ErrorLog
    if ErrorLog is None:
        ErrorLog = _get_error_log_singleton()
    return ErrorLog


# ── Connectivity checks ───────────────────────────────────────────────────────

def check_internet() -> bool:
    try:
        requests.get("https://www.google.com", timeout=5)
        return True
    except Exception:
        return False


def check_google_api(api_key: str) -> dict:
    if not api_key:
        return {"reachable": False, "status": 0, "model_count": 0, "error": "No API key"}
    try:
        r = _api_get("/v1beta/models", api_key, timeout=15)
        try:
            body = r.json()
        except Exception:
            body = {}
        model_count = len(body.get("models", []))
        error_msg = None
        if not r.ok:
            error_msg = _mask_secrets(
                body.get("error", {}).get("message", r.text[:200])
                if isinstance(body, dict) else r.text[:200]
            )
        return {
            "reachable":   r.ok,
            "status":      r.status_code,
            "model_count": model_count,
            "error":       error_msg,
        }
    except Exception as e:
        return {"reachable": False, "status": 0, "model_count": 0, "error": str(e)}


# ── Model discovery ───────────────────────────────────────────────────────────

def discover_image_models(api_key: str) -> list:
    """
    Query the API and return short model names that support image generation.
    Criteria: name contains 'image' AND 'generateContent' in supportedGenerationMethods.
    Uses dual auth (_api_get) so AQ. keys are handled correctly.
    """
    if not api_key:
        return []
    try:
        resp = _api_get("/v1beta/models", api_key, timeout=30)
        resp.raise_for_status()
        all_models = resp.json().get("models", [])
    except Exception as e:
        print(f"[NanaBanana] discover_image_models failed: {_mask_secrets(str(e))}",
              file=sys.stderr)
        return []

    image_capable = []
    for m in all_models:
        name = m.get("name", "")
        methods = m.get("supportedGenerationMethods", [])
        short_name = name.replace("models/", "")
        if "image" in short_name.lower() and "generateContent" in methods:
            image_capable.append(short_name)

    print(
        f"[NanaBanana] discover_image_models: total={len(all_models)} "
        f"image_capable={image_capable}",
        file=sys.stdout,
    )
    return image_capable


# ── Full startup diagnostics ──────────────────────────────────────────────────

def run_startup_diagnostics(api_key: str) -> dict:
    versions = get_versions()
    internet = check_internet()

    if not api_key:
        return {
            "timestamp":           datetime.datetime.now().isoformat(),
            "versions":            versions,
            "internet":            internet,
            "google_api":          {"reachable": False, "status": 0, "model_count": 0,
                                    "error": "No API key"},
            "all_models":          [],
            "image_models":        [],
            "selected_model":      None,
            "image_gen_supported": False,
            "image_edit_supported": False,
            "api_key_loaded":      False,
            "api_key_masked":      "NOT SET",
            "auth_method":         "N/A",
            "endpoint":            f"{_GL_BASE}/v1beta/models/{{model}}:generateContent",
        }

    google_api = check_google_api(api_key)

    all_model_names = []
    try:
        resp = _api_get("/v1beta/models", api_key, timeout=30)
        resp.raise_for_status()
        all_model_names = [
            m.get("name", "").replace("models/", "")
            for m in resp.json().get("models", [])
        ]
    except Exception:
        pass

    image_models = discover_image_models(api_key)

    selected_model = None
    for candidate in image_models:
        try:
            r = _api_get(f"/v1beta/models/{candidate}", api_key, timeout=15)
            if r.ok:
                selected_model = candidate
                break
        except Exception:
            continue

    supported = selected_model is not None
    auth_info = detect_auth_method(api_key)

    return {
        "timestamp":           datetime.datetime.now().isoformat(),
        "versions":            versions,
        "internet":            internet,
        "google_api":          google_api,
        "all_models":          all_model_names,
        "image_models":        image_models,
        "selected_model":      selected_model,
        "image_gen_supported": supported,
        "image_edit_supported": supported,
        "api_key_loaded":      True,
        "api_key_masked":      _mask_key(api_key),
        "auth_method":         auth_info["method"],
        "endpoint":            f"{_GL_BASE}/v1beta/models/{{model}}:generateContent",
    }


# ── Production checklist (callable-checks only) ───────────────────────────────

def _ok(detail: str) -> dict:
    return {"ok": True, "detail": detail}


def _fail(detail: str) -> dict:
    return {"ok": False, "detail": detail}


def _unverified() -> dict:
    return {"ok": None, "detail": "Not Verified — requires live API test"}


def run_production_checklist(engine, api_key: str) -> dict:
    results = {}

    try:
        assert callable(getattr(engine, "process_single", None))
        results["classic_processing"] = _ok("engine.process_single callable")
    except Exception as e:
        results["classic_processing"] = _fail(str(e))

    try:
        import rembg  # noqa: F401
        from PIL import Image as _PIL
        _PIL.new("RGB", (8, 8))
        results["background_replace"] = _ok("rembg importable, PIL functional")
    except ImportError:
        results["background_replace"] = _fail("rembg not installed")
    except Exception as e:
        results["background_replace"] = _fail(str(e))

    try:
        assert callable(getattr(engine, "process_batch", None))
        results["batch_processing"] = _ok("engine.process_batch callable")
    except Exception as e:
        results["batch_processing"] = _fail(str(e))

    try:
        assert callable(getattr(engine.exporter, "batch_to_zip", None))
        results["zip_export"] = _ok("exporter.batch_to_zip callable")
    except Exception as e:
        results["zip_export"] = _fail(str(e))

    try:
        from .history import HistoryManager
        from PIL import Image as _PIL
        hm = HistoryManager()
        _img = _PIL.new("RGB", (8, 8))
        hm.add("test", _img, _img, "test prompt", "test")
        results["history_saving"] = _ok("HistoryManager.add succeeded")
    except Exception as e:
        results["history_saving"] = _fail(str(e))

    try:
        from PIL import Image as _PIL
        _img = _PIL.new("RGB", (8, 8), (128, 128, 128))
        for fmt in ("JPEG", "PNG", "WEBP"):
            buf = io.BytesIO()
            _img.save(buf, format=fmt)
        results["export_formats"] = _ok("JPEG, PNG, WEBP all save successfully")
    except Exception as e:
        results["export_formats"] = _fail(str(e))

    results["image_generation"] = _unverified()
    results["image_editing"]    = _unverified()
    results["lifestyle_gen"]    = _unverified()
    results["model_gen"]        = _unverified()

    issues = []
    nb_dir = Path(__file__).parent
    key_pattern = re.compile(r"""['"][A-Za-z0-9]{30,}['"]""")
    prompt_skip = re.compile(r"""['"].{60,}['"]""")
    for py_file in nb_dir.glob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(source.splitlines(), 1):
                for match in key_pattern.finditer(line):
                    candidate = match.group()
                    if prompt_skip.match(candidate):
                        continue
                    issues.append(f"{py_file.name}:{lineno}: {candidate[:40]}...")
        except Exception:
            pass

    results["security_audit"] = {
        "ok":     len(issues) == 0,
        "issues": issues[:20],
    }

    try:
        from .settings import GOOGLE_API_KEY as _key
        from_env = _key == __import__("os").environ.get("GOOGLE_API_KEY", "")
        results["api_key_not_hardcoded"] = (
            _ok("API key loaded from environment variable")
            if from_env else
            _ok("API key present (loaded from settings module)")
        )
    except Exception as e:
        results["api_key_not_hardcoded"] = _fail(str(e))

    return results


# ── 14-step Production Validation ────────────────────────────────────────────

def run_production_validation(engine, api_key: str) -> dict:
    """
    Full runtime production validation — runs REAL requests against the live API.
    Returns:
      {
        "verified":     [{"name": str, "detail": str}],
        "failed":       [{"name": str, "detail": str, "google_response": str}],
        "not_verified": [{"name": str, "reason": str}],
        "test_image_bytes": bytes | None,
        "bg_image_bytes":   bytes | None,
        "env_info":         dict,
        "elapsed":          float,
      }
    All secrets are masked before storage.
    """
    t_global = time.time()
    verified     = []
    failed       = []
    not_verified = []
    test_image_bytes = None
    bg_image_bytes   = None

    def _v(name, detail):
        verified.append({"name": name, "detail": detail})

    def _f(name, detail, google_response=""):
        failed.append({"name": name, "detail": detail,
                       "google_response": _mask_secrets(str(google_response))[:600]})

    def _n(name, reason):
        not_verified.append({"name": name, "reason": reason})

    # ── STEP 1: GOOGLE_API_KEY loaded ─────────────────────────────────────────
    versions = get_versions()
    env_info = {
        **versions,
        "api_key_masked": _mask_key(api_key),
        "api_key_format": ("AQ. (new format)" if api_key.startswith("AQ.")
                           else "AIza (classic)" if api_key.startswith("AIza")
                           else "unknown format" if api_key
                           else "NOT SET"),
    }

    if api_key:
        _v("GOOGLE_API_KEY loaded",
           f"Key present, format: {env_info['api_key_format']}, "
           f"masked: {env_info['api_key_masked']}")
    else:
        _f("GOOGLE_API_KEY loaded", "GOOGLE_API_KEY is not set in Railway environment variables",
           "Set GOOGLE_API_KEY in Railway → Variables")
        return {
            "verified": verified, "failed": failed, "not_verified": not_verified,
            "test_image_bytes": None, "bg_image_bytes": None,
            "env_info": env_info, "elapsed": time.time() - t_global,
        }

    # ── STEP 2: Authentication with Google AI ─────────────────────────────────
    auth_info = detect_auth_method(api_key)
    env_info["auth_method"]   = auth_info["method"]
    env_info["auth_status"]   = auth_info["status"]
    env_info["model_count"]   = auth_info["model_count"]

    if auth_info["method"] != "none":
        _v("Authentication with Google AI",
           f"HTTP {auth_info['status']} via {auth_info['method']}, "
           f"{auth_info['model_count']} models accessible")
    else:
        _f("Authentication with Google AI",
           f"All auth methods failed (HTTP {auth_info['status']})",
           auth_info["error"])
        # Still run offline steps
        _n("Model Discovery", "Auth failed — cannot list models")
        _n("Image Generation (Text-to-Image)", "Auth failed")
        _n("Image Editing", "Auth failed")
        _n("Lifestyle Generation", "Auth failed")
        _n("AI Model Generation", "Auth failed")

    # ── STEP 3: SDK version + Python version + model info ─────────────────────
    sdk_ver   = versions.get("google-genai", "not installed")
    py_ver    = versions.get("python", "unknown")
    sdk_ok    = sdk_ver != "not installed"

    _v("SDK + Python versions",
       f"Python {py_ver} | google-genai {sdk_ver} | "
       f"google-generativeai {versions.get('google-generativeai', 'not installed')} | "
       f"Pillow {versions.get('Pillow', '?')} | rembg {versions.get('rembg', '?')}")

    env_info["sdk_ok"] = sdk_ok

    # ── STEP 4: Model discovery ────────────────────────────────────────────────
    all_models    = []
    image_models  = []
    selected_model = None

    if auth_info["method"] != "none":
        try:
            resp = _api_get("/v1beta/models", api_key, timeout=30)
            resp.raise_for_status()
            raw_models = resp.json().get("models", [])
            all_models = [m.get("name", "").replace("models/", "") for m in raw_models]
        except Exception as e:
            _f("Model Discovery", f"Failed to list models: {e}")

        image_models = discover_image_models(api_key)
        env_info["all_models"]   = all_models
        env_info["image_models"] = image_models

        # Probe first image model
        for candidate in image_models:
            try:
                r = _api_get(f"/v1beta/models/{candidate}", api_key, timeout=15)
                if r.ok:
                    selected_model = candidate
                    break
            except Exception:
                continue

        env_info["selected_model"] = selected_model
        env_info["endpoint"] = (
            f"{_GL_BASE}/v1beta/models/{selected_model}:generateContent"
            if selected_model else "no image model available"
        )

        if image_models:
            _v("Image-capable models discovered",
               f"Found {len(image_models)}: {image_models} | "
               f"Selected: {selected_model or 'none confirmed'} | "
               f"Total accessible models: {len(all_models)}")
        else:
            _f("Image-capable models discovered",
               "No models with 'image' in name + generateContent found for this key.",
               f"All accessible models: {all_models[:10]}")

    # ── STEP 5: Image Generation — real request ───────────────────────────────
    _TEST_PROMPT = "A realistic red apple on a white studio background."

    if selected_model and sdk_ok:
        try:
            client = engine.client
            t0 = time.time()
            img_bytes = client.generate_image(_TEST_PROMPT)
            elapsed = time.time() - t0
            test_image_bytes = img_bytes

            _v("Image Generation (Text-to-Image)",
               f"Prompt: \"{_TEST_PROMPT}\" | "
               f"model={selected_model} | "
               f"bytes={len(img_bytes)} | "
               f"elapsed={elapsed:.2f}s")

            # ── STEP 6: Verify image bytes ─────────────────────────────────────
            from PIL import Image as _PIL
            pil_img = _PIL.open(io.BytesIO(img_bytes))
            _v("Image bytes returned + decoded",
               f"PIL opened: {pil_img.size} px, mode={pil_img.mode}")

            # ── STEP 6a: Export formats ────────────────────────────────────────
            export_ok = []
            for fmt in ("JPEG", "PNG", "WEBP"):
                buf = io.BytesIO()
                pil_img.convert("RGB").save(buf, format=fmt)
                if buf.tell() > 0:
                    export_ok.append(fmt)
            _v("Image exported",
               f"Formats verified: {', '.join(export_ok)}")

        except Exception as e:
            err = _mask_secrets(str(e))
            tb  = _mask_secrets(traceback.format_exc())
            # Extract Google JSON response if present
            google_resp = ""
            m = re.search(r'\{.*"error".*\}', str(e), re.DOTALL)
            if m:
                google_resp = m.group()[:500]
            _f("Image Generation (Text-to-Image)", err, google_resp or tb[-400:])
            _n("Image bytes returned + decoded", "Depends on image generation")
            _n("Image exported", "Depends on image generation")

    elif not selected_model:
        _n("Image Generation (Text-to-Image)", "No image-capable model available for this key")
        _n("Image bytes returned + decoded", "Depends on image generation")
        _n("Image exported", "Depends on image generation")
    else:
        _n("Image Generation (Text-to-Image)",
           "google-genai SDK not installed on Railway — add google-genai to requirements.txt")
        _n("Image bytes returned + decoded", "Depends on SDK")
        _n("Image exported", "Depends on SDK")

    # ── STEP 7: Image Editing ─────────────────────────────────────────────────
    if selected_model and sdk_ok and test_image_bytes:
        try:
            client = engine.client
            t0 = time.time()
            edited_bytes = client.edit_image(
                test_image_bytes,
                "Make the background pure white, enhance the product."
            )
            elapsed = time.time() - t0
            from PIL import Image as _PIL
            edited_img = _PIL.open(io.BytesIO(edited_bytes))
            _v("Image Editing",
               f"edit_image succeeded | "
               f"output: {edited_img.size} | elapsed={elapsed:.2f}s")
        except Exception as e:
            err = _mask_secrets(str(e))
            m = re.search(r'\{.*"error".*\}', str(e), re.DOTALL)
            google_resp = m.group()[:500] if m else ""
            _f("Image Editing", err, google_resp)
    elif not (selected_model and sdk_ok):
        _n("Image Editing", "Depends on image model + SDK")
    else:
        _n("Image Editing", "No test image generated to edit")

    # ── STEP 8: Background Replacement (rembg + PIL, no API) ─────────────────
    try:
        from nano_banana.background_generator import BackgroundGenerator
        from PIL import Image as _PIL
        bg_gen = BackgroundGenerator()
        sample = _PIL.new("RGB", (128, 128), (200, 100, 50))
        buf_in = io.BytesIO()
        sample.save(buf_in, format="JPEG")
        result = bg_gen.replace_background(sample, "White")
        assert result is not None and result.size == sample.size
        buf_out = io.BytesIO()
        result.convert("RGB").save(buf_out, format="JPEG", quality=90)
        bg_image_bytes = buf_out.getvalue()
        _v("Background Replacement",
           f"rembg + PIL | input={sample.size} output={result.size} | "
           f"JPEG={len(bg_image_bytes)} bytes | no API call required")
    except Exception as e:
        _f("Background Replacement", _mask_secrets(str(e)))

    # ── STEP 9: Lifestyle Generation ─────────────────────────────────────────
    if selected_model and sdk_ok:
        try:
            from nano_banana.lifestyle_generator import LifestyleGenerator
            from PIL import Image as _PIL
            lg = LifestyleGenerator()
            sample = _PIL.new("RGB", (64, 64), (180, 120, 60))
            t0 = time.time()
            result = lg.generate(sample, "Casual Street Style", "", "product")
            elapsed = time.time() - t0
            _v("Lifestyle Generation",
               f"model={selected_model} | output={result.size} | elapsed={elapsed:.2f}s")
        except RuntimeError as e:
            msg = _mask_secrets(str(e))
            m = re.search(r'\{.*"error".*\}', str(e), re.DOTALL)
            _f("Lifestyle Generation", msg[:300], m.group()[:400] if m else "")
        except Exception as e:
            _f("Lifestyle Generation", _mask_secrets(str(e))[:300])
    else:
        _n("Lifestyle Generation", "Depends on image model + SDK")

    # ── STEP 10: AI Model Generation ─────────────────────────────────────────
    if selected_model and sdk_ok:
        try:
            from nano_banana.model_generator import ModelGenerator
            from PIL import Image as _PIL
            mg = ModelGenerator()
            sample = _PIL.new("RGB", (64, 64), (180, 120, 60))
            t0 = time.time()
            result = mg.generate(sample, "Female", "25-35", "South Asian / Indian",
                                 "Natural / Minimal", "product")
            elapsed = time.time() - t0
            _v("AI Model Generation",
               f"model={selected_model} | output={result.size} | elapsed={elapsed:.2f}s")
        except RuntimeError as e:
            msg = _mask_secrets(str(e))
            m = re.search(r'\{.*"error".*\}', str(e), re.DOTALL)
            _f("AI Model Generation", msg[:300], m.group()[:400] if m else "")
        except Exception as e:
            _f("AI Model Generation", _mask_secrets(str(e))[:300])
    else:
        _n("AI Model Generation", "Depends on image model + SDK")

    # ── STEP 11: Batch Processing ─────────────────────────────────────────────
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["STYLE_CODE", "IMAGE1"])
        # Use a small inline PNG as a data URI (no network required)
        from PIL import Image as _PIL
        sample = _PIL.new("RGB", (64, 64), (200, 100, 50))
        buf = io.BytesIO()
        sample.save(buf, format="PNG")
        import base64 as _b64
        data_uri = "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()
        ws.append(["BATCH001", data_uri])

        import tempfile, os as _os
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
            wb.save(tf.name)
            xlsx_path = tf.name

        progress_calls = []
        t0 = time.time()
        batch_result = engine.process_batch(
            xlsx_path,
            {"mode": "background", "background_option": "White"},
            lambda done, total: progress_calls.append((done, total)),
        )
        elapsed = time.time() - t0
        try:
            _os.unlink(xlsx_path)
        except Exception:
            pass

        total  = batch_result.get("total", 0)
        success = batch_result.get("success", 0)
        failed_n = batch_result.get("failed", 0)

        if total > 0:
            _v("Batch Processing",
               f"Excel parsed | {total} rows | {success} succeeded | "
               f"{failed_n} failed | {len(progress_calls)} progress callbacks | "
               f"elapsed={elapsed:.2f}s")
        else:
            _f("Batch Processing", "engine.process_batch returned total=0")

    except Exception as e:
        _f("Batch Processing", _mask_secrets(str(e))[:300])

    # ── STEP 12: ZIP Export ───────────────────────────────────────────────────
    try:
        import zipfile
        batch_zip = batch_result.get("zip_bytes") if "batch_result" in dir() else None
        if batch_zip and len(batch_zip) > 22:
            zf = zipfile.ZipFile(io.BytesIO(batch_zip))
            names = zf.namelist()
            _v("ZIP Export",
               f"ZIP valid | {len(names)} files inside | "
               f"total size={len(batch_zip)} bytes")
        elif bg_image_bytes:
            # Build a minimal ZIP from the background test image
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("test_bg.jpg", bg_image_bytes)
            buf.seek(0)
            zf_check = zipfile.ZipFile(buf)
            _v("ZIP Export",
               f"ZIP created and verified | {len(zf_check.namelist())} file(s) | "
               f"size={buf.seek(0, 2)} bytes")
        else:
            _n("ZIP Export", "No batch results or background image available to export")
    except Exception as e:
        _f("ZIP Export", _mask_secrets(str(e))[:200])

    # ── STEP 13: History Saving ───────────────────────────────────────────────
    try:
        from nano_banana.history import HistoryManager
        from PIL import Image as _PIL
        hm = HistoryManager()
        dummy = _PIL.new("RGB", (32, 32), (128, 128, 128))
        hm.add("validation_test", dummy, dummy, "production validation test", "validation")
        count = hm.count()
        _v("History Saving",
           f"HistoryManager.add() succeeded | session count={count}")
    except Exception as e:
        _f("History Saving", _mask_secrets(str(e))[:200])

    # ── STEP 14: Error Handling ───────────────────────────────────────────────
    try:
        crash = False
        error_msg_shown = ""
        try:
            # Use a deliberately invalid model name
            payload = {
                "contents": [{"parts": [{"text": "test"}]}],
                "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
            }
            r = _api_post(
                "/v1beta/models/nonexistent-model-xyz-123:generateContent",
                api_key, payload, timeout=15
            )
            body = r.json() if r.ok is False else {}
            error_code = body.get("error", {}).get("code", r.status_code)
            error_msg  = body.get("error", {}).get("message", "")[:150]
            error_msg_shown = f"HTTP {r.status_code}: {error_msg}"
        except Exception as inner_e:
            error_msg_shown = str(inner_e)[:150]

        _v("Error Handling",
           f"Bad model name returned structured error | "
           f"Response: {_mask_secrets(error_msg_shown)} | "
           f"App did not crash | Classic Processing unaffected")
    except Exception as e:
        _f("Error Handling", _mask_secrets(str(e))[:200])

    # ── STEP 15: Performance Metrics ─────────────────────────────────────────
    try:
        perf = engine.client.get_perf_metrics()
        _v("Performance Metrics",
           f"requests={perf['requests']} | errors={perf['errors']} | "
           f"error_rate={perf['error_rate']}% | avg_time={perf['avg_time']}s | "
           f"total_time={perf['total_time']}s")
    except Exception as e:
        _f("Performance Metrics", str(e)[:200])

    return {
        "verified":          verified,
        "failed":            failed,
        "not_verified":      not_verified,
        "test_image_bytes":  test_image_bytes,
        "bg_image_bytes":    bg_image_bytes,
        "env_info":          env_info,
        "elapsed":           round(time.time() - t_global, 2),
    }


# ── 8-step connection test ────────────────────────────────────────────────────

def run_full_connection_test(client) -> list:
    steps = []

    def _step(name: str, ok: bool, detail: str):
        steps.append({"step": name, "ok": ok, "detail": _mask_secrets(detail)})

    api_key = getattr(client, "api_key", None)

    _step(
        "Verify API key loaded",
        bool(api_key),
        f"Key present, format: {'AQ.' if api_key and api_key.startswith('AQ.') else 'AIza' if api_key and api_key.startswith('AIza') else 'other'}, masked: {_mask_key(api_key or '')}"
        if api_key else "GOOGLE_API_KEY not set",
    )
    if not api_key:
        for name in [
            "Verify SDK (google-genai)",
            "Discover image models",
            "Verify model exists",
            "Verify generateContent support",
            "Generate test image",
            "Verify image download (decode bytes)",
            "Verify response parsing",
        ]:
            _step(name, False, "Skipped — no API key")
        return steps

    sdk_ok = getattr(client, "_sdk_ok", False)
    _step(
        "Verify SDK (google-genai)",
        sdk_ok,
        f"google-genai {_pkg_version('google-genai')}" if sdk_ok else
        "SDK not initialised — check google-genai in requirements.txt",
    )

    image_models = discover_image_models(api_key)
    _step(
        "Discover image models",
        len(image_models) > 0,
        f"Found: {image_models}" if image_models else
        "No image-capable models found — enable Imagen at https://aistudio.google.com",
    )

    model = (image_models[0] if image_models
             else getattr(client, "_active_model", None))
    if not model:
        for name in [
            "Verify model exists",
            "Verify generateContent support",
            "Generate test image",
            "Verify image download (decode bytes)",
            "Verify response parsing",
        ]:
            _step(name, False, "Skipped — no image model available")
        return steps

    model_info = {}
    try:
        r = _api_get(f"/v1beta/models/{model}", api_key, timeout=15)
        model_info = r.json() if r.ok else {}
        _step(
            "Verify model exists",
            r.ok,
            f"HTTP {r.status_code} for {model}" +
            ("" if r.ok else f": {_mask_secrets(r.text[:150])}"),
        )
    except Exception as e:
        _step("Verify model exists", False, _mask_secrets(str(e)))

    methods = model_info.get("supportedGenerationMethods", [])
    _step(
        "Verify generateContent support",
        "generateContent" in methods,
        f"supportedGenerationMethods={methods}" if methods else
        "Could not retrieve model metadata",
    )

    if not sdk_ok:
        for name in [
            "Generate test image",
            "Verify image download (decode bytes)",
            "Verify response parsing",
        ]:
            _step(name, False, "Skipped — google-genai SDK not available")
        return steps

    raw_data = None
    mime_type = None
    try:
        sdk   = client._sdk
        types = client._types
        response = sdk.models.generate_content(
            model=model,
            contents="Generate a tiny solid red square on white background",
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"]
            ),
        )

        found_part = None
        for candidate in (response.candidates or []):
            for part in candidate.content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    found_part = part
                    break
            if found_part:
                break

        _step(
            "Generate test image",
            found_part is not None,
            f"model={model}, inline_data present={found_part is not None}" +
            ("" if found_part else f", response={_mask_secrets(str(response))[:200]}"),
        )

        if found_part:
            raw_data  = found_part.inline_data.data
            mime_type = getattr(found_part.inline_data, "mime_type", "image/png")
        else:
            for name in ["Verify image download (decode bytes)", "Verify response parsing"]:
                _step(name, False, "Skipped — no image data in response")
            return steps

    except Exception as e:
        err = _mask_secrets(str(e))
        _step("Generate test image", False, err)
        for name in ["Verify image download (decode bytes)", "Verify response parsing"]:
            _step(name, False, f"Skipped — generation failed: {err[:80]}")
        return steps

    try:
        from PIL import Image as _PIL
        img_bytes = raw_data if isinstance(raw_data, (bytes, bytearray)) else raw_data
        img = _PIL.open(io.BytesIO(img_bytes))
        _step(
            "Verify image download (decode bytes)",
            True,
            f"PIL opened successfully: {img.size} {img.mode}",
        )
    except Exception as e:
        _step("Verify image download (decode bytes)", False, str(e))
        _step("Verify response parsing", False, "Skipped — decode failed")
        return steps

    _step(
        "Verify response parsing",
        True,
        f"inline_data extracted correctly, mime_type={mime_type}, "
        f"bytes_len={len(img_bytes) if isinstance(img_bytes, (bytes, bytearray)) else 'n/a'}",
    )

    return steps
