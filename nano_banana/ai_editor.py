"""Nano Banana — PIL-based photo editor with optional AI finishing."""
import io
from PIL import Image, ImageEnhance, ImageFilter

from .api_client import GeminiClient


class AIEditor:
    def __init__(self):
        self.client = GeminiClient()

    # ── PIL adjustments (no API needed) ──────────────────────────────────────

    def adjust(self, image: Image.Image, settings: dict) -> Image.Image:
        """
        Apply photo adjustments using PIL.

        All settings are -100 to +100, with 0 = no change.
        """
        img = image.convert("RGB")

        def _scale(val, neutral=1.0, lo=0.0, hi=2.0):
            """Map -100..+100 to lo..hi with 0 -> neutral."""
            v = float(val or 0)
            if v >= 0:
                return neutral + (hi - neutral) * v / 100
            else:
                return neutral + (neutral - lo) * v / 100

        # Brightness
        if settings.get("brightness"):
            img = ImageEnhance.Brightness(img).enhance(_scale(settings["brightness"]))

        # Contrast
        if settings.get("contrast"):
            img = ImageEnhance.Contrast(img).enhance(_scale(settings["contrast"]))

        # Exposure (similar to brightness but affects midtones more)
        if settings.get("exposure"):
            img = ImageEnhance.Brightness(img).enhance(_scale(settings["exposure"], 1.0, 0.3, 1.7))

        # Saturation / Vibrance (use Color enhancer)
        sat_val = (settings.get("saturation") or 0) + (settings.get("vibrance") or 0) * 0.5
        if sat_val:
            img = ImageEnhance.Color(img).enhance(_scale(sat_val))

        # Sharpness
        if settings.get("sharpness"):
            img = ImageEnhance.Sharpness(img).enhance(_scale(settings["sharpness"]))

        # Clarity (unsharp mask for midtone contrast)
        if settings.get("clarity"):
            v = settings["clarity"]
            if v > 0:
                radius = 2 + v * 0.1
                img = img.filter(ImageFilter.UnsharpMask(radius=radius, percent=int(v), threshold=3))

        # Texture (unsharp mask with fine radius)
        if settings.get("texture"):
            v = settings["texture"]
            if v > 0:
                img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=int(v * 1.5), threshold=2))

        # Noise reduction (Gaussian blur, slight)
        if settings.get("noise_reduction"):
            v = settings["noise_reduction"]
            if v > 0:
                radius = v * 0.05
                img = img.filter(ImageFilter.GaussianBlur(radius=max(0.1, radius)))

        # Temperature (warm/cool shift via channel tweaks)
        if settings.get("temperature"):
            t = settings["temperature"]
            img = self._apply_temperature(img, t)

        # Tint (green/magenta shift)
        if settings.get("tint"):
            img = self._apply_tint(img, settings["tint"])

        # Highlights / Shadows / Whites / Blacks — simple curve approximation
        for adj in ("highlights", "shadows", "whites", "blacks"):
            if settings.get(adj):
                img = self._apply_tone(img, adj, settings[adj])

        return img

    def _apply_temperature(self, img: Image.Image, value: float) -> Image.Image:
        """Warm (>0) or cool (<0) color temperature shift."""
        r, g, b = img.split()
        factor = abs(value) / 100 * 30  # max 30 level shift
        if value > 0:  # warmer
            r = r.point(lambda x: min(255, x + factor))
            b = b.point(lambda x: max(0, x - factor * 0.5))
        else:  # cooler
            b = b.point(lambda x: min(255, x + factor))
            r = r.point(lambda x: max(0, x - factor * 0.5))
        return Image.merge("RGB", (r, g, b))

    def _apply_tint(self, img: Image.Image, value: float) -> Image.Image:
        """Green (>0) or magenta (<0) tint."""
        r, g, b = img.split()
        factor = abs(value) / 100 * 20
        if value > 0:  # green tint
            g = g.point(lambda x: min(255, x + factor))
        else:  # magenta tint
            r = r.point(lambda x: min(255, x + factor))
            b = b.point(lambda x: min(255, x + factor))
        return Image.merge("RGB", (r, g, b))

    def _apply_tone(self, img: Image.Image, tone_type: str, value: float) -> Image.Image:
        """Highlights/shadows/whites/blacks tone adjustments."""
        v = float(value) / 100

        def curve(x):
            norm = x / 255.0
            if tone_type == "highlights":
                if norm > 0.5:
                    norm = norm + v * (norm - 0.5)
            elif tone_type == "shadows":
                if norm < 0.5:
                    norm = norm + v * (0.5 - norm) * (-1 if v > 0 else 1) * (-1)
                    norm = max(0, norm + v * (0.5 - norm))
            elif tone_type == "whites":
                norm = norm + v * (norm ** 2)
            elif tone_type == "blacks":
                norm = norm + v * ((1 - norm) ** 2) * (-1)
            return int(max(0, min(255, norm * 255)))

        return img.point(curve)

    # ── AI finishing (PIL-based presets, no API needed) ───────────────────────

    _FINISH_PRESETS = {
        "Luxury":      {"contrast": 20, "brightness": 5,  "saturation": -10, "sharpness": 25, "temperature": 8},
        "Marketplace": {"brightness": 15, "contrast": 10, "saturation": 10,  "sharpness": 30, "noise_reduction": 15},
        "Studio":      {"contrast": 15, "brightness": 8,  "saturation": 5,   "sharpness": 20},
        "Natural":     {"temperature": 15, "saturation": 10, "brightness": 5, "contrast": 5},
        "Commercial":  {"saturation": 20, "contrast": 20, "sharpness": 35,   "brightness": 10},
    }

    def apply_ai_finish(self, image: Image.Image, finish_type: str) -> Image.Image:
        """Apply a photography finish preset using PIL (no API required)."""
        settings = self._FINISH_PRESETS.get(finish_type, {"contrast": 10, "sharpness": 20})
        return self.adjust(image, settings)

    # ── Upscaling ─────────────────────────────────────────────────────────────

    def upscale(self, image: Image.Image, scale: int = 2) -> Image.Image:
        """Upscale image using LANCZOS resampling."""
        new_w = image.width * scale
        new_h = image.height * scale
        return image.resize((new_w, new_h), Image.LANCZOS)
