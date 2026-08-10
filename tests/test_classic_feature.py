"""Tests for ClassicFeature — resize, crop, packshot, convert, validate, marketplace."""
import io
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from PIL import Image


def _jpeg(w=800, h=600, color=(120, 160, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def _get_feature():
    from psydox.features.classic.service import ClassicFeature
    return ClassicFeature()


def test_resize_produces_target_size():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(), "operation": "resize", "width": 500, "height": 500}, {})
    assert result["success"]
    img = Image.open(io.BytesIO(result["outputs"][0]["bytes"]))
    assert img.size == (500, 500)


def test_resize_keep_ratio_default():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(800, 400), "operation": "resize",
                        "width": 500, "height": 500, "keep_ratio": True}, {})
    assert result["success"]
    img = Image.open(io.BytesIO(result["outputs"][0]["bytes"]))
    assert img.size == (500, 500)  # canvas is always target size


def test_crop_produces_target_size():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(1000, 1000), "operation": "crop",
                        "width": 300, "height": 400}, {})
    assert result["success"]
    img = Image.open(io.BytesIO(result["outputs"][0]["bytes"]))
    assert img.size == (300, 400)


def test_convert_to_png():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(), "operation": "convert", "format": "PNG"}, {})
    assert result["success"]
    assert result["outputs"][0]["mime"] == "image/png"


def test_convert_to_webp():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(), "operation": "convert", "format": "WEBP"}, {})
    assert result["success"]
    assert result["outputs"][0]["mime"] == "image/webp"


def test_packshot_centers_on_white():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(400, 600), "operation": "packshot",
                        "size": 1000, "padding": 0.1}, {})
    assert result["success"]
    img = Image.open(io.BytesIO(result["outputs"][0]["bytes"]))
    assert img.size == (1000, 1000)


def test_validate_small_image_reports_issue():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(200, 200), "operation": "validate",
                        "min_width": 500, "min_height": 500}, {})
    assert result["success"]  # validate always returns outputs
    assert not result["metadata"]["valid"]
    assert result["errors"]  # issues list


def test_validate_large_image_is_valid():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(1200, 1200), "operation": "validate",
                        "min_width": 500, "min_height": 500}, {})
    assert result["success"]
    assert result["metadata"]["valid"]


def test_compress_reduces_size():
    f = _get_feature()
    original = _jpeg(1500, 1500)
    result = f.execute({"image_bytes": original, "operation": "compress", "quality": 40}, {})
    assert result["success"]
    assert len(result["outputs"][0]["bytes"]) < len(original)


def test_marketplace_amazon_main():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(), "operation": "marketplace",
                        "preset": "amazon_main"}, {})
    assert result["success"]
    img = Image.open(io.BytesIO(result["outputs"][0]["bytes"]))
    assert img.size == (2000, 2000)


def test_marketplace_multi_preset():
    f = _get_feature()
    result = f.execute({"image_bytes": _jpeg(), "operation": "marketplace",
                        "presets": ["amazon_main", "thumbnail"]}, {})
    assert result["success"]
    assert len(result["outputs"]) == 2


def test_invalid_operation_returns_error():
    f = _get_feature()
    ok, errors = f.validate_input({"image_bytes": _jpeg(), "operation": "fly"})
    assert not ok


def test_missing_image_validation_error():
    f = _get_feature()
    ok, errors = f.validate_input({"operation": "resize"})
    assert not ok
    assert errors


def test_manifest_fields():
    f = _get_feature()
    m = f.manifest
    assert m.id == "classic"
    assert not m.requires_ai
    assert m.supports_batch
