"""Tests for Background Studio (solid colors, gradients)."""
import sys
import io
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def _white_jpeg(w=256, h=256) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 200, 200)).save(buf, "JPEG")
    return buf.getvalue()


def test_all_solid_colors_defined():
    from psydox.features.background.service import SOLID_COLORS
    expected = ["White", "Black", "Grey", "Red", "Blue", "Green", "Pink",
                "Navy", "Purple", "Lavender", "Cream", "Beige", "Brown",
                "Orange", "Yellow", "Mint", "Light Pink", "Light Blue",
                "Light Green", "Dark Green", "Dark Blue", "Dark Grey", "Light Grey"]
    for name in expected:
        assert name in SOLID_COLORS, f"'{name}' missing from SOLID_COLORS"


def test_all_gradient_presets_defined():
    from psydox.features.background.service import GRADIENT_PRESETS
    expected = ["Blue → Purple", "Purple → Pink", "Pink → Orange",
                "Orange → Yellow", "Green → Blue", "Black → Grey",
                "Grey → White", "Red → Orange"]
    for name in expected:
        assert name in GRADIENT_PRESETS, f"'{name}' missing from GRADIENT_PRESETS"


def test_solid_color_produces_jpeg():
    from psydox.features.background.service import BackgroundFeature
    feat   = BackgroundFeature()
    result = feat.execute(
        {"image_bytes": _white_jpeg(), "bg_type": "solid", "color_name": "White"},
        {},
    )
    assert result["success"]
    data = result["outputs"][0]["bytes"]
    assert data[:3] == b"\xff\xd8\xff"   # JPEG magic


def test_solid_hex_color():
    from psydox.features.background.service import BackgroundFeature
    result = BackgroundFeature().execute(
        {"image_bytes": _white_jpeg(), "bg_type": "solid", "color_hex": "FF0000"},
        {},
    )
    assert result["success"]


def test_solid_rgb_color():
    from psydox.features.background.service import BackgroundFeature
    result = BackgroundFeature().execute(
        {"image_bytes": _white_jpeg(), "bg_type": "solid", "color_rgb": (0, 128, 255)},
        {},
    )
    assert result["success"]


def test_gradient_preset():
    from psydox.features.background.service import BackgroundFeature
    result = BackgroundFeature().execute(
        {"image_bytes": _white_jpeg(), "bg_type": "gradient",
         "gradient_name": "Blue → Purple"},
        {},
    )
    assert result["success"]


def test_gradient_output_has_correct_size():
    from psydox.features.background.service import BackgroundFeature
    from PIL import Image
    result = BackgroundFeature().execute(
        {"image_bytes": _white_jpeg(), "bg_type": "gradient",
         "gradient_name": "Pink → Orange"},
        {"ratio_wh": (400, 500)},
    )
    assert result["success"]
    img = Image.open(io.BytesIO(result["outputs"][0]["bytes"]))
    assert img.size == (400, 500)


def test_gradient_custom_stops():
    from psydox.features.background.service import BackgroundFeature
    result = BackgroundFeature().execute(
        {"image_bytes": _white_jpeg(), "bg_type": "gradient",
         "gradient_stops": [(255, 0, 0), (0, 0, 255)], "gradient_dir": 90},
        {},
    )
    assert result["success"]


def test_validate_missing_image():
    from psydox.features.background.service import BackgroundFeature
    ok, errors = BackgroundFeature().validate_input({"bg_type": "solid", "color_name": "White"})
    assert not ok
    assert errors


def test_validate_solid_missing_color():
    from psydox.features.background.service import BackgroundFeature
    ok, errors = BackgroundFeature().validate_input(
        {"image_bytes": b"x", "bg_type": "solid"}
    )
    assert not ok
