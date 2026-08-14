"""
Psydox Category Registry

Canonical product categories and their processing rules.

Adding a new category: add one entry to _CATALOGUE — no code changes elsewhere.

get_category_registry() returns the singleton CategoryRegistry.
registry.get(id) returns a CategoryDefinition or the "generic" fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import logging

_log = logging.getLogger("psydox.category.registry")


@dataclass
class CategoryDefinition:
    id:   str      # canonical snake_case key, e.g. "footwear"
    name: str      # display name, e.g. "Footwear"
    icon: str

    # Strings that map to this category (checked case-insensitively).
    # Order matters for substring matching: more specific aliases first.
    aliases: list[str] = field(default_factory=list)

    # Prompt engineering
    prompt_keywords:   list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)

    # Image processing defaults
    background_default: str = "white"             # "white" | "grey" | "contextual"
    aspect_ratio:       tuple = (1, 1)            # recommended W:H
    padding_pct:        float = 0.08              # fraction of canvas edge
    shadow:             str = "none"              # "none" | "ground" | "natural"
    composition:        str = "centered"          # "centered" | "angled" | "hero"

    # Recommended output assets for a complete product kit
    recommended_assets: list[str] = field(default_factory=list)

    # Per-marketplace overrides that take priority over category defaults
    marketplace_hints:  dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id":                 self.id,
            "name":               self.name,
            "icon":               self.icon,
            "background_default": self.background_default,
            "aspect_ratio":       self.aspect_ratio,
            "padding_pct":        self.padding_pct,
            "shadow":             self.shadow,
            "composition":        self.composition,
            "recommended_assets": self.recommended_assets,
        }


# ── Category catalogue ────────────────────────────────────────────────────────

_CATALOGUE: list[dict] = [
    {
        "id": "footwear",
        "name": "Footwear",
        "icon": "👟",
        "aliases": [
            "shoe", "shoes", "sneaker", "sneakers", "boot", "boots",
            "sandal", "sandals", "slipper", "slippers", "loafer", "loafers",
            "heel", "heels", "pump", "pumps", "moccasin", "oxford", "derby",
            "running shoe", "sports shoe", "athletic shoe", "football boot",
            "football shoe", "cricket shoe", "flipflop", "flip-flop",
        ],
        "prompt_keywords": [
            "product photography", "studio background", "shoe photography",
            "clean white background", "side view", "three-quarter view",
        ],
        "negative_keywords": [
            "person wearing", "feet", "leg", "lifestyle", "street",
        ],
        "background_default": "white",
        "aspect_ratio": (1, 1),
        "padding_pct": 0.10,
        "shadow": "ground",
        "composition": "angled",
        "recommended_assets": [
            "main", "side", "back", "detail", "pair", "transparent", "lifestyle",
        ],
        "marketplace_hints": {
            "myntra":   {"aspect_ratio": (4, 5), "padding_pct": 0.05},
            "ajio":     {"aspect_ratio": (3, 4), "padding_pct": 0.05},
            "flipkart": {"aspect_ratio": (1, 1), "background_default": "white"},
        },
    },
    {
        "id": "apparel",
        "name": "Apparel",
        "icon": "👕",
        "aliases": [
            "shirt", "t-shirt", "tshirt", "tee", "top", "blouse", "tunic",
            "dress", "skirt", "jeans", "pants", "trousers", "shorts",
            "jacket", "coat", "hoodie", "sweatshirt", "sweater", "pullover",
            "suit", "blazer", "kurta", "saree", "sari", "lehenga", "salwar",
            "leggings", "tights", "jumpsuit", "dungaree", "overalls",
            "clothing", "garment", "apparel", "wear", "outerwear", "innerwear",
            "underwear", "lingerie", "nightwear", "pajama", "pyjama",
            "activewear", "sportswear", "swimwear", "ethnic wear", "western wear",
        ],
        "prompt_keywords": [
            "product photography", "flat lay", "studio background",
            "clean white background", "ghost mannequin", "apparel photography",
        ],
        "negative_keywords": [
            "person wearing", "model", "lifestyle", "outdoor",
        ],
        "background_default": "white",
        "aspect_ratio": (4, 5),
        "padding_pct": 0.06,
        "shadow": "none",
        "composition": "centered",
        "recommended_assets": [
            "main", "front", "back", "detail", "flat_lay", "lifestyle",
        ],
        "marketplace_hints": {
            "myntra":   {"aspect_ratio": (4, 5)},
            "ajio":     {"aspect_ratio": (3, 4)},
            "flipkart": {"aspect_ratio": (1, 1)},
        },
    },
    {
        "id": "accessories",
        "name": "Accessories",
        "icon": "👜",
        "aliases": [
            "bag", "bags", "handbag", "handbags", "purse", "clutch",
            "backpack", "wallet", "belt", "belts", "hat", "cap", "caps",
            "sunglasses", "glasses", "spectacles", "scarf", "scarves",
            "gloves", "tie", "ties", "watch", "watches", "bracelet",
            "cufflinks", "socks", "sock", "tote", "messenger bag",
            "luggage", "suitcase", "laptop bag", "phone case", "accessory",
        ],
        "prompt_keywords": [
            "product photography", "studio background", "clean background",
            "accessory photography", "detail shot",
        ],
        "negative_keywords": ["person wearing", "lifestyle", "outdoor"],
        "background_default": "white",
        "aspect_ratio": (1, 1),
        "padding_pct": 0.08,
        "shadow": "natural",
        "composition": "centered",
        "recommended_assets": [
            "main", "side", "detail", "interior", "transparent", "lifestyle",
        ],
    },
    {
        "id": "jewelry",
        "name": "Jewelry",
        "icon": "💍",
        "aliases": [
            "jewelry", "jewellery", "ring", "rings", "necklace", "necklaces",
            "earring", "earrings", "bracelet", "bracelets", "anklet",
            "pendant", "brooch", "bangle", "bangles", "chain", "chains",
            "diamond", "gold", "silver", "pearl", "gemstone", "gem",
            "fashion jewelry", "fine jewelry", "costume jewelry",
        ],
        "prompt_keywords": [
            "macro photography", "jewelry photography", "reflective surface",
            "dark background", "gradient background", "luxury product",
        ],
        "negative_keywords": ["person wearing", "lifestyle"],
        "background_default": "grey",
        "aspect_ratio": (1, 1),
        "padding_pct": 0.12,
        "shadow": "natural",
        "composition": "hero",
        "recommended_assets": [
            "main", "detail", "angle", "lifestyle", "transparent",
        ],
    },
    {
        "id": "beauty",
        "name": "Beauty",
        "icon": "💄",
        "aliases": [
            "cosmetics", "makeup", "lipstick", "foundation", "concealer",
            "mascara", "eyeliner", "eyeshadow", "blush", "highlighter",
            "lip gloss", "lip liner", "nail polish", "nail varnish",
            "nail art", "beauty", "beauty product",
        ],
        "prompt_keywords": [
            "product photography", "beauty photography", "cosmetics",
            "white background", "soft lighting", "luxury",
        ],
        "negative_keywords": ["person wearing", "applied on face"],
        "background_default": "white",
        "aspect_ratio": (1, 1),
        "padding_pct": 0.10,
        "shadow": "natural",
        "composition": "centered",
        "recommended_assets": [
            "main", "detail", "open", "lifestyle", "hero",
        ],
    },
    {
        "id": "skincare",
        "name": "Skincare",
        "icon": "🧴",
        "aliases": [
            "skincare", "skin care", "moisturizer", "moisturiser", "serum",
            "toner", "cleanser", "face wash", "scrub", "mask", "face mask",
            "sunscreen", "suncream", "spf", "eye cream", "face cream",
            "body lotion", "body wash", "shampoo", "conditioner",
            "hair care", "hair oil", "hair serum", "face oil",
            "cream", "lotion", "gel", "foam", "mist", "essence",
            "treatment", "exfoliator",
        ],
        "prompt_keywords": [
            "product photography", "skincare photography", "clean background",
            "studio lighting", "premium packaging",
        ],
        "negative_keywords": ["person applying", "skin texture", "before after"],
        "background_default": "white",
        "aspect_ratio": (1, 1),
        "padding_pct": 0.10,
        "shadow": "natural",
        "composition": "centered",
        "recommended_assets": [
            "main", "detail", "ingredients", "hero", "lifestyle",
        ],
    },
    {
        "id": "electronics",
        "name": "Electronics",
        "icon": "📱",
        "aliases": [
            "phone", "smartphone", "mobile", "tablet", "laptop", "computer",
            "headphones", "earphones", "earbuds", "speaker", "camera",
            "charger", "cable", "adapter", "smartwatch", "fitness band",
            "keyboard", "mouse", "monitor", "tv", "television", "remote",
            "gaming", "console", "power bank", "electronics", "gadget",
            "device", "tech", "electronic",
        ],
        "prompt_keywords": [
            "product photography", "studio lighting", "tech photography",
            "clean background", "reflective surface", "premium",
        ],
        "negative_keywords": ["person using", "lifestyle", "outdoor"],
        "background_default": "white",
        "aspect_ratio": (1, 1),
        "padding_pct": 0.08,
        "shadow": "natural",
        "composition": "angled",
        "recommended_assets": [
            "main", "front", "back", "side", "detail", "packaging",
        ],
    },
    {
        "id": "home",
        "name": "Home & Living",
        "icon": "🏠",
        "aliases": [
            "furniture", "home decor", "decor", "cushion", "pillow",
            "bedsheet", "bedding", "curtain", "curtains", "rug", "carpet",
            "lamp", "vase", "candle", "frame", "wall art", "shelf",
            "kitchenware", "cookware", "cutlery", "crockery", "dinnerware",
            "storage", "organizer", "home", "household", "living",
        ],
        "prompt_keywords": [
            "product photography", "interior photography", "home decor",
            "lifestyle", "studio background",
        ],
        "negative_keywords": [],
        "background_default": "contextual",
        "aspect_ratio": (1, 1),
        "padding_pct": 0.06,
        "shadow": "ground",
        "composition": "hero",
        "recommended_assets": [
            "main", "detail", "lifestyle", "room_context",
        ],
    },
    {
        "id": "generic",
        "name": "Generic Product",
        "icon": "📦",
        "aliases": [],   # fallback — matches everything
        "prompt_keywords": [
            "product photography", "clean background", "studio lighting",
        ],
        "negative_keywords": [],
        "background_default": "white",
        "aspect_ratio": (1, 1),
        "padding_pct": 0.08,
        "shadow": "none",
        "composition": "centered",
        "recommended_assets": [
            "main", "detail", "lifestyle",
        ],
    },
]


# ── Registry ──────────────────────────────────────────────────────────────────

class CategoryRegistry:
    """Immutable catalogue of canonical product categories."""

    def __init__(self) -> None:
        self._cats: dict[str, CategoryDefinition] = {}
        self._build()

    def _build(self) -> None:
        for entry in _CATALOGUE:
            defn = CategoryDefinition(
                id=entry["id"],
                name=entry["name"],
                icon=entry["icon"],
                aliases=entry.get("aliases", []),
                prompt_keywords=entry.get("prompt_keywords", []),
                negative_keywords=entry.get("negative_keywords", []),
                background_default=entry.get("background_default", "white"),
                aspect_ratio=tuple(entry.get("aspect_ratio", (1, 1))),
                padding_pct=float(entry.get("padding_pct", 0.08)),
                shadow=entry.get("shadow", "none"),
                composition=entry.get("composition", "centered"),
                recommended_assets=entry.get("recommended_assets", []),
                marketplace_hints=entry.get("marketplace_hints", {}),
            )
            self._cats[defn.id] = defn

    def get(self, category_id: str) -> CategoryDefinition:
        """Return definition or "generic" fallback."""
        return self._cats.get(category_id) or self._cats["generic"]

    def all(self) -> list[CategoryDefinition]:
        return list(self._cats.values())

    def ids(self) -> list[str]:
        return list(self._cats.keys())


_registry: Optional[CategoryRegistry] = None


def get_category_registry() -> CategoryRegistry:
    global _registry
    if _registry is None:
        _registry = CategoryRegistry()
    return _registry
