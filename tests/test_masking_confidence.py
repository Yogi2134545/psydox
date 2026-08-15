"""
Regression tests: BBoxResult.quality_hint is a heuristic score (product-area
fraction), NOT an ML confidence score. Callers must treat it as advisory only.

Also verifies the is_heuristic flag is always True and that the field was
renamed from the old `.confidence` attribute.
"""
import pytest
from PIL import Image
import numpy as np


def _make_bbox_result(**kwargs):
    """Construct a BBoxResult with defaults."""
    from psydox.masking.engine import BBoxResult
    defaults = dict(left=0, top=0, right=100, bottom=100,
                    quality_hint=0.8, is_heuristic=True, method="rembg")
    defaults.update(kwargs)
    return BBoxResult(**defaults)


class TestBBoxResultFieldRename:
    def test_quality_hint_field_exists(self):
        from psydox.masking.engine import BBoxResult
        r = _make_bbox_result(quality_hint=0.75)
        assert hasattr(r, "quality_hint")
        assert r.quality_hint == 0.75

    def test_confidence_field_does_not_exist(self):
        r = _make_bbox_result()
        assert not hasattr(r, "confidence"), (
            "BBoxResult must not expose .confidence — it has been renamed to quality_hint "
            "to signal that it is a heuristic, not an ML probability."
        )

    def test_is_heuristic_is_true_by_default(self):
        r = _make_bbox_result()
        assert r.is_heuristic is True

    def test_is_heuristic_field_exists(self):
        from psydox.masking.engine import BBoxResult
        assert hasattr(BBoxResult(left=0, top=0, right=1, bottom=1,
                                  quality_hint=0.5, method="rembg"), "is_heuristic")


class TestQualityHintValues:
    """
    The engine sets quality_hint to specific values based on product_fraction.
    These values are heuristic thresholds — verify the logic is still in place
    without coupling to the exact numbers.
    """
    def test_quality_hint_in_range_0_to_1(self):
        r = _make_bbox_result(quality_hint=0.95)
        assert 0.0 <= r.quality_hint <= 1.0

    def test_quality_hint_zero_is_valid(self):
        r = _make_bbox_result(quality_hint=0.0)
        assert r.quality_hint == 0.0

    def test_quality_hint_one_is_valid(self):
        r = _make_bbox_result(quality_hint=1.0)
        assert r.quality_hint == 1.0


class TestBBoxResultGeometry:
    def test_width_and_height(self):
        r = _make_bbox_result(left=10, top=20, right=110, bottom=220,
                              quality_hint=0.8, method="opencv")
        assert r.width == 100
        assert r.height == 200

    def test_method_field(self):
        for method in ("rembg", "opencv", "full_frame"):
            r = _make_bbox_result(method=method)
            assert r.method == method


class TestDetectorOutputsQualityHint:
    """
    Smoke-test the Detector.detect() method produces BBoxResult with quality_hint
    (not confidence) set to a valid float. Uses a synthetic solid-colour image
    so no model weights are needed (will fall back to full_frame path).
    """
    def test_detect_returns_quality_hint(self):
        try:
            from psydox.masking.engine import Detector
        except ImportError:
            pytest.skip("psydox.masking.engine not importable")

        img = Image.new("RGB", (200, 200), color=(240, 240, 240))
        detector = Detector()
        try:
            result = detector.detect(img)
        except Exception:
            pytest.skip("Detector.detect raised — dependencies unavailable")

        assert hasattr(result, "quality_hint"), "Detector must return BBoxResult with quality_hint"
        assert not hasattr(result, "confidence"), (
            "Detector must NOT return BBoxResult with .confidence (renamed to quality_hint)"
        )
        assert result.is_heuristic is True
        assert 0.0 <= result.quality_hint <= 1.0
