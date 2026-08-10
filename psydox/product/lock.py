"""
Psydox Product Lock

Declares which product properties may or may not be changed by a given feature.
Used by the Prompt Engine to generate strict preservation constraints and by
Fidelity Engine to know which attributes to verify.

Usage:
    lock = ProductLock.from_feature("background")
    lock.is_locked("color")     # True — background gen must not change color
    lock.constraint_text()      # "Preserve: product color, logo text, shape..."

Features declare their lock profile in their manifest via `lock_profile`.
If no profile is declared, a conservative default is applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LockLevel(str, Enum):
    STRICT   = "strict"   # absolutely must not change
    SOFT     = "soft"     # try to preserve, minor variation acceptable
    FREE     = "free"     # feature is explicitly allowed to change this


class LockedProperty(str, Enum):
    COLOR        = "color"
    SECONDARY_COLOR = "secondary_color"
    LOGO         = "logo"
    BRAND_TEXT   = "brand_text"
    PATTERN      = "pattern"
    SHAPE        = "shape"
    PROPORTIONS  = "proportions"
    MATERIAL     = "material"
    TEXTURE      = "texture"
    FEATURES     = "features"  # buttons, zippers, etc.


# Default lock profiles for standard features
_PROFILES: dict[str, dict[LockedProperty, LockLevel]] = {
    "background": {
        LockedProperty.COLOR:        LockLevel.STRICT,
        LockedProperty.SECONDARY_COLOR: LockLevel.STRICT,
        LockedProperty.LOGO:         LockLevel.STRICT,
        LockedProperty.BRAND_TEXT:   LockLevel.STRICT,
        LockedProperty.PATTERN:      LockLevel.STRICT,
        LockedProperty.SHAPE:        LockLevel.STRICT,
        LockedProperty.PROPORTIONS:  LockLevel.STRICT,
        LockedProperty.MATERIAL:     LockLevel.STRICT,
        LockedProperty.TEXTURE:      LockLevel.STRICT,
        LockedProperty.FEATURES:     LockLevel.STRICT,
    },
    "lifestyle": {
        LockedProperty.COLOR:        LockLevel.STRICT,
        LockedProperty.LOGO:         LockLevel.STRICT,
        LockedProperty.BRAND_TEXT:   LockLevel.STRICT,
        LockedProperty.PATTERN:      LockLevel.STRICT,
        LockedProperty.SHAPE:        LockLevel.STRICT,
        LockedProperty.PROPORTIONS:  LockLevel.SOFT,
        LockedProperty.MATERIAL:     LockLevel.SOFT,
        LockedProperty.TEXTURE:      LockLevel.SOFT,
        LockedProperty.FEATURES:     LockLevel.SOFT,
    },
    "model_gen": {
        LockedProperty.COLOR:        LockLevel.STRICT,
        LockedProperty.LOGO:         LockLevel.STRICT,
        LockedProperty.BRAND_TEXT:   LockLevel.STRICT,
        LockedProperty.PATTERN:      LockLevel.STRICT,
        LockedProperty.SHAPE:        LockLevel.SOFT,
        LockedProperty.PROPORTIONS:  LockLevel.SOFT,
        LockedProperty.MATERIAL:     LockLevel.SOFT,
        LockedProperty.FEATURES:     LockLevel.SOFT,
    },
    "lighting": {
        LockedProperty.COLOR:        LockLevel.SOFT,
        LockedProperty.LOGO:         LockLevel.STRICT,
        LockedProperty.BRAND_TEXT:   LockLevel.STRICT,
        LockedProperty.PATTERN:      LockLevel.STRICT,
        LockedProperty.SHAPE:        LockLevel.STRICT,
        LockedProperty.PROPORTIONS:  LockLevel.STRICT,
        LockedProperty.MATERIAL:     LockLevel.SOFT,
        LockedProperty.FEATURES:     LockLevel.STRICT,
    },
    "shadow": {
        LockedProperty.COLOR:        LockLevel.STRICT,
        LockedProperty.LOGO:         LockLevel.STRICT,
        LockedProperty.BRAND_TEXT:   LockLevel.STRICT,
        LockedProperty.PATTERN:      LockLevel.STRICT,
        LockedProperty.SHAPE:        LockLevel.STRICT,
        LockedProperty.PROPORTIONS:  LockLevel.STRICT,
        LockedProperty.MATERIAL:     LockLevel.STRICT,
        LockedProperty.FEATURES:     LockLevel.STRICT,
    },
    "enhance": {
        LockedProperty.COLOR:        LockLevel.SOFT,
        LockedProperty.LOGO:         LockLevel.STRICT,
        LockedProperty.BRAND_TEXT:   LockLevel.STRICT,
        LockedProperty.PATTERN:      LockLevel.SOFT,
        LockedProperty.SHAPE:        LockLevel.STRICT,
        LockedProperty.PROPORTIONS:  LockLevel.STRICT,
        LockedProperty.FEATURES:     LockLevel.STRICT,
    },
}

# Conservative default for unknown features
_DEFAULT_PROFILE: dict[LockedProperty, LockLevel] = {
    p: LockLevel.STRICT for p in LockedProperty
}

_LOCK_DESCRIPTIONS = {
    LockedProperty.COLOR:        "product color",
    LockedProperty.SECONDARY_COLOR: "secondary colors",
    LockedProperty.LOGO:         "logo",
    LockedProperty.BRAND_TEXT:   "brand text",
    LockedProperty.PATTERN:      "pattern",
    LockedProperty.SHAPE:        "shape",
    LockedProperty.PROPORTIONS:  "proportions",
    LockedProperty.MATERIAL:     "material appearance",
    LockedProperty.TEXTURE:      "texture",
    LockedProperty.FEATURES:     "product features (buttons, zippers, etc.)",
}


@dataclass
class ProductLock:
    profile: dict[LockedProperty, LockLevel] = field(default_factory=dict)
    user_overrides: dict[LockedProperty, LockLevel] = field(default_factory=dict)

    @staticmethod
    def from_feature(feature_id: str) -> "ProductLock":
        base = _PROFILES.get(feature_id, _DEFAULT_PROFILE)
        return ProductLock(profile=dict(base))

    @staticmethod
    def strict_all() -> "ProductLock":
        return ProductLock(profile=dict(_DEFAULT_PROFILE))

    def is_locked(self, prop: LockedProperty | str) -> bool:
        p = LockedProperty(prop) if isinstance(prop, str) else prop
        level = self.user_overrides.get(p) or self.profile.get(p, LockLevel.STRICT)
        return level != LockLevel.FREE

    def get_level(self, prop: LockedProperty) -> LockLevel:
        return self.user_overrides.get(prop) or self.profile.get(prop, LockLevel.STRICT)

    def override(self, prop: LockedProperty, level: LockLevel) -> "ProductLock":
        self.user_overrides[prop] = level
        return self

    def strict_properties(self) -> list[LockedProperty]:
        return [p for p in LockedProperty if self.get_level(p) == LockLevel.STRICT]

    def soft_properties(self) -> list[LockedProperty]:
        return [p for p in LockedProperty if self.get_level(p) == LockLevel.SOFT]

    def free_properties(self) -> list[LockedProperty]:
        return [p for p in LockedProperty if self.get_level(p) == LockLevel.FREE]

    def constraint_text(self) -> str:
        """Generate a natural-language constraint for AI prompts."""
        strict = self.strict_properties()
        soft   = self.soft_properties()
        lines  = []
        if strict:
            descriptions = [_LOCK_DESCRIPTIONS[p] for p in strict]
            lines.append(f"MUST PRESERVE exactly: {', '.join(descriptions)}.")
        if soft:
            descriptions = [_LOCK_DESCRIPTIONS[p] for p in soft]
            lines.append(f"Try to preserve (minor variation acceptable): {', '.join(descriptions)}.")
        return " ".join(lines)
