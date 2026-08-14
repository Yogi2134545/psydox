"""
Psydox Lifestyle Engine

Bridges structured scene/category controls to the AI orchestrator.

Usage::

    engine = LifestyleEngine()
    result = engine.generate(
        image_bytes=product_png,
        scene_id="casual_street",
        category_id="footwear",
        product_desc="Nike Air Max 90, white with red swoosh",
        marketplace_id="instagram_story",   # optional aspect ratio hint
    )
    if result.success:
        save(result.image_bytes)

The engine:
  1. Looks up the scene from SceneLibrary
  2. Pulls category prompt_keywords and negative_keywords from CategoryRegistry
  3. Builds an enriched PromptContext
  4. Constructs a StructuredPrompt via PromptEngine.build_lifestyle()
  5. Submits to the AIOrchestrator
  6. Returns an EngineResult with image + quality metadata
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger("psydox.lifestyle.engine")


@dataclass
class LifestyleRequest:
    image_bytes:    bytes
    scene_id:       str   = "casual_street"
    category_id:    str   = "generic"
    product_desc:   str   = ""
    product_colors: list  = field(default_factory=list)
    product_brand:  list  = field(default_factory=list)
    marketplace_id: Optional[str] = None
    custom_notes:   str   = ""   # appended to scene description verbatim


@dataclass
class LifestyleResult:
    success:       bool
    image_bytes:   Optional[bytes]
    scene_id:      str
    prompt_text:   str        # the final prompt sent to the provider
    provider:      str        = ""
    model:         str        = ""
    quality_score: Optional[int]  = None
    cost_estimate: float          = 0.0
    error:         str            = ""


class LifestyleEngine:
    """
    Category- and scene-aware wrapper over the AI orchestrator.

    Enriches prompts with:
    - SceneDefinition.description (scene environment details)
    - CategoryDefinition.prompt_keywords (product-type cues)
    - CategoryDefinition.negative_keywords (things to avoid)
    - Marketplace aspect ratio hint (if preset provided)
    """

    def generate(self, request: LifestyleRequest) -> LifestyleResult:
        try:
            return self._generate(request)
        except Exception as exc:
            _log.exception("LifestyleEngine.generate failed")
            return LifestyleResult(
                success=False,
                image_bytes=None,
                scene_id=request.scene_id,
                prompt_text="",
                error=str(exc),
            )

    # ── Implementation ─────────────────────────────────────────────────────────

    def _generate(self, request: LifestyleRequest) -> LifestyleResult:
        from psydox.lifestyle.scenes     import get_scene_library
        from psydox.category.registry    import get_category_registry
        from psydox.ai_core.prompt_engine import PromptEngine, PromptContext
        from psydox.ai_core.orchestrator  import get_orchestrator, AIRequest
        from psydox.ai_core.router        import TaskType

        # 1. Look up scene
        library = get_scene_library()
        scene   = library.get(request.scene_id) or library.get("casual_street")

        # 2. Look up category for keyword enrichment
        cat = get_category_registry().get(request.category_id)

        # 3. Build environment description
        environment = scene.description
        if request.custom_notes:
            environment = f"{environment}, {request.custom_notes}"

        # 4. Append category positive keywords to style
        style_parts = [scene.mood]
        if cat.prompt_keywords:
            style_parts.extend(cat.prompt_keywords[:3])   # top 3 only — avoid prompt bloat
        style = ", ".join(style_parts)

        # 5. Build negatives from scene negatives + category negatives
        negatives = list(cat.negative_keywords)

        # 6. Aspect ratio from marketplace preset (if provided)
        aspect_ratio = ""
        if request.marketplace_id:
            try:
                from psydox.marketplace.registry import get_marketplace_registry
                preset = get_marketplace_registry().get(request.marketplace_id)
                if preset:
                    aspect_ratio = f"{preset.width}:{preset.height}"
            except Exception:
                pass

        # 7. Build PromptContext
        ctx = PromptContext(
            product_desc=request.product_desc,
            product_type=cat.name,
            product_colors=request.product_colors,
            product_brand=request.product_brand,
            style=style,
            environment=environment,
            lighting=scene.lighting,
            camera_angle=scene.camera,
            aspect_ratio=aspect_ratio,
            custom_instructions="",
        )

        # 8. Build StructuredPrompt
        structured = PromptEngine().build_lifestyle(ctx)
        # Inject category negatives into the prompt's negatives list
        structured.negatives = list(structured.negatives) + negatives
        prompt_text = structured.to_text()

        # 9. Submit to orchestrator
        ai_request = AIRequest(
            task=TaskType.LIFESTYLE,
            prompt=prompt_text,
            reference_bytes=request.image_bytes,
            feature_id="lifestyle",
        )
        result = get_orchestrator().generate(ai_request, run_quality=True)

        if not result.success:
            return LifestyleResult(
                success=False,
                image_bytes=None,
                scene_id=request.scene_id,
                prompt_text=prompt_text,
                error=result.user_message or "AI generation failed",
            )

        # 10. Apply aspect ratio crop if needed
        image_bytes = result.image_bytes
        if aspect_ratio and request.marketplace_id:
            try:
                image_bytes = self._apply_ratio(image_bytes, aspect_ratio)
            except Exception as exc:
                _log.warning("Ratio crop failed: %s", exc)

        return LifestyleResult(
            success=True,
            image_bytes=image_bytes,
            scene_id=request.scene_id,
            prompt_text=prompt_text,
            provider=result.provider or "",
            model=result.model or "",
            quality_score=result.quality_score,
            cost_estimate=result.cost_estimate or 0.0,
        )

    def _apply_ratio(self, image_bytes: bytes, aspect_ratio: str) -> bytes:
        """Crop/letterbox to target aspect ratio (e.g. '1000:1250')."""
        from PIL import Image

        tw, th = (int(x) for x in aspect_ratio.split(":"))
        img    = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        iw, ih = img.size

        # Crop to aspect, then scale to target
        target_aspect = tw / th
        src_aspect    = iw / ih
        if src_aspect > target_aspect:
            new_iw = int(ih * target_aspect)
            left   = (iw - new_iw) // 2
            img    = img.crop((left, 0, left + new_iw, ih))
        elif src_aspect < target_aspect:
            new_ih = int(iw / target_aspect)
            top    = (ih - new_ih) // 2
            img    = img.crop((0, top, iw, top + new_ih))

        scale = min(tw / img.width, th / img.height, 2.0)
        nw, nh = int(img.width * scale), int(img.height * scale)
        img = img.resize((nw, nh), Image.LANCZOS)

        canvas = Image.new("RGB", (tw, th), (255, 255, 255))
        canvas.paste(img, ((tw - nw) // 2, (th - nh) // 2))

        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=92)
        return buf.getvalue()
