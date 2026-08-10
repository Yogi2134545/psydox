"""
Psydox Feature — Classic Processing

Deterministic, fast, zero-AI operations:
  resize      — resize with aspect-ratio preservation
  crop        — center/smart crop to ratio
  convert     — format conversion (JPEG / PNG / WEBP)
  packshot    — white/transparent background, centered product
  validate    — image validation (resolution, format, file size)
  compress    — quality-controlled compression
  marketplace — preset marketplace formats (Amazon, Shopify, etc.)

All operations run in <1s on standard hardware.
No AI calls, no network calls.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

from psydox.core.registry import FeatureModule
from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType

_log = logging.getLogger("psydox.features.classic")

# ── Marketplace presets ────────────────────────────────────────────────────────
MARKETPLACE_PRESETS: dict[str, dict] = {
    "amazon_main":     {"w": 2000, "h": 2000, "fmt": "JPEG", "bg": "white", "label": "Amazon Main"},
    "amazon_swatch":   {"w": 500,  "h": 500,  "fmt": "JPEG", "bg": "white", "label": "Amazon Swatch"},
    "shopify_product": {"w": 2048, "h": 2048, "fmt": "JPEG", "bg": "white", "label": "Shopify Product"},
    "instagram_sq":    {"w": 1080, "h": 1080, "fmt": "JPEG", "bg": "white", "label": "Instagram Square"},
    "instagram_port":  {"w": 1080, "h": 1350, "fmt": "JPEG", "bg": "white", "label": "Instagram Portrait"},
    "instagram_land":  {"w": 1080, "h": 566,  "fmt": "JPEG", "bg": "white", "label": "Instagram Landscape"},
    "facebook_post":   {"w": 1200, "h": 630,  "fmt": "JPEG", "bg": "white", "label": "Facebook Post"},
    "google_ads":      {"w": 1200, "h": 628,  "fmt": "JPEG", "bg": "white", "label": "Google Ads"},
    "thumbnail":       {"w": 400,  "h": 400,  "fmt": "JPEG", "bg": "white", "label": "Thumbnail"},
}

_MANIFEST = FeatureManifest(
    id="classic",
    name="Classic Processing",
    description="Fast, deterministic image operations: resize, crop, packshot, format conversion, marketplace formats",
    category=FeatureCategory.UTILITY,
    icon="⚡",
    status=FeatureStatus.STABLE,
    requires_ai=False,
    supports_batch=True,
    supports_reference=False,
    supports_brand=False,
    supports_quality_check=True,
    processing_type=ProcessingType.INSTANT,
    version="1.0.0",
    tags=["resize", "crop", "packshot", "convert", "batch", "marketplace", "classic"],
    required_permission="classic",
)


class ClassicFeature(FeatureModule):
    """Deterministic image processing — no AI."""

    @property
    def manifest(self) -> FeatureManifest:
        return _MANIFEST

    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        errors = []
        if not inputs.get("image_bytes"):
            errors.append("Image is required.")
        op = inputs.get("operation", "resize")
        valid_ops = {"resize", "crop", "convert", "packshot", "validate", "compress", "marketplace"}
        if op not in valid_ops:
            errors.append(f"Unknown operation '{op}'. Valid: {', '.join(sorted(valid_ops))}")
        return len(errors) == 0, errors

    def execute(self, inputs: dict, context: dict) -> dict:
        from PIL import Image

        op          = inputs.get("operation", "resize")
        image_bytes = inputs["image_bytes"]

        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
        except Exception as e:
            return {"success": False, "outputs": [], "errors": [f"Cannot open image: {e}"], "metadata": {}}

        try:
            if op == "resize":
                return self._resize(img, inputs)
            elif op == "crop":
                return self._crop(img, inputs)
            elif op == "convert":
                return self._convert(img, inputs)
            elif op == "packshot":
                return self._packshot(img, inputs)
            elif op == "validate":
                return self._validate(img, inputs, len(image_bytes))
            elif op == "compress":
                return self._compress(img, inputs)
            elif op == "marketplace":
                return self._marketplace(img, inputs)
            else:
                return {"success": False, "outputs": [], "errors": [f"Unknown op: {op}"], "metadata": {}}
        except Exception as e:
            _log.exception("ClassicFeature.execute(%s) failed", op)
            return {"success": False, "outputs": [], "errors": [f"Processing error: {e}"], "metadata": {}}

    # ── Operations ────────────────────────────────────────────────────────────

    def _resize(self, img, inputs: dict) -> dict:
        from PIL import Image
        w    = int(inputs.get("width",  1000))
        h    = int(inputs.get("height", 1000))
        keep = inputs.get("keep_ratio", True)
        fmt  = inputs.get("format", "JPEG").upper()
        bg   = inputs.get("bg_color", (255, 255, 255))

        if keep:
            img.thumbnail((w, h), Image.LANCZOS)
            canvas = Image.new("RGB", (w, h), bg)
            x = (w - img.width) // 2
            y = (h - img.height) // 2
            if img.mode == "RGBA":
                canvas.paste(img, (x, y), img)
            else:
                canvas.paste(img, (x, y))
            result = canvas
        else:
            result = img.convert("RGB").resize((w, h), Image.LANCZOS)

        buf = io.BytesIO()
        _save(result, buf, fmt)
        return _ok([{"bytes": buf.getvalue(), "label": f"{w}x{h}", "mime": _mime(fmt)}],
                   {"width": w, "height": h, "format": fmt, "operation": "resize"})

    def _crop(self, img, inputs: dict) -> dict:
        from PIL import Image
        w    = int(inputs.get("width",  1000))
        h    = int(inputs.get("height", 1000))
        fmt  = inputs.get("format", "JPEG").upper()
        mode = inputs.get("crop_mode", "center")

        iw, ih = img.size
        scale  = max(w / iw, h / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        resized = img.convert("RGB").resize((nw, nh), Image.LANCZOS)

        if mode == "center":
            left = (nw - w) // 2
            top  = (nh - h) // 2
        else:
            left, top = 0, 0

        cropped = resized.crop((left, top, left + w, top + h))
        buf = io.BytesIO()
        _save(cropped, buf, fmt)
        return _ok([{"bytes": buf.getvalue(), "label": f"{w}x{h} crop", "mime": _mime(fmt)}],
                   {"width": w, "height": h, "operation": "crop"})

    def _convert(self, img, inputs: dict) -> dict:
        fmt     = inputs.get("format", "JPEG").upper()
        quality = int(inputs.get("quality", 90))
        rgb     = img.convert("RGB") if fmt in ("JPEG", "WEBP") else img

        buf = io.BytesIO()
        if fmt == "JPEG":
            rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        elif fmt == "PNG":
            rgb.save(buf, format="PNG", optimize=True)
        elif fmt == "WEBP":
            rgb.save(buf, format="WEBP", quality=quality)
        else:
            rgb.save(buf, format="JPEG", quality=quality)

        return _ok([{"bytes": buf.getvalue(), "label": fmt, "mime": _mime(fmt)}],
                   {"format": fmt, "quality": quality, "operation": "convert"})

    def _packshot(self, img, inputs: dict) -> dict:
        """Center product on clean background with optional padding."""
        from PIL import Image
        size    = int(inputs.get("size", 2000))
        padding = float(inputs.get("padding", 0.08))
        fmt     = inputs.get("format", "JPEG").upper()
        bg_hex  = inputs.get("bg_color", "#FFFFFF")
        bg      = _hex_to_rgb(bg_hex)

        avail = int(size * (1 - 2 * padding))
        img_rgb = img.convert("RGBA") if img.mode == "RGBA" else img.convert("RGB")
        img_rgb.thumbnail((avail, avail), Image.LANCZOS)

        canvas = Image.new("RGB", (size, size), bg)
        x = (size - img_rgb.width)  // 2
        y = (size - img_rgb.height) // 2

        if img_rgb.mode == "RGBA":
            canvas.paste(img_rgb, (x, y), img_rgb)
        else:
            canvas.paste(img_rgb, (x, y))

        buf = io.BytesIO()
        _save(canvas, buf, fmt)
        return _ok([{"bytes": buf.getvalue(), "label": "packshot", "mime": _mime(fmt)}],
                   {"size": size, "padding": padding, "bg": bg_hex, "operation": "packshot"})

    def _validate(self, img, inputs: dict, file_size_bytes: int) -> dict:
        min_w    = int(inputs.get("min_width",  500))
        min_h    = int(inputs.get("min_height", 500))
        max_mb   = float(inputs.get("max_mb", 20.0))
        issues   = []
        w, h     = img.size

        if w < min_w:
            issues.append(f"Width {w}px is below minimum {min_w}px")
        if h < min_h:
            issues.append(f"Height {h}px is below minimum {min_h}px")
        if file_size_bytes > max_mb * 1024 * 1024:
            mb = file_size_bytes / 1024 / 1024
            issues.append(f"File size {mb:.1f}MB exceeds limit {max_mb}MB")

        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        return {
            "success": True,
            "outputs": [{"bytes": buf.getvalue(), "label": "validated", "mime": "image/jpeg"}],
            "errors":  issues,
            "metadata": {
                "width": w, "height": h, "mode": img.mode,
                "file_size_bytes": file_size_bytes,
                "valid": len(issues) == 0,
                "operation": "validate",
            },
        }

    def _compress(self, img, inputs: dict) -> dict:
        quality    = int(inputs.get("quality", 75))
        target_kb  = inputs.get("target_kb")
        fmt        = inputs.get("format", "JPEG").upper()
        rgb        = img.convert("RGB")

        if target_kb:
            target_bytes = int(target_kb) * 1024
            for q in range(quality, 10, -5):
                buf = io.BytesIO()
                rgb.save(buf, format="JPEG", quality=q)
                if buf.tell() <= target_bytes:
                    quality = q
                    break
            else:
                buf = io.BytesIO()
                rgb.save(buf, format="JPEG", quality=10)
        else:
            buf = io.BytesIO()
            _save(rgb, buf, fmt, quality=quality)

        size_kb = buf.tell() // 1024
        return _ok([{"bytes": buf.getvalue(), "label": f"compressed_{size_kb}kb", "mime": _mime(fmt)}],
                   {"quality": quality, "size_kb": size_kb, "operation": "compress"})

    def _marketplace(self, img, inputs: dict) -> dict:
        """Generate one or more marketplace-format versions."""
        from PIL import Image
        preset_key = inputs.get("preset", "amazon_main")
        presets    = inputs.get("presets")  # list of preset keys for batch

        if presets:
            keys = presets
        else:
            keys = [preset_key]

        outputs  = []
        meta_all = []
        for key in keys:
            if key not in MARKETPLACE_PRESETS:
                continue
            p   = MARKETPLACE_PRESETS[key]
            w, h = p["w"], p["h"]
            fmt  = p["fmt"]
            bg   = _hex_to_rgb(p.get("bg_color", "#FFFFFF"))

            # Fit product centered on white background
            tmp = img.convert("RGB")
            tmp.thumbnail((w, h), Image.LANCZOS)
            canvas = Image.new("RGB", (w, h), bg)
            canvas.paste(tmp, ((w - tmp.width) // 2, (h - tmp.height) // 2))

            buf = io.BytesIO()
            _save(canvas, buf, fmt)
            outputs.append({"bytes": buf.getvalue(), "label": p["label"], "mime": _mime(fmt)})
            meta_all.append({"preset": key, "label": p["label"], "size": f"{w}x{h}"})

        if not outputs:
            return {"success": False, "outputs": [], "errors": ["No valid preset selected"], "metadata": {}}

        return _ok(outputs, {"presets": meta_all, "operation": "marketplace"})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ok(outputs: list, metadata: dict) -> dict:
    return {"success": True, "outputs": outputs, "errors": [], "metadata": metadata}


def _save(img, buf: io.BytesIO, fmt: str, quality: int = 92) -> None:
    if fmt == "PNG":
        img.save(buf, format="PNG", optimize=True)
    elif fmt == "WEBP":
        img.save(buf, format="WEBP", quality=quality)
    else:
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)


def _mime(fmt: str) -> str:
    return {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(fmt, "image/jpeg")


def _hex_to_rgb(hex_str: str) -> tuple:
    h = hex_str.lstrip("#")
    if len(h) == 6:
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    return (255, 255, 255)
