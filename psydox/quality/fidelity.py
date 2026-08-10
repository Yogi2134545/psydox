"""
Psydox Fidelity Engine

Measures how faithfully the generated image preserves the original product.
All scoring is algorithmic (histogram, structural similarity approximation,
edge detection) — no AI vision API calls.

IMPORTANT: These are approximations, not exact computer-vision scores.
Where a reliable score cannot be computed, the field is marked with
confidence="approximation" so callers and UIs can display appropriate caveats.

Scores returned (0.0–1.0 each):
  overall_score   — weighted average
  color_score     — histogram similarity in product region
  shape_score     — edge map overlap approximation
  pattern_score   — texture similarity approximation
  logo_score      — "Provider capability unavailable" (needs dedicated logo detection)
  text_score      — "Provider capability unavailable" (needs OCR)
  warnings        — list of specific issues
  confidence      — "approximation" or "unavailable" per score
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger("psydox.quality.fidelity")

_UNAVAILABLE = "unavailable"
_APPROX      = "approximation"


@dataclass
class FidelityScore:
    overall_score:  float
    color_score:    float
    shape_score:    float
    pattern_score:  float
    logo_score:     Optional[float]  # None = provider capability unavailable
    text_score:     Optional[float]  # None = provider capability unavailable
    warnings:       list[str]        = field(default_factory=list)
    confidence:     str              = _APPROX   # "approximation" | "unavailable"

    def badge_text(self) -> str:
        if self.confidence == _UNAVAILABLE:
            return "⚠️ Fidelity check unavailable"
        pct = int(self.overall_score * 100)
        icon = "✅" if pct >= 75 else "⚠️" if pct >= 50 else "❌"
        return f"{icon} Fidelity {pct}% (approx.)"

    def to_dict(self) -> dict:
        return {
            "overall_score": round(self.overall_score, 3),
            "color_score":   round(self.color_score, 3),
            "shape_score":   round(self.shape_score, 3),
            "pattern_score": round(self.pattern_score, 3),
            "logo_score":    self.logo_score,
            "text_score":    self.text_score,
            "warnings":      self.warnings,
            "confidence":    self.confidence,
            "note":          "Scores are algorithmic approximations. Logo/text detection requires dedicated provider capability.",
        }


class FidelityEngine:
    """
    Compares original product image vs generated output.
    Requires both images.  Returns FidelityScore.
    Never raises.
    """

    def score(self, original_bytes: bytes, result_bytes: bytes) -> FidelityScore:
        if not original_bytes or not result_bytes:
            return FidelityScore(
                overall_score=0.0, color_score=0.0, shape_score=0.0,
                pattern_score=0.0, logo_score=None, text_score=None,
                warnings=["Missing original or result image"],
                confidence=_UNAVAILABLE,
            )
        try:
            return self._score(original_bytes, result_bytes)
        except Exception as exc:
            _log.warning("FidelityEngine.score failed: %s", exc)
            return FidelityScore(
                overall_score=0.0, color_score=0.0, shape_score=0.0,
                pattern_score=0.0, logo_score=None, text_score=None,
                warnings=[f"Fidelity check error: {exc}"],
                confidence=_UNAVAILABLE,
            )

    def _score(self, original_bytes: bytes, result_bytes: bytes) -> FidelityScore:
        from PIL import Image

        orig = Image.open(io.BytesIO(original_bytes)).convert("RGB")
        res  = Image.open(io.BytesIO(result_bytes)).convert("RGB")

        # Resize both to same size for comparison
        target_size = (256, 256)
        orig_r = orig.resize(target_size, Image.LANCZOS)
        res_r  = res.resize(target_size, Image.LANCZOS)

        # ── Color score (histogram similarity) ────────────────────────────────
        color_score = self._histogram_similarity(orig_r, res_r)

        # ── Shape score (edge overlap approximation) ──────────────────────────
        shape_score = self._edge_similarity(orig_r, res_r)

        # ── Pattern score (texture: normalized cross-correlation on greyscale) ─
        pattern_score = self._texture_similarity(orig_r, res_r)

        # ── Logo / text scores — unavailable without dedicated provider ────────
        logo_score = None   # Provider capability unavailable
        text_score = None   # Provider capability unavailable

        # ── Warnings ──────────────────────────────────────────────────────────
        warnings: list[str] = []
        if color_score < 0.6:
            warnings.append(f"Significant color shift detected (similarity {color_score:.2f})")
        if shape_score < 0.5:
            warnings.append(f"Product shape may have changed (edge similarity {shape_score:.2f})")
        if pattern_score < 0.5:
            warnings.append(f"Texture/pattern may have changed (similarity {pattern_score:.2f})")
        warnings.append("Logo and text fidelity: provider capability unavailable — manual review recommended")

        # ── Overall (weighted, excluding unavailable scores) ──────────────────
        overall = color_score * 0.5 + shape_score * 0.3 + pattern_score * 0.2

        return FidelityScore(
            overall_score=round(overall, 3),
            color_score=round(color_score, 3),
            shape_score=round(shape_score, 3),
            pattern_score=round(pattern_score, 3),
            logo_score=logo_score,
            text_score=text_score,
            warnings=warnings,
            confidence=_APPROX,
        )

    def _histogram_similarity(self, a, b) -> float:
        try:
            import numpy as np
            score = 0.0
            for ch in range(3):
                ha, _ = np.histogram(np.array(a)[:,:,ch], bins=64, range=(0,256))
                hb, _ = np.histogram(np.array(b)[:,:,ch], bins=64, range=(0,256))
                ha = ha / (ha.sum() + 1e-10)
                hb = hb / (hb.sum() + 1e-10)
                score += float(np.sqrt(ha * hb).sum())
            return score / 3.0
        except ImportError:
            # PIL histogram returns counts for all bands concatenated
            ha = a.histogram()
            hb = b.histogram()
            ta = sum(ha) or 1
            tb = sum(hb) or 1
            bc = sum((ha[i]/ta * hb[i]/tb)**0.5 for i in range(len(ha)))
            return min(bc, 1.0)

    def _edge_similarity(self, a, b) -> float:
        try:
            import numpy as np
            def edges(img):
                g  = np.array(img.convert("L"), dtype=float)
                gx = np.abs(g[:, 1:] - g[:, :-1])
                gy = np.abs(g[1:, :] - g[:-1, :])
                s  = min(gx.shape[0], gy.shape[0]), min(gx.shape[1], gy.shape[1])
                return gx[:s[0], :s[1]] + gy[:s[0], :s[1]]
            ea = edges(a)
            eb = edges(b)
            thresh_a = ea > ea.mean()
            thresh_b = eb > eb.mean()
            intersection = (thresh_a & thresh_b).sum()
            denom = thresh_a.sum() + thresh_b.sum()
            return float(2 * intersection / (denom + 1e-10))
        except ImportError:
            from PIL import ImageFilter
            ea = a.convert("L").filter(ImageFilter.FIND_EDGES)
            eb = b.convert("L").filter(ImageFilter.FIND_EDGES)
            ha = ea.histogram()
            hb = eb.histogram()
            ta, tb = sum(ha) or 1, sum(hb) or 1
            bc = sum((ha[i]/ta * hb[i]/tb)**0.5 for i in range(len(ha)))
            return min(bc, 1.0)

    def _texture_similarity(self, a, b) -> float:
        try:
            import numpy as np
            ga   = np.array(a.convert("L"), dtype=float)
            gb   = np.array(b.convert("L"), dtype=float)
            ga_n = ga - ga.mean()
            gb_n = gb - gb.mean()
            denom = (np.sqrt((ga_n**2).sum()) * np.sqrt((gb_n**2).sum())) + 1e-10
            return float(np.clip((ga_n * gb_n).sum() / denom, 0.0, 1.0))
        except ImportError:
            ha = a.convert("L").histogram()
            hb = b.convert("L").histogram()
            ta, tb = sum(ha) or 1, sum(hb) or 1
            bc = sum((ha[i]/ta * hb[i]/tb)**0.5 for i in range(len(ha)))
            return min(bc, 1.0)
