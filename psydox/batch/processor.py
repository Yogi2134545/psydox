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
    zip_bytes:         Optional[bytes] = None
    errors:            list[str]       = field(default_factory=list)
    failed_excel_bytes: Optional[bytes] = None  # Excel of failed rows, None when 0 failures


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

    # Top / bottom strips — use detected background colour (same fix as process_images.py).
    if py > 0 or py_b > 0:
        if py > 0:
            canvas_arr[:py, px:px + nw]      = original_bg
        if py_b > 0:
            canvas_arr[py + nh:, px:px + nw] = original_bg

    canvas_arr[py:py + nh, px:px + nw] = sc
    return Image.fromarray(canvas_arr)


def image_bytes_to_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=False, subsampling=0)
    return buf.getvalue()


# ── Failure tracking helpers ──────────────────────────────────────────────────

@dataclass
class _FailedEntry:
    style_code: str
    url:        str
    url_index:  int           # 1-based position among that style's URLs
    reason:     str
    raw_row:    Optional[tuple] = None  # full original Excel row (all columns)


def _safe_reason(exc: Exception) -> str:
    """Convert an exception to a short, user-safe string (no stack traces)."""
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200] + "…"
    return msg


_HTTP_REASONS: dict[int, str] = {
    400: "HTTP 400 — Bad request",
    401: "HTTP 401 — Unauthorized",
    403: "HTTP 403 — Access forbidden",
    404: "HTTP 404 — Image not found",
    410: "HTTP 410 — Image permanently removed",
    422: "HTTP 422 — Unprocessable URL",
    429: "HTTP 429 — Too many requests (rate limited)",
    500: "HTTP 500 — Server error",
    502: "HTTP 502 — Bad gateway",
    503: "HTTP 503 — Service unavailable",
    504: "HTTP 504 — Gateway timeout",
}

_DL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def _download_with_reason(url: str, timeout: int) -> tuple:
    """
    Like download_image() but also returns the failure reason.
    Returns (image_bytes, None) on success, (None, reason_str) on failure.
    Provides specific HTTP error codes instead of a generic "Failed".
    """
    if not url or not url.strip():
        return None, "Image URL is empty"

    try:
        import requests
        from psydox.batch.excel_reader import resolve_url
        from urllib.parse import urlparse as _up

        direct = resolve_url(url)
        try:
            resp = requests.get(direct, headers=_DL_HEADERS, timeout=timeout, stream=True)
        except requests.exceptions.Timeout:
            return None, "Connection timeout"
        except requests.exceptions.ConnectionError:
            host = _up(url).netloc
            return None, f"Network error — could not reach {host}"
        except requests.exceptions.MissingSchema:
            return None, "Invalid image URL"
        except Exception as exc:
            return None, f"Request error: {_safe_reason(exc)}"

        if resp.status_code != 200:
            return None, _HTTP_REASONS.get(
                resp.status_code,
                f"HTTP {resp.status_code} — Download failed",
            )

        if "text/html" in resp.headers.get("Content-Type", ""):
            return None, "URL returns an HTML page, not an image (possible login wall)"

        data = b"".join(resp.iter_content(65536))
        if not data:
            return None, "Downloaded file is empty"
        return data, None

    except Exception as exc:
        return None, f"Download error: {_safe_reason(exc)}"


def build_failed_excel(
    failed_entries: list,
    headers: list,
    raw_rows: dict,
) -> bytes:
    """
    Build an Excel file containing only the failed rows.

    Columns = original input columns (from headers) + Failure_Reason (appended last).
    Each entry in failed_entries produces one row, preserving original cell values.
    """
    try:
        import openpyxl
    except ImportError:
        _log.error("openpyxl is required to build the failed-images Excel output")
        return b""

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Failed Images"

    n_headers = len(headers) if headers else 1
    ws.append(list(headers) + ["Failure_Reason"])

    for entry in failed_entries:
        raw = raw_rows.get(entry.style_code) if raw_rows else None
        row_vals = list(raw) if raw else []
        # Pad / trim to exactly n_headers columns so Failure_Reason lands in the right column
        while len(row_vals) < n_headers:
            row_vals.append(None)
        ws.append(row_vals[:n_headers] + [entry.reason])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Bulk processor ────────────────────────────────────────────────────────────

def run_batch(
    styles: dict[str, list[str]],
    cfg: BatchConfig,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    raw_rows: Optional[dict] = None,
    headers: Optional[list] = None,
) -> BatchResult:
    """
    Download and process all images from the styles dict.
    Returns a BatchResult with a ZIP archive in zip_bytes.

    progress_cb(done, total, current_style) — called after each style.
    raw_rows / headers — when provided, a failed_images.xlsx is generated in
    failed_excel_bytes containing failed rows with their original input columns
    plus a Failure_Reason column.
    """
    result         = BatchResult(total=len(styles))
    zip_buf        = io.BytesIO()
    _failed: list  = []   # list of _FailedEntry

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        done = 0
        for style_code, urls in styles.items():
            if progress_cb:
                progress_cb(done, result.total, style_code)

            style_success = 0
            for idx, url in enumerate(urls, start=1):
                try:
                    img_bytes, dl_reason = _download_with_reason(url, timeout=cfg.timeout)
                    if not img_bytes:
                        reason = dl_reason or "Download failed"
                        _log.warning("Failed to download %s (url #%d): %s — %s", style_code, idx, url, reason)
                        result.failed += 1
                        result.errors.append(f"{style_code} #{idx}: {reason}")
                        _failed.append(_FailedEntry(
                            style_code=style_code, url=url, url_index=idx,
                            reason=reason,
                            raw_row=raw_rows.get(style_code) if raw_rows else None,
                        ))
                        continue

                    try:
                        img = Image.open(io.BytesIO(img_bytes))
                        processed = convert_image(img, cfg)
                        jpeg_bytes = image_bytes_to_jpeg(processed, cfg.jpeg_quality)
                    except Exception as conv_exc:
                        reason = f"Invalid image content: {_safe_reason(conv_exc)}"
                        _log.warning("Error converting %s url #%d: %s", style_code, idx, conv_exc)
                        result.errors.append(f"{style_code} #{idx}: {conv_exc}")
                        result.failed += 1
                        _failed.append(_FailedEntry(
                            style_code=style_code, url=url, url_index=idx,
                            reason=reason,
                            raw_row=raw_rows.get(style_code) if raw_rows else None,
                        ))
                        continue

                    filename = f"{style_code}/{style_code}_{idx:02d}.jpg"
                    zf.writestr(filename, jpeg_bytes)
                    style_success += 1
                    result.success += 1

                except Exception as exc:
                    reason = _safe_reason(exc)
                    _log.warning("Error processing %s url #%d: %s", style_code, idx, exc)
                    result.errors.append(f"{style_code} #{idx}: {exc}")
                    result.failed += 1
                    _failed.append(_FailedEntry(
                        style_code=style_code, url=url, url_index=idx,
                        reason=reason,
                        raw_row=raw_rows.get(style_code) if raw_rows else None,
                    ))

            if style_success == 0:
                result.skipped += 1

            done += 1
            if progress_cb:
                progress_cb(done, result.total, style_code)

    zip_buf.seek(0)
    result.zip_bytes = zip_buf.getvalue()

    if _failed and raw_rows is not None:
        result.failed_excel_bytes = build_failed_excel(_failed, headers or [], raw_rows)

    return result
