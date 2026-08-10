"""
Psydox Feature — Background Studio

Handles all background replacement modes:
  SOLID       — 23 named colors + custom HEX/RGB + color picker
  GRADIENT    — 11 named gradients + custom (2–3 stop, direction, strength)
  STUDIO      — AI studio environment
  LIFESTYLE   — AI lifestyle scene
  OUTDOOR     — AI outdoor environment
  EDITORIAL   — AI editorial look
  CUSTOM_AI   — Custom AI prompt

Classic (PIL) paths are used wherever deterministic processing suffices.
AI is invoked only for STUDIO / LIFESTYLE / OUTDOOR / EDITORIAL / CUSTOM_AI.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

from PIL import Image, ImageDraw

from psydox.core.registry import FeatureModule
from psydox.core.manifest import (
    FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType,
)

_log = logging.getLogger("psydox.features.background")

# ── Color palette ─────────────────────────────────────────────────────────────

SOLID_COLORS: dict[str, tuple[int, int, int]] = {
    "White":       (255, 255, 255),
    "Black":       (0,   0,   0),
    "Light Grey":  (220, 220, 220),
    "Grey":        (180, 180, 180),
    "Dark Grey":   (80,  80,  80),
    "Cream":       (255, 253, 230),
    "Beige":       (245, 235, 208),
    "Ivory":       (255, 255, 240),
    "Pearl":       (240, 238, 230),
    "Brown":       (139, 100, 56),
    "Red":         (220, 38,  38),
    "Orange":      (234, 88,  12),
    "Yellow":      (234, 179, 8),
    "Light Green": (187, 247, 208),
    "Green":       (22,  163, 74),
    "Mint":        (167, 243, 208),
    "Dark Green":  (6,   95,  70),
    "Light Blue":  (186, 230, 253),
    "Blue":        (59,  130, 246),
    "Dark Blue":   (30,  64,  175),
    "Navy":        (15,  23,  42),
    "Purple":      (124, 58,  237),
    "Lavender":    (196, 181, 253),
    "Pink":        (244, 114, 182),
    "Light Pink":  (252, 231, 243),
}

GRADIENT_PRESETS: dict[str, tuple] = {
    # name: (color_stops, direction_deg)
    "Blue → Purple":   ([(59, 130, 246), (124, 58, 237)],    135),
    "Purple → Pink":   ([(124, 58, 237), (244, 114, 182)],   135),
    "Pink → Orange":   ([(244, 114, 182), (234, 88, 12)],    90),
    "Orange → Yellow": ([(234, 88, 12), (234, 179, 8)],      90),
    "Green → Blue":    ([(22, 163, 74), (59, 130, 246)],     135),
    "Mint → Cyan":     ([(167, 243, 208), (34, 211, 238)],   135),
    "Blue → Cyan":     ([(59, 130, 246), (34, 211, 238)],    90),
    "Black → Grey":    ([(0, 0, 0), (120, 120, 120)],        180),
    "Grey → White":    ([(120, 120, 120), (240, 240, 240)],  180),
    "Purple → Blue":   ([(124, 58, 237), (59, 130, 246)],   -45),
    "Red → Orange":    ([(220, 38, 38), (234, 88, 12)],      90),
}

AI_BG_TYPES = ["Studio", "Lifestyle", "Outdoor", "Editorial", "Custom AI"]

_MANIFEST = FeatureManifest(
    id="background",
    name="Background Studio",
    description="Replace or enhance product background with solid, gradient, or AI-generated scenes",
    category=FeatureCategory.BACKGROUND,
    icon="🎨",
    status=FeatureStatus.STABLE,
    requires_ai=False,           # can operate without AI (solid/gradient)
    supports_batch=True,
    supports_reference=True,
    supports_brand=True,
    supports_quality_check=True,
    processing_type=ProcessingType.INSTANT,  # changes to SLOW for AI modes
    version="2.1.0",
    tags=["background", "color", "gradient", "studio", "ai"],
    required_permission="classic_processing",
)


class BackgroundFeature(FeatureModule):

    @property
    def manifest(self) -> FeatureManifest:
        return _MANIFEST

    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not inputs.get("image_bytes"):
            errors.append("Product image is required.")
        bg_type = inputs.get("bg_type", "solid")
        if bg_type not in ("solid", "gradient", "transparent", *[t.lower() for t in AI_BG_TYPES]):
            errors.append(f"Unknown bg_type: {bg_type}")
        if bg_type == "solid":
            if not inputs.get("color_name") and not inputs.get("color_rgb"):
                errors.append("Solid mode requires color_name or color_rgb.")
        if bg_type == "gradient":
            if not inputs.get("gradient_name") and not inputs.get("gradient_stops"):
                errors.append("Gradient mode requires gradient_name or gradient_stops.")
        return len(errors) == 0, errors

    def get_ui_config(self) -> dict:
        return {
            "inputs": [
                {"name": "image_bytes", "type": "image",   "label": "Product image", "required": True},
                {"name": "bg_type",     "type": "select",  "label": "Background type",
                 "options": ["solid", "gradient", "transparent"] + [t.lower() for t in AI_BG_TYPES],
                 "default": "solid"},
            ],
            "options": [
                {"name": "color_name",     "type": "select", "label": "Color",
                 "options": list(SOLID_COLORS.keys()), "condition": "bg_type==solid"},
                {"name": "color_hex",      "type": "text",   "label": "Custom HEX",
                 "condition": "bg_type==solid"},
                {"name": "gradient_name",  "type": "select", "label": "Gradient preset",
                 "options": list(GRADIENT_PRESETS.keys()), "condition": "bg_type==gradient"},
                {"name": "gradient_dir",   "type": "slider", "label": "Gradient direction (°)",
                 "min": 0, "max": 360, "default": 135, "condition": "bg_type==gradient"},
                {"name": "ai_prompt",      "type": "text",   "label": "Scene description",
                 "condition": "bg_type in ['studio','lifestyle','outdoor','editorial','custom ai']"},
                {"name": "ratio_wh",       "type": "size",   "label": "Output size"},
            ],
        }

    def execute(self, inputs: dict, context: dict) -> dict:
        image_bytes  = inputs["image_bytes"]
        bg_type      = inputs.get("bg_type", "solid").lower()
        ratio_wh     = context.get("ratio_wh")

        try:
            if bg_type == "solid":
                result = self._classic_solid(image_bytes, inputs, ratio_wh)
            elif bg_type == "gradient":
                result = self._classic_gradient(image_bytes, inputs, ratio_wh)
            elif bg_type == "transparent":
                result = self._remove_background(image_bytes, ratio_wh)
            else:
                # AI path: studio, lifestyle, outdoor, editorial, custom ai
                result = self._generate_ai(image_bytes, bg_type, inputs, ratio_wh)

            if result is None:
                return {"success": False, "outputs": [], "errors": ["Processing returned no result."], "metadata": {}}

            return {
                "success": True,
                "outputs": [{"bytes": result, "label": bg_type.title(), "mime": "image/jpeg"}],
                "errors":  [],
                "metadata": {"bg_type": bg_type, "feature_id": self.manifest.id},
            }
        except Exception as exc:
            _log.exception("BackgroundFeature.execute failed")
            return {"success": False, "outputs": [], "errors": [str(exc)], "metadata": {}}

    # ── Classic solid color ────────────────────────────────────────────────────

    def _classic_solid(self, image_bytes: bytes, inputs: dict,
                        ratio_wh: Optional[tuple]) -> bytes:
        color_rgb = self._resolve_color(inputs)
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        if ratio_wh:
            canvas_size = ratio_wh
        else:
            canvas_size = img.size

        canvas = Image.new("RGB", canvas_size, color_rgb)
        # Scale and center product
        scale  = min(canvas_size[0] / img.width, canvas_size[1] / img.height, 1.5)
        nw, nh = int(img.width * scale), int(img.height * scale)
        img_s  = img.resize((nw, nh), Image.LANCZOS)
        ox = (canvas_size[0] - nw) // 2
        oy = (canvas_size[1] - nh) // 2
        if img.mode == "RGBA":
            canvas.paste(img_s, (ox, oy), mask=img_s.split()[3])
        else:
            canvas.paste(img_s.convert("RGB"), (ox, oy))
        return _to_jpeg(canvas)

    def _resolve_color(self, inputs: dict) -> tuple[int, int, int]:
        # Priority: color_rgb > color_hex > color_name > white
        if inputs.get("color_rgb"):
            return tuple(inputs["color_rgb"])[:3]
        if inputs.get("color_hex"):
            h = inputs["color_hex"].lstrip("#")
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        if inputs.get("color_name") and inputs["color_name"] in SOLID_COLORS:
            return SOLID_COLORS[inputs["color_name"]]
        return (255, 255, 255)

    # ── Classic gradient ───────────────────────────────────────────────────────

    def _classic_gradient(self, image_bytes: bytes, inputs: dict,
                            ratio_wh: Optional[tuple]) -> bytes:
        # Resolve stops and direction
        if inputs.get("gradient_name") and inputs["gradient_name"] in GRADIENT_PRESETS:
            stops, default_dir = GRADIENT_PRESETS[inputs["gradient_name"]]
        elif inputs.get("gradient_stops"):
            stops = inputs["gradient_stops"]
            default_dir = 135
        else:
            stops, default_dir = [(59, 130, 246), (124, 58, 237)], 135

        direction = int(inputs.get("gradient_dir", default_dir))

        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        cw, ch = ratio_wh if ratio_wh else img.size
        canvas = self._make_gradient(cw, ch, stops, direction)

        scale  = min(cw / img.width, ch / img.height, 1.5)
        nw, nh = int(img.width * scale), int(img.height * scale)
        img_s  = img.resize((nw, nh), Image.LANCZOS)
        ox = (cw - nw) // 2
        oy = (ch - nh) // 2
        if img.mode == "RGBA":
            canvas.paste(img_s, (ox, oy), mask=img_s.split()[3])
        else:
            canvas.paste(img_s.convert("RGB"), (ox, oy))
        return _to_jpeg(canvas)

    def _make_gradient(self, w: int, h: int, stops: list, direction_deg: int) -> Image.Image:
        import math
        # Try numpy for speed; fall back to PIL pixel-by-pixel
        try:
            import numpy as np
            return self._make_gradient_np(w, h, stops, direction_deg, np)
        except ImportError:
            return self._make_gradient_pil(w, h, stops, direction_deg)

    def _make_gradient_np(self, w, h, stops, direction_deg, np):
        import math
        rad = math.radians(direction_deg)
        dx, dy = math.cos(rad), math.sin(rad)
        ys, xs = np.mgrid[0:h, 0:w]
        proj = xs * dx + ys * dy
        proj = (proj - proj.min()) / (proj.max() - proj.min() + 1e-10)
        r = np.zeros((h, w), dtype=np.uint8)
        g = np.zeros((h, w), dtype=np.uint8)
        b = np.zeros((h, w), dtype=np.uint8)
        n = len(stops) - 1
        for i in range(n):
            c1, c2 = stops[i], stops[i + 1]
            mask = (proj >= i / n) & (proj <= (i + 1) / n)
            t    = np.clip((proj[mask] - i / n) * n, 0, 1)
            r[mask] = (c1[0] + t * (c2[0] - c1[0])).astype(np.uint8)
            g[mask] = (c1[1] + t * (c2[1] - c1[1])).astype(np.uint8)
            b[mask] = (c1[2] + t * (c2[2] - c1[2])).astype(np.uint8)
        arr = np.stack([r, g, b], axis=-1)
        return Image.fromarray(arr, "RGB")

    def _make_gradient_pil(self, w, h, stops, direction_deg):
        """Pure-PIL gradient: renders along the longer axis, then rotates."""
        import math
        from PIL import ImageDraw
        n = len(stops) - 1
        # Build a linear horizontal gradient and rotate
        canvas = Image.new("RGB", (w, h))
        draw   = ImageDraw.Draw(canvas)
        for x in range(w):
            t_global = x / max(w - 1, 1)
            seg      = min(int(t_global * n), n - 1)
            t_seg    = t_global * n - seg
            c1, c2   = stops[seg], stops[min(seg + 1, n)]
            r = int(c1[0] + t_seg * (c2[0] - c1[0]))
            g_val = int(c1[1] + t_seg * (c2[1] - c1[1]))
            b = int(c1[2] + t_seg * (c2[2] - c1[2]))
            draw.line([(x, 0), (x, h)], fill=(r, g_val, b))
        # Rotate by direction (PIL rotate uses counter-clockwise degrees)
        rotated = canvas.rotate(-direction_deg, expand=False)
        # Crop back to original size
        rw, rh = rotated.size
        ox = (rw - w) // 2
        oy = (rh - h) // 2
        if rw >= w and rh >= h:
            return rotated.crop((ox, oy, ox + w, oy + h))
        return canvas

    # ── Transparent (rembg) ───────────────────────────────────────────────────

    def _remove_background(self, image_bytes: bytes,
                             ratio_wh: Optional[tuple]) -> bytes:
        try:
            from rembg import remove as rembg_remove
            result = rembg_remove(image_bytes)
            img = Image.open(io.BytesIO(result)).convert("RGBA")
        except ImportError:
            _log.warning("rembg not installed — returning original image")
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

        if ratio_wh:
            cw, ch = ratio_wh
            canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            scale  = min(cw / img.width, ch / img.height, 1.5)
            nw, nh = int(img.width * scale), int(img.height * scale)
            img_s  = img.resize((nw, nh), Image.LANCZOS)
            canvas.paste(img_s, ((cw - nw) // 2, (ch - nh) // 2), mask=img_s.split()[3])
            img = canvas

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # ── AI generation ─────────────────────────────────────────────────────────

    def _generate_ai(self, image_bytes: bytes, bg_type: str,
                      inputs: dict, ratio_wh: Optional[tuple]) -> Optional[bytes]:
        custom_prompt = inputs.get("ai_prompt", "")
        product_desc  = inputs.get("product_desc", "")

        prompt_map = {
            "studio":    "Professional studio photography background, seamless paper backdrop, "
                         "soft diffused lighting, clean and premium commercial look",
            "lifestyle": custom_prompt or "Authentic lifestyle setting, natural environment, "
                         "candid and real, modern lifestyle photography",
            "outdoor":   custom_prompt or "Beautiful outdoor environment, natural lighting, "
                         "scenic background, professional outdoor photography",
            "editorial": custom_prompt or "High-end editorial photography background, "
                         "artistic composition, fashion magazine quality",
            "custom ai": custom_prompt or "Professional product photography background",
        }
        base_prompt = prompt_map.get(bg_type, custom_prompt or "Professional product photography background")

        if product_desc:
            base_prompt = f"Product: {product_desc}. Background: {base_prompt}"

        base_prompt += (
            " CRITICAL: preserve the product EXACTLY as it appears in the reference image. "
            "Do not alter the product color, shape, logo, or any details. "
            "Only change the background environment."
        )

        try:
            from psydox.ai_core.orchestrator import get_orchestrator, AIRequest
            from psydox.ai_core.router import TaskType
            req = AIRequest(
                task=TaskType.CREATIVE_BACKGROUND,
                prompt=base_prompt,
                reference_bytes=image_bytes,
                feature_id=self.manifest.id,
            )
            result = get_orchestrator().generate(req, run_quality=True)
            if not result.success:
                return None
            img = Image.open(io.BytesIO(result.image_bytes)).convert("RGB")
            if ratio_wh:
                img = _apply_ratio(img, ratio_wh)
            return _to_jpeg(img)
        except Exception as exc:
            _log.exception("BackgroundFeature AI generation failed")
            return None


# ── Utilities ─────────────────────────────────────────────────────────────────

def _to_jpeg(img: Image.Image, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _apply_ratio(img: Image.Image, target_wh: tuple) -> Image.Image:
    tw, th = target_wh
    iw, ih = img.size
    scale  = min(tw / iw, th / ih, 2.0)
    nw, nh = int(iw * scale), int(ih * scale)
    scaled = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (tw, th), (255, 255, 255))
    canvas.paste(scaled, ((tw - nw) // 2, (th - nh) // 2))
    return canvas
