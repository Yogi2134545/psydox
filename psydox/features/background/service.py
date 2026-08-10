"""
Psydox Feature — Background

Handles both classic (instant, no AI) and AI-generated backgrounds.
Wraps the existing BackgroundGenerator and AIOrchestrator.
Routes intelligently: solid/gradient → classic; scene → AI.
"""
import io
import logging
from PIL import Image

from psydox.core.registry import FeatureModule
from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType
from psydox.ai_core.router import TaskType

_log = logging.getLogger("psydox.features.background")

# Backgrounds that can be generated instantly with PIL
_CLASSIC_BACKGROUNDS = {
    "White":          (255, 255, 255),
    "Light Grey":     (240, 240, 240),
    "Grey":           (180, 180, 180),
    "Dark Grey":      (80,  80,  80),
    "Black":          (20,  20,  20),
    "Luxury White":   (248, 248, 248),
    "Cream":          (255, 253, 240),
    "Beige":          (245, 235, 210),
    "Light Blue":     (220, 235, 250),
    "Navy":           (20,  30,  70),
    "Mint":           (200, 240, 225),
    "Lavender":       (225, 215, 245),
    "Blush Pink":     (255, 225, 230),
    "Coral":          (255, 200, 185),
    "Sage Green":     (185, 210, 185),
    "Charcoal":       (55,  55,  60),
    "Off-White":      (252, 250, 245),
    "Rose Gold":      (245, 215, 210),
}

_CLASSIC_GRADIENTS = {
    "Marble":         ((245, 245, 245), (220, 220, 220)),
    "Studio Light":   ((250, 250, 252), (215, 215, 220)),
    "Blue-Purple":    ((100, 140, 230), (160, 80,  200)),
    "Pink-Orange":    ((255, 180, 180), (255, 150, 80)),
    "Green-Blue":     ((80,  200, 180), (60,  100, 200)),
    "Warm Sunset":    ((255, 150, 60),  (255, 100, 120)),
    "Cool Ice":       ((200, 230, 255), (170, 200, 240)),
    "Midnight":       ((20,  20,  50),  (60,  30,  90)),
    "Gold":           ((230, 190, 80),  (200, 150, 40)),
    "Luxury Dark":    ((30,  25,  40),  (50,  40,  65)),
}

_MANIFEST = FeatureManifest(
    id="background",
    name="AI Background",
    description="Replace product backgrounds — instant for colors, AI for lifestyle scenes",
    category=FeatureCategory.BACKGROUND,
    icon="✨",
    status=FeatureStatus.STABLE,
    requires_ai=False,  # classic path works without AI
    supports_batch=True,
    supports_reference=True,
    supports_quality_check=True,
    processing_type=ProcessingType.INSTANT,
    version="2.0.0",
    tags=["background", "studio", "lifestyle", "instant"],
    required_permission="ai_studio",
)


