"""
Psydox Studio — tool executors (no streamlit dependency).

This module contains the pure execution logic so it can be imported
in test environments where streamlit is not available.
"""
from __future__ import annotations

import io
import logging

from psydox.access import require_owner

_log = logging.getLogger("psydox.studio.executor")


def execute_tool(tool_id: str, inputs: dict, user_email: str) -> dict:
    """Route a tool call to the appropriate backend service.

    AI tools raise PermissionError internally via require_owner(),
    which is caught here and returned as a structured error dict.
    This is the server-side access gate — the UI should hide AI tools
    for non-owners, but this ensures bypass-resistance.
    """
    try:
        if tool_id == "background":
            return _exec_background(inputs)
        if tool_id == "resize":
            return _exec_resize(inputs)
        if tool_id == "crop":
            return _exec_crop(inputs)
        if tool_id in ("packshot", "marketplace"):
            return _exec_classic(inputs)
        if tool_id in ("ai_background", "ai_scene"):
            require_owner(user_email)
            return _exec_background(inputs)
        if tool_id == "ai_lifestyle":
            require_owner(user_email)
            return _exec_lifestyle(inputs)
        if tool_id == "ai_model":
            require_owner(user_email)
            return _exec_model_gen(inputs)
        return {"success": False, "errors": [f"Unknown tool: {tool_id}"], "outputs": [], "metadata": {}}
    except PermissionError as e:
        return {"success": False, "errors": [str(e)], "outputs": [], "metadata": {}}
    except Exception as e:
        _log.exception("Tool %s execution failed", tool_id)
        return {"success": False, "errors": [str(e)], "outputs": [], "metadata": {}}


# ── Backend connectors ────────────────────────────────────────────────────────

def _exec_background(inputs: dict) -> dict:
    from psydox.features.background.service import BackgroundFeature
    return BackgroundFeature().execute(inputs, {})


def _exec_classic(inputs: dict) -> dict:
    from psydox.features.classic.service import ClassicFeature
    return ClassicFeature().execute(inputs, {})


def _exec_resize(inputs: dict) -> dict:
    """PIL resize — direct implementation for reliability."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(inputs["image_bytes"])).convert("RGB")
        tw  = inputs.get("target_w", img.width)
        th  = inputs.get("target_h", img.height)
        fit = inputs.get("fit_mode", "fit")

        if fit == "stretch":
            out = img.resize((tw, th), Image.LANCZOS)
        elif fit == "fill":
            scale = max(tw / img.width, th / img.height)
            nw, nh = int(img.width * scale), int(img.height * scale)
            tmp  = img.resize((nw, nh), Image.LANCZOS)
            left = (nw - tw) // 2
            top  = (nh - th) // 2
            out  = tmp.crop((left, top, left + tw, top + th))
        else:  # fit (letterbox)
            img.thumbnail((tw, th), Image.LANCZOS)
            canvas = Image.new("RGB", (tw, th), (255, 255, 255))
            canvas.paste(img, ((tw - img.width) // 2, (th - img.height) // 2))
            out = canvas

        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=95)
        return {
            "success": True,
            "outputs": [{"bytes": buf.getvalue(), "label": f"Resized {tw}×{th}", "mime": "image/jpeg"}],
            "errors": [], "metadata": {},
        }
    except Exception as e:
        return {"success": False, "outputs": [], "errors": [str(e)], "metadata": {}}


def _exec_crop(inputs: dict) -> dict:
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(inputs["image_bytes"])).convert("RGB")
        box = inputs.get("crop_box")
        if not box:
            return {"success": False, "errors": ["No crop box provided."], "outputs": [], "metadata": {}}
        left, top, right, bottom = [int(x) for x in box]
        left   = max(0, left);    top    = max(0, top)
        right  = min(img.width, right);  bottom = min(img.height, bottom)
        out    = img.crop((left, top, right, bottom))
        buf    = io.BytesIO()
        out.save(buf, "JPEG", quality=95)
        return {
            "success": True,
            "outputs": [{"bytes": buf.getvalue(), "label": "Cropped", "mime": "image/jpeg"}],
            "errors": [], "metadata": {},
        }
    except Exception as e:
        return {"success": False, "outputs": [], "errors": [str(e)], "metadata": {}}


def exec_enhance(image_bytes: bytes, brightness: float = 1.0, contrast: float = 1.0,
                 saturation: float = 1.0, sharpness: float = 1.0) -> bytes | None:
    """PIL enhance — returns result bytes or None on failure."""
    from PIL import Image, ImageEnhance
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if brightness != 1.0: img = ImageEnhance.Brightness(img).enhance(brightness)
        if contrast   != 1.0: img = ImageEnhance.Contrast(img).enhance(contrast)
        if saturation != 1.0: img = ImageEnhance.Color(img).enhance(saturation)
        if sharpness  != 1.0: img = ImageEnhance.Sharpness(img).enhance(sharpness)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        return buf.getvalue()
    except Exception as e:
        _log.warning("exec_enhance failed: %s", e)
        return None


def _exec_lifestyle(inputs: dict) -> dict:
    from psydox.features.lifestyle.service import LifestyleFeature
    return LifestyleFeature().execute(inputs, {})


def _exec_model_gen(inputs: dict) -> dict:
    from psydox.features.model_gen.service import ModelGenFeature
    return ModelGenFeature().execute(inputs, {})
