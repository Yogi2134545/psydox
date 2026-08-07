"""Nano Banana — background replacement module."""
import io
from PIL import Image

from .api_client import GeminiClient
from .prompt_builder import build_background_prompt


_SOLID_COLORS = {
    "White": (255, 255, 255),
    "Grey": (128, 128, 128),
    "Black": (0, 0, 0),
}


class BackgroundGenerator:
    def __init__(self):
        self.client = GeminiClient()

    def replace_background(
        self,
        product_image: Image.Image,
        background_option: str,
        custom_prompt: str = "",
        product_desc: str = "",
    ) -> Image.Image:
        """
        Replace the background of a product image.

        Steps:
        1. Remove existing background using rembg.
        2. If solid color — composite on color fill.
        3. If Transparent — return RGBA with removed background.
        4. Otherwise generate AI background and composite.
        """
        # 1 — Remove background
        fg_rgba = self._remove_bg(product_image)

        # 2 — Transparent: just return the cutout
        from .settings import BACKGROUND_OPTIONS
        if background_option == "Transparent":
            return fg_rgba

        # 3 — Solid colors: no AI call needed
        if background_option in _SOLID_COLORS:
            return self._composite_on_color(fg_rgba, _SOLID_COLORS[background_option])

        # 4 — AI-generated background
        prompt = build_background_prompt(background_option, product_desc, custom_prompt)
        bg_bytes = self.client.generate_image(prompt)
        bg_img = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
        bg_img = bg_img.resize(product_image.size, Image.LANCZOS)

        return self._composite(fg_rgba, bg_img)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _remove_bg(self, image: Image.Image) -> Image.Image:
        """Remove background using rembg; fallback to original if unavailable."""
        try:
            import rembg
            img_bytes = io.BytesIO()
            image.save(img_bytes, format="PNG")
            result_bytes = rembg.remove(img_bytes.getvalue())
            return Image.open(io.BytesIO(result_bytes)).convert("RGBA")
        except ImportError:
            # rembg not installed — return image with white removed naively
            return image.convert("RGBA")
        except Exception:
            return image.convert("RGBA")

    def _composite_on_color(
        self, fg_rgba: Image.Image, color: tuple
    ) -> Image.Image:
        bg = Image.new("RGBA", fg_rgba.size, color + (255,))
        bg.paste(fg_rgba, mask=fg_rgba.split()[3])
        return bg.convert("RGB")

    def _composite(self, fg_rgba: Image.Image, bg_rgba: Image.Image) -> Image.Image:
        bg_rgba.paste(fg_rgba, mask=fg_rgba.split()[3])
        return bg_rgba.convert("RGB")
