"""Nano Banana — AI model generator."""
import io
from PIL import Image

from .api_client import GeminiClient
from .prompt_builder import build_model_prompt


class ModelGenerator:
    def __init__(self):
        self.client = GeminiClient()

    def generate(
        self,
        product_image: Image.Image,
        gender: str,
        age_group: str,
        ethnicity: str,
        clothing_style: str,
        product_desc: str = "",
    ) -> Image.Image:
        """Generate an AI model wearing/holding the product."""
        prompt = build_model_prompt(gender, age_group, ethnicity, clothing_style, product_desc)

        # Product image as style reference
        ref_bytes = io.BytesIO()
        product_image.save(ref_bytes, format="PNG")
        ref_bytes = ref_bytes.getvalue()

        result_bytes = self.client.generate_image(prompt, reference_image_bytes=ref_bytes)
        result = Image.open(io.BytesIO(result_bytes))
        return result.convert("RGB")
