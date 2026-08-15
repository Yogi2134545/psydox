"""
Nano Banana — lifestyle scene generator.

Used by diagnostics (run_production_validation step 9) and legacy callers.
AI Studio Lifestyle generation uses the canonical path:
  LifestyleFeature → AIOrchestrator → GeminiImageProvider → GeminiClient

This class is kept for diagnostics compatibility only.
"""
import io
from PIL import Image

from .api_client import GeminiClient
from .prompt_builder import build_lifestyle_prompt


class LifestyleGenerator:
    def __init__(self):
        self.client = GeminiClient()

    def generate(self, product_image, style, custom_prompt="", product_desc=""):
        prompt = custom_prompt if custom_prompt else build_lifestyle_prompt(style, product_desc)
        ref_bytes = io.BytesIO()
        product_image.save(ref_bytes, format="JPEG", quality=92)

        result_bytes = self.client.generate_image(prompt, reference_image_bytes=ref_bytes.getvalue())
        return Image.open(io.BytesIO(result_bytes)).convert("RGB")
