"""
DemoFutureFeature — Extensibility Proof

This module exists to prove that Psydox's architecture is truly extensible:
a new feature can be added by dropping a single file here, without touching
app.py, dashboard.py, loader.py, or any core module.

Auto-discovery finds it automatically.
It appears in the dashboard quick-create grid.
It participates in RBAC, workflows, jobs, and quality checks.
It is gated behind ENABLE_DEMO_FUTURE_FEATURE=true so it does NOT appear
in production unless the env var is set.

To enable: set ENABLE_DEMO_FUTURE_FEATURE=true
To disable: unset it or remove this directory.
Neither action requires editing any other file.
"""
import io
import logging
from PIL import Image, ImageDraw

from psydox.core.registry import FeatureModule
from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType

_log = logging.getLogger("psydox.features.demo_future")

_MANIFEST = FeatureManifest(
    id="demo_future",
    name="Future Feature",
    description="Extensibility demonstration: zero-edit feature addition",
    category=FeatureCategory.UTILITY,
    icon="🚀",
    status=FeatureStatus.EXPERIMENTAL,
    requires_ai=False,
    supports_batch=True,
    supports_reference=False,
    supports_brand=False,
    supports_quality_check=True,
    processing_type=ProcessingType.INSTANT,
    version="0.1.0",
    tags=["demo", "extensibility", "future"],
    required_permission="classic",
    feature_flag="ENABLE_DEMO_FUTURE_FEATURE",
)


class DemoFutureFeature(FeatureModule):
    """
    Proof-of-concept feature.

    Behaviour: adds a configurable border/stamp to the image to prove
    that the full pipeline (upload → execute → QA → job → export)
    works for a brand-new feature with zero core-file edits.
    """

    @property
    def manifest(self) -> FeatureManifest:
        return _MANIFEST

    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        if not inputs.get("image_bytes"):
            return False, ["Image is required."]
        return True, []

    def execute(self, inputs: dict, context: dict) -> dict:
        image_bytes = inputs["image_bytes"]
        label_text  = inputs.get("label", "DEMO FUTURE FEATURE")
        border_px   = int(inputs.get("border_px", 8))
        color       = inputs.get("border_color", "#00FF99")

        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            w, h = img.size

            # Parse border color
            hex_c = color.lstrip("#")
            rgb   = tuple(int(hex_c[i:i+2], 16) for i in (0, 2, 4)) if len(hex_c) == 6 else (0, 255, 153)

            # Draw border
            draw = ImageDraw.Draw(img)
            for i in range(border_px):
                draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=rgb)

            # Draw label in corner
            draw.rectangle([0, h - 30, w, h], fill=(0, 0, 0, 180))
            draw.text((8, h - 22), label_text, fill=(255, 255, 255))

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=92)

            return {
                "success": True,
                "outputs": [{"bytes": buf.getvalue(), "label": label_text, "mime": "image/jpeg"}],
                "errors":  [],
                "metadata": {
                    "feature_id": self.manifest.id,
                    "border_px":  border_px,
                    "color":      color,
                    "label":      label_text,
                    "note":       "Extensibility proof: zero core-file edits required",
                },
            }
        except Exception as e:
            _log.exception("DemoFutureFeature.execute failed")
            return {"success": False, "outputs": [], "errors": [str(e)], "metadata": {}}
