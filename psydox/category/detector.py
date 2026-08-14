"""
Psydox Category Detector

Maps a raw category string (from ProductIntelligenceEngine) to a
canonical CategoryDefinition.

Matching order — first match wins:
  1. Exact id match        e.g. "footwear"
  2. Exact alias match     e.g. "sneaker" → footwear
  3. Substring alias match e.g. "running shoe" → footwear (alias "shoe" matches)
  4. Substring id match    e.g. "foot" → footwear
  5. Fallback              "generic" @ confidence 0.0

detect_from_image() reuses the existing ProductIntelligenceEngine —
no duplicate AI calls, no duplicate vision provider.
"""
from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger("psydox.category.detector")


class CategoryDetector:
    """
    Maps free-text category labels to canonical CategoryDefinitions.

    Instantiate once and reuse — registry lookup is cheap in-memory.
    """

    def __init__(self, registry=None):
        from psydox.category.registry import get_category_registry
        self._registry = registry or get_category_registry()

    # ── Public API ─────────────────────────────────────────────────────────────

    def detect_from_text(self, raw: str) -> tuple:
        """
        Map a raw category string to (CategoryDefinition, confidence).

        Confidence is an estimate of match quality, NOT a model confidence —
        it reflects how specific the alias match was.
        """
        if not raw or not raw.strip():
            return self._registry.get("generic"), 0.0

        normalised = raw.strip().lower()

        # 1. Exact id match
        for cat in self._registry.all():
            if normalised == cat.id:
                return cat, 0.99

        # 2. Exact alias match
        for cat in self._registry.all():
            for alias in cat.aliases:
                if normalised == alias.lower():
                    return cat, 0.95

        # 3. Substring alias match (alias IS a substring of raw)
        best_cat  = None
        best_len  = 0
        for cat in self._registry.all():
            for alias in cat.aliases:
                a = alias.lower()
                if a in normalised and len(a) > best_len:
                    best_cat = cat
                    best_len = len(a)
        if best_cat:
            confidence = min(0.90, 0.50 + 0.04 * best_len)
            return best_cat, round(confidence, 2)

        # 4. Substring id match
        for cat in self._registry.all():
            if cat.id in normalised or normalised in cat.id:
                return cat, 0.50

        # 5. Generic fallback
        return self._registry.get("generic"), 0.0

    def detect_from_attributes(self, attrs) -> tuple:
        """
        Map ProductAttributes to (CategoryDefinition, confidence).

        attrs — a psydox.product.intelligence.ProductAttributes instance.
        Reuses already-computed attributes to avoid a second AI call.
        """
        if attrs is None or not attrs.category:
            return self._registry.get("generic"), 0.0
        cat_av = attrs.category
        cat, match_conf = self.detect_from_text(cat_av.value)
        # Combined confidence: match quality × vision confidence
        combined = round(match_conf * cat_av.confidence, 3)
        return cat, combined

    def detect_from_image(self, image_bytes: bytes) -> tuple:
        """
        Analyze image via ProductIntelligenceEngine and return
        (CategoryDefinition, confidence).

        This is the only path that performs an AI call.  Reuses the
        existing engine — no duplicate vision provider.
        """
        from psydox.product.intelligence import ProductIntelligenceEngine
        attrs = ProductIntelligenceEngine().analyze(image_bytes)
        return self.detect_from_attributes(attrs)
