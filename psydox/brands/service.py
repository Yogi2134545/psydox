"""
Psydox Brand Profiles Service

A brand profile stores visual identity preferences used across AI generation.
When "Use Brand Style" is selected, these defaults propagate to all features.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger("psydox.brands")


@dataclass
class BrandProfile:
    id:                 str
    owner_email:        str
    name:               str
    primary_color:      str   = "#000000"
    secondary_color:    str   = "#FFFFFF"
    accent_color:       str   = "#0066FF"
    preferred_bg:       str   = "white"
    lighting_style:     str   = "soft_studio"
    photo_style:        str   = "clean"
    model_style:        str   = "professional"
    preferred_ratios:   list  = field(default_factory=lambda: ["1:1", "4:5"])
    ai_defaults:        dict  = field(default_factory=dict)
    created_at:         float = field(default_factory=time.time)
    updated_at:         float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "owner_email":      self.owner_email,
            "name":             self.name,
            "primary_color":    self.primary_color,
            "secondary_color":  self.secondary_color,
            "accent_color":     self.accent_color,
            "preferred_bg":     self.preferred_bg,
            "lighting_style":   self.lighting_style,
            "photo_style":      self.photo_style,
            "model_style":      self.model_style,
            "preferred_ratios": self.preferred_ratios,
            "ai_defaults":      self.ai_defaults,
            "created_at":       self.created_at,
            "updated_at":       self.updated_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "BrandProfile":
        return BrandProfile(
            id              = d["id"],
            owner_email     = d["owner_email"],
            name            = d["name"],
            primary_color   = d.get("primary_color",   "#000000"),
            secondary_color = d.get("secondary_color", "#FFFFFF"),
            accent_color    = d.get("accent_color",    "#0066FF"),
            preferred_bg    = d.get("preferred_bg",    "white"),
            lighting_style  = d.get("lighting_style",  "soft_studio"),
            photo_style     = d.get("photo_style",     "clean"),
            model_style     = d.get("model_style",     "professional"),
            preferred_ratios = d.get("preferred_ratios", ["1:1", "4:5"]),
            ai_defaults     = d.get("ai_defaults",     {}),
            created_at      = d.get("created_at",      time.time()),
            updated_at      = d.get("updated_at",      time.time()),
        )


class BrandService:
    def __init__(self, cache: dict):
        self._cache = cache

    def create(self, owner_email: str, name: str, **kwargs) -> BrandProfile:
        brand = BrandProfile(id=str(uuid.uuid4()), owner_email=owner_email, name=name, **kwargs)
        self._cache[brand.id] = brand
        self._persist(brand)
        return brand

    def get(self, brand_id: str, owner_email: str) -> Optional[BrandProfile]:
        b = self._cache.get(brand_id)
        if b and b.owner_email == owner_email:
            return b
        return self._load(brand_id, owner_email)

    def list(self, owner_email: str) -> list[BrandProfile]:
        try:
            from psydox.storage.database import get_db
            rows = get_db().execute(
                "SELECT data FROM brand_profiles WHERE owner_email=? ORDER BY created_at DESC",
                (owner_email,)
            ).fetchall()
            brands = []
            for (data_json,) in rows:
                try:
                    b = BrandProfile.from_dict(json.loads(data_json))
                    self._cache[b.id] = b
                    brands.append(b)
                except Exception:
                    pass
            return brands
        except Exception as exc:
            _log.debug("BrandService.list error: %s", exc)
            return [b for b in self._cache.values() if b.owner_email == owner_email]

    def update(self, brand_id: str, owner_email: str, **kwargs) -> Optional[BrandProfile]:
        brand = self.get(brand_id, owner_email)
        if not brand:
            return None
        for k, v in kwargs.items():
            if hasattr(brand, k):
                setattr(brand, k, v)
        brand.updated_at = time.time()
        self._cache[brand.id] = brand
        self._persist(brand)
        return brand

    def delete(self, brand_id: str, owner_email: str) -> bool:
        brand = self.get(brand_id, owner_email)
        if not brand:
            return False
        self._cache.pop(brand_id, None)
        try:
            from psydox.storage.database import get_db
            db = get_db()
            db.execute("DELETE FROM brand_profiles WHERE id=? AND owner_email=?", (brand_id, owner_email))
            db.commit()
        except Exception:
            pass
        return True

    def _persist(self, brand: BrandProfile) -> None:
        try:
            from psydox.storage.database import get_db
            db = get_db()
            db.execute(
                """INSERT OR REPLACE INTO brand_profiles
                   (id, owner_email, name, data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (brand.id, brand.owner_email, brand.name,
                 json.dumps(brand.to_dict()), brand.created_at, brand.updated_at)
            )
            db.commit()
        except Exception as exc:
            _log.debug("BrandService._persist error: %s", exc)

    def _load(self, brand_id: str, owner_email: str) -> Optional[BrandProfile]:
        try:
            from psydox.storage.database import get_db
            row = get_db().execute(
                "SELECT data FROM brand_profiles WHERE id=? AND owner_email=?",
                (brand_id, owner_email)
            ).fetchone()
            if not row:
                return None
            brand = BrandProfile.from_dict(json.loads(row[0]))
            self._cache[brand.id] = brand
            return brand
        except Exception as exc:
            _log.debug("BrandService._load error: %s", exc)
            return None


def get_brand_service() -> BrandService:
    try:
        import streamlit as st
        @st.cache_resource
        def _store():
            return {}
        return BrandService(_store())
    except ImportError:
        return BrandService({})
