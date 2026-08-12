"""
Nano Banana v2 — PIL-based photo editor.

Improvements over v1:
  - Dead GeminiClient import/instantiation removed (this module is pure PIL)
  - Shadows curve fixed: single clean formula, no double-adjustment
    v1 bug: applied v*(0.5-norm) twice in the shadows branch → asymmetric result
    v2 fix: norm += v * (0.5 - norm)  — symmetric, predictable lift/crush
  - Clarity now works bidirectionally (negative = soften, positive = sharpen midtones)
  - Texture now works bidirectionally (negative = smooth, positive = enhance grain)
"""
from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter


class AIEditorV2:
    # ── PIL adjustments (no API needed) ──────────────────────────────────────

    def adjust(self, image: Image.Image, settings: dict) -> Image.Image:
        """
        Apply photo adjustments using PIL.
        All settings are -100 to +100, with 0 = no change.
        """
        img = image.convert("RGB")

        def _scale(val, neutral=1.0, lo=0.0, hi=2.0):
            v = float(val or 0)
            if v >= 0:
                return neutral + (hi - neutral) * v / 100
            else:
                return neutral + (neutral - lo) * v / 100

        if settings.get("brightness"):
            img = ImageEnhance.Brightness(img).enhance(_scale(settings["brightness"]))

        if settings.get("contrast"):
            img = ImageEnhance.Contrast(img).enhance(_scale(settings["contrast"]))

        if settings.get("exposure"):
            img = ImageEnhance.Brightness(img).enhance(_scale(settings["exposure"], 1.0, 0.3, 1.7))

        sat_val = (settings.get("saturation") or 0) + (settings.get("vibrance") or 0) * 0.5
        if sat_val:
            img = ImageEnhance.Color(img).enhance(_scale(sat_val))

        if settings.get("sharpness"):
            img = ImageEnhance.Sharpness(img).enhance(_scale(settings["sharpness"]))

        # Clarity: positive → unsharp mask midtone pop; negative → gentle blur/soften
        if settings.get("clarity"):
            v = settings["clarity"]
            if v > 0:
                radius = 2 + v * 0.1
                img = img.filter(ImageFilter.UnsharpMask(radius=radius, percent=int(v), threshold=3))
            else:
                radius = abs(v) * 0.04
                if radius > 0.1:
                    img = img.filter(ImageFilter.GaussianBlur(radius=radius))

        # Texture: positive → fine-radius unsharp mask; negative → detail smoothing
        if settings.get("texture"):
            v = settings["texture"]
            if v > 0:
                img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=int(v * 1.5), threshold=2))
            else:
                img = img.filter(ImageFilter.GaussianBlur(radius=abs(v) * 0.02))

        if settings.get("noise_reduction"):
            v = settings["noise_reduction"]
            if v > 0:
                radius = v * 0.05
                img = img.filter(ImageFilter.GaussianBlur(radius=max(0.1, radius)))

        if settings.get("temperature"):
            img = self._apply_temperature(img, settings["temperature"])

        if settings.get("tint"):
            img = self._apply_tint(img, settings["tint"])

        for adj in ("highlights", "shadows", "whites", "blacks"):
            if settings.get(adj):
                img = self._apply_tone(img, adj, settings[adj])

        return img

    def _apply_temperature(self, img: Image.Image, value: float) -> Image.Image:
        r, g, b = img.split()
        factor = abs(value) / 100 * 30
        if value > 0:
            r = r.point(lambda x: min(255, x + factor))
            b = b.point(lambda x: max(0, x - factor * 0.5))
        else:
            b = b.point(lambda x: min(255, x + factor))
            r = r.point(lambda x: max(0, x - factor * 0.5))
        return Image.merge("RGB", (r, g, b))

    def _apply_tint(self, img: Image.Image, value: float) -> Image.Image:
        r, g, b = img.split()
        factor = abs(value) / 100 * 20
        if value > 0:
            g = g.point(lambda x: min(255, x + factor))
        else:
            r = r.point(lambda x: min(255, x + factor))
            b = b.point(lambda x: min(255, x + factor))
        return Image.merge("RGB", (r, g, b))

    def _apply_tone(self, img: Image.Image, tone_type: str, value: float) -> Image.Image:
        """
        Highlights/shadows/whites/blacks tone adjustments.

        Shadows fix (v1 had double-adjustment):
          v1: norm += v*(0.5-norm)*(-1 if v>0 else 1)*(-1)
              norm = max(0, norm + v*(0.5-norm))   ← applies a second time!
          v2: norm += v * (0.5 - norm)             ← single clean formula
              v > 0 → lifts dark pixels toward mid-grey
              v < 0 → crushes dark pixels further toward black
        """
        v = float(value) / 100

        def curve(x):
            norm = x / 255.0
            if tone_type == "highlights":
                if norm > 0.5:
                    norm_ = norm + v * (norm - 0.5)
                else:
                    norm_ = norm
            elif tone_type == "shadows":
                if norm < 0.5:
                    norm_ = norm + v * (0.5 - norm)
                else:
                    norm_ = norm
            elif tone_type == "whites":
                norm_ = norm + v * (norm ** 2)
            elif tone_type == "blacks":
                norm_ = norm + v * ((1 - norm) ** 2) * (-1)
            else:
                norm_ = norm
            return int(max(0, min(255, norm_ * 255)))

        return img.point(curve)

    # ── AI finishing (PIL presets, no API) ────────────────────────────────────

    _FINISH_PRESETS: dict[str, dict] = {
        "Luxury":      {"contrast": 20, "brightness": 5,  "saturation": -10, "sharpness": 25, "temperature": 8},
        "Marketplace": {"brightness": 15, "contrast": 10, "saturation": 10,  "sharpness": 30, "noise_reduction": 15},
        "Studio":      {"contrast": 15, "brightness": 8,  "saturation": 5,   "sharpness": 20},
        "Natural":     {"temperature": 15, "saturation": 10, "brightness": 5, "contrast": 5},
        "Commercial":  {"saturation": 20, "contrast": 20, "sharpness": 35,   "brightness": 10},
    }

    def apply_ai_finish(self, image: Image.Image, finish_type: str) -> Image.Image:
        settings = self._FINISH_PRESETS.get(finish_type, {"contrast": 10, "sharpness": 20})
        return self.adjust(image, settings)

    # ── Upscaling ─────────────────────────────────────────────────────────────

    def upscale(self, image: Image.Image, scale: int = 2) -> Image.Image:
        return image.resize((image.width * scale, image.height * scale), Image.LANCZOS)
