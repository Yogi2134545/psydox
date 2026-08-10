"""
Psydox Demo Feature
ARCHITECTURAL TEST — proves the plugin system works end to end.

To add this feature:
  1. This file exists ✓
  2. Register it → registry.register(DemoFeature())
  3. Appears in dashboard automatically ✓
  4. Has RBAC permission ✓
  5. Can join workflows ✓
  6. Runs QA ✓

To disable: set ENABLE_DEMO_FEATURE=false
To remove:  unregister from loader.py
No core dashboard files need editing.
"""
import io
from PIL import Image, ImageDraw

from psydox.core.registry import FeatureModule
from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType


_MANIFEST = FeatureManifest(
    id="demo_watermark",
    name="Demo Watermark",
    description="Adds a 'DEMO' watermark — proves the plugin architecture",
    category=FeatureCategory.UTILITY,
    icon="🧪",
    status=FeatureStatus.EXPERIMENTAL,
    requires_ai=False,
    supports_batch=True,
    supports_reference=False,
    supports_quality_check=False,
    processing_type=ProcessingType.INSTANT,
    version="1.0.0",
    tags=["demo", "test", "plugin"],
    required_permission="ai_studio",
    feature_flag="ENABLE_DEMO_FEATURE",  # off by default — set to 'true' to enable
)


class DemoFeature(FeatureModule):
    """
    Minimal feature that adds a watermark to the uploaded image.
    Serves as a living proof that the plugin system is extensible.
    """

    @property
    def manifest(self) -> FeatureManifest:
        return _MANIFEST

    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        if not inputs.get("image_bytes"):
            return False, ["Product image is required."]
        return True, []

    def execute(self, inputs: dict, context: dict) -> dict:
        image_bytes = inputs["image_bytes"]
        text        = inputs.get("watermark_text", "DEMO")
        opacity     = inputs.get("opacity", 40)

        try:
            img  = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            out  = self._add_watermark(img, text, opacity)
            buf  = io.BytesIO()
            out.save(buf, format="JPEG", quality=92)

            return {
                "success": True,
                "outputs": [{"bytes": buf.getvalue(), "label": f"{text} watermark", "mime": "image/jpeg"}],
                "errors":  [],
                "metadata": {
                    "watermark_text": text,
                    "opacity":        opacity,
                    "feature_id":     self.manifest.id,
                    "plugin_proof":   "This feature was added without editing core dashboard code.",
                },
            }
        except Exception as e:
            return {"success": False, "outputs": [], "errors": [str(e)], "metadata": {}}

    def _add_watermark(self, img: Image.Image, text: str, opacity: int) -> Image.Image:
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw    = ImageDraw.Draw(overlay)
        w, h    = img.size
        draw.text(
            (w // 2, h // 2), text, fill=(255, 255, 255, opacity),
            anchor="mm",
        )
        base = img.convert("RGBA")
        base.alpha_composite(overlay)
        return base.convert("RGB")

    def get_ui_config(self) -> dict:
        return {
            "inputs": [
                {"id": "image_bytes", "type": "image", "label": "Product Image", "required": True},
            ],
            "options": [
                {"id": "watermark_text", "type": "text",   "label": "Watermark Text", "default": "DEMO"},
                {"id": "opacity",        "type": "slider", "label": "Opacity",        "min": 10, "max": 80, "default": 40},
            ],
        }
