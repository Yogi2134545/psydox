"""
Psydox Batch Processor

Downloads images from Excel catalog URLs, converts each to the target ratio
and background, and returns a ZIP archive.

Processing is identical to process_images.convert_to_4_5():
  - Fit image to target canvas (letterbox / pillarbox — no cropping)
  - Detect and optionally replace background colour
  - Save as JPEG at the specified quality

ZIP structure mirrors the old batch view:
  {STYLE_CODE}/{STYLE_CODE}_01.jpg
  {STYLE_CODE}/{STYLE_CODE}_02.jpg
  ...

Usage:
    from psydox.batch.processor import run_batch, RATIO_PRESETS, BG_OPTIONS
"""
from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from PIL import Image

_log = logging.getLogger("psydox.batch.processor")

# ── Ratio presets (identical to process_images.RATIO_PRESETS) ────────────────
RATIO_PRESETS: dict[str, tuple[int, int] | None] = {
    "4:5  (1080×1350)": (1080, 1350),
    "1:1  (1080×1080)": (1080, 1080),
    "3:4  (1080×1440)": (1080, 1440),
    "9:16 (1080×1920)": (1080, 1920),
    "16:9 (1920×1080)": (1920, 1080),
    "Custom":           None,
}

# ── Background options (identical to app.py batch section) ───────────────────
BG_OPTIONS: dict[str, object] = {
    "Auto (keep original)": "auto",
    "White":     (255, 255, 255),
    "Ivory":     (255, 253, 240),
    "Cream":     (245, 245, 220),
    "Pearl":     (240, 240, 240),
    "Silver":    (220, 220, 220),
    "Grey":      (200, 200, 200),
    "Ash":       (180, 180, 180),
    "Stone":     (150, 150, 150),
    "Slate":     (100, 100, 100),
    "Charcoal":  (60,  60,  60),
    "Dark":      (30,  30,  30),
    "Black":     (0,   0,   0),
    "Blush":     (255, 230, 230),
    "Peach":     (255, 220, 180),
    "Sky Blue":  (200, 220, 245),
    "Lavender":  (220, 200, 240),
    "Sage":      (200, 220, 190),
}

DEFAULT_JPEG_QUALITY = 92
_BG_SAMPLE_DEPTH     = 30


@dataclass
class BatchConfig:
    target_w:     int   = 1080
    target_h:     int   = 1350
    jpeg_quality: int   = DEFAULT_JPEG_QUALITY
    bg_rgb:       object = "auto"   # "auto" | (R,G,B)
    max_retries:  int   = 3
    timeout:      int   = 15


@dataclass
class BatchResult:
    total:   int = 0
    success: int = 0
    failed:  int = 0
    skipped: int = 0
    zip_bytes: Optional[bytes] = None
    errors: list[str] = field(default_factory=list)


# ── Core image conversion (identical to process_images.convert_to_4_5) ───────

def _is_solid_background(img: Image.Image) -> tuple[bool, tuple]:
    """Detect whether the image has a solid background. Returns (is_solid, bg_rgb)."""
    try:
        import numpy as np
        rgb = np.array(img.convert("RGB"), dtype=np.float32)
        h, w = rgb.shape[:2]
        d = min(_BG_SAMPLE_DEPTH, h // 4, w // 4)
        if d < 1:
            return False, (235, 235, 235)
        strips = np.concatenate([
            rgb[:d, :].reshape(-1, 3),  rgb[h - d:, :].reshape(-1, 3),
            rgb[:, :d].reshape(-1, 3),  rgb[:, w - d:].reshape(-1, 3),
        ])
        bg_color = np.median(strips, axis=0)
        diffs    = np.linalg.norm(strips - bg_color, axis=1)
        solid    = float(np.percentile(diffs, 90)) < 18
        return solid, tuple(int(c) for c in bg_color)
    except Exception:
        return False, (235, 235, 235)


def _replace_mixed_background(img: Image.Image, bg_rgb: tuple) -> Image.Image:
    """Replace non-solid background with a solid colour using cv2 if available."""
    try:
        import cv2
        import numpy as np
        orig_arr = np.array(img.convert("RGB"))
        oh, ow = orig_arr.shape[:2]
        lab  = cv2.cvtColor(orig_arr, cv2.COLOR_RGB2LAB).astype(np.float32)
        d    = _BG_SAMPLE_DEPTH
        strips = np.concatenate([
            lab[:d, :].reshape(-1, 3),  lab[oh - d:, :].reshape(-1, 3),
            lab[:, :d].reshape(-1, 3),  lab[:, ow - d:].reshape(-1, 3),
        ])
        bg_lab  = np.median(strips, axis=0)
        diff    = np.linalg.norm(lab - bg_lab, axis=2)
        thresh  = float(np.clip(np.mean(diff) + 1.2 * np.std(diff), 8.0, 40.0))
        mask    = (diff > thresh).astype(np.uint8) * 255

        k    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)

        alpha     = (mask.astype(float) / 255.0)[:, :, None]
        bg_canvas = __import__("numpy").full_like(orig_arr, bg_rgb, dtype=float)
        composite = (orig_arr.astype(float) * alpha + bg_canvas * (1 - alpha))
        composite = composite.clip(0, 255).astype("uint8")
        return Image.fromarray(composite)
    except Exception:
        return img


