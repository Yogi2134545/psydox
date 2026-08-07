"""Nano Banana — lifestyle scene generator."""
import io
from PIL import Image

from .api_client import GeminiClient
from .prompt_builder import build_lifestyle_prompt


class LifestyleGenerator:
    def __init__(self):
        self.client = GeminiClient()

    def generate(
        self,
        product_image: Image.Image,
        style: str,
        custom_prompt: str = "",
        product_desc: str = "",
    ) -> Image.Image:
        """Generate a lifestyle scene incorporating the product."""
        prompt = custom_prompt if custom_prompt else build_lifestyle_prompt(style, product_desc)

        # Convert product image to bytes as reference
        ref_bytes = io.BytesIO()
        product_image.save(ref_bytes, format="PNG")
        ref_bytes = ref_bytes.getvalue()

        result_bytes = self.client.generate_image(prompt, reference_image_bytes=ref_bytes)
        result = Image.open(io.BytesIO(result_bytes))
        return result.convert("RGB")
