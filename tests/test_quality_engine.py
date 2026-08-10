"""Tests for nano_banana.quality_engine — algorithmic quality scoring."""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nano_banana.quality_engine import (
    AIQualityEngine,
    ProductFidelityValidator,
    QualityVerdict,
    _laplacian_variance,
    _histogram_similarity,
)
from PIL import Image
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    _HAS_NUMPY = False

needs_numpy = pytest.mark.skipif(not _HAS_NUMPY, reason="numpy not installed")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _solid_jpeg(color=(200, 200, 200), size=(1024, 1024)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _noise_jpeg(size=(1024, 1024)) -> bytes:
    if _HAS_NUMPY:
        arr = np.random.randint(0, 256, (*size, 3), dtype=np.uint8)
        img = Image.fromarray(arr, mode="RGB")
    else:
        import random
        pixels = bytes(random.randint(0, 255) for _ in range(size[0] * size[1] * 3))
        img = Image.frombytes("RGB", size, pixels)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _tiny_jpeg(color=(200, 200, 200), size=(100, 100)) -> bytes:
    return _solid_jpeg(color, size)


# ── _laplacian_variance ───────────────────────────────────────────────────────

class TestLaplacianVariance:
    def test_flat_image_low_variance(self):
        img = Image.new("L", (256, 256), 128)
        assert _laplacian_variance(img.convert("RGB")) < 10.0

    @needs_numpy
    def test_noisy_image_high_variance(self):
        rng = np.random.default_rng(42)
        arr = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
        img = Image.fromarray(arr, "RGB")
        assert _laplacian_variance(img) > 100.0

    def test_non_negative(self):
        img = _noise_jpeg()
        result = _laplacian_variance(Image.open(io.BytesIO(img)).convert("RGB"))
        assert result >= 0.0


# ── _histogram_similarity ─────────────────────────────────────────────────────

class TestHistogramSimilarity:
    def test_identical_images_near_100(self):
        img = Image.new("RGB", (256, 256), (128, 64, 200))
        score = _histogram_similarity(img, img)
        assert score >= 99.0

    def test_opposite_colors_low_score(self):
        white = Image.new("RGB", (256, 256), (255, 255, 255))
        black = Image.new("RGB", (256, 256), (0, 0, 0))
        score = _histogram_similarity(white, black)
        assert score < 10.0

    def test_score_between_0_and_100(self):
        a = Image.new("RGB", (64, 64), (100, 150, 200))
        b = Image.new("RGB", (64, 64), (120, 130, 180))
        score = _histogram_similarity(a, b)
        assert 0.0 <= score <= 100.0


# ── AIQualityEngine ───────────────────────────────────────────────────────────

class TestAIQualityEngine:
    def setup_method(self):
        self.engine = AIQualityEngine()

    @needs_numpy
    def test_good_image_approved(self):
        result = self.engine.score(_noise_jpeg())
        assert result.verdict == QualityVerdict.APPROVED
        assert result.score >= 70

    def test_too_small_resolution_fails(self):
        result = self.engine.score(_tiny_jpeg())
        assert not result.resolution_ok
        assert any("resolution" in i.lower() for i in result.issues)

    def test_all_black_brightness_fails(self):
        black = _solid_jpeg(color=(0, 0, 0))
        result = self.engine.score(black)
        assert not result.brightness_ok

    def test_all_white_brightness_fails(self):
        white = _solid_jpeg(color=(255, 255, 255))
        result = self.engine.score(white)
        assert not result.brightness_ok

    def test_color_match_with_same_reference(self):
        img = _noise_jpeg()
        result = self.engine.score(img, original_bytes=img)
        assert result.color_match_score >= 90.0

    def test_color_match_different_color(self):
        red_ref = _solid_jpeg(color=(200, 50, 50), size=(1024, 1024))
        blue_result = _solid_jpeg(color=(50, 50, 200), size=(1024, 1024))
        result = self.engine.score(blue_result, original_bytes=red_ref)
        assert result.color_match_score < 80.0

    def test_invalid_bytes_rejected(self):
        result = self.engine.score(b"not an image")
        assert result.verdict == QualityVerdict.REJECTED
        assert result.score == 0

    def test_score_range(self):
        result = self.engine.score(_noise_jpeg())
        assert 0 <= result.score <= 100

    def test_badge_text_format(self):
        result = self.engine.score(_noise_jpeg())
        badge = result.badge_text()
        assert "/100" in badge
        assert result.verdict.value in badge


# ── ProductFidelityValidator ──────────────────────────────────────────────────

class TestProductFidelityValidator:
    def setup_method(self):
        self.validator = ProductFidelityValidator()

    def test_same_image_high_score(self):
        img = _solid_jpeg()
        result = self.validator.validate(img, img)
        assert result["score"] >= 95

    def test_different_color_lower_score(self):
        red  = _solid_jpeg(color=(220, 50, 50))
        blue = _solid_jpeg(color=(50, 50, 220))
        result = self.validator.validate(red, blue)
        assert result["score"] < 80

    def test_returns_required_keys(self):
        img = _solid_jpeg()
        result = self.validator.validate(img, img)
        assert "score" in result
        assert "color_match" in result
        assert "details" in result

    def test_corrupt_input_returns_default(self):
        result = self.validator.validate(b"bad", b"bad")
        assert result["score"] == 50  # neutral fallback
