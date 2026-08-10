"""
Psydox Quality Engine

Algorithmic quality scoring — no AI API calls.  Uses:
  - PIL for resolution / aspect ratio / brightness
  - NumPy finite-differences for sharpness (Laplacian variance)
  - Histogram similarity (Bhattacharyya coefficient) for color fidelity

All thresholds are configurable via QualityConfig.

Scoring (100-point scale):
  Resolution  20 pts  — meets minimum dimensions
  Sharpness   30 pts  — Laplacian variance above threshold
  Color match 30 pts  — histogram similarity vs original (if provided)
  Brightness  20 pts  — not over/under-exposed

Verdicts:
  APPROVED    80+
  REVIEW      50–79
  NEEDS_FIX   <50
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

_log = logging.getLogger("psydox.quality.engine")


class QualityVerdict(str, Enum):
    APPROVED  = "APPROVED"
    REVIEW    = "REVIEW"
    NEEDS_FIX = "NEEDS_FIX"


@dataclass
class QualityConfig:
    min_dimension:     int   = 512
    min_sharpness:     float = 20.0
    min_brightness:    int   = 30
    max_brightness:    int   = 230
    approved_threshold: int  = 80
    review_threshold:  int   = 50
    color_weight:      float = 0.3    # weight for color-match score
    resolution_weight: float = 0.2
    sharpness_weight:  float = 0.3
    brightness_weight: float = 0.2


@dataclass
class QualityScore:
    score:           int
    verdict:         QualityVerdict
    resolution_ok:   bool
    sharpness_score: float
    color_match_score: float      # 0.0 if no reference
    brightness_ok:   bool
    issues:          list[str]    = field(default_factory=list)
    details:         dict         = field(default_factory=dict)
    has_reference:   bool         = False

    def badge_text(self) -> str:
        icons = {
            QualityVerdict.APPROVED:  "✅ Approved",
            QualityVerdict.REVIEW:    "👁️ Review",
            QualityVerdict.NEEDS_FIX: "🔧 Needs Fix",
        }
        return f"{icons[self.verdict]} ({self.score}/100)"


class AIQualityEngine:
    """Algorithmic quality scorer — no AI calls."""

    def __init__(self, config: Optional[QualityConfig] = None):
        self._cfg = config or QualityConfig()

    def score(self, result_bytes: bytes, original_bytes: Optional[bytes] = None) -> QualityScore:
        try:
            return self._score(result_bytes, original_bytes)
        except Exception as exc:
            _log.warning("QualityEngine.score failed: %s", exc)
            return QualityScore(
                score=0, verdict=QualityVerdict.NEEDS_FIX,
                resolution_ok=False, sharpness_score=0.0,
                color_match_score=0.0, brightness_ok=False,
                issues=[f"Quality check error: {exc}"],
            )

    def _score(self, result_bytes: bytes, original_bytes: Optional[bytes]) -> QualityScore:
        from PIL import Image

        img = Image.open(io.BytesIO(result_bytes)).convert("RGB")
        w, h = img.size
        cfg   = self._cfg
        issues: list[str] = []

        # ── Resolution ────────────────────────────────────────────────────────
        resolution_ok = (w >= cfg.min_dimension and h >= cfg.min_dimension)
        if not resolution_ok:
            issues.append(f"Low resolution: {w}×{h} (min {cfg.min_dimension}px)")
        resolution_pts = 20 if resolution_ok else max(0, int(20 * min(w, h) / cfg.min_dimension))

        # ── Sharpness (Laplacian variance, no scipy) ──────────────────────────
        sharpness = self._laplacian_variance(img)
        sharp_ok  = sharpness >= cfg.min_sharpness
        if not sharp_ok:
            issues.append(f"Image may be blurry (sharpness {sharpness:.1f})")
        sharp_pts = min(30, int(30 * min(sharpness, cfg.min_sharpness * 5) / (cfg.min_sharpness * 5)))

        # ── Color match ───────────────────────────────────────────────────────
        color_match = 0.0
        has_ref     = False
        if original_bytes:
            has_ref = True
            try:
                orig = Image.open(io.BytesIO(original_bytes)).convert("RGB")
                color_match = self._histogram_similarity(orig, img)
            except Exception:
                color_match = 0.5  # neutral if comparison fails
            if color_match < 0.5:
                issues.append(f"Color deviation from original (similarity {color_match:.2f})")
        color_pts = int(30 * color_match) if has_ref else 15  # neutral 15/30 if no reference

        # ── Brightness ────────────────────────────────────────────────────────
        mean_brightness = self._mean_brightness(img)
        brightness_ok   = cfg.min_brightness <= mean_brightness <= cfg.max_brightness
        if not brightness_ok:
            if mean_brightness < cfg.min_brightness:
                issues.append(f"Image too dark (brightness {mean_brightness})")
            else:
                issues.append(f"Image too bright/overexposed (brightness {mean_brightness})")
        brightness_pts = 20 if brightness_ok else max(0, int(20 * (1 - abs(mean_brightness - 128) / 128)))

        # ── Total ─────────────────────────────────────────────────────────────
        total = resolution_pts + sharp_pts + color_pts + brightness_pts

        if total >= cfg.approved_threshold:
            verdict = QualityVerdict.APPROVED
        elif total >= cfg.review_threshold:
            verdict = QualityVerdict.REVIEW
        else:
            verdict = QualityVerdict.NEEDS_FIX

        return QualityScore(
            score=total, verdict=verdict,
            resolution_ok=resolution_ok, sharpness_score=round(sharpness, 2),
            color_match_score=round(color_match, 3), brightness_ok=brightness_ok,
            issues=issues, has_reference=has_ref,
            details={
                "resolution_pts": resolution_pts, "sharp_pts": sharp_pts,
                "color_pts": color_pts, "brightness_pts": brightness_pts,
                "width": w, "height": h, "mean_brightness": mean_brightness,
            },
        )

    def _laplacian_variance(self, img) -> float:
        try:
            import numpy as np
            arr = np.array(img.convert("L"), dtype=float)
            lap = (-arr[:-2,1:-1] - arr[2:,1:-1] - arr[1:-1,:-2] - arr[1:-1,2:] + 4*arr[1:-1,1:-1])
            return float(lap.var())
        except ImportError:
            # PIL fallback: use ImageFilter.FIND_EDGES variance
            from PIL import ImageFilter, ImageStat
            edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
            stat  = ImageStat.Stat(edges)
            return stat.var[0]

    def _histogram_similarity(self, img_a, img_b) -> float:
        """Bhattacharyya coefficient averaged over R, G, B channels."""
        try:
            import numpy as np
            score = 0.0
            for ch in range(3):
                a  = np.array(img_a)[:,:,ch].flatten().astype(float)
                b  = np.array(img_b)[:,:,ch].flatten().astype(float)
                ha, _ = np.histogram(a, bins=64, range=(0,256))
                hb, _ = np.histogram(b, bins=64, range=(0,256))
                ha = ha / (ha.sum() + 1e-10)
                hb = hb / (hb.sum() + 1e-10)
                score += float(np.sqrt(ha * hb).sum())
            return score / 3.0
        except ImportError:
            # PIL histogram returns counts for all bands concatenated
            ha = img_a.histogram()
            hb = img_b.histogram()
            total_a = sum(ha) or 1
            total_b = sum(hb) or 1
            bc = sum(
                (ha[i] / total_a * hb[i] / total_b) ** 0.5
                for i in range(len(ha))
            )
            return min(bc, 1.0)

    def _mean_brightness(self, img) -> int:
        try:
            import numpy as np
            return int(np.array(img).mean())
        except ImportError:
            from PIL import ImageStat
            stat = ImageStat.Stat(img)
            return int(sum(stat.mean) / len(stat.mean))