def convert_image(img: Image.Image, cfg: BatchConfig) -> Image.Image:
    """
    Convert a PIL image to the target ratio and background.
    Logic is identical to process_images.convert_to_4_5().
    """
    import numpy as np

    TW, TH = cfg.target_w, cfg.target_h
    img = img.convert("RGB")

    # Detect original background BEFORE any replacement
    arr = np.array(img, dtype=np.uint8)
    ih, iw = arr.shape[:2]
    d = min(_BG_SAMPLE_DEPTH, ih // 4, iw // 4)
    if d >= 1:
        edge = np.concatenate([
            arr[:d, :].reshape(-1, 3),     arr[ih - d:, :].reshape(-1, 3),
            arr[:, :d].reshape(-1, 3),     arr[:, iw - d:].reshape(-1, 3),
        ])
        original_bg = tuple(int(c) for c in np.median(edge, axis=0).astype(np.uint8))
    else:
        original_bg = (235, 235, 235)

    # Background handling — mirrors process_images.convert_to_4_5:
    #   tuple (R,G,B) → replace bg, then letterbox with that colour
    #   "auto" / else → FIT/letterbox: extend image edge pixels into strips
    import numpy as _np

    orig_w, orig_h = img.size
    scale = min(TW / orig_w, TH / orig_h, 2.0)
    nw    = max(1, int(orig_w * scale))
    nh    = max(1, int(orig_h * scale))

    if isinstance(cfg.bg_rgb, (list, tuple)) and len(cfg.bg_rgb) == 3:
        bg_fill = tuple(int(c) for c in cfg.bg_rgb)
        img = _replace_mixed_background(img, bg_fill)
        scaled = img.resize((nw, nh), Image.LANCZOS)
        px = (TW - nw) // 2
        py = (TH - nh) // 2
        canvas_arr = _np.full((TH, TW, 3), bg_fill, dtype=_np.uint8)
        canvas_arr[py:py + nh, px:px + nw] = _np.array(scaled, dtype=_np.uint8)
        return Image.fromarray(canvas_arr)

    scaled = img.resize((nw, nh), Image.LANCZOS)
    sc     = _np.array(scaled, dtype=_np.uint8)
    px     = (TW - nw) // 2
    py     = (TH - nh) // 2
    px_r   = TW - nw - px
    py_b   = TH - nh - py

    _ec = min(8, nh, nw)
    corner_c = tuple(int(c) for c in sc[:_ec, :_ec, :].mean(axis=(0, 1)).astype(_np.uint8))
    canvas_arr = _np.full((TH, TW, 3), corner_c, dtype=_np.uint8)

    if px > 0 or px_r > 0:
        _ew  = min(8, nw)
        l_edge = sc[:, :_ew, :].mean(axis=1, keepdims=True).astype(_np.uint8)
        r_edge = sc[:, max(0, nw - _ew):, :].mean(axis=1, keepdims=True).astype(_np.uint8)
        if px > 0:
            canvas_arr[py:py + nh, :px]      = _np.tile(l_edge, (1, px,   1))
        if px_r > 0:
            canvas_arr[py:py + nh, px + nw:] = _np.tile(r_edge, (1, px_r, 1))

    if py > 0 or py_b > 0:
        _eh  = min(8, nh)
        t_edge = sc[:_eh, :, :].mean(axis=0, keepdims=True).astype(_np.uint8)
        b_edge = sc[max(0, nh - _eh):, :, :].mean(axis=0, keepdims=True).astype(_np.uint8)
        if py > 0:
            canvas_arr[:py, px:px + nw]      = _np.tile(t_edge, (py,   1, 1))
        if py_b > 0:
            canvas_arr[py + nh:, px:px + nw] = _np.tile(b_edge, (py_b, 1, 1))

    canvas_arr[py:py + nh, px:px + nw] = sc
    return Image.fromarray(canvas_arr)


def image_bytes_to_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=False, subsampling=0)
    return buf.getvalue()


# ── Bulk processor ────────────────────────────────────────────────────────────

def run_batch(
    styles: dict[str, list[str]],
    cfg: BatchConfig,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> BatchResult:
    """
    Download and process all images from the styles dict.
    Returns a BatchResult with a ZIP archive in zip_bytes.

    progress_cb(done, total, current_style) — called after each style.
    """
    from psydox.batch.excel_reader import download_image, resolve_url

    result  = BatchResult(total=len(styles))
    zip_buf = io.BytesIO()

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        done = 0
        for style_code, urls in styles.items():
            if progress_cb:
                progress_cb(done, result.total, style_code)

            style_success = 0
            for idx, url in enumerate(urls, start=1):
                try:
                    img_bytes = download_image(url, timeout=cfg.timeout)
                    if not img_bytes:
                        _log.warning("Failed to download %s (url #%d): %s", style_code, idx, url)
                        result.failed += 1
                        continue

                    img = Image.open(io.BytesIO(img_bytes))
                    processed = convert_image(img, cfg)
                    jpeg_bytes = image_bytes_to_jpeg(processed, cfg.jpeg_quality)

                    filename = f"{style_code}/{style_code}_{idx:02d}.jpg"
                    zf.writestr(filename, jpeg_bytes)
                    style_success += 1
                    result.success += 1

                except Exception as exc:
                    _log.warning("Error processing %s url #%d: %s", style_code, idx, exc)
                    result.errors.append(f"{style_code} #{idx}: {exc}")
                    result.failed += 1

            if style_success == 0:
                result.skipped += 1

            done += 1
            if progress_cb:
                progress_cb(done, result.total, style_code)

    zip_buf.seek(0)
    result.zip_bytes = zip_buf.getvalue()
    return result
