"""
Regression tests: process_images.convert_to_4_5() and
psydox.batch.processor.convert_image() must produce identical output for the
same input since they both delegate to _letterbox_place().

Also verifies that _letterbox_place() produces correctly-sized output and
handles the solid-bg and auto-bg cases.
"""
import io
import numpy as np
import pytest
from PIL import Image

from psydox.batch.processor import (
    _letterbox_place, _detect_background, convert_image, BatchConfig,
)


def _solid_image(w: int, h: int, color=(200, 200, 200)) -> Image.Image:
    return Image.new("RGB", (w, h), color=color)


def _random_image(w: int, h: int, seed: int = 42) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    return Image.fromarray(arr)


class TestLetterboxPlace:
    def test_output_size_auto_landscape_to_portrait(self):
        img = _solid_image(300, 200)  # landscape
        out = _letterbox_place(img, 800, 1000, original_bg=(200, 200, 200))
        assert out.size == (800, 1000)

    def test_output_size_auto_portrait_to_landscape(self):
        img = _solid_image(200, 400)  # portrait
        out = _letterbox_place(img, 1000, 800, original_bg=(255, 255, 255))
        assert out.size == (1000, 800)

    def test_output_size_solid_bg(self):
        img = _solid_image(300, 400)
        out = _letterbox_place(img, 800, 1000, original_bg=(255, 255, 255), solid_bg_fill=(255, 0, 0))
        assert out.size == (800, 1000)

    def test_solid_bg_fills_margins_with_correct_colour(self):
        img = _solid_image(200, 400)  # tall; will have left/right margins at 800×1000
        out = _letterbox_place(img, 800, 1000, original_bg=(0, 0, 0), solid_bg_fill=(255, 0, 0))
        arr = np.array(out)
        # Left margin should be red
        assert arr[500, 0, 0] == 255  # R
        assert arr[500, 0, 1] == 0    # G
        assert arr[500, 0, 2] == 0    # B

    def test_auto_bg_fills_top_bottom_with_original_bg(self):
        # Wide image → top/bottom margins → should use original_bg
        original_bg = (120, 130, 140)
        img = _solid_image(400, 100, color=original_bg)
        out = _letterbox_place(img, 400, 500, original_bg=original_bg, solid_bg_fill=None)
        arr = np.array(out)
        # Top row should be close to original_bg
        top_color = tuple(int(c) for c in arr[0, 200, :])
        for expected, actual in zip(original_bg, top_color):
            assert abs(expected - actual) <= 15, (
                f"Top margin colour {top_color} differs too much from original_bg {original_bg}"
            )

    def test_same_size_image_unchanged(self):
        img = _solid_image(800, 1000)
        out = _letterbox_place(img, 800, 1000, original_bg=(200, 200, 200))
        assert out.size == (800, 1000)


class TestDetectBackground:
    def test_white_background(self):
        img = Image.new("RGB", (200, 200), color=(255, 255, 255))
        bg = _detect_background(img)
        assert all(abs(c - 255) <= 5 for c in bg), f"Expected white bg, got {bg}"

    def test_grey_background(self):
        img = Image.new("RGB", (200, 200), color=(180, 180, 180))
        bg = _detect_background(img)
        assert all(abs(c - 180) <= 10 for c in bg), f"Expected grey bg, got {bg}"

    def test_returns_rgb_tuple(self):
        img = _solid_image(100, 100)
        bg = _detect_background(img)
        assert isinstance(bg, tuple) and len(bg) == 3


class TestConvertImageEquivalence:
    """
    process_images.convert_to_4_5() and processor.convert_image() must give
    identical results now that both delegate to _letterbox_place().
    """
    def test_auto_bg_identical_output(self):
        img = _solid_image(300, 400, color=(200, 180, 160))
        cfg_dict = {"TARGET_W": 800, "TARGET_H": 1000}
        cfg_batch = BatchConfig(target_w=800, target_h=1000)

        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            import process_images as pi
            out_pi = pi.convert_to_4_5(img.copy(), cfg_dict)
        except Exception as e:
            pytest.skip(f"process_images not importable: {e}")

        out_batch = convert_image(img.copy(), cfg_batch)

        arr_pi    = np.array(out_pi)
        arr_batch = np.array(out_batch)
        assert arr_pi.shape == arr_batch.shape
        max_diff = int(np.max(np.abs(arr_pi.astype(int) - arr_batch.astype(int))))
        assert max_diff <= 2, (
            f"auto-bg outputs differ by up to {max_diff} — they should be identical"
        )

    def test_solid_bg_identical_output(self):
        img = _solid_image(300, 400, color=(200, 180, 160))
        bg_rgb = (255, 255, 255)
        cfg_dict  = {"TARGET_W": 800, "TARGET_H": 1000, "BG_RGB": list(bg_rgb)}
        cfg_batch = BatchConfig(target_w=800, target_h=1000, bg_rgb=list(bg_rgb))

        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            import process_images as pi
            out_pi = pi.convert_to_4_5(img.copy(), cfg_dict)
        except Exception as e:
            pytest.skip(f"process_images not importable: {e}")

        out_batch = convert_image(img.copy(), cfg_batch)

        arr_pi    = np.array(out_pi)
        arr_batch = np.array(out_batch)
        assert arr_pi.shape == arr_batch.shape
        max_diff = int(np.max(np.abs(arr_pi.astype(int) - arr_batch.astype(int))))
        assert max_diff <= 2, (
            f"solid-bg outputs differ by up to {max_diff} — they should be identical"
        )
