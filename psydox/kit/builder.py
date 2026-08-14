"""
Psydox Product Kit Builder

Generates a category-driven asset checklist for a product, optionally
tailored to one or more marketplaces.

A ProductKit describes every output asset that should be produced for a
product — not what was produced, but what should be.  It is configuration,
not state.

Key types:
  AssetSpec       — one output slot (main, detail, lifestyle, …)
  ProcessingHints — suggested background / shadow / composition for a slot
  ProductKit      — the full asset list for a category × marketplace combo

Building:
  kit = ProductKitBuilder().build("footwear", marketplace_ids=["amazon_main"])
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger("psydox.kit.builder")

# ── Asset-slot metadata ────────────────────────────────────────────────────────
# These are generic defaults; category / marketplace hints override them.

_SLOT_DEFAULTS: dict[str, dict] = {
    "main": {
        "label":       "Main product image",
        "purpose":     "Primary listing image; shown first in search results",
        "required":    True,
        "priority":    1,
        "composition": "centered",
        "shadow":      "none",
    },
    "front": {
        "label":       "Front view",
        "purpose":     "Full-front product shot for apparel / flat-lay",
        "required":    True,
        "priority":    2,
        "composition": "centered",
        "shadow":      "none",
    },
    "back": {
        "label":       "Back view",
        "purpose":     "Rear angle for completeness",
        "required":    False,
        "priority":    3,
        "composition": "centered",
        "shadow":      "none",
    },
    "side": {
        "label":       "Side view",
        "purpose":     "Profile angle highlighting silhouette",
        "required":    False,
        "priority":    3,
        "composition": "angled",
        "shadow":      "ground",
    },
    "pair": {
        "label":       "Pair / set shot",
        "purpose":     "Both items together (footwear, earrings, etc.)",
        "required":    False,
        "priority":    4,
        "composition": "centered",
        "shadow":      "ground",
    },
    "detail": {
        "label":       "Detail / close-up",
        "purpose":     "Texture, material, logo, or unique feature close-up",
        "required":    False,
        "priority":    4,
        "composition": "hero",
        "shadow":      "none",
    },
    "flat_lay": {
        "label":       "Flat lay",
        "purpose":     "Overhead flat-lay for apparel / accessories",
        "required":    False,
        "priority":    4,
        "composition": "centered",
        "shadow":      "none",
    },
    "interior": {
        "label":       "Interior / inside view",
        "purpose":     "Interior of bags, shoes, etc.",
        "required":    False,
        "priority":    5,
        "composition": "centered",
        "shadow":      "none",
    },
    "packaging": {
        "label":       "Packaging",
        "purpose":     "Product in original packaging",
        "required":    False,
        "priority":    5,
        "composition": "centered",
        "shadow":      "none",
    },
    "open": {
        "label":       "Open / uncapped",
        "purpose":     "Product open (beauty / skincare)",
        "required":    False,
        "priority":    4,
        "composition": "hero",
        "shadow":      "natural",
    },
    "angle": {
        "label":       "Angled view",
        "purpose":     "45° hero angle showing depth",
        "required":    False,
        "priority":    4,
        "composition": "angled",
        "shadow":      "natural",
    },
    "transparent": {
        "label":       "Transparent PNG",
        "purpose":     "No-background asset for compositing / marketplaces",
        "required":    False,
        "priority":    3,
        "composition": "centered",
        "shadow":      "none",
    },
    "lifestyle": {
        "label":       "Lifestyle image",
        "purpose":     "In-context / in-use product shot",
        "required":    False,
        "priority":    5,
        "composition": "hero",
        "shadow":      "none",
    },
    "hero": {
        "label":       "Hero / brand image",
        "purpose":     "Styled editorial or banner image",
        "required":    False,
        "priority":    6,
        "composition": "hero",
        "shadow":      "none",
    },
    "room_context": {
        "label":       "Room / scene context",
        "purpose":     "Product styled within a full room or scene",
        "required":    False,
        "priority":    5,
        "composition": "hero",
        "shadow":      "none",
    },
    "ingredients": {
        "label":       "Key ingredients callout",
        "purpose":     "Highlighting main ingredients for skincare / beauty",
        "required":    False,
        "priority":    5,
        "composition": "centered",
        "shadow":      "none",
    },
}


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ProcessingHints:
    background:  str    # "white" | "grey" | "contextual" | "transparent"
    shadow:      str    # "none" | "ground" | "natural"
    composition: str    # "centered" | "angled" | "hero"
    aspect_ratio: tuple = (1, 1)
    padding_pct:  float = 0.08

    def to_dict(self) -> dict:
        return {
            "background":   self.background,
            "shadow":       self.shadow,
            "composition":  self.composition,
            "aspect_ratio": list(self.aspect_ratio),
            "padding_pct":  self.padding_pct,
        }


@dataclass
class AssetSpec:
    slot:             str
    label:            str
    purpose:          str
    required:         bool
    priority:         int
    hints:            ProcessingHints
    marketplace_ids:  list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "slot":           self.slot,
            "label":          self.label,
            "purpose":        self.purpose,
            "required":       self.required,
            "priority":       self.priority,
            "hints":          self.hints.to_dict(),
            "marketplace_ids": self.marketplace_ids,
        }


@dataclass
class ProductKit:
    category_id:    str
    category_name:  str
    category_icon:  str
    assets:         list[AssetSpec]
    marketplace_ids: list[str] = field(default_factory=list)

    @property
    def required_assets(self) -> list[AssetSpec]:
        return [a for a in self.assets if a.required]

    @property
    def optional_assets(self) -> list[AssetSpec]:
        return [a for a in self.assets if not a.required]

    def slots(self) -> list[str]:
        return [a.slot for a in self.assets]

    def to_dict(self) -> dict:
        return {
            "category_id":    self.category_id,
            "category_name":  self.category_name,
            "category_icon":  self.category_icon,
            "marketplace_ids": self.marketplace_ids,
            "assets":         [a.to_dict() for a in self.assets],
        }


# ── Builder ────────────────────────────────────────────────────────────────────

class ProductKitBuilder:
    """
    Builds a ProductKit from a category id and optional marketplace ids.

    Reuses CategoryRegistry and MarketplaceRegistry — no new AI calls.
    """

    def build(
        self,
        category_id: str,
        marketplace_ids: Optional[list] = None,
    ) -> ProductKit:
        """
        Build a ProductKit for the given category and marketplaces.

        Parameters
        ----------
        category_id:
            A canonical category id (e.g. "footwear") or any string accepted
            by CategoryDetector.detect_from_text().
        marketplace_ids:
            Optional list of marketplace preset ids to tailor the kit to
            (e.g. ["amazon_main", "myntra_main"]).
        """
        from psydox.category.registry   import get_category_registry
        from psydox.marketplace.registry import get_marketplace_registry

        cat_registry = get_category_registry()
        mp_registry  = get_marketplace_registry()

        # Resolve category — accept free text via detector
        cat = cat_registry.get(category_id)
        if cat.id == "generic" and category_id not in ("generic", ""):
            from psydox.category.detector import CategoryDetector
            resolved, _ = CategoryDetector().detect_from_text(category_id)
            cat = resolved

        marketplace_ids = list(marketplace_ids or [])
        presets = [p for p in (mp_registry.get(mid) for mid in marketplace_ids) if p is not None]

        # Collect slot list from category recommended_assets
        slots: list[str] = list(cat.recommended_assets) or ["main", "detail", "lifestyle"]

        # Add any slots that a chosen marketplace requires but category doesn't list
        for preset in presets:
            rule = preset.compliance
            if getattr(rule, "bg_required", False) and "main" not in slots:
                slots.insert(0, "main")

        # Remove duplicates while preserving order
        seen: set = set()
        ordered_slots: list[str] = []
        for s in slots:
            if s not in seen:
                ordered_slots.append(s)
                seen.add(s)

        assets = []
        for slot in ordered_slots:
            spec = self._build_asset(slot, cat, presets)
            assets.append(spec)

        # Sort by priority (ascending), then by slot name for stability
        assets.sort(key=lambda a: (a.priority, a.slot))

        return ProductKit(
            category_id=cat.id,
            category_name=cat.name,
            category_icon=cat.icon,
            assets=assets,
            marketplace_ids=marketplace_ids,
        )

    # ── Private ────────────────────────────────────────────────────────────────

    def _build_asset(self, slot: str, cat, presets: list) -> AssetSpec:
        defaults = _SLOT_DEFAULTS.get(slot, {
            "label":       slot.replace("_", " ").title(),
            "purpose":     "",
            "required":    False,
            "priority":    9,
            "composition": cat.composition,
            "shadow":      cat.shadow,
        })

        # Start from category defaults
        background  = cat.background_default
        shadow      = defaults.get("shadow",      cat.shadow)
        composition = defaults.get("composition", cat.composition)
        aspect      = cat.aspect_ratio
        padding     = cat.padding_pct

        # Lifestyle / contextual slots get contextual bg regardless of category default
        if slot == "lifestyle":
            background = "contextual"
        elif slot == "transparent":
            background = "transparent"
            shadow     = "none"

        # Apply per-marketplace overrides from category.marketplace_hints
        # Use the first matching marketplace that has hints for this category
        mp_ids_applied: list[str] = []
        for preset in presets:
            hint = cat.marketplace_hints.get(preset.marketplace, {})
            if hint:
                if "aspect_ratio" in hint:
                    aspect = tuple(hint["aspect_ratio"])
                if "padding_pct" in hint:
                    padding = float(hint["padding_pct"])
                if "background_default" in hint:
                    background = hint["background_default"]
                mp_ids_applied.append(preset.id)
                break  # First matching marketplace wins

        # White bg always required for "main" if any marketplace has bg_required
        if slot == "main":
            for preset in presets:
                if getattr(preset.compliance, "bg_required", False):
                    background = "white"
                    break

        hints = ProcessingHints(
            background=background,
            shadow=shadow,
            composition=composition,
            aspect_ratio=aspect,
            padding_pct=padding,
        )

        return AssetSpec(
            slot=slot,
            label=defaults.get("label", slot.replace("_", " ").title()),
            purpose=defaults.get("purpose", ""),
            required=bool(defaults.get("required", False)),
            priority=int(defaults.get("priority", 9)),
            hints=hints,
            marketplace_ids=mp_ids_applied,
        )
