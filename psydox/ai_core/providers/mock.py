"""
Psydox AI Core — Mock Providers (testing / DEBUG_MODE)
These providers never call any external API.
Enabled automatically when DEBUG_MODE=true.
"""
import io
import time
from PIL import Image, ImageDraw
from .base import ImageGenerationProvider, VisionProvider, ProviderResult, ProviderCapability


def _make_placeholder(prompt: str, ref_bytes: bytes | None = None, size=(1024, 1024)) -> bytes:
    img  = Image.new("RGB", size, (228, 228, 235))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size[0], 56], fill=(66, 66, 180))
    draw.text((size[0] // 2, 28), "MOCK · NO API CALL", fill=(255, 255, 255), anchor="mm")
    draw.rectangle([8, 64, size[0] - 8, size[1] - 8], outline=(180, 180, 200), width=2)
    y = 80
    for word_group in _chunks(prompt[:300].split(), 8):
        draw.text((16, y), " ".join(word_group), fill=(70, 70, 80))
        y += 22
        if y > size[1] - 80:
            break
    if ref_bytes:
        try:
            ref = Image.open(io.BytesIO(ref_bytes)).convert("RGB")
            ref.thumbnail((160, 160))
            img.paste(ref, (size[0] - 172, size[1] - 172))
        except Exception:
            pass
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


class MockImageProvider(ImageGenerationProvider):
    """Mock image generation — returns a synthetic placeholder JPEG."""

    @property
    def name(self) -> str: return "mock"

    @property
    def capabilities(self) -> list[ProviderCapability]:
        return [ProviderCapability.IMAGE_GENERATION, ProviderCapability.IMAGE_EDITING]

    def is_available(self) -> bool: return True

    def generate(self, prompt, reference_bytes=None, model=None, **kwargs) -> ProviderResult:
        t0 = time.monotonic()
        img_bytes = _make_placeholder(prompt, reference_bytes)
        return ProviderResult(
            success=True,
            image_bytes=img_bytes,
            provider=self.name,
            model="mock-v1",
            latency_ms=int((time.monotonic() - t0) * 1000),
            cost_estimate=0.0,
        )

    def estimate_cost(self, *args, **kwargs) -> float:
        return 0.0


class MockVisionProvider(VisionProvider):
    """Mock vision analysis — returns a canned JSON response."""

    _MOCK_ANALYSIS = '{"product_type":"sneaker","primary_colors":["white"],"secondary_colors":["blue"],"pattern":"solid","material_hints":["mesh","rubber"],"key_features":["side stripe","air unit"],"brand_text":["MOCK"],"style_keywords":["athletic","minimal","clean"],"confidence":0.85,"raw_description":"A white and blue athletic sneaker with mesh upper."}'

    @property
    def name(self) -> str: return "mock_vision"

    def is_available(self) -> bool: return True

    def analyze(self, image_bytes, prompt, model=None) -> ProviderResult:
        return ProviderResult(
            success=True,
            text=self._MOCK_ANALYSIS,
            provider=self.name,
            model="mock-v1",
            latency_ms=5,
            cost_estimate=0.0,
        )
