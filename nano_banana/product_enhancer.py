"""Nano Banana — AI product enhancement module."""
import io
from PIL import Image

from .api_client import GeminiClient
from .prompt_builder import build_enhancement_prompt


class ProductEnhancer:
    def __init__(self):
        self.client = GeminiClient()

    def enhance(
        self,
        image: Image.Image,
        enhancements: list,
        product_desc: str = "",
    ) -> Image.Image:
        """
        Apply a list of named enhancements to the product image via Gemini.
        Falls back to original if API not configured.
        """
        if not enhancements:
            return image

        prompt = build_enhancement_prompt(enhancements, product_desc)

        img_bytes = io.BytesIO()
        image.save(img_bytes, format="PNG")
        result_bytes = self.client.edit_image(img_bytes.getvalue(), prompt)
        result = Image.open(io.BytesIO(result_bytes))
        return result.convert("RGB")
