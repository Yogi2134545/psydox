"""
Psydox Marketplace Registry

Full specification for every supported marketplace/channel preset.

Extends the 9 basic presets in psydox.features.classic.service.MARKETPLACE_PRESETS
with:
  - Compliance rules  (bg_required, min_resolution, max_file_kb, quality)
  - Padding rules     (padding_pct, product_coverage_pct)
  - Indian platforms  (Flipkart, Myntra, AJIO, Meesho, WooCommerce)
  - Custom slot

ClassicFeature.MARKETPLACE_PRESETS is intentionally NOT modified here —
backward compatibility is preserved by keeping that dict unchanged.
New code should call get_marketplace_registry() for richer specs.

Usage:
    reg    = get_marketplace_registry()
    preset = reg.get("myntra_main")
    print(preset.label, preset.width, preset.height, preset.compliance)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import logging

_log = logging.getLogger("psydox.marketplace.registry")


@dataclass
class ComplianceRule:
    """Marketplace-specific compliance requirements."""
    bg_required:         Optional[str]  = None      # "white" | "grey" | None (any)
    min_width:           int            = 400
    min_height:          int            = 400
    max_file_kb:         int            = 10240     # 10 MB default
    min_quality:         int            = 85
    no_text_overlay:     bool           = False
    no_watermark:        bool           = True
    no_border:           bool           = False
    no_logo_on_main:     bool           = False
    product_coverage_min_pct: float     = 0.70      # product must cover ≥70% of canvas
    notes:               str            = ""

    def to_dict(self) -> dict:
        return {
            "bg_required":        self.bg_required,
            "min_resolution":     f"{self.min_width}×{self.min_height}",
            "max_file_kb":        self.max_file_kb,
            "min_quality":        self.min_quality,
            "no_text_overlay":    self.no_text_overlay,
            "no_watermark":       self.no_watermark,
            "no_border":          self.no_border,
            "no_logo_on_main":    self.no_logo_on_main,
            "product_coverage":   f"≥{int(self.product_coverage_min_pct * 100)}%",
            "notes":              self.notes,
        }


@dataclass
class MarketplacePreset:
    id:            str
    label:         str
    marketplace:   str    # e.g. "amazon", "flipkart", "myntra"
    width:         int
    height:        int
    format:        str    # "JPEG" | "PNG"
    bg_color:      str    # "#FFFFFF" | "white" | "grey"
    padding_pct:   float  = 0.05
    quality:       int    = 92
    icon:          str    = "🛒"
    compliance:    ComplianceRule = field(default_factory=ComplianceRule)

    @property
    def aspect_ratio(self) -> tuple:
        from math import gcd
        g = gcd(self.width, self.height)
        return (self.width // g, self.height // g)

    @property
    def resolution_label(self) -> str:
        return f"{self.width}×{self.height}"

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "label":       self.label,
            "marketplace": self.marketplace,
            "width":       self.width,
            "height":      self.height,
            "format":      self.format,
            "bg_color":    self.bg_color,
            "padding_pct": self.padding_pct,
            "quality":     self.quality,
            "aspect_ratio": f"{self.aspect_ratio[0]}:{self.aspect_ratio[1]}",
            "compliance":  self.compliance.to_dict(),
        }


# ── Preset catalogue ──────────────────────────────────────────────────────────

_CATALOGUE: list[dict] = [
    # ── Amazon ────────────────────────────────────────────────────────────────
    {
        "id": "amazon_main", "label": "Amazon Main Image", "marketplace": "amazon",
        "icon": "📦",
        "width": 2000, "height": 2000, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 92,
        "compliance": {
            "bg_required": "white", "min_width": 1000, "min_height": 1000,
            "max_file_kb": 10240, "min_quality": 85,
            "no_text_overlay": True, "no_watermark": True,
            "no_logo_on_main": True, "no_border": True,
            "product_coverage_min_pct": 0.85,
            "notes": "Main image must be pure white (#FFFFFF) background. "
                     "Product must fill at least 85% of image frame. "
                     "No text, graphics, or additional products.",
        },
    },
    {
        "id": "amazon_swatch", "label": "Amazon Swatch", "marketplace": "amazon",
        "icon": "📦",
        "width": 500, "height": 500, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.10, "quality": 90,
        "compliance": {
            "bg_required": "white", "min_width": 300, "min_height": 300,
            "max_file_kb": 1024, "min_quality": 80,
            "no_text_overlay": False, "no_watermark": True,
            "notes": "Color/variant swatch thumbnail.",
        },
    },

    # ── Flipkart ──────────────────────────────────────────────────────────────
    {
        "id": "flipkart_main", "label": "Flipkart Main", "marketplace": "flipkart",
        "icon": "🛍️",
        "width": 1000, "height": 1000, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 92,
        "compliance": {
            "bg_required": "white", "min_width": 500, "min_height": 500,
            "max_file_kb": 5120, "min_quality": 85,
            "no_text_overlay": True, "no_watermark": True,
            "no_logo_on_main": True, "product_coverage_min_pct": 0.80,
            "notes": "Solid white background. No additional objects. "
                     "Image must be ≤5 MB.",
        },
    },
    {
        "id": "flipkart_additional", "label": "Flipkart Additional", "marketplace": "flipkart",
        "icon": "🛍️",
        "width": 1000, "height": 1000, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.08, "quality": 90,
        "compliance": {
            "bg_required": None, "min_width": 500, "min_height": 500,
            "max_file_kb": 5120, "min_quality": 80,
            "notes": "Additional angles and lifestyle images allowed.",
        },
    },

    # ── Myntra ────────────────────────────────────────────────────────────────
    {
        "id": "myntra_main", "label": "Myntra Main", "marketplace": "myntra",
        "icon": "👗",
        "width": 1080, "height": 1350, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.04, "quality": 92,
        "compliance": {
            "bg_required": "white", "min_width": 600, "min_height": 750,
            "max_file_kb": 3072, "min_quality": 85,
            "no_text_overlay": True, "no_watermark": True,
            "product_coverage_min_pct": 0.85,
            "notes": "4:5 portrait ratio. White background mandatory for main. "
                     "Product should occupy at least 85% of the canvas.",
        },
    },
    {
        "id": "myntra_lifestyle", "label": "Myntra Lifestyle", "marketplace": "myntra",
        "icon": "👗",
        "width": 1080, "height": 1350, "format": "JPEG", "bg_color": "#EEEEEE",
        "padding_pct": 0.04, "quality": 90,
        "compliance": {
            "bg_required": None, "min_width": 600, "min_height": 750,
            "max_file_kb": 3072, "min_quality": 80,
            "notes": "Lifestyle context allowed. May show model/mannequin.",
        },
    },

    # ── AJIO ─────────────────────────────────────────────────────────────────
    {
        "id": "ajio_main", "label": "AJIO Main", "marketplace": "ajio",
        "icon": "🔴",
        "width": 1500, "height": 2000, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 92,
        "compliance": {
            "bg_required": "white", "min_width": 750, "min_height": 1000,
            "max_file_kb": 5120, "min_quality": 85,
            "no_text_overlay": True, "no_watermark": True,
            "product_coverage_min_pct": 0.80,
            "notes": "3:4 portrait ratio. White background. "
                     "High resolution preferred (1500×2000).",
        },
    },

    # ── Meesho ────────────────────────────────────────────────────────────────
    {
        "id": "meesho_main", "label": "Meesho Main", "marketplace": "meesho",
        "icon": "🟣",
        "width": 1080, "height": 1080, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 90,
        "compliance": {
            "bg_required": "white", "min_width": 500, "min_height": 500,
            "max_file_kb": 3072, "min_quality": 80,
            "no_text_overlay": True, "no_watermark": True,
            "notes": "Square 1:1 ratio. Clean white background. Max 3 MB.",
        },
    },

    # ── Shopify ────────────────────────────────────────────────────────────────
    {
        "id": "shopify_product", "label": "Shopify Product", "marketplace": "shopify",
        "icon": "🟢",
        "width": 2048, "height": 2048, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 92,
        "compliance": {
            "bg_required": None, "min_width": 800, "min_height": 800,
            "max_file_kb": 10240, "min_quality": 85,
            "notes": "Shopify recommends 2048×2048 for zoom capability. "
                     "Background is store-dependent.",
        },
    },

    # ── WooCommerce ────────────────────────────────────────────────────────────
    {
        "id": "woocommerce_main", "label": "WooCommerce Main", "marketplace": "woocommerce",
        "icon": "🔵",
        "width": 800, "height": 800, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.08, "quality": 90,
        "compliance": {
            "bg_required": None, "min_width": 400, "min_height": 400,
            "max_file_kb": 5120, "min_quality": 80,
            "notes": "Default theme size. Actual dimensions depend on active theme. "
                     "Background is store-dependent.",
        },
    },

    # ── Social / Ads ──────────────────────────────────────────────────────────
    {
        "id": "instagram_sq", "label": "Instagram Square", "marketplace": "instagram",
        "icon": "📸",
        "width": 1080, "height": 1080, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 92,
        "compliance": {
            "min_width": 600, "min_height": 600, "max_file_kb": 8192, "min_quality": 85,
        },
    },
    {
        "id": "instagram_port", "label": "Instagram Portrait", "marketplace": "instagram",
        "icon": "📸",
        "width": 1080, "height": 1350, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 92,
        "compliance": {"min_width": 600, "min_height": 750, "max_file_kb": 8192},
    },
    {
        "id": "instagram_land", "label": "Instagram Landscape", "marketplace": "instagram",
        "icon": "📸",
        "width": 1080, "height": 566, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 92,
        "compliance": {"min_width": 600, "min_height": 314, "max_file_kb": 8192},
    },
    {
        "id": "facebook_post", "label": "Facebook Post", "marketplace": "facebook",
        "icon": "👍",
        "width": 1200, "height": 630, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 92,
        "compliance": {"min_width": 600, "min_height": 315, "max_file_kb": 8192},
    },
    {
        "id": "google_ads", "label": "Google Ads", "marketplace": "google",
        "icon": "🔍",
        "width": 1200, "height": 628, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.05, "quality": 92,
        "compliance": {
            "bg_required": "white", "min_width": 600, "min_height": 314,
            "max_file_kb": 5120, "min_quality": 85,
            "notes": "Google Shopping: white/light background required. "
                     "No promotional overlays.",
        },
    },
    {
        "id": "thumbnail", "label": "Thumbnail", "marketplace": "generic",
        "icon": "🖼️",
        "width": 400, "height": 400, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.10, "quality": 85,
        "compliance": {"min_width": 200, "min_height": 200, "max_file_kb": 512},
    },

    # ── Custom slot ────────────────────────────────────────────────────────────
    {
        "id": "custom", "label": "Custom", "marketplace": "custom",
        "icon": "⚙️",
        "width": 1080, "height": 1080, "format": "JPEG", "bg_color": "#FFFFFF",
        "padding_pct": 0.08, "quality": 92,
        "compliance": {},
    },
]


# ── Registry ──────────────────────────────────────────────────────────────────

class MarketplaceRegistry:
    """Immutable catalogue of all marketplace presets."""

    def __init__(self) -> None:
        self._presets: dict[str, MarketplacePreset] = {}
        self._build()

    def _build(self) -> None:
        for entry in _CATALOGUE:
            compliance_data = entry.get("compliance", {})
            compliance = ComplianceRule(
                bg_required=compliance_data.get("bg_required"),
                min_width=compliance_data.get("min_width", 400),
                min_height=compliance_data.get("min_height", 400),
                max_file_kb=compliance_data.get("max_file_kb", 10240),
                min_quality=compliance_data.get("min_quality", 85),
                no_text_overlay=compliance_data.get("no_text_overlay", False),
                no_watermark=compliance_data.get("no_watermark", True),
                no_border=compliance_data.get("no_border", False),
                no_logo_on_main=compliance_data.get("no_logo_on_main", False),
                product_coverage_min_pct=compliance_data.get("product_coverage_min_pct", 0.70),
                notes=compliance_data.get("notes", ""),
            )
            preset = MarketplacePreset(
                id=entry["id"],
                label=entry["label"],
                marketplace=entry["marketplace"],
                icon=entry.get("icon", "🛒"),
                width=entry["width"],
                height=entry["height"],
                format=entry["format"],
                bg_color=entry["bg_color"],
                padding_pct=float(entry.get("padding_pct", 0.05)),
                quality=int(entry.get("quality", 92)),
                compliance=compliance,
            )
            self._presets[preset.id] = preset

    def get(self, preset_id: str) -> Optional[MarketplacePreset]:
        """Return preset or None."""
        return self._presets.get(preset_id)

    def by_marketplace(self, marketplace: str) -> list[MarketplacePreset]:
        """Return all presets for a given marketplace name."""
        m = marketplace.lower()
        return [p for p in self._presets.values() if p.marketplace == m]

    def all(self) -> list[MarketplacePreset]:
        return list(self._presets.values())

    def ids(self) -> list[str]:
        return list(self._presets.keys())

    def as_classic_presets(self) -> dict:
        """
        Compatibility shim: return a dict matching ClassicFeature.MARKETPLACE_PRESETS
        format so existing code continues to work unchanged.
        """
        return {
            p.id: {"w": p.width, "h": p.height, "fmt": p.format,
                   "bg": p.bg_color, "label": p.label}
            for p in self._presets.values()
        }


_registry: Optional[MarketplaceRegistry] = None


def get_marketplace_registry() -> MarketplaceRegistry:
    global _registry
    if _registry is None:
        _registry = MarketplaceRegistry()
    return _registry
