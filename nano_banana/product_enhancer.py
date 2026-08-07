"""Nano Banana — PIL-based product enhancement (no API required)."""
import io
from PIL import Image, ImageEnhance, ImageFilter


_PRESET_SETTINGS = {
    "Remove Dust":                  {"noise_reduction": 60, "sharpness": 20},
    "Remove Wrinkles":              {"noise_reduction": 40, "clarity": 30},
    "Remove Scratches":             {"noise_reduction": 50, "clarity": 20},
    "Improve Stitching":            {"sharpness": 50, "clarity": 40},
    "Improve Fabric":               {"sharpness": 40, "clarity": 30, "saturation": 10},
    "Improve Leather":              {"contrast": 15, "saturation": 10, "sharpness": 30},
    "Improve Jewelry":              {"sharpness": 60, "clarity": 50, "contrast": 20},
    "Improve Glass":                {"clarity": 40, "contrast": 15},
    "Improve Metal":                {"sharpness": 50, "contrast": 20},
    "Improve Product Edges":        {"sharpness": 70, "clarity": 40},
    "Improve Colors":               {"saturation": 25, "vibrance": 15, "contrast": 10},
    "Premium Marketplace Optimization": {
        "brightness": 10, "contrast": 15, "saturation": 15,
        "sharpness": 30, "clarity": 20, "noise_reduction": 20,
    },
}


class ProductEnhancer:
    def __init__(self):
        pass  # no API client needed

    def enhance(self, image: Image.Image, enhancements: list, product_desc: str = "") -> Image.Image:
        if not enhancements:
            return image

        # Merge all selected preset settings
        merged = {}
        for name in enhancements:
            for k, v in _PRESET_SETTINGS.get(name, {}).items():
                merged[k] = merged.get(k, 0) + v

        # Cap values at -100..100
        merged = {k: max(-100, min(100, v)) for k, v in merged.items()}

        return self._apply(image.convert("RGB"), merged)

    def _apply(self, img: Image.Image, s: dict) -> Image.Image:
        def _scale(val, lo=0.0, neutral=1.0, hi=2.0):
            v = float(val or 0)
            return neutral + (hi - neutral) * v / 100 if v >= 0 else neutral + (neutral - lo) * v / 100

        if s.get("brightness"):
            img = ImageEnhance.Brightness(img).enhance(_scale(s["brightness"]))
        if s.get("contrast"):
            img = ImageEnhance.Contrast(img).enhance(_scale(s["contrast"]))
        sat = (s.get("saturation") or 0) + (s.get("vibrance") or 0) * 0.5
        if sat:
            img = ImageEnhance.Color(img).enhance(_scale(sat))
        if s.get("sharpness"):
            img = ImageEnhance.Sharpness(img).enhance(_scale(s["sharpness"]))
        if s.get("clarity", 0) > 0:
            v = s["clarity"]
            img = img.filter(ImageFilter.UnsharpMask(radius=2 + v * 0.1, percent=int(v), threshold=3))
        if s.get("noise_reduction", 0) > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=max(0.1, s["noise_reduction"] * 0.04)))
        return img
