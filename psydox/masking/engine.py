"""
Psydox Masking Engine

Product segmentation: bounding-box detection and background removal.
Uses rembg for high-quality alpha masks when available,
falls back to OpenCV LAB-colour-difference masking.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

_log = logging.getLogger("psydox.masking.engine")

_BG_SAMPLE_DEPTH = 30

try:
    from rembg import remove as _rembg_remove
    _rembg_ok = True
except Exception:
    _rembg_ok = False

try:
    import cv2 as _cv2
    _cv2_ok = True
except Exception:
    _cv2_ok = False


@dataclass
class BBoxResult:
    left:       int
    top:        int
    right:      int
    bottom:     int
    # quality_hint is a heuristic score (product-area fraction), NOT an ML confidence score.
    quality_hint: float
    method:     str   # "rembg" | "opencv" | "full_frame"
    is_heuristic: bool = True

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def as_tuple(self) -> tuple:
        return (self.left, self.top, self.right, self.bottom)


@dataclass
class MaskResult:
    image_rgba: bytes   # PNG with alpha channel
    bbox:       BBoxResult
    method:     str     # "rembg" | "opencv"


class MaskingEngine:
    """
    Product segmentation engine.

    Prefers rembg for high-quality alpha masks; falls back to OpenCV
    LAB-colour-difference when rembg is unavailable.
    """

    def detect(self, img: Image.Image) -> BBoxResult:
        """Return a bounding box around the product in the image."""
        w, h = img.width, img.height
        if _rembg_ok:
            bbox   = self._bbox_rembg(img)
            method = "rembg"
        elif _cv2_ok:
            bbox   = self._bbox_opencv(img)
            method = "opencv"
        else:
            bbox   = (0, 0, w, h)
            method = "full_frame"

        left, top, right, bottom = bbox
        product_fraction = max(1, (right - left) * (bottom - top)) / max(1, w * h)
        if method == "rembg":
            confidence = 0.40 if product_fraction > 0.90 else 0.95
        elif method == "opencv":
            confidence = 0.40 if product_fraction > 0.90 else 0.75
        else:
            confidence = 0.0

        return BBoxResult(
            left=left, top=top, right=right, bottom=bottom,
            quality_hint=confidence, method=method,
        )

    def segment(self, img: Image.Image) -> MaskResult:
        """Remove background and return transparent PNG bytes + detected bounding box."""
        if _rembg_ok:
            try:
                # Single rembg call — derive bbox from the same RGBA result.
                rgba, bbox = self._rembg_once(img)
                method = "rembg"
            except Exception as exc:
                _log.warning("rembg segment failed (%s), falling back to opencv", exc)
                rgba   = self._opencv_segment(img)
                bbox   = self._make_bbox_from_opencv(img)
                method = "opencv"
        else:
            rgba   = self._opencv_segment(img)
            bbox   = self._make_bbox_from_opencv(img)
            method = "opencv"

        buf = io.BytesIO()
        rgba.save(buf, "PNG")
        return MaskResult(image_rgba=buf.getvalue(), bbox=bbox, method=method)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _rembg_once(self, img: Image.Image) -> tuple:
        """
        Call rembg once and return (rgba_image, BBoxResult).
        Eliminates the double rembg call that would occur if detect() were
        called before segment() separately.
        """
        rgba_img = _rembg_remove(img.convert("RGBA"))
        alpha    = np.array(rgba_img)[:, :, 3]
        rows     = np.any(alpha > 10, axis=1)
        cols     = np.any(alpha > 10, axis=0)
        w, h     = img.width, img.height
        if not rows.any():
            bbox = BBoxResult(left=0, top=0, right=w, bottom=h,
                              quality_hint=0.0, method="rembg")
        else:
            top    = int(np.argmax(rows))
            bottom = int(len(rows) - np.argmax(rows[::-1]) - 1)
            left   = int(np.argmax(cols))
            right  = int(len(cols) - np.argmax(cols[::-1]) - 1)
            product_fraction = max(1, (right - left) * (bottom - top)) / max(1, w * h)
            conf   = 0.40 if product_fraction > 0.90 else 0.95
            bbox   = BBoxResult(left=left, top=top, right=right, bottom=bottom,
                                quality_hint=conf, method="rembg")
        return rgba_img, bbox

    def _make_bbox_from_opencv(self, img: Image.Image) -> BBoxResult:
        """Run OpenCV bbox detection and wrap result in BBoxResult."""
        raw = self._bbox_opencv(img)
        l, t, r, b = raw
        w, h = img.width, img.height
        product_fraction = max(1, (r - l) * (b - t)) / max(1, w * h)
        conf = 0.40 if product_fraction > 0.90 else 0.75
        return BBoxResult(left=l, top=t, right=r, bottom=b,
                          quality_hint=conf, method="opencv")

    def _bbox_rembg(self, img: Image.Image) -> tuple:
        try:
            no_bg = _rembg_remove(img.convert("RGBA"))
            alpha = np.array(no_bg)[:, :, 3]
            rows  = np.any(alpha > 10, axis=1)
            cols  = np.any(alpha > 10, axis=0)
            if not rows.any():
                return (0, 0, img.width, img.height)
            top    = int(np.argmax(rows))
            bottom = int(len(rows) - np.argmax(rows[::-1]) - 1)
            left   = int(np.argmax(cols))
            right  = int(len(cols) - np.argmax(cols[::-1]) - 1)
            return (left, top, right, bottom)
        except Exception as exc:
            _log.warning("rembg bbox failed (%s), falling back to opencv", exc)
            return self._bbox_opencv(img)

    def _bbox_opencv(self, img: Image.Image) -> tuple:
        if not _cv2_ok:
            return (0, 0, img.width, img.height)
        arr = np.array(img.convert("RGB"))
        h, w = arr.shape[:2]
        lab  = _cv2.cvtColor(arr, _cv2.COLOR_RGB2LAB).astype(np.float32)
        b    = max(5, min(20, h // 30, w // 30))
        strips = np.concatenate([
            lab[:b, :].reshape(-1, 3),  lab[h - b:, :].reshape(-1, 3),
            lab[:, :b].reshape(-1, 3),  lab[:, w - b:].reshape(-1, 3),
        ])
        bg_color = np.median(strips, axis=0)
        diff     = np.linalg.norm(lab - bg_color, axis=2)
        thresh   = float(np.clip(np.mean(diff) + 1.5 * np.std(diff), 8.0, 35.0))
        mask     = (diff > thresh).astype(np.uint8) * 255

        k    = _cv2.getStructuringElement(_cv2.MORPH_ELLIPSE, (15, 15))
        mask = _cv2.morphologyEx(mask, _cv2.MORPH_CLOSE, k)
        mask = _cv2.morphologyEx(mask, _cv2.MORPH_OPEN,  k)

        coords = _cv2.findNonZero(mask)
        if coords is None or len(coords) < 100:
            return (0, 0, w, h)
        x, y, bw, bh = _cv2.boundingRect(coords)
        if bw * bh < 0.10 * w * h:
            return (0, 0, w, h)
        pad = max(10, int(min(w, h) * 0.02))
        return (max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad))

    def _opencv_segment(self, img: Image.Image) -> Image.Image:
        """Build RGBA image with background removed using OpenCV LAB mask."""
        if not _cv2_ok:
            return img.convert("RGBA")
        orig = np.array(img.convert("RGB"))
        oh, ow = orig.shape[:2]
        lab  = _cv2.cvtColor(orig, _cv2.COLOR_RGB2LAB).astype(np.float32)
        d    = _BG_SAMPLE_DEPTH
        strips = np.concatenate([
            lab[:d, :].reshape(-1, 3),  lab[oh - d:, :].reshape(-1, 3),
            lab[:, :d].reshape(-1, 3),  lab[:, ow - d:].reshape(-1, 3),
        ])
        bg_lab = np.median(strips, axis=0)
        diff   = np.linalg.norm(lab - bg_lab, axis=2)
        thresh = float(np.clip(np.mean(diff) + 1.2 * np.std(diff), 8.0, 40.0))
        mask   = (diff > thresh).astype(np.uint8) * 255

        k    = _cv2.getStructuringElement(_cv2.MORPH_ELLIPSE, (13, 13))
        mask = _cv2.morphologyEx(mask, _cv2.MORPH_CLOSE, k)
        mask = _cv2.morphologyEx(mask, _cv2.MORPH_OPEN,  k)

        rgba = np.zeros((oh, ow, 4), dtype=np.uint8)
        rgba[:, :, :3] = orig
        rgba[:, :, 3]  = mask
        return Image.fromarray(rgba, "RGBA")
