"""Nano Banana — background replacement using rembg + PIL (no Gemini required)."""
import io
from PIL import Image, ImageDraw, ImageFilter
import math

# Solid backgrounds
_SOLID = {
    "White":       (255, 255, 255),
    "Grey":        (180, 180, 180),
    "Black":       (20,  20,  20),
    "Luxury White":(248, 248, 248),
}

# Gradient backgrounds: (top_color, bottom_color)
_GRADIENT = {
    "Marble":        ((245, 245, 245), (220, 220, 220)),
    "Concrete":      ((160, 160, 155), (120, 120, 115)),
    "Wood":          ((180, 130,  80), (140,  95,  55)),
    "Luxury Studio": ((240, 235, 230), (200, 195, 190)),
    "Kitchen":       ((235, 230, 220), (200, 195, 185)),
    "Living Room":   ((230, 220, 210), (190, 180, 170)),
    "Bedroom":       ((230, 225, 240), (200, 195, 210)),
    "Office":        ((220, 225, 235), (180, 185, 200)),
    "Retail Store":  ((245, 245, 245), (210, 210, 215)),
    "Luxury Boutique":((240, 230, 215),(200, 185, 165)),
    "Beach":         ((135, 195, 235), (220, 200, 160)),
    "Mountain":      ((100, 130, 180), (150, 170, 140)),
    "Forest":        (( 60, 110,  60), (100, 150,  80)),
    "Nature":        (( 80, 150,  80), (150, 200, 100)),
    "Garden":        ((120, 180,  80), (200, 230, 140)),
    "Airport":       ((200, 210, 225), (170, 180, 200)),
    "Hotel":         ((225, 215, 200), (185, 170, 150)),
    "Restaurant":    ((200, 175, 150), (155, 130, 110)),
    "Cafe":          ((215, 195, 170), (170, 148, 120)),
    "Gym":           (( 50,  50,  60), (100, 100, 120)),
    "Sports Ground": (( 60, 130,  60), (140, 190,  80)),
    "Festival":      ((200,  80, 160), (240, 160,  60)),
    "Wedding":       ((255, 240, 245), (240, 220, 230)),
    "Christmas":     (( 20,  80,  30), (180,  20,  20)),
    "Diwali":        ((200, 100,  20), (240, 180,   0)),
    "Rain":          (( 80,  90, 110), (130, 140, 160)),
    "Snow":          ((200, 215, 235), (240, 245, 250)),
    "Sunset":        ((240, 100,  40), (250, 180,  60)),
    "Golden Hour":   ((240, 170,  60), (250, 210, 100)),
    "Night":         (( 10,  10,  30), ( 40,  40,  80)),
    "Auto (keep original)": None,
}


class BackgroundGenerator:
    def __init__(self):
        pass  # no API client needed

    def replace_background(
        self,
        product_image: Image.Image,
        background_option: str,
        custom_prompt: str = "",
        product_desc: str = "",
    ) -> Image.Image:
        if background_option == "Auto (keep original)":
            return product_image.convert("RGB")

        if background_option == "Transparent":
            return self._remove_bg(product_image)

        fg_rgba = self._remove_bg(product_image)

        if background_option in _SOLID:
            return self._on_color(fg_rgba, _SOLID[background_option])

        if background_option in _GRADIENT and _GRADIENT[background_option] is not None:
            bg = self._make_gradient(fg_rgba.size, *_GRADIENT[background_option])
            return self._composite(fg_rgba, bg)

        # Custom prompt or unknown → white background
        return self._on_color(fg_rgba, (255, 255, 255))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _remove_bg(self, image: Image.Image) -> Image.Image:
        try:
            import rembg
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            result = rembg.remove(buf.getvalue())
            return Image.open(io.BytesIO(result)).convert("RGBA")
        except Exception:
            return image.convert("RGBA")

    def _make_gradient(self, size, top_color, bottom_color) -> Image.Image:
        w, h = size
        bg = Image.new("RGBA", size)
        draw = ImageDraw.Draw(bg)
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
            g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
            b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b, 255))
        return bg

    def _on_color(self, fg_rgba: Image.Image, color: tuple) -> Image.Image:
        bg = Image.new("RGBA", fg_rgba.size, color + (255,))
        bg.paste(fg_rgba, mask=fg_rgba.split()[3])
        return bg.convert("RGB")

    def _composite(self, fg_rgba: Image.Image, bg: Image.Image) -> Image.Image:
        bg = bg.resize(fg_rgba.size, Image.LANCZOS)
        bg.paste(fg_rgba, mask=fg_rgba.split()[3])
        return bg.convert("RGB")
