"""Psydox Feature — Lifestyle Generation (wraps existing LifestyleGenerator via AIOrchestrator)."""
import io
import logging
from PIL import Image

from psydox.core.registry import FeatureModule
from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType

_log = logging.getLogger("psydox.features.lifestyle")

_MANIFEST = FeatureManifest(
    id="lifestyle",
    name="AI Lifestyle",
    description="Place your product in authentic lifestyle photography scenes",
    category=FeatureCategory.CREATIVE,
    icon="🌴",
    status=FeatureStatus.STABLE,
    requires_ai=True,
    supports_batch=False,
    supports_reference=True,
    supports_brand=True,
    supports_quality_check=True,
    processing_type=ProcessingType.SLOW,
    version="2.0.0",
    tags=["lifestyle", "ai", "scene", "creative"],
    required_permission="ai_studio",
)


class LifestyleFeature(FeatureModule):

    @property
    def manifest(self) -> FeatureManifest:
        return _MANIFEST

    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        errors = []
        if not inputs.get("image_bytes"):
            errors.append("Product image is required.")
        return len(errors) == 0, errors

    def execute(self, inputs: dict, context: dict) -> dict:
        image_bytes  = inputs["image_bytes"]
        style        = inputs.get("style", "Casual Street Style")
        custom_prompt = inputs.get("custom_prompt", "")
        product_desc  = inputs.get("product_desc", "")
        ratio_wh     = context.get("ratio_wh")

        try:
            from psydox.ai_core.orchestrator import AIOrchestrator, get_orchestrator, AIRequest
            from psydox.ai_core.prompt_engine import PromptEngine, PromptContext
            from psydox.ai_core.router import TaskType

            ctx = PromptContext(
                product_desc=product_desc,
                style=style,
                environment=custom_prompt or style,
            )
            prompt = custom_prompt or PromptEngine().build_lifestyle(ctx).to_text()

            request = AIRequest(
                task=TaskType.LIFESTYLE,
                prompt=prompt,
                reference_bytes=image_bytes,
                feature_id=self.manifest.id,
            )
            _router = context.get("router")
            _orch = AIOrchestrator(router=_router) if _router else get_orchestrator()
            result = _orch.generate(request, run_quality=True)

            if not result.success:
                return {
                    "success": False, "outputs": [], "errors": [result.user_message or "AI generation failed."],
                    "metadata": {},
                }

            img = Image.open(io.BytesIO(result.image_bytes)).convert("RGB")
            if ratio_wh:
                img = self._apply_ratio(img, ratio_wh)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=92)

            return {
                "success": True,
                "outputs": [{"bytes": buf.getvalue(), "label": style, "mime": "image/jpeg"}],
                "errors":  [],
                "metadata": {
                    "style":           style,
                    "provider":        result.provider,
                    "model":           result.model,
                    "quality_score":   result.quality_score,
                    "quality_verdict": result.quality_verdict,
                    "cost_estimate":   result.cost_estimate,
                    "feature_id":      self.manifest.id,
                },
            }
        except Exception as e:
            _log.exception("LifestyleFeature.execute failed")
            return {"success": False, "outputs": [], "errors": [str(e)], "metadata": {}}

    def _apply_ratio(self, img: Image.Image, target_wh: tuple) -> Image.Image:
        tw, th = target_wh
        iw, ih = img.size
        scale = min(tw / iw, th / ih, 2.0)
        nw, nh = int(iw * scale), int(ih * scale)
        scaled = img.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (tw, th), (255, 255, 255))
        canvas.paste(scaled, ((tw - nw) // 2, (th - nh) // 2))
        return canvas
