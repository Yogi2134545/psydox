"""
Psydox Product Intelligence Engine

Uses Gemini vision to extract structured, confidence-tagged product attributes.
Every attribute carries a value, confidence (0–1), and source tag.

Never fabricates uncertain attributes — if confidence < threshold, attribute is
omitted rather than guessed.

Design principles:
  - Caller always gets a valid ProductAttributes object, even on total failure
    (fallback: all attributes empty, confidence 0.0)
  - Uses JSON-mode Gemini response for deterministic parsing
  - Falls back to MockVisionProvider in DEBUG_MODE
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger("psydox.product.intelligence")

_CONFIDENCE_THRESHOLD = 0.35  # below this, attribute is suppressed


@dataclass
class AttributeValue:
    """A single product attribute with provenance."""
    value: str
    confidence: float          # 0.0–1.0
    source: str = "vision"     # "vision" | "user" | "inferred" | "locked"

    def is_reliable(self) -> bool:
        return self.confidence >= _CONFIDENCE_THRESHOLD

    def to_dict(self) -> dict:
        return {"value": self.value, "confidence": round(self.confidence, 3), "source": self.source}


@dataclass
class ProductAttributes:
    """Structured product metadata extracted from an image."""
    category:       Optional[AttributeValue] = None
    sub_category:   Optional[AttributeValue] = None
    primary_color:  Optional[AttributeValue] = None
    secondary_colors: list[AttributeValue]   = field(default_factory=list)
    pattern:        Optional[AttributeValue] = None
    material:       Optional[AttributeValue] = None
    brand_text:     list[AttributeValue]     = field(default_factory=list)
    key_features:   list[AttributeValue]     = field(default_factory=list)
    style_keywords: list[AttributeValue]     = field(default_factory=list)
    overall_confidence: float = 0.0
    raw_description: str = ""
    analysis_model: str = ""
    analysis_source: str = "unavailable"   # "vision" | "mock" | "unavailable"

    def is_useful(self) -> bool:
        return self.overall_confidence >= _CONFIDENCE_THRESHOLD and self.category is not None

    def to_prompt_clause(self) -> str:
        """Build a preservation clause for AI prompts."""
        parts = []
        if self.category and self.category.is_reliable():
            parts.append(f"a {self.category.value}")
        if self.primary_color and self.primary_color.is_reliable():
            parts.append(f"in {self.primary_color.value}")
        if self.pattern and self.pattern.is_reliable() and self.pattern.value != "solid":
            parts.append(f"with {self.pattern.value} pattern")
        if self.brand_text:
            brands = [b.value for b in self.brand_text if b.is_reliable()]
            if brands:
                parts.append(f"showing brand text: {', '.join(brands)}")
        if not parts:
            return ""
        return "The product is " + " ".join(parts) + ". Preserve ALL product details exactly."

    def to_dict(self) -> dict:
        def _av(a: Optional[AttributeValue]):
            return a.to_dict() if a else None
        return {
            "category":           _av(self.category),
            "sub_category":       _av(self.sub_category),
            "primary_color":      _av(self.primary_color),
            "secondary_colors":   [a.to_dict() for a in self.secondary_colors],
            "pattern":            _av(self.pattern),
            "material":           _av(self.material),
            "brand_text":         [a.to_dict() for a in self.brand_text],
            "key_features":       [a.to_dict() for a in self.key_features],
            "style_keywords":     [a.to_dict() for a in self.style_keywords],
            "overall_confidence": round(self.overall_confidence, 3),
            "analysis_source":    self.analysis_source,
        }


_ANALYSIS_PROMPT = """You are a product photography analyst.
Analyze this product image and return a JSON object with ONLY these keys:
{
  "category": {"value": "...", "confidence": 0.0},
  "sub_category": {"value": "...", "confidence": 0.0},
  "primary_color": {"value": "...", "confidence": 0.0},
  "secondary_colors": [{"value": "...", "confidence": 0.0}],
  "pattern": {"value": "solid|striped|checked|floral|geometric|other", "confidence": 0.0},
  "material": {"value": "...", "confidence": 0.0},
  "brand_text": [{"value": "...", "confidence": 0.0}],
  "key_features": [{"value": "...", "confidence": 0.0}],
  "style_keywords": [{"value": "...", "confidence": 0.0}],
  "overall_confidence": 0.0,
  "raw_description": "..."
}

Rules:
- confidence is 0.0–1.0. Use 0.0 if you cannot determine the attribute.
- Never guess. If uncertain, use low confidence.
- brand_text: only include if clearly visible text/logo exists.
- key_features: include things like "zipper", "button", "hood", "collar" etc.
- Return ONLY valid JSON, no commentary.
"""


class ProductIntelligenceEngine:
    """
    Analyzes a product image and returns structured ProductAttributes.
    Always returns a valid object — never raises.
    """

    def analyze(self, image_bytes: bytes, product_id: str = "") -> ProductAttributes:
        """
        Analyze image_bytes and return ProductAttributes.
        Falls back gracefully if AI is unavailable.
        """
        if not image_bytes:
            return ProductAttributes(analysis_source="unavailable")

        try:
            return self._analyze_via_router(image_bytes)
        except Exception as exc:
            _log.warning("ProductIntelligenceEngine: analysis failed (%s), returning empty attrs", exc)
            return ProductAttributes(analysis_source="unavailable")

    def _analyze_via_router(self, image_bytes: bytes) -> ProductAttributes:
        from psydox.ai_core.router import build_router, TaskType
        router = build_router()
        vision = router.get_vision_provider()

        if vision is None:
            return ProductAttributes(analysis_source="unavailable")

        result_json = vision.analyze(image_bytes, _ANALYSIS_PROMPT)

        try:
            data = json.loads(result_json)
        except (json.JSONDecodeError, TypeError):
            # Try to extract JSON block from free-text response
            import re
            m = re.search(r'\{.*\}', result_json, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group())
                except Exception:
                    return ProductAttributes(analysis_source="vision", overall_confidence=0.0)
            else:
                return ProductAttributes(analysis_source="vision", overall_confidence=0.0)

        return self._parse(data)

    def _parse(self, data: dict) -> ProductAttributes:
        def _av(raw) -> Optional[AttributeValue]:
            if not raw or not isinstance(raw, dict):
                return None
            v = raw.get("value", "")
            c = float(raw.get("confidence", 0.0))
            if not v or c < 0.35:
                return None
            return AttributeValue(value=str(v).strip(), confidence=min(max(c, 0.0), 1.0))

        def _avlist(raw) -> list[AttributeValue]:
            if not isinstance(raw, list):
                return []
            result = []
            for item in raw:
                av = _av(item)
                if av:
                    result.append(av)
            return result

        attrs = ProductAttributes(
            category         = _av(data.get("category")),
            sub_category     = _av(data.get("sub_category")),
            primary_color    = _av(data.get("primary_color")),
            secondary_colors = _avlist(data.get("secondary_colors", [])),
            pattern          = _av(data.get("pattern")),
            material         = _av(data.get("material")),
            brand_text       = _avlist(data.get("brand_text", [])),
            key_features     = _avlist(data.get("key_features", [])),
            style_keywords   = _avlist(data.get("style_keywords", [])),
            overall_confidence = float(data.get("overall_confidence", 0.0)),
            raw_description  = str(data.get("raw_description", ""))[:500],
            analysis_source  = "vision",
        )
        return attrs
