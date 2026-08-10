"""
Nano Banana — AI Quality Engine
Scores AI-generated product images against the original reference.

All checks are ALGORITHMIC (PIL / numpy) — no AI API calls.
Labels are honest: "Algorithmic Quality Check", not "AI Quality Score".

Scoring:
  Resolution  20 pts  pass/fail  (both dims >= MIN_DIMENSION)
  Sharpness   30 pts  0-100 scaled via Laplacian variance
  Color match 30 pts  0-100 scaled via histogram Bhattacharyya similarity
  Brightness  20 pts  pass/fail  (20 < mean < 235)

Verdicts: APPROVED (>=70), REVIEW (40-69), REJECTED (<40)
"""
import io
import logging
from dataclasses import dataclass, field
from enum import Enum

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    _HAS_NUMPY = False
from PIL import Image, ImageFilter, ImageStat

_log = logging.getLogger("nano_banana.quality_engine")


class QualityVerdict(str, Enum):
    APPROVED = "APPROVED"  # score >= 70 — ready for use
    REVIEW   = "REVIEW"    # score 40-69 — human review recommended
    REJECTED = "REJECTED"  # score < 40  — regenerate recommended


@dataclass
class QualityScore:
    score: int                  # composite 0–100
    verdict: QualityVerdict
    resolution_ok: bool
    sharpness_score: float      # 0–100
    color_match_score: float    # 0–100 vs reference; 75.0 when no reference
    brightness_ok: bool
    issues: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def badge_text(self) -> str:
        """Short badge label for the UI."""
        icons = {
            QualityVerdict.APPROVED: "✅",
            QualityVerdict.REVIEW:   "⚠️",
            QualityVerdict.REJECTED: "❌",
        }
        return f"{icons[self.verdict]} {self.verdict.value} ({self.score}/100)"


# ── Fidelity validator ────────────────────────────────────────────────────────

class ProductFidelityValidator:
    """
    Compares a generated image against the original reference using color
    histograms (Bhattacharyya coefficient). PIL/numpy only — no API.
    """

    def validate(self, original_bytes: bytes, result_bytes: bytes) -> dict:
        """
        Returns {"score": 0-100, "color_match": 0-100, "details": {...}}
        """
        try:
            orig   = Image.open(io.BytesIO(original_bytes)).convert("RGB")
            result = Image.open(io.BytesIO(result_bytes)).convert("RGB")
            cmp    = (256, 256)
            score  = _histogram_similarity(
                orig.resize(cmp, Image.LANCZOS),
                result.resize(cmp, Image.LANCZOS),
            )
            return {
                "score":       int(score),
                "color_match": round(score, 1),
                "details": {
                    "original_size": orig.size,
                    "result_size":   result.size,
                },
            }
        except Exception as e:
            _log.warning("FidelityValidator.validate failed: %s", e)
            return {"score": 50, "color_match": 50.0, "details": {"error": str(e)}}


# ── Quality engine ────────────────────────────────────────────────────────────

