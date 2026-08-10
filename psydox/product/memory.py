"""
Psydox Product Memory

Persists a product profile across sessions so every AI operation can reuse
prior analysis instead of re-running it.

Storage: SQLite (via psydox.storage.database).  Falls back to in-memory dict
if database is unavailable so the app never crashes on storage failure.

ProductProfile contains:
  - product_id         : SHA256 hash of original image bytes
  - original_image     : bytes of the source image
  - attributes         : ProductAttributes dict (JSON)
  - important_details  : free-text notes (user or AI)
  - brand              : brand name if detected
  - restrictions       : list of locked properties
  - generation_history : list of {job_id, feature_id, prompt_fingerprint, quality_score}
  - approved_outputs   : list of output hashes that were approved
  - rejected_outputs   : list of output hashes that were rejected
  - created_at / updated_at
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import streamlit as st
    _HAS_ST = True
except ImportError:
    st = None  # type: ignore
    _HAS_ST = False

_log = logging.getLogger("psydox.product.memory")


@dataclass
class ProductProfile:
    product_id:         str
    original_hash:      str
    attributes:         dict           = field(default_factory=dict)
    important_details:  str            = ""
    brand:              str            = ""
    restrictions:       list[str]      = field(default_factory=list)
    generation_history: list[dict]     = field(default_factory=list)
    approved_outputs:   list[str]      = field(default_factory=list)
    rejected_outputs:   list[str]      = field(default_factory=list)
    created_at:         float          = field(default_factory=time.time)
    updated_at:         float          = field(default_factory=time.time)

    def record_generation(self, job_id: str, feature_id: str,
                           prompt_fp: str, quality_score: int) -> None:
        self.generation_history.append({
            "job_id":          job_id,
            "feature_id":      feature_id,
            "prompt_fingerprint": prompt_fp,
            "quality_score":   quality_score,
            "ts":              time.time(),
        })
        self.generation_history = self.generation_history[-100:]  # keep last 100
        self.updated_at = time.time()

    def approve_output(self, output_hash: str) -> None:
        if output_hash not in self.approved_outputs:
            self.approved_outputs.append(output_hash)
        self.updated_at = time.time()

    def reject_output(self, output_hash: str) -> None:
        if output_hash not in self.rejected_outputs:
            self.rejected_outputs.append(output_hash)
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {
            "product_id":         self.product_id,
            "original_hash":      self.original_hash,
            "attributes":         self.attributes,
            "important_details":  self.important_details,
            "brand":              self.brand,
            "restrictions":       self.restrictions,
            "generation_history": self.generation_history,
            "approved_outputs":   self.approved_outputs,
            "rejected_outputs":   self.rejected_outputs,
            "created_at":         self.created_at,
            "updated_at":         self.updated_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "ProductProfile":
        p = ProductProfile(
            product_id=d["product_id"],
            original_hash=d["original_hash"],
        )
        p.attributes         = d.get("attributes", {})
        p.important_details  = d.get("important_details", "")
        p.brand              = d.get("brand", "")
        p.restrictions       = d.get("restrictions", [])
        p.generation_history = d.get("generation_history", [])
        p.approved_outputs   = d.get("approved_outputs", [])
        p.rejected_outputs   = d.get("rejected_outputs", [])
        p.created_at         = d.get("created_at", time.time())
        p.updated_at         = d.get("updated_at", time.time())
        return p


def image_hash(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()[:16]


class ProductMemory:
    """
    Stores and retrieves ProductProfile objects.
    Primary backend: SQLite via psydox.storage.  Fallback: session dict.
    """

    def __init__(self, store: dict):
        self._store = store  # keyed by product_id
        self._db_ok = False
        try:
            from psydox.storage.database import get_db
            self._db = get_db()
            self._db_ok = True
        except Exception:
            self._db = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_or_create(self, image_bytes: bytes) -> ProductProfile:
        pid = image_hash(image_bytes)
        existing = self.get(pid)
        if existing:
            return existing
        profile = ProductProfile(product_id=pid, original_hash=pid)
        self._store[pid] = profile
        self._persist(profile)
        return profile

    def get(self, product_id: str) -> Optional[ProductProfile]:
        # Check session cache first
        if product_id in self._store:
            return self._store[product_id]
        # Try DB
        if self._db_ok:
            try:
                row = self._db.execute(
                    "SELECT data FROM product_profiles WHERE product_id=?", (product_id,)
                ).fetchone()
                if row:
                    p = ProductProfile.from_dict(json.loads(row[0]))
                    self._store[product_id] = p
                    return p
            except Exception as exc:
                _log.debug("ProductMemory DB read failed: %s", exc)
        return None

    def save(self, profile: ProductProfile) -> None:
        profile.updated_at = time.time()
        self._store[profile.product_id] = profile
        self._persist(profile)

    def analyze_and_enrich(self, profile: ProductProfile, image_bytes: bytes) -> ProductProfile:
        """Run product intelligence and store results in the profile."""
        if profile.attributes.get("overall_confidence", 0) >= 0.3:
            return profile  # already analyzed
        try:
            from psydox.product.intelligence import ProductIntelligenceEngine
            attrs = ProductIntelligenceEngine().analyze(image_bytes)
            profile.attributes = attrs.to_dict()
            if attrs.brand_text:
                profile.brand = attrs.brand_text[0].value
            self.save(profile)
        except Exception as exc:
            _log.warning("analyze_and_enrich failed: %s", exc)
        return profile

    # ── Persistence ────────────────────────────────────────────────────────────

    def _persist(self, profile: ProductProfile) -> None:
        if not self._db_ok:
            return
        try:
            data = json.dumps(profile.to_dict())
            self._db.execute(
                "INSERT OR REPLACE INTO product_profiles (product_id, data, updated_at) VALUES (?,?,?)",
                (profile.product_id, data, profile.updated_at),
            )
            self._db.commit()
        except Exception as exc:
            _log.debug("ProductMemory DB write failed: %s", exc)


def _memory_store() -> dict:
    if _HAS_ST:
        @st.cache_resource
        def _store():
            return {}
        return _store()
    return {}


def get_product_memory() -> ProductMemory:
    return ProductMemory(_memory_store())
