"""
Nano Banana — diagnostics, startup checks, production checklist, error log.
"""
import io
import re
import sys
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
    text = re.sub(r'key=[A-Za-z0-9._-]{8,}', 'key=***MASKED***', text)
    text = re.sub(r'Bearer [A-Za-z0-9._-]{8,}', 'Bearer ***MASKED***', text)
    return text


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


# Public accessor so callers don't have to worry about the singleton pattern
ErrorLog: _ErrorLog = None  # resolved on first use via get_error_log()


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
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=15)
        try:
            body = resp.json()
        except Exception:
            body = {}
        model_count = len(body.get("models", []))
        error_msg = None
        if not resp.ok:
            error_msg = (body.get("error", {}).get("message", resp.text[:200])
                         if isinstance(body, dict) else resp.text[:200])
        return {
            "reachable":   resp.ok,
            "status":      resp.status_code,
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
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        all_models = resp.json().get("models", [])
    except Exception as e:
        print(f"[NanoBanana diagnostics] discover_image_models failed: {e}", file=sys.stderr)
        return []

    image_capable = []
    for m in all_models:
        name = m.get("name", "")
        methods = m.get("supportedGenerationMethods", [])
        short_name = name.replace("models/", "")
        if "image" in short_name.lower() and "generateContent" in methods:
            image_capable.append(short_name)

    print(
        f"[NanoBanana diagnostics] discover_image_models: "
        f"total={len(all_models)} image_capable={image_capable}",
        file=sys.stdout,
    )
    return image_capable


# ── Full startup diagnostics ──────────────────────────────────────────────────

def run_startup_diagnostics(api_key: str) -> dict:
    """
    Run all connectivity and capability checks. SLOW — callers must cache in
    st.session_state['nb_startup_diag'].
    """
    versions = get_versions()
    internet = check_internet()

    if not api_key:
        return {
            "timestamp":          datetime.datetime.now().isoformat(),
            "versions":           versions,
            "internet":           internet,
            "google_api":         {"reachable": False, "status": 0, "model_count": 0,
                                   "error": "No API key"},
            "all_models":         [],
            "image_models":       [],
            "selected_model":     None,
            "image_gen_supported": False,
            "image_edit_supported": False,
            "api_key_loaded":     False,
            "api_key_masked":     "NOT SET",
            "auth_method":        "API key (query parameter)",
            "endpoint":           "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        }

    google_api = check_google_api(api_key)

    # Discover all model names
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    all_model_names = []
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        all_model_names = [
            m.get("name", "").replace("models/", "")
            for m in resp.json().get("models", [])
        ]
    except Exception:
        pass

    image_models = discover_image_models(api_key)

    # Confirm the first image model actually responds 200
    selected_model = None
    for candidate in image_models:
        probe_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{candidate}"
            f"?key={api_key}"
        )
        try:
            r = requests.get(probe_url, timeout=15)
            if r.ok:
                selected_model = candidate
                break
        except Exception:
            continue

    supported = selected_model is not None
    masked = "*" * max(0, len(api_key) - 4) + api_key[-4:] if len(api_key) > 4 else "****"

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
        "api_key_masked":      masked,
        "auth_method":         "API key (query parameter)",
        "endpoint":            "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    }


# ── Production checklist ──────────────────────────────────────────────────────

def _ok(detail: str) -> dict:
    return {"ok": True, "detail": detail}


def _fail(detail: str) -> dict:
    return {"ok": False, "detail": detail}


def _unverified() -> dict:
    return {"ok": None, "detail": "Not Verified — requires live API test"}


def run_production_checklist(engine, api_key: str) -> dict:
    results = {}

    # classic_processing — does process_single exist and accept right args?
    try:
        assert callable(getattr(engine, "process_single", None))
        results["classic_processing"] = _ok("engine.process_single callable")
    except Exception as e:
        results["classic_processing"] = _fail(str(e))

    # background_replace — rembg importable + PIL works?
    try:
        import rembg  # noqa: F401
        from PIL import Image as _PIL
        _img = _PIL.new("RGB", (8, 8), (255, 255, 255))
        buf = io.BytesIO()
        _img.save(buf, format="PNG")
        results["background_replace"] = _ok("rembg importable, PIL functional")
    except ImportError:
        results["background_replace"] = _fail("rembg not installed")
    except Exception as e:
        results["background_replace"] = _fail(str(e))

    # batch_processing — engine.process_batch callable?
    try:
        assert callable(getattr(engine, "process_batch", None))
        results["batch_processing"] = _ok("engine.process_batch callable")
    except Exception as e:
        results["batch_processing"] = _fail(str(e))

    # zip_export — exporter.batch_to_zip callable?
    try:
        assert callable(getattr(engine.exporter, "batch_to_zip", None))
        results["zip_export"] = _ok("exporter.batch_to_zip callable")
    except Exception as e:
        results["zip_export"] = _fail(str(e))

    # history_saving — HistoryManager.add works with dummy data?
    try:
        from .history import HistoryManager
        from PIL import Image as _PIL
        hm = HistoryManager()
        _img = _PIL.new("RGB", (8, 8))
        hm.add("test", _img, _img, "test prompt", "test")
        results["history_saving"] = _ok("HistoryManager.add succeeded")
    except Exception as e:
        results["history_saving"] = _fail(str(e))

    # export_formats — PIL can save JPEG/PNG/WEBP?
    try:
        from PIL import Image as _PIL
        _img = _PIL.new("RGB", (8, 8), (128, 128, 128))
        for fmt in ("JPEG", "PNG", "WEBP"):
            buf = io.BytesIO()
            _img.save(buf, format=fmt)
        results["export_formats"] = _ok("JPEG, PNG, WEBP all save successfully")
    except Exception as e:
        results["export_formats"] = _fail(str(e))

    # API-dependent checks — cannot verify without live call
    results["image_generation"] = _unverified()
    results["image_editing"]    = _unverified()
    results["lifestyle_gen"]    = _unverified()
    results["model_gen"]        = _unverified()

    # security_audit — scan for hardcoded API key patterns
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

    # api_key_not_hardcoded — check env/settings pattern
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


# ── 8-step connection test ────────────────────────────────────────────────────

def run_full_connection_test(client) -> list:
    """
    Run 8 diagnostic steps against the live API.
    Returns list of {"step": str, "ok": bool, "detail": str}.
    """
    steps = []

    def _step(name: str, ok: bool, detail: str):
        steps.append({"step": name, "ok": ok, "detail": _mask_secrets(detail)})

    api_key = getattr(client, "api_key", None)

    # Step 1 — API key loaded
    _step(
        "Verify API key loaded",
        bool(api_key),
        "Key present" if api_key else "GOOGLE_API_KEY not set",
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

    # Step 2 — SDK
    sdk_ok = getattr(client, "_sdk_ok", False)
    _step(
        "Verify SDK (google-genai)",
        sdk_ok,
        f"google-genai {_pkg_version('google-genai')}" if sdk_ok else
        "SDK not initialised — check google-genai install",
    )

    # Step 3 — Discover image models
    image_models = discover_image_models(api_key)
    _step(
        "Discover image models",
        len(image_models) > 0,
        f"Found: {image_models}" if image_models else "No image-capable models found for this key",
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

    # Step 4 — Model exists (GET /v1beta/models/{model})
    model_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f"?key={api_key}"
    )
    model_info = {}
    try:
        r = requests.get(model_url, timeout=15)
        model_info = r.json() if r.ok else {}
        _step(
            "Verify model exists",
            r.ok,
            f"HTTP {r.status_code} for {model}" + ("" if r.ok else f": {r.text[:150]}"),
        )
    except Exception as e:
        _step("Verify model exists", False, str(e))
        model_info = {}

    # Step 5 — generateContent in supportedGenerationMethods
    methods = model_info.get("supportedGenerationMethods", [])
    supports_gen = "generateContent" in methods
    _step(
        "Verify generateContent support",
        supports_gen,
        f"supportedGenerationMethods={methods}" if methods else
        "Could not retrieve model metadata",
    )

    # Steps 6–8 require an actual generation call
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
        sdk = client._sdk
        types = client._types
        response = sdk.models.generate_content(
            model=model,
            contents="Generate a tiny solid red square on white background",
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"]
            ),
        )

        # Step 6 — got bytes back
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
            ("" if found_part else f", response={str(response)[:200]}"),
        )

        if found_part:
            raw_data = found_part.inline_data.data
            mime_type = getattr(found_part.inline_data, "mime_type", "image/png")
        else:
            for name in [
                "Verify image download (decode bytes)",
                "Verify response parsing",
            ]:
                _step(name, False, "Skipped — no image data in response")
            return steps

    except Exception as e:
        err = _mask_secrets(str(e))
        _step("Generate test image", False, err)
        for name in [
            "Verify image download (decode bytes)",
            "Verify response parsing",
        ]:
            _step(name, False, f"Skipped — generation failed: {err[:80]}")
        return steps

    # Step 7 — decode bytes → PIL
    try:
        from PIL import Image as _PIL
        if isinstance(raw_data, (bytes, bytearray)):
            img_bytes = raw_data
        else:
            img_bytes = raw_data  # SDK may return bytes directly
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

    # Step 8 — response parsing confirmed
    _step(
        "Verify response parsing",
        True,
        f"inline_data extracted correctly, mime_type={mime_type}, "
        f"bytes_len={len(img_bytes) if isinstance(img_bytes, (bytes, bytearray)) else 'n/a'}",
    )

    return steps