class AIQualityEngine:
    """
    Algorithmic quality checker for AI-generated images.
    Checks resolution, sharpness, brightness, and (optionally) color fidelity.
    """

    MIN_DIMENSION = 512      # px — images smaller than this score 0 on resolution
    MIN_SHARPNESS = 20.0     # Laplacian variance below this → blur flag

    def __init__(self):
        self._validator = ProductFidelityValidator()

    def score(
        self,
        result_bytes: bytes,
        original_bytes: bytes = None,
    ) -> QualityScore:
        """
        Score a generated image.
        original_bytes is optional — when provided, color fidelity is measured.
        """
        issues:  list = []
        details: dict = {}

        try:
            img = Image.open(io.BytesIO(result_bytes)).convert("RGB")
        except Exception as e:
            return QualityScore(
                score=0, verdict=QualityVerdict.REJECTED,
                resolution_ok=False, sharpness_score=0.0,
                color_match_score=0.0, brightness_ok=False,
                issues=[f"Cannot open image: {e}"],
            )

        w, h = img.size
        details["width"]  = w
        details["height"] = h

        # ── 1. Resolution ─────────────────────────────────────────────────────
        resolution_ok = w >= self.MIN_DIMENSION and h >= self.MIN_DIMENSION
        if not resolution_ok:
            issues.append(
                f"Resolution too low: {w}×{h} px "
                f"(minimum {self.MIN_DIMENSION}px per dimension)"
            )

        # ── 2. Sharpness (Laplacian variance) ─────────────────────────────────
        lap_var = _laplacian_variance(img)
        sharpness_score = min(100.0, (lap_var / 500.0) * 100.0)
        details["laplacian_variance"] = round(lap_var, 2)
        if lap_var < self.MIN_SHARPNESS:
            issues.append(
                f"Image appears blurry (sharpness index: {lap_var:.1f}, "
                f"threshold: {self.MIN_SHARPNESS})"
            )

        # ── 3. Brightness ─────────────────────────────────────────────────────
        mean_brightness = _mean_brightness(img)
        details["mean_brightness"] = round(mean_brightness, 1)
        brightness_ok = 20.0 < mean_brightness < 235.0
        if not brightness_ok:
            if mean_brightness <= 20.0:
                issues.append("Image is too dark (near-black output).")
            else:
                issues.append("Image is overexposed (near-white output).")

        # ── 4. Color fidelity vs reference (optional) ─────────────────────────
        color_match_score = 75.0  # neutral default when no reference
        if original_bytes:
            fid = self._validator.validate(original_bytes, result_bytes)
            color_match_score = fid.get("color_match", 75.0)
            details["color_match"] = color_match_score
            if color_match_score < 30.0:
                issues.append(
                    f"Color profile differs significantly from original "
                    f"({color_match_score:.0f}/100 match)."
                )

        # ── Composite score ───────────────────────────────────────────────────
        res_pts    = 20 if resolution_ok else 0
        sharp_pts  = int((min(sharpness_score, 100.0) / 100.0) * 30)
        color_pts  = int((min(color_match_score, 100.0) / 100.0) * 30)
        bright_pts = 20 if brightness_ok else 0
        total      = res_pts + sharp_pts + color_pts + bright_pts

        if total >= 70:
            verdict = QualityVerdict.APPROVED
        elif total >= 40:
            verdict = QualityVerdict.REVIEW
        else:
            verdict = QualityVerdict.REJECTED

        return QualityScore(
            score=total,
            verdict=verdict,
            resolution_ok=resolution_ok,
            sharpness_score=round(sharpness_score, 1),
            color_match_score=round(color_match_score, 1),
            brightness_ok=brightness_ok,
            issues=issues,
            details=details,
        )


# ── Pure functions ────────────────────────────────────────────────────────────

def _histogram_similarity(img1: Image.Image, img2: Image.Image) -> float:
    """Bhattacharyya coefficient between per-channel histograms → 0–100."""
    if _HAS_NUMPY:
        a = np.array(img1, dtype=np.float32)
        b = np.array(img2, dtype=np.float32)
        score = 0.0
        for ch in range(3):
            h1, _ = np.histogram(a[:, :, ch], bins=64, range=(0, 256))
            h2, _ = np.histogram(b[:, :, ch], bins=64, range=(0, 256))
            h1 = h1 / (h1.sum() + 1e-10)
            h2 = h2 / (h2.sum() + 1e-10)
            score += float(np.sum(np.sqrt(h1 * h2)))
        return (score / 3.0) * 100.0
    else:
        # PIL histogram returns counts for all bands concatenated (len = 256 * bands)
        ha = img1.histogram()
        hb = img2.histogram()
        ta, tb = sum(ha) or 1, sum(hb) or 1
        # Bhattacharyya: sum(sqrt(p_i * q_i)) where p,q are normalized distributions
        bc = sum((ha[i]/ta * hb[i]/tb)**0.5 for i in range(len(ha)))
        return min(bc, 1.0) * 100.0


def _laplacian_variance(img) -> float:
    """Laplacian variance for sharpness. Higher = sharper."""
    if _HAS_NUMPY:
        gray = np.array(img.convert("L"), dtype=np.float32)
        dx2 = gray[:, 2:] - 2.0 * gray[:, 1:-1] + gray[:, :-2]
        dy2 = gray[2:, :] - 2.0 * gray[1:-1, :] + gray[:-2, :]
        lap = dx2[1:-1, :] + dy2[:, 1:-1]
        return float(np.var(lap))
    else:
        gray = img.convert("L").resize((64, 64), Image.LANCZOS)
        pixels = list(gray.tobytes())  # L-mode: 1 byte per pixel
        w, h = gray.size
        lap = []
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                c = pixels[y * w + x]
                nb = pixels[(y-1)*w+x] + pixels[(y+1)*w+x] + pixels[y*w+x-1] + pixels[y*w+x+1]
                lap.append(4 * c - nb)
        if not lap:
            return 0.0
        n = len(lap)
        mean_l = sum(lap) / n
        return sum((v - mean_l) ** 2 for v in lap) / n


def _mean_brightness(img) -> float:
    if _HAS_NUMPY:
        return float(np.mean(np.array(img.convert("L"), dtype=np.float32)))
    else:
        return ImageStat.Stat(img.convert("L")).mean[0]
