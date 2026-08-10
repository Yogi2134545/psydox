"""Psydox Feature — AI Model Generation (wraps existing ModelGenerator via AIOrchestrator)."""
import io
import logging
from PIL import Image

from psydox.core.registry import FeatureModule
from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType

_log = logging.getLogger("psydox.features.model_gen")

_MANIFEST = FeatureManifest(
    id="model_gen",
    name="AI Model",
    description="Show your product on AI-generated fashion models",
    category=FeatureCategory.MODEL,
    icon="👤",
    status=FeatureStatus.STABLE,
    requires_ai=True,
    supports_batch=False,
    supports_reference=True,
    supports_quality_check=True,
    processing_type=ProcessingType.SLOW,
    version="2.0.0",
    tags=["model", "fashion", "ai", "human"],
    required_permission="ai_studio",
)


class ModelGenFeature(FeatureModule):

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
        gender       = inputs.get("gender", "Female")
        age_group    = inputs.get("age_group", "25-35")
        ethnicity    = inputs.get("ethnicity", "South Asian / Indian")
        style        = inputs.get("style", "Natural / Minimal")
        product_desc = inputs.get("product_desc", "")
        ratio_wh     = context.get("ratio_wh")

        try:
            from psydox.ai_core.orchestrator import get_orchestrator, AIRequest
            from psydox.ai_core.prompt_engine import PromptEngine, PromptContext
            from psydox.ai_core.router import TaskType
            from nano_banana.prompt_builder import build_model_prompt

            prompt = build_model_prompt(gender, age_group, ethnicity, style, product_desc)
            ctx    = PromptContext(product_desc=product_desc, style=style)

            request = AIRequest(
                task=TaskType.MODEL_GENERATION,
                prompt=prompt,
                reference_bytes=image_bytes,
                feature_id=self.manifest.id,
            )
            result = get_orchestrator().generate(request, run_quality=True)

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

            label = f"{gender} {age_group} · {ethnicity}"
            return {
                "success": True,
                "outputs": [{"bytes": buf.getvalue(), "label": label, "mime": "image/jpeg"}],
                "errors":  [],
                "metadata": {
                    "gender":          gender,
                    "age_group":       age_group,
                    "ethnicity":       ethnicity,
                    "style":           style,
                    "provider":        result.provider,
                    "quality_score":   result.quality_score,
                    "quality_verdict": result.quality_verdict,
                    "cost_estimate":   result.cost_estimate,
                    "feature_id":      self.manifest.id,
                },
            }
        except Exception as e:
            _log.exception("ModelGenFeature.execute failed")
            return {"success": False, "outputs": [], "errors": [str(e)], "metadata": {}}

    def _apply_ratio(self, img: Image.Image, target_wh: tuple) -> Image.Image:
        tw, th = target_wh
        iw, ih = img.size
        scale  = min(tw / iw, th / ih, 2.0)
        nw, nh = int(iw * scale), int(ih * scale)
        scaled = img.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (tw, th), (255, 255, 255))
        canvas.paste(scaled, ((tw - nw) // 2, (th - nh) // 2))
        return canvas
