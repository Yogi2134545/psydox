"""
Psydox Studio — tool executors (no streamlit dependency).

This module contains the pure execution logic so it can be imported
in test environments where streamlit is not available.
"""
from __future__ import annotations

import io
import logging

from psydox.access import require_ai_permission

_log = logging.getLogger("psydox.studio.executor")


def execute_tool(tool_id: str, inputs: dict, user_email: str) -> dict:
    """Route a tool call to the appropriate backend service.

    AI tools are gated by require_ai_permission() which allows
    owner / admin / manager / editor / creative roles.
    This is the server-side access gate — the UI should hide AI tools
    for non-permitted roles, but this ensures bypass-resistance.
    """
    try:
        if tool_id == "background":
            _ai_bg = {"studio", "lifestyle", "outdoor", "editorial", "custom ai", "custom_ai"}
            if (inputs.get("bg_type") or "").lower() in _ai_bg:
                require_ai_permission(user_email)
            return _exec_background(inputs)
        if tool_id == "resize":
            return _exec_resize(inputs)
        if tool_id == "crop":
            return _exec_crop(inputs)
        if tool_id in ("packshot", "marketplace"):
            return _exec_classic(inputs)
        if tool_id in ("ai_background", "ai_scene"):
            require_ai_permission(user_email)
            return _exec_background(inputs)
        if tool_id == "ai_lifestyle":
            require_ai_permission(user_email)
            return _exec_lifestyle(inputs)
        if tool_id == "ai_model":
            require_ai_permission(user_email)
            return _exec_model_gen(inputs)
        if tool_id == "ai_angles":
            require_ai_permission(user_email)
            return execute_angle_generation(inputs, user_email)
        if tool_id == "jadu_ka_ghar":
            require_ai_permission(user_email)
            return _exec_jadu_ka_ghar(inputs)
        if tool_id == "masking":
            return _exec_masking(inputs)
        return {"success": False, "errors": [f"Unknown tool: {tool_id}"], "outputs": [], "metadata": {}}
    except PermissionError as e:
        return {"success": False, "errors": [str(e)], "outputs": [], "metadata": {}}
    except Exception as e:
        _log.exception("Tool %s execution failed", tool_id)
        return {"success": False, "errors": [str(e)], "outputs": [], "metadata": {}}


# ── Backend connectors ────────────────────────────────────────────────────────

def _exec_background(inputs: dict) -> dict:
    ctx = _build_context(inputs)
    if inputs.get("_ratio_wh"):
        ctx["ratio_wh"] = inputs["_ratio_wh"]
    clean = {k: v for k, v in inputs.items() if not k.startswith("_")}
    from psydox.features.background.service import BackgroundFeature
    return BackgroundFeature().execute(clean, ctx)


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
    ctx = _build_context(inputs)
    if inputs.get("_ratio_wh"):
        ctx["ratio_wh"] = inputs["_ratio_wh"]
    clean = {k: v for k, v in inputs.items() if not k.startswith("_")}
    from psydox.features.lifestyle.service import LifestyleFeature
    return LifestyleFeature().execute(clean, ctx)


def _exec_model_gen(inputs: dict) -> dict:
    ctx   = _build_context(inputs)
    clean = {k: v for k, v in inputs.items() if not k.startswith("_")}
    if inputs.get("_ratio_wh"):
        ctx["ratio_wh"] = inputs["_ratio_wh"]
    from psydox.features.model_gen.service import ModelGenFeature

    angles = clean.pop("angles", None) or ["Front"]
    feature = ModelGenFeature()
    all_outputs: list = []
    all_errors:  list = []

    for angle in angles:
        result = feature.execute({**clean, "angle": angle}, ctx)
        if result.get("success") and result.get("outputs"):
            all_outputs.extend(result["outputs"])
        else:
            all_errors.extend(result.get("errors") or [f"Generation failed for {angle}"])

    return {
        "success":  len(all_outputs) > 0,
        "outputs":  all_outputs,
        "errors":   all_errors,
        "metadata": {"angles": angles, "total": len(angles), "generated": len(all_outputs)},
    }


def execute_angle_generation(inputs: dict, user_email: str) -> dict:
    """
    Multi-angle AI generation via GenerationPipeline.
    Returns outputs list with one entry per generated angle.
    """
    from psydox.generation.pipeline import GenerationPipeline

    image_bytes = inputs.get("image_bytes")
    if not image_bytes:
        return {"success": False, "errors": ["No image provided."], "outputs": [], "metadata": {}}

    angle_ids   = inputs.get("angle_ids") or []
    provider_id = inputs.get("provider_id") or "gemini"
    product_id  = inputs.get("product_id") or ""

    if not angle_ids:
        return {"success": False, "errors": ["No angles selected."], "outputs": [], "metadata": {}}

    try:
        pipeline = GenerationPipeline(user_email=user_email)
        multi    = pipeline.generate_angles(
            image_bytes=image_bytes,
            angle_ids=angle_ids,
            provider_id=provider_id,
            product_id=product_id,
        )

        # Include ALL angle results so the UI can show complete per-angle status,
        # even for angles that failed with no image bytes.
        outputs = []
        errors  = []
        for ar in multi.angle_results:
            outputs.append({
                "bytes":          ar.image_bytes,   # None when failed
                "label":          f"{ar.display_name} — {ar.outcome}",
                "mime":           "image/jpeg",
                "angle_id":       ar.angle_id,
                "display_name":   ar.display_name,
                "outcome":        ar.outcome,
                "quality_score":  ar.quality_score,
                "fidelity_score": ar.fidelity_score,
                "cost_inr":       ar.cost_inr,
                "attempts":       ar.attempts,
                "reason":         getattr(ar, "reason", ""),
            })
            if ar.outcome in ("HARD_FAIL", "FAILED", "BUDGET_CONFLICT"):
                errors.append(f"{ar.display_name}: {getattr(ar, 'reason', ar.outcome)}")

        return {
            "success":  multi.approved > 0 or multi.review > 0,
            "outputs":  outputs,
            "errors":   errors,
            "metadata": multi.to_dict(),
        }
    except PermissionError as e:
        return {"success": False, "errors": [str(e)], "outputs": [], "metadata": {}}
    except Exception as e:
        _log.exception("execute_angle_generation failed: %s", e)
        return {"success": False, "errors": [str(e)], "outputs": [], "metadata": {}}


def _exec_jadu_ka_ghar(inputs: dict) -> dict:
    """Execute any Jadu Ka Ghar (Ideogram) operation."""
    from jadu_ka_ghar.engine import IdeogramEngine
    clean = {k: v for k, v in inputs.items() if not k.startswith("_")}
    return IdeogramEngine().run(clean)


def _exec_masking(inputs: dict) -> dict:
    clean = {k: v for k, v in inputs.items() if not k.startswith("_")}
    from psydox.masking.service import MaskingFeature
    return MaskingFeature().execute(clean, {})


def _build_context(inputs: dict) -> dict:
    """Extract and validate provider selection from inputs, return orchestrator context."""
    provider_id = inputs.get("_provider_id")
    ctx: dict = {}
    if provider_id:
        try:
            from psydox.ai_core.provider_registry import get_provider_registry
            registry = get_provider_registry()
            router   = registry.build_router(preferred_id=provider_id)
            ctx["router"] = router
            ctx["provider_id"] = provider_id
        except Exception as e:
            _log.warning("Could not build router for provider '%s': %s", provider_id, e)
    return ctx
