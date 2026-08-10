"""
Tests for DemoFutureFeature — proves the zero-edit extensibility architecture.

These tests verify that a brand-new feature can:
  1. Be discovered automatically (no core file edits)
  2. Appear in the feature registry
  3. Execute successfully
  4. Pass quality validation
  5. Return proper job-compatible output

The feature is gated by ENABLE_DEMO_FUTURE_FEATURE env var.
"""
import io
import os
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
os.environ["DEBUG_MODE"] = "true"
os.environ["ENABLE_DEMO_FUTURE_FEATURE"] = "true"

from PIL import Image


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (180, 100, 50)).save(buf, "JPEG")
    return buf.getvalue()


def test_demo_future_feature_executes():
    from psydox.features.demo_future.service import DemoFutureFeature
    f = DemoFutureFeature()
    result = f.execute({"image_bytes": _jpeg(), "border_px": 5, "label": "TEST"}, {})
    assert result["success"]
    assert result["outputs"]
    assert result["outputs"][0]["bytes"]


def test_demo_future_feature_manifest():
    from psydox.features.demo_future.service import DemoFutureFeature
    m = DemoFutureFeature().manifest
    assert m.id == "demo_future"
    assert m.feature_flag == "ENABLE_DEMO_FUTURE_FEATURE"
    assert not m.requires_ai


def test_demo_future_feature_is_enabled_with_flag():
    from psydox.features.demo_future.service import DemoFutureFeature
    os.environ["ENABLE_DEMO_FUTURE_FEATURE"] = "true"
    assert DemoFutureFeature().is_enabled()


def test_demo_future_feature_disabled_without_flag():
    from psydox.features.demo_future.service import DemoFutureFeature
    saved = os.environ.pop("ENABLE_DEMO_FUTURE_FEATURE", None)
    try:
        assert not DemoFutureFeature().is_enabled()
    finally:
        if saved:
            os.environ["ENABLE_DEMO_FUTURE_FEATURE"] = saved


def test_demo_future_auto_discovered():
    """
    CRITICAL TEST: proves auto-discovery finds the feature without
    any manual registration in loader.py, app.py, or any core file.
    """
    from psydox.core.autodiscovery import discover_features
    from psydox.core.registry import FeatureRegistry
    os.environ["ENABLE_DEMO_FUTURE_FEATURE"] = "true"

    registry = FeatureRegistry()
    for feature in discover_features():
        registry.register(feature)

    ids = registry.ids()
    assert "demo_future" in ids, (
        f"demo_future was NOT auto-discovered. "
        f"Registered IDs: {ids}. "
        f"This means the extensibility architecture is broken — "
        f"a new feature requires manually editing core files."
    )


def test_demo_future_output_is_valid_image():
    from psydox.features.demo_future.service import DemoFutureFeature
    result = DemoFutureFeature().execute({"image_bytes": _jpeg()}, {})
    assert result["success"]
    img = Image.open(io.BytesIO(result["outputs"][0]["bytes"]))
    assert img.size[0] > 0 and img.size[1] > 0


def test_demo_future_metadata_has_note():
    from psydox.features.demo_future.service import DemoFutureFeature
    result = DemoFutureFeature().execute({"image_bytes": _jpeg()}, {})
    assert "note" in result["metadata"]
    assert "zero" in result["metadata"]["note"].lower()
