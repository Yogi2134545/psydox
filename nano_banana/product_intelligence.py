"""
Nano Banana — Product Intelligence
Analyzes product images using Gemini text+vision to extract structured attributes.
Results are used to enrich generation prompts with accurate product preservation clauses.

This is an AI feature — requires GOOGLE_API_KEY with generateContent access.
Falls back gracefully (returns empty attributes) when the API is unavailable.
"""
import io
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api_client import GeminiClient

_log = logging.getLogger("nano_banana.product_intelligence")

_TEXT_MODEL = "gemini-2.0-flash"

_ANALYSIS_PROMPT = """You are a professional product photographer's AI assistant.
Analyze the product image and return a JSON object with ONLY these fields:
{
  "product_type": "<short category, e.g. sneaker, t-shirt, handbag, watch>",
  "primary_colors": ["<color1>", "<color2>"],
  "secondary_colors": ["<accent1>"],
  "pattern": "<one of: solid, striped, checked, printed, textured, camo, floral, geometric, abstract, logo-heavy, other>",
  "material_hints": ["<material1>", "<material2>"],
  "key_features": ["<distinctive detail 1>", "<detail 2>"],
  "brand_text": ["<any visible brand name or logo text>"],
  "style_keywords": ["<word1>", "<word2>", "<word3>"],
  "confidence": 0.85,
  "raw_description": "<one sentence, suitable for use in an image generation prompt>"
}
Return ONLY valid JSON. No markdown, no code fences, no explanation."""


@dataclass
class ProductAttributes:
    product_type: str = ""
    primary_colors: list = field(default_factory=list)
    secondary_colors: list = field(default_factory=list)
    pattern: str = "solid"
    material_hints: list = field(default_factory=list)
    key_features: list = field(default_factory=list)
    brand_text: list = field(default_factory=list)
    style_keywords: list = field(default_factory=list)
    confidence: float = 0.0
    raw_description: str = ""

    def is_useful(self) -> bool:
        """True when the analysis returned enough data to act on."""
        return self.confidence >= 0.3 and bool(self.product_type)

    def to_prompt_clause(self) -> str:
        """
        Build a product-preservation clause to prepend/append to generation prompts.
        Returns empty string when attributes are not useful.
        """
        if not self.is_useful():
            return ""

        parts: list[str] = []

        if self.product_type:
            parts.append(f"The product is a {self.product_type}.")

        colors = self.primary_colors + self.secondary_colors
        if colors:
            parts.append(f"Exact colors: {', '.join(colors)} — do not change.")

        if self.pattern and self.pattern not in ("solid", "other", ""):
            parts.append(f"Pattern: {self.pattern} — preserve exactly.")

        if self.brand_text:
            brands = ", ".join(self.brand_text)
            parts.append(f"Visible branding: {brands} — reproduce exactly, do not alter or omit.")

        if self.key_features:
            parts.append(f"Distinctive features: {', '.join(self.key_features[:3])}.")

        return " ".join(parts)


class ProductAnalyzer:
    """
    Uses Gemini's text+vision capability to extract structured product attributes
    from a reference image.

    - Calls the fast gemini-2.0-flash model for text analysis (not the image gen model).
    - Falls back to empty ProductAttributes on any error — never raises.
    - Results should be cached by the caller; do not call on every rerun.
    """

    def __init__(self, client: "GeminiClient"):
        self._client = client

    def analyze(self, image_bytes: bytes) -> ProductAttributes:
        """
        Analyze product image. Always returns ProductAttributes (never raises).
        confidence=0.0 means the analysis did not run or failed.
        """
        if not self._client or not getattr(self._client, "api_key", None):
            return ProductAttributes(confidence=0.0)
        if not getattr(self._client, "_sdk_ok", False):
            return ProductAttributes(confidence=0.0)

        try:
            return self._run(image_bytes)
        except Exception as exc:
            _log.warning("ProductAnalyzer.analyze failed: %s", exc)
            return ProductAttributes(confidence=0.0)

    def _run(self, image_bytes: bytes) -> ProductAttributes:
        from PIL import Image as _PIL

        pil_img = _PIL.open(io.BytesIO(image_bytes)).convert("RGB")

        response = self._client._sdk.models.generate_content(
            model=_TEXT_MODEL,
            contents=[pil_img, _ANALYSIS_PROMPT],
        )

        text = ""
        for candidate in (response.candidates or []):
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text

        text = text.strip()

        # Strip markdown code fences if the model added them despite instructions
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        data = json.loads(text)

        return ProductAttributes(
            product_type=str(data.get("product_type", "")).strip(),
            primary_colors=list(data.get("primary_colors", [])),
            secondary_colors=list(data.get("secondary_colors", [])),
            pattern=str(data.get("pattern", "solid")).strip(),
            material_hints=list(data.get("material_hints", [])),
            key_features=list(data.get("key_features", [])),
            brand_text=list(data.get("brand_text", [])),
            style_keywords=list(data.get("style_keywords", [])),
            confidence=float(data.get("confidence", 0.0)),
            raw_description=str(data.get("raw_description", "")).strip(),
        )