class BackgroundFeature(FeatureModule):

    @property
    def manifest(self) -> FeatureManifest:
        return _MANIFEST

    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        errors = []
        if not inputs.get("image_bytes"):
            errors.append("Product image is required.")
        bg = inputs.get("background_option", "")
        if not bg:
            errors.append("Select a background option.")
        return len(errors) == 0, errors

    def execute(self, inputs: dict, context: dict) -> dict:
        image_bytes     = inputs["image_bytes"]
        background_opt  = inputs.get("background_option", "White")
        custom_prompt   = inputs.get("custom_prompt", "")
        product_desc    = inputs.get("product_desc", "")
        ratio_wh        = context.get("ratio_wh")

        try:
            src_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as e:
            return self._error(f"Cannot open image: {e}")

        # Route: classic (instant) vs AI
        if background_opt in _CLASSIC_BACKGROUNDS:
            result_img = self._classic_solid(src_img, _CLASSIC_BACKGROUNDS[background_opt])
            engine_label = "Classic (instant)"
        elif background_opt in _CLASSIC_GRADIENTS:
            result_img = self._classic_gradient(src_img, *_CLASSIC_GRADIENTS[background_opt])
            engine_label = "Classic (instant)"
        elif background_opt == "Transparent":
            result_img = self._remove_background(src_img)
            engine_label = "Classic (rembg)"
        elif background_opt == "Auto (keep original)":
            result_img = src_img
            engine_label = "Classic (passthrough)"
        else:
            # Scene / custom → AI generation
            result = self._generate_ai(src_img, background_opt, custom_prompt, product_desc)
            if not result["success"]:
                return result
            result_img   = Image.open(io.BytesIO(result["image_bytes"])).convert("RGB")
            engine_label = result.get("engine", "AI")

        # Apply ratio
        if ratio_wh:
            result_img = self._apply_ratio(result_img, ratio_wh)

        buf = io.BytesIO()
        result_img.save(buf, format="JPEG", quality=92)

        return {
            "success": True,
            "outputs": [{"bytes": buf.getvalue(), "label": "result", "mime": "image/jpeg"}],
            "errors":  [],
            "metadata": {
                "background_option": background_opt,
                "engine":            engine_label,
                "feature_id":        self.manifest.id,
            },
        }

    # ── Classic helpers ───────────────────────────────────────────────────────

    def _remove_background(self, img: Image.Image) -> Image.Image:
        try:
            import rembg
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result = rembg.remove(buf.getvalue())
            return Image.open(io.BytesIO(result)).convert("RGBA")
        except Exception:
            return img.convert("RGBA")

    def _classic_solid(self, src: Image.Image, color: tuple) -> Image.Image:
        fg = self._remove_background(src)
        bg = Image.new("RGBA", fg.size, color + (255,))
        if fg.mode == "RGBA":
            bg.paste(fg, mask=fg.split()[3])
        else:
            bg.paste(fg)
        return bg.convert("RGB")

    def _classic_gradient(self, src: Image.Image, top, bottom) -> Image.Image:
        from PIL import ImageDraw
        fg = self._remove_background(src)
        w, h = fg.size
        bg = Image.new("RGBA", (w, h))
        draw = ImageDraw.Draw(bg)
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b, 255))
        if fg.mode == "RGBA":
            bg.paste(fg, mask=fg.split()[3])
        else:
            bg.paste(fg)
        return bg.convert("RGB")

    def _generate_ai(self, src: Image.Image, bg_opt: str, custom_prompt: str, product_desc: str) -> dict:
        try:
            from psydox.ai_core.orchestrator import get_orchestrator, AIRequest
            from psydox.ai_core.prompt_engine import PromptEngine, PromptContext
            from psydox.ai_core.router import TaskType

            buf = io.BytesIO()
            src.save(buf, format="JPEG", quality=90)
            ref_bytes = buf.getvalue()

            ctx = PromptContext(
                product_desc=product_desc,
                environment=custom_prompt or bg_opt,
            )
            prompt = PromptEngine().build_background(ctx).to_text()

            request = AIRequest(
                task=TaskType.CREATIVE_BACKGROUND,
                prompt=prompt,
                reference_bytes=ref_bytes,
                feature_id=self.manifest.id,
            )
            result = get_orchestrator().generate(request)
            if result.success:
                return {
                    "success": True,
                    "image_bytes": result.image_bytes,
                    "engine": f"AI ({result.provider})",
                }
            return self._error(result.user_message or result.error or "AI generation failed.")
        except Exception as e:
            return self._error(str(e))

    def _apply_ratio(self, img: Image.Image, target_wh: tuple) -> Image.Image:
        tw, th = target_wh
        iw, ih = img.size
        scale = min(tw / iw, th / ih, 2.0)
        nw, nh = int(iw * scale), int(ih * scale)
        scaled = img.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (tw, th), (255, 255, 255))
        canvas.paste(scaled, ((tw - nw) // 2, (th - nh) // 2))
        return canvas

    @staticmethod
    def _error(msg: str) -> dict:
        return {"success": False, "outputs": [], "errors": [msg], "metadata": {}}

    def get_ui_config(self) -> dict:
        options = list(_CLASSIC_BACKGROUNDS.keys()) + list(_CLASSIC_GRADIENTS.keys())
        return {
            "inputs": [
                {"id": "image_bytes", "type": "image", "label": "Product Image", "required": True},
                {"id": "product_desc", "type": "text", "label": "Product Description", "required": False},
            ],
            "options": [
                {"id": "background_option", "type": "select", "label": "Background",
                 "choices": options + ["Transparent", "Auto (keep original)"]},
                {"id": "custom_prompt", "type": "text", "label": "Custom AI Prompt",
                 "placeholder": "Describe a scene…"},
            ],
        }
