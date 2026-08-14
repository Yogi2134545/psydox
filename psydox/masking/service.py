"""
Psydox Feature — Masking Studio

Product background removal and bounding-box detection.

Modes:
  transparent — remove background, return transparent PNG (rembg / OpenCV)
  white_bg    — composite product onto white background
  custom_bg   — composite product onto a custom RGB background
  detect      — draw bounding box on original image for inspection
"""
from __future__ import annotations

import io
import logging

from PIL import Image, ImageDraw

from psydox.core.registry import FeatureModule
from psydox.core.manifest import (
    FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType,
)

_log = logging.getLogger("psydox.masking.service")

_MANIFEST = FeatureManifest(
    id="masking",
    name="Masking Studio",
    description="Remove or replace backgrounds using AI segmentation (rembg) or edge-detection fallback",
    category=FeatureCategory.EDITING,
    icon="🎭",
    status=FeatureStatus.STABLE,
    requires_ai=False,
    supports_batch=True,
    supports_reference=False,
    supports_brand=False,
    supports_quality_check=True,
    processing_type=ProcessingType.FAST,
    version="1.0.0",
    tags=["masking", "background", "removal", "transparent", "segmentation"],
    required_permission="classic_processing",
)


class MaskingFeature(FeatureModule):

    @property
    def manifest(self) -> FeatureManifest:
        return _MANIFEST

    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not inputs.get("image_bytes"):
            errors.append("Product image is required.")
        mode = inputs.get("mode", "transparent")
        if mode not in ("transparent", "white_bg", "custom_bg", "detect"):
            errors.append(f"Unknown masking mode: {mode}")
        if mode == "custom_bg":
            rgb = inputs.get("bg_rgb")
            if not (isinstance(rgb, (list, tuple)) and len(rgb) == 3):
                errors.append("custom_bg mode requires bg_rgb as (R, G, B).")
        return len(errors) == 0, errors

    def execute(self, inputs: dict, context: dict) -> dict:
        from psydox.masking.engine import MaskingEngine

        try:
            img    = Image.open(io.BytesIO(inputs["image_bytes"])).convert("RGB")
            mode   = inputs.get("mode", "transparent")
            engine = MaskingEngine()

            if mode == "detect":
                return self._exec_detect(img, engine)

            seg = engine.segment(img)

            if mode == "transparent":
                return {
                    "success": True,
                    "outputs": [{"bytes": seg.image_rgba, "label": "Background removed", "mime": "image/png"}],
                    "errors":  [],
                    "metadata": {"method": seg.method, "bbox": seg.bbox.as_tuple()},
                }

            if mode in ("white_bg", "custom_bg"):
                bg_rgb = (255, 255, 255)
                if mode == "custom_bg":
                    raw = inputs.get("bg_rgb", (255, 255, 255))
                    bg_rgb = tuple(int(c) for c in raw)
                return self._composite(seg, bg_rgb)

            return {"success": False, "errors": [f"Unknown mode: {mode}"], "outputs": [], "metadata": {}}

        except Exception as exc:
            _log.exception("MaskingFeature.execute failed")
            return {"success": False, "errors": [str(exc)], "outputs": [], "metadata": {}}

    # ── Mode helpers ───────────────────────────────────────────────────────────

    def _exec_detect(self, img: Image.Image, engine) -> dict:
        bbox = engine.detect(img)
        annotated = img.copy()
        draw = ImageDraw.Draw(annotated)
        draw.rectangle(bbox.as_tuple(), outline=(0, 220, 0), width=3)
        buf = io.BytesIO()
        annotated.save(buf, "JPEG", quality=95)
        label = (
            f"Bbox — {bbox.method}, "
            f"conf {bbox.confidence:.0%}, "
            f"{bbox.width}×{bbox.height} px"
        )
        return {
            "success": True,
            "outputs": [{"bytes": buf.getvalue(), "label": label, "mime": "image/jpeg"}],
            "errors":  [],
            "metadata": {
                "method":     bbox.method,
                "confidence": bbox.confidence,
                "bbox":       bbox.as_tuple(),
            },
        }

    def _composite(self, seg, bg_rgb: tuple) -> dict:
        bg   = Image.new("RGBA", Image.open(io.BytesIO(seg.image_rgba)).size, (*bg_rgb, 255))
        mask = Image.open(io.BytesIO(seg.image_rgba)).convert("RGBA")
        bg.paste(mask, mask=mask.split()[3])
        out = bg.convert("RGB")
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=95)
        label = f"BG → {bg_rgb}"
        return {
            "success": True,
            "outputs": [{"bytes": buf.getvalue(), "label": label, "mime": "image/jpeg"}],
            "errors":  [],
            "metadata": {"method": seg.method, "bg_rgb": bg_rgb},
        }

    def get_ui_config(self) -> dict:
        return {
            "inputs": [
                {"name": "image_bytes", "type": "image",  "label": "Product image", "required": True},
                {"name": "mode",        "type": "select", "label": "Mode",
                 "options": ["transparent", "white_bg", "custom_bg", "detect"],
                 "default": "transparent"},
            ],
            "options": [
                {"name": "bg_rgb", "type": "color", "label": "Background colour",
                 "condition": "mode==custom_bg"},
            ],
        }
