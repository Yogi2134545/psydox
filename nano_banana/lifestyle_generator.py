"""Nano Banana — lifestyle scene generator (requires Imagen API access)."""
import io
from PIL import Image

from .api_client import GeminiClient
from .prompt_builder import build_lifestyle_prompt

_NO_API_MSG = (
    "Lifestyle Scene Generation requires Imagen API access.\n\n"
    "Your current GOOGLE_API_KEY supports text + vision only.\n\n"
    "To enable image generation:\n"
    "1. Go to https://aistudio.google.com\n"
    "2. Enable the Imagen API for your account (requires billing)\n"
    "3. Or use Vertex AI with a service account key\n\n"
    "Alternatively, use the Background tab (works without Imagen)."
)


class LifestyleGenerator:
    def __init__(self):
        self.client = GeminiClient()

    def generate(self, product_image, style, custom_prompt="", product_desc=""):
        prompt = custom_prompt if custom_prompt else build_lifestyle_prompt(style, product_desc)
        ref_bytes = io.BytesIO()
        product_image.save(ref_bytes, format="PNG")

        try:
            result_bytes = self.client.generate_image(prompt, reference_image_bytes=ref_bytes.getvalue())
            return Image.open(io.BytesIO(result_bytes)).convert("RGB")
        except Exception as e:
            err = str(e)
            if "404" in err or "400" in err or "403" in err:
                raise RuntimeError(_NO_API_MSG) from None
            raise
