"""
E-Commerce Product Image Processor  —  Engine + GUI Dashboard
==============================================================
Run:  python process_images.py
Requires: pip install -r requirements.txt
"""

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG  — edit only this section; the rest auto-follows
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_INPUT_EXCEL   = "input.xlsx"
DEFAULT_OUTPUT_FOLDER = "processed_images"
DEFAULT_TARGET_W      = 1080          # output width  (4 : 5 ratio)
DEFAULT_TARGET_H      = 1350          # output height (4 : 5 ratio)
DEFAULT_JPEG_QUALITY  = 92            # 1-95  (90+ for professional output)
DEFAULT_MAX_RETRIES   = 5             # retry downloads up to 5 times
DEFAULT_REQUEST_TIMEOUT = 15          # seconds
DEFAULT_USE_REMBG     = False         # True = better product detection (needs onnxruntime)
DEFAULT_BG_GREY       = 235           # 0=black … 255=white; 235 = light studio grey
DEFAULT_PACK_MODE     = False         # True = also build a pack-shot composite per style
DEFAULT_BG_RGB        = None          # None = use BG_GREY; tuple (R,G,B) = custom colour

RATIO_PRESETS = {
    "4:5  (1080×1350)":  (1080, 1350),
    "1:1  (1080×1080)":  (1080, 1080),
    "3:4  (1080×1440)":  (1080, 1440),
    "9:16 (1080×1920)":  (1080, 1920),
    "16:9 (1920×1080)":  (1920, 1080),
    "Custom":            None,
}

BG_PRESETS = {
    "Auto (keep original)": "auto",           # detect & match product's own bg
    "White (255)":          (255, 255, 255),
    "Studio Grey (235)":    (235, 235, 235),
    "Light Grey (210)":     (210, 210, 210),
    "Dark (50)":            (50,  50,  50),
    "Black (0)":            (0,   0,   0),
    "Custom …":             None,
}
# ══════════════════════════════════════════════════════════════════════════════

import os, re, csv, time, shutil, logging, hashlib, threading, queue, sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import numpy as np
import pandas as pd
from PIL import Image, ImageFilter

# ─── optional cv2 ──────────────────────────────────────────────────────────
_cv2_available = False
try:
    import cv2
    _cv2_available = True
except ImportError:
    pass

# ─── optional rembg ────────────────────────────────────────────────────────
_rembg_available = False
try:
    from rembg import remove as _rembg_remove
    _rembg_available = True
except ImportError:
    pass


# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING — dual handler: file + queue (GUI reads from queue)
# ══════════════════════════════════════════════════════════════════════════════
_log_queue: queue.Queue = queue.Queue()
_preview_queue: queue.Queue = queue.Queue()   # (before_pil, after_pil, before_score, after_score)

class _QueueHandler(logging.Handler):
    def emit(self, record):
        _log_queue.put(self.format(record))

_fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S")
_qh  = _QueueHandler(); _qh.setFormatter(_fmt)
_sh  = logging.StreamHandler(sys.stdout); _sh.setFormatter(_fmt)

log = logging.getLogger("imgproc")
log.setLevel(logging.INFO)
log.addHandler(_qh); log.addHandler(_sh)

# File log only when writable (skip on Streamlit Cloud)
try:
    _fh = logging.FileHandler("processing.log", encoding="utf-8"); _fh.setFormatter(_fmt)
    log.addHandler(_fh)
except (PermissionError, OSError):
    pass

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp"}


# ══════════════════════════════════════════════════════════════════════════════
#  1.  EXCEL READER
# ══════════════════════════════════════════════════════════════════════════════
def read_excel(path: str) -> dict:
    log.info(f"Reading Excel: {path}")
    df = pd.read_excel(path, header=0, dtype=str)
    df.fillna("", inplace=True)
    result = {}
    for _, row in df.iterrows():
        code = str(row.iloc[0]).strip()
        if not code or code.lower() == "nan":
            continue
        sources = [str(v).strip() for v in row.iloc[1:] if str(v).strip() and str(v).strip().lower() != "nan"]
        if sources:
            result.setdefault(code, []).extend(sources)
    log.info(f"Found {len(result)} unique style codes.")
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  2.  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def sanitize_folder_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r'\s+', "_", name)
    name = name.strip("._")
    return name or "UNNAMED"

def unique_filename(folder: Path, filename: str) -> Path:
    stem   = Path(filename).stem
    suffix = Path(filename).suffix or ".jpg"
    dest   = folder / f"{stem}{suffix}"
    n = 1
    while dest.exists():
        dest = folder / f"{stem}_{n}{suffix}"
        n += 1
    return dest

def guess_extension(url: str, ct: str = "") -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in SUPPORTED_EXT:
        return ext
    for mime, e in [("image/jpeg", ".jpg"), ("image/png", ".png"), ("image/webp", ".webp")]:
        if mime in ct.lower():
            return e
    return ".jpg"


# ══════════════════════════════════════════════════════════════════════════════
#  3.  DOWNLOAD / COPY
# ══════════════════════════════════════════════════════════════════════════════
_SESSION = requests.Session()
_SESSION.verify = True   # Zscaler cert is baked into the CA bundle
_SESSION.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
})

def _resolve_url(url: str) -> str:
    """Convert share-page URLs to direct download URLs."""
    # Google Drive: /file/d/<ID>/view  →  /uc?export=download&id=<ID>
    m = re.search(r'drive\.google\.com/file/d/([A-Za-z0-9_-]+)', url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    # Google Drive: open?id=<ID>
    m = re.search(r'drive\.google\.com/open\?id=([A-Za-z0-9_-]+)', url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    # Dropbox: dl=0  →  dl=1
    if 'dropbox.com' in url:
        return re.sub(r'[?&]dl=0', lambda x: x.group().replace('dl=0', 'dl=1'), url) \
               if 'dl=0' in url else url.rstrip('?') + ('&dl=1' if '?' in url else '?dl=1')
    # OneDrive share links: embed → download
    if '1drv.ms' in url or 'onedrive.live.com' in url:
        return url.replace('redir?', 'download?').replace('embed?', 'download?')
    return url

def download_image(url: str, dest_folder: Path, cfg: dict) -> Path | None:
    from urllib.parse import unquote
    direct_url = _resolve_url(url)
    for attempt in range(1, cfg["MAX_RETRIES"] + 1):
        try:
            resp = _SESSION.get(direct_url, timeout=cfg["REQUEST_TIMEOUT"], stream=True, allow_redirects=True)
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "")
            # If we got HTML instead of an image, the link is a viewer page — fail fast
            if "text/html" in ct:
                log.error(f"    ✗ got HTML page instead of image: {url}")
                return None
            ext      = guess_extension(direct_url, ct)
            raw_name = unquote(Path(urlparse(direct_url).path).name or hashlib.md5(url.encode()).hexdigest())
            raw_name = re.sub(r'[\\/:*?"<>|]', "_", raw_name)
            if not Path(raw_name).suffix:
                raw_name += ext
            dest = unique_filename(dest_folder, raw_name)
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            log.info(f"    ✓ downloaded → {dest.name}")
            return dest
        except Exception as exc:
            log.warning(f"    attempt {attempt}/{cfg['MAX_RETRIES']} failed: {exc}")
            if attempt < cfg["MAX_RETRIES"]:
                time.sleep(1.5 * attempt)
    log.error(f"    ✗ gave up: {url}")
    return None

def copy_local(src: str, dest_folder: Path) -> Path | None:
    import stat as _stat
    p = Path(src)
    if not p.exists():
        log.error(f"    ✗ file not found: {src}");  return None
    if p.suffix.lower() not in SUPPORTED_EXT:
        log.warning(f"    ✗ unsupported format: {src}");  return None
    dest = unique_filename(dest_folder, p.name)
    shutil.copy2(p, dest)
    # Strip read-only bit so we can delete the temp copy later
    try:
        dest.chmod(dest.stat().st_mode | _stat.S_IWRITE)
    except Exception:
        pass
    log.info(f"    ✓ copied → {dest.name}")
    return dest

def collect_image(source: str, dest_folder: Path, cfg: dict) -> Path | None:
    if source.startswith(("http://", "https://")):
        return download_image(source, dest_folder, cfg)
    return copy_local(source, dest_folder)


# ══════════════════════════════════════════════════════════════════════════════
#  4.  PRODUCT BOUNDING-BOX DETECTION
# ══════════════════════════════════════════════════════════════════════════════
def get_product_bbox(img: Image.Image, use_rembg: bool) -> tuple:
    if use_rembg and _rembg_available:
        return _bbox_rembg(img)
    return _bbox_opencv(img)

def _bbox_rembg(img: Image.Image) -> tuple:
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
    except Exception as e:
        log.warning(f"rembg failed ({e}), falling back to OpenCV.")
        return _bbox_opencv(img)

def _bbox_opencv(img: Image.Image) -> tuple:
    if not _cv2_available:
        # cv2 not available — return full image as bbox
        w, h = img.size
        return (0, 0, w, h)
    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).astype(np.float32)
    b = max(5, min(20, h // 30, w // 30))

    strips = np.concatenate([
        lab[:b, :].reshape(-1, 3),  lab[h-b:, :].reshape(-1, 3),
        lab[:, :b].reshape(-1, 3),  lab[:, w-b:].reshape(-1, 3),
    ])
    bg_color = np.median(strips, axis=0)
    diff     = np.linalg.norm(lab - bg_color, axis=2)
    thresh   = float(np.clip(np.mean(diff) + 1.5 * np.std(diff), 8.0, 35.0))
    mask     = (diff > thresh).astype(np.uint8) * 255

    k    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)

    coords = cv2.findNonZero(mask)
    if coords is None or len(coords) < 100:
        return (0, 0, w, h)
    x, y, bw, bh = cv2.boundingRect(coords)
    if bw * bh < 0.10 * w * h:
        return (0, 0, w, h)

    pad = max(10, int(min(w, h) * 0.02))
    return (max(0, x-pad), max(0, y-pad), min(w, x+bw+pad), min(h, y+bh+pad))


# ══════════════════════════════════════════════════════════════════════════════
#  5.  BACKGROUND — solid-colour detection + natural extension + dual-BG fix
# ══════════════════════════════════════════════════════════════════════════════
_BG_SOLID_TOL    = 18
_BG_SAMPLE_DEPTH = 30

def is_solid_background(img: Image.Image) -> tuple:
    rgb = np.array(img.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    d = _BG_SAMPLE_DEPTH
    corner_size = min(d, h // 4, w // 4)
    corners = np.concatenate([
        rgb[:corner_size, :corner_size].reshape(-1, 3),
        rgb[:corner_size, w-corner_size:].reshape(-1, 3),
        rgb[h-corner_size:, :corner_size].reshape(-1, 3),
        rgb[h-corner_size:, w-corner_size:].reshape(-1, 3),
    ])
    bg_color = np.median(corners, axis=0)
    strips = np.concatenate([
        rgb[:d, :].reshape(-1, 3), rgb[h-d:, :].reshape(-1, 3),
        rgb[:, :d].reshape(-1, 3), rgb[:, w-d:].reshape(-1, 3),
    ])
    diffs = np.linalg.norm(strips - bg_color, axis=1)
    solid = float(np.percentile(diffs, 90)) < _BG_SOLID_TOL
    return solid, tuple(int(c) for c in bg_color)

def compute_quality_score(img: Image.Image, target_w: int = 0, target_h: int = 0) -> int:
    """Return 0-100 quality score for an image (before or after processing)."""
    w, h = img.size
    # Ratio match vs 4:5
    actual = w / h
    target = (target_w / target_h) if (target_w and target_h) else (4 / 5)
    ratio_score = max(0, 100 - abs(actual - target) / target * 150)
    # Background uniformity
    solid, _ = is_solid_background(img)
    bg_score = 90 if solid else 35
    # Product margin — check that product doesn't fill edge-to-edge
    try:
        bbox = get_product_bbox(img, False)
        pl, pt, pr, pb = bbox
        margin_l = pl / w;  margin_r = (w - pr) / w
        margin_t = pt / h;  margin_b = (h - pb) / h
        min_margin = min(margin_l, margin_r, margin_t, margin_b)
        margin_score = min(100, min_margin * 800)   # 12.5% margin → 100
    except Exception:
        margin_score = 50
    return int(ratio_score * 0.40 + bg_score * 0.35 + margin_score * 0.25)


def replace_mixed_background(img: Image.Image, cfg: dict) -> Image.Image:
    """If the image has a non-uniform (dual/gradient) background, composite
    the product onto a clean solid canvas. No-op when background is solid."""
    solid, bg_detected = is_solid_background(img)
    if solid:
        return img

    # Extra check: compare top-half vs bottom-half background colour.
    # If they differ significantly this is a dual-background image.
    arr_check = np.array(img.convert("RGB"), dtype=np.float32)
    h2 = arr_check.shape[0] // 2
    top_med = np.median(arr_check[:h2, :10].reshape(-1, 3), axis=0)
    bot_med = np.median(arr_check[h2:, :10].reshape(-1, 3), axis=0)
    if np.linalg.norm(top_med - bot_med) < 15:
        # Backgrounds are similar — not a true dual-bg, skip expensive op
        return img

    bg_val = cfg.get("BG_GREY", DEFAULT_BG_GREY)
    bg_rgb = (bg_val, bg_val, bg_val)

    if not _cv2_available:
        return img  # skip background replacement if cv2 not available

    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    lab  = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).astype(np.float32)
    d    = _BG_SAMPLE_DEPTH

    # Sample all four edges to get a per-region bg estimate, then build a mask
    strips = np.concatenate([
        lab[:d, :].reshape(-1, 3), lab[h-d:, :].reshape(-1, 3),
        lab[:, :d].reshape(-1, 3), lab[:, w-d:].reshape(-1, 3),
    ])
    bg_lab   = np.median(strips, axis=0)
    diff     = np.linalg.norm(lab - bg_lab, axis=2)
    thresh   = float(np.clip(np.mean(diff) + 1.2 * np.std(diff), 8.0, 40.0))
    mask     = (diff > thresh).astype(np.uint8) * 255          # 255 = product

    k    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)

    # Feather the mask edge for a smooth composite
    mask_f = cv2.GaussianBlur(mask.astype(np.float32), (7, 7), 0) / 255.0

    bg_canvas = np.full_like(arr, bg_rgb, dtype=np.float32)
    fg        = arr.astype(np.float32)
    alpha     = mask_f[:, :, np.newaxis]
    composite = (fg * alpha + bg_canvas * (1 - alpha)).clip(0, 255).astype(np.uint8)

    log.info("  ⚑ dual/mixed background detected — replaced with solid grey.")
    return Image.fromarray(composite)

def extend_canvas_naturally(img: Image.Image, new_w: int, new_h: int,
                             paste_x: int, paste_y: int, cfg: dict = None) -> Image.Image:
    """Fill extended canvas with the image's background colour (or configured grey
    if the background is mixed/non-solid)."""
    solid, bg_rgb = is_solid_background(img)
    if not solid and cfg is not None:
        v = cfg.get("BG_GREY", DEFAULT_BG_GREY)
        bg_rgb = (v, v, v)
    canvas = Image.new("RGB", (new_w, new_h), bg_rgb)
    canvas.paste(img, (paste_x, paste_y))
    return canvas


# ══════════════════════════════════════════════════════════════════════════════
#  5b.  GRID-LINE REMOVAL  — erase cell borders in composite pack images
# ══════════════════════════════════════════════════════════════════════════════
def remove_grid_lines(img: Image.Image) -> Image.Image:
    """Remove supplier grid/cell-border lines using margin-only detection.
    Only fires when clear margins exist around the product (safe guard)."""
    arr  = np.array(img.convert("RGB")).astype(np.float32)
    h, w = arr.shape[:2]

    # ── background from corners ───────────────────────────────────────────────
    cs = max(8, min(25, h // 8, w // 8))
    corners = np.concatenate([
        arr[:cs, :cs].reshape(-1,3), arr[:cs, -cs:].reshape(-1,3),
        arr[-cs:,:cs].reshape(-1,3), arr[-cs:,-cs:].reshape(-1,3),
    ])
    bg = np.median(corners, axis=0)

    # ── product bounding box ──────────────────────────────────────────────────
    product_mask = np.linalg.norm(arr - bg, axis=2) > 22
    rows_p = np.any(product_mask, axis=1)
    cols_p = np.any(product_mask, axis=0)
    if not rows_p.any():
        return img

    top    = int(np.argmax(rows_p))
    bottom = int(h - np.argmax(rows_p[::-1]) - 1)
    left   = int(np.argmax(cols_p))
    right  = int(w - np.argmax(cols_p[::-1]) - 1)

    # Safety guard: need at least 5% margin on each side to safely detect lines
    min_margin = int(min(h, w) * 0.05)
    has_top_margin    = top    >= min_margin
    has_bottom_margin = (h - 1 - bottom) >= min_margin
    has_left_margin   = left   >= min_margin
    has_right_margin  = (w - 1 - right)  >= min_margin

    # If product fills the frame with no margins, nothing to detect
    if not any([has_top_margin, has_bottom_margin, has_left_margin, has_right_margin]):
        return img

    result  = arr.copy()
    changed = False

    def _col_is_line_in_margins(x: int) -> bool:
        """Check if column x looks like a border line in the available margins."""
        samples = []
        if has_top_margin:
            samples.append(arr[:top, x])
        if has_bottom_margin:
            samples.append(arr[bottom+1:, x])
        if not samples:
            return False
        strip = np.concatenate(samples, axis=0)
        if strip.shape[0] < 3:
            return False
        diff = np.linalg.norm(strip - bg, axis=1)
        # bg-coloured gap
        if (diff < 30).mean() > 0.85:
            return True
        # solid dark/coloured rule (low variance, not bg)
        if strip.var() < 400 and diff.mean() > 20:
            return True
        return False

    def _row_is_line_in_margins(y: int) -> bool:
        """Check if row y looks like a border line in the available margins."""
        samples = []
        if has_left_margin:
            samples.append(arr[y, :left])
        if has_right_margin:
            samples.append(arr[y, right+1:])
        if not samples:
            return False
        strip = np.concatenate(samples, axis=0)
        if strip.shape[0] < 3:
            return False
        diff = np.linalg.norm(strip - bg, axis=1)
        if (diff < 30).mean() > 0.85:
            return True
        if strip.var() < 400 and diff.mean() > 20:
            return True
        return False

    # ── vertical lines ────────────────────────────────────────────────────────
    x = 0
    while x < w:
        if _col_is_line_in_margins(x):
            x_end = x + 1
            while x_end < w and x_end - x < 8 and _col_is_line_in_margins(x_end):
                x_end += 1
            result[:, x:x_end] = bg
            changed = True
            x = x_end
        else:
            x += 1

    # ── horizontal lines ──────────────────────────────────────────────────────
    y = 0
    while y < h:
        if _row_is_line_in_margins(y):
            y_end = y + 1
            while y_end < h and y_end - y < 8 and _row_is_line_in_margins(y_end):
                y_end += 1
            result[y:y_end, :] = bg
            changed = True
            y = y_end
        else:
            y += 1

    if changed:
        log.info("  ✂ grid/border lines removed.")
    return Image.fromarray(result.astype(np.uint8))


# ══════════════════════════════════════════════════════════════════════════════
#  6.  MAIN CONVERSION  (smart-crop first, extend if needed)
# ══════════════════════════════════════════════════════════════════════════════
def convert_to_4_5(img: Image.Image, cfg: dict) -> Image.Image:
    TW, TH = cfg["TARGET_W"], cfg["TARGET_H"]
    auto_mode = cfg.get("BG_RGB") == "auto"

    # Convert to RGB early, drop alpha channel (saves memory)
    img = img.convert("RGB")

    # Cap input size: if source is much larger than target, pre-downscale fast
    # with BOX filter first. This cuts LANCZOS work on huge originals (e.g. 6000×8000px)
    MAX_SIDE = max(TW, TH) * 3  # anything more than 3× target is wasteful
    orig_w, orig_h = img.size
    if orig_w > MAX_SIDE or orig_h > MAX_SIDE:
        pre_scale = MAX_SIDE / max(orig_w, orig_h)
        pre_w = max(1, int(orig_w * pre_scale))
        pre_h = max(1, int(orig_h * pre_scale))
        img = img.resize((pre_w, pre_h), Image.BOX)

    # Only replace mixed backgrounds when a specific bg colour is chosen
    if not auto_mode:
        img = replace_mixed_background(img, cfg)

    orig_w, orig_h = img.size

    MARGIN = 0.04  # breathing room on every edge

    # Fit the full image inside canvas — never crop any edge
    scale = min(
        TW * (1 - 2 * MARGIN) / orig_w,
        TH * (1 - 2 * MARGIN) / orig_h,
        2.0
    )

    nw = max(1, int(orig_w * scale))
    nh = max(1, int(orig_h * scale))
    scaled = img.resize((nw, nh), Image.LANCZOS)

    # Centre on canvas
    px = (TW - nw) // 2
    py = (TH - nh) // 2

    sa = np.array(scaled, dtype=np.uint8)   # nh × nw × 3

    # Build canvas by extending edge pixels outward in all directions.
    # This eliminates any visible rectangle on gradient/studio backgrounds
    # regardless of source aspect ratio.
    canvas_arr = np.empty((TH, TW, 3), dtype=np.uint8)

    # Place scaled image in its position
    canvas_arr[py:py+nh, px:px+nw] = sa

    # Top strip — repeat top row of image
    if py > 0:
        canvas_arr[0:py, px:px+nw] = np.repeat(sa[0:1, :, :], py, axis=0)

    # Bottom strip — repeat bottom row
    bh = TH - py - nh
    if bh > 0:
        canvas_arr[py+nh:TH, px:px+nw] = np.repeat(sa[-1:, :, :], bh, axis=0)

    # Left strip — repeat left column
    if px > 0:
        canvas_arr[py:py+nh, 0:px] = np.repeat(sa[:, 0:1, :], px, axis=1)

    # Right strip — repeat right column
    rw = TW - px - nw
    if rw > 0:
        canvas_arr[py:py+nh, px+nw:TW] = np.repeat(sa[:, -1:, :], rw, axis=1)

    # Corners — fill with the nearest image corner pixel
    tl = sa[0, 0]
    tr = sa[0, -1]
    bl = sa[-1, 0]
    br = sa[-1, -1]
    if py > 0 and px > 0:
        canvas_arr[0:py, 0:px] = tl
    if py > 0 and rw > 0:
        canvas_arr[0:py, px+nw:TW] = tr
    if bh > 0 and px > 0:
        canvas_arr[py+nh:TH, 0:px] = bl
    if bh > 0 and rw > 0:
        canvas_arr[py+nh:TH, px+nw:TW] = br

    return Image.fromarray(canvas_arr)


# ══════════════════════════════════════════════════════════════════════════════
#  7.  RATIO GUARD + SAVE
# ══════════════════════════════════════════════════════════════════════════════
def verify_ratio(img: Image.Image, cfg: dict) -> bool:
    """Return True only if the image is EXACTLY the target resolution."""
    return img.size == (cfg["TARGET_W"], cfg["TARGET_H"])

def save_image(processed: Image.Image, dest: Path, quality: int) -> bool:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # subsampling=0 keeps full chroma resolution (4:4:4) — best quality at any quality level
        processed.convert("RGB").save(dest, "JPEG", quality=quality,
                                      optimize=True, subsampling=0)
        return True
    except Exception as e:
        log.error(f"    ✗ save failed {dest}: {e}")
        try: dest.unlink(missing_ok=True)
        except Exception: pass
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  7b.  PACK COMPOSITOR  — combine multiple product images into one canvas
# ══════════════════════════════════════════════════════════════════════════════
def _bg_from_cfg(cfg: dict, detected_bg: tuple = None) -> tuple:
    """Return (R,G,B) background tuple from cfg.
    When BG_RGB is 'auto', returns detected_bg (from the image) if available."""
    rgb = cfg.get("BG_RGB")
    if rgb == "auto":
        return detected_bg if detected_bg else (255, 255, 255)
    if rgb and isinstance(rgb, (list, tuple)) and len(rgb) == 3:
        return tuple(int(c) for c in rgb)
    v = cfg.get("BG_GREY", DEFAULT_BG_GREY)
    return (v, v, v)

def build_pack_image(pil_images: list, cfg: dict) -> Image.Image:
    """Composite multiple cropped products onto one target canvas — no borders."""
    TW, TH = cfg["TARGET_W"], cfg["TARGET_H"]
    bg_rgb  = _bg_from_cfg(cfg)
    n = len(pil_images)
    if n == 0:
        return None

    # ── optimal grid ─────────────────────────────────────────────────────────
    if   n == 1: cols, rows = 1, 1
    elif n == 2: cols, rows = 2, 1
    elif n == 3: cols, rows = 3, 1
    elif n == 4: cols, rows = 2, 2
    elif n <= 6: cols, rows = 3, 2
    else:
        cols = min(4, n)
        rows = (n + cols - 1) // cols

    OUTER = int(min(TW, TH) * 0.04)   # 4 % outer margin
    GAP   = int(min(TW, TH) * 0.015)  # 1.5 % gap between cells (no border!)
    cell_w = (TW - 2 * OUTER - (cols - 1) * GAP) // cols
    cell_h = (TH - 2 * OUTER - (rows - 1) * GAP) // rows

    canvas = Image.new("RGB", (TW, TH), bg_rgb)

    for i, img in enumerate(pil_images[:cols * rows]):
        col_i = i % cols
        row_i = i // cols

        # clean background then tight-crop to product
        img = replace_mixed_background(img, cfg)
        pl, pt, pr, pb = get_product_bbox(img, cfg["USE_REMBG"])
        cropped = img.crop((pl, pt, pr, pb))

        # scale to fill cell (5 % inner breathing room)
        inner = int(min(cell_w, cell_h) * 0.05)
        scale = min((cell_w - 2 * inner) / cropped.width,
                    (cell_h - 2 * inner) / cropped.height)
        nw = int(cropped.width  * scale)
        nh = int(cropped.height * scale)
        scaled = cropped.resize((nw, nh), Image.LANCZOS)

        # centre inside cell
        cx = OUTER + col_i * (cell_w + GAP) + (cell_w - nw) // 2
        cy = OUTER + row_i * (cell_h + GAP) + (cell_h - nh) // 2
        canvas.paste(scaled, (cx, cy))

    return canvas


# ══════════════════════════════════════════════════════════════════════════════
#  8.  ORCHESTRATOR (parallel workers — download + process simultaneously)
# ══════════════════════════════════════════════════════════════════════════════
import os as _os
_WORKERS = 2   # 2 threads — good balance of speed and memory on Railway 8GB

def _process_one(args):
    """Process a single image: download → convert → force exact size → save.
    Never skips a successfully downloaded image — always produces output."""
    source, folder, cfg, idx, total_src = args
    result = dict(source=source, status="", output_path="",
                  is_success=False, is_failed_dl=False, is_skipped=False)

    log.info(f"  [{idx}/{total_src}] {source[:90]}")

    raw = collect_image(source, folder, cfg)
    if raw is None:
        result.update(status="FAILED_DOWNLOAD", is_failed_dl=True)
        return result

    def _safe_unlink(p):
        try: p.unlink(missing_ok=True)
        except Exception: pass

    # ── Open image ────────────────────────────────────────────────────────────
    try:
        with Image.open(raw) as im:
            im.load()
            img_copy = im.convert("RGB")
    except Exception as e:
        log.error(f"  ✗ open error {raw.name}: {e}")
        _safe_unlink(raw)
        result.update(status=f"FAILED_OPEN: {e}", is_failed_dl=True)
        return result

    _safe_unlink(raw)   # free disk space immediately after loading

    # ── Convert ───────────────────────────────────────────────────────────────
    TW, TH = cfg["TARGET_W"], cfg["TARGET_H"]
    try:
        processed = convert_to_4_5(img_copy, cfg)
    except Exception as e:
        log.warning(f"  ⚠ convert error ({e}) — falling back to simple fit")
        # Fallback: simple letterbox resize, always produces valid output
        try:
            img_rgb = img_copy.convert("RGB")
            img_rgb.thumbnail((TW, TH), Image.LANCZOS)
            canvas = Image.new("RGB", (TW, TH), (235, 235, 235))
            ox = (TW - img_rgb.width)  // 2
            oy = (TH - img_rgb.height) // 2
            canvas.paste(img_rgb, (ox, oy))
            processed = canvas
        except Exception as e2:
            log.error(f"  ✗ fallback also failed: {e2}")
            result.update(status=f"FAILED_CONVERT: {e2}", is_skipped=True)
            return result

    # ── Force EXACT target size — fix any 1-2px rounding from int arithmetic ─
    if processed.size != (TW, TH):
        processed = processed.resize((TW, TH), Image.LANCZOS)

    # ── Preview thumbnails ────────────────────────────────────────────────────
    try:
        before_score = compute_quality_score(img_copy, TW, TH)
        after_score  = compute_quality_score(processed, TW, TH)
        src_fmt = (Path(source).suffix.lstrip(".").upper()
                   if not source.startswith("http") else "URL")
        thumb_before = img_copy.copy();  thumb_before.thumbnail((400, 600))
        thumb_after  = processed.copy(); thumb_after.thumbnail((400, 600))
        _preview_queue.put_nowait((thumb_before, thumb_after,
                                   before_score, after_score, src_fmt))
    except Exception:
        pass

    # ── Save ──────────────────────────────────────────────────────────────────
    out_path = unique_filename(folder, Path(source).stem + ".jpg")
    del img_copy  # free memory before saving

    if not save_image(processed, out_path, cfg["JPEG_QUALITY"]):
        # Retry once with reduced quality before giving up
        if not save_image(processed, out_path, max(70, cfg["JPEG_QUALITY"] - 10)):
            result.update(status="FAILED_SAVE", is_skipped=True)
            return result

    del processed  # free memory

    log.info(f"  ✓ {out_path.name}  [{TW}×{TH}]")
    result.update(status="OK", output_path=str(out_path), is_success=True)
    return result


def process_all(cfg: dict,
                progress_cb=None,
                stop_event=None):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out_root = Path(cfg["OUTPUT_FOLDER"])
    out_root.mkdir(parents=True, exist_ok=True)

    total = success = failed_dl = skipped = 0
    folders_created = []
    report_rows     = []

    style_map    = read_excel(cfg["INPUT_EXCEL"])
    total_images = sum(len(v) for v in style_map.values())
    done         = 0

    log.info(f"Starting with {_WORKERS} parallel workers for {total_images} images.")

    for style_code, sources in style_map.items():
        if stop_event and stop_event.is_set():
            log.info("⛔ Processing stopped by user.")
            break

        safe   = sanitize_folder_name(style_code)
        folder = out_root / safe
        folder.mkdir(parents=True, exist_ok=True)
        if str(folder) not in folders_created:
            folders_created.append(str(folder))
        log.info(f"\n── Style: {style_code}  →  {folder}")

        # Build task list for this style code
        tasks = [
            (src, folder, cfg, i + 1, len(sources))
            for i, src in enumerate(sources)
        ]
        total += len(tasks)

        pack_pil_images = []   # collect originals when pack mode is on

        with ThreadPoolExecutor(max_workers=min(_WORKERS, len(tasks))) as pool:
            futures = {pool.submit(_process_one, t): t for t in tasks}
            for fut in as_completed(futures):
                if stop_event and stop_event.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                res = fut.result()
                src = futures[fut][0]
                report_rows.append(dict(style_code=style_code, source=src,
                                        status=res["status"],
                                        output_path=res["output_path"]))
                if res["is_success"]:
                    success += 1
                    if cfg.get("PACK_MODE") and res["output_path"]:
                        try:
                            with Image.open(res["output_path"]) as im:
                                pack_pil_images.append(im.copy())
                        except Exception:
                            pass
                elif res["is_failed_dl"]: failed_dl += 1
                else:                     skipped  += 1
                done += 1
                if progress_cb: progress_cb(done, total_images)

        # ── pack composite (optional) ─────────────────────────────────────────
        if cfg.get("PACK_MODE") and len(pack_pil_images) > 1:
            try:
                composite = build_pack_image(pack_pil_images, cfg)
                if composite:
                    pack_path = unique_filename(folder, "PACK.jpg")
                    if save_image(composite, pack_path, cfg["JPEG_QUALITY"]):
                        log.info(f"  📦 Pack shot → {pack_path.name}  "
                                 f"[{cfg['TARGET_W']}×{cfg['TARGET_H']}]")
            except Exception as e:
                log.error(f"  ✗ Pack composite failed: {e}")

    # Write CSV report
    rp = out_root / "summary_report.csv"
    with open(rp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["style_code","source","status","output_path"])
        w.writeheader(); w.writerows(report_rows)

    summary = (
        f"\n{'═'*55}\n"
        f"  DONE — Total attempted : {total}\n"
        f"         Successfully processed : {success}\n"
        f"         Failed downloads       : {failed_dl}\n"
        f"         Skipped (errors)       : {skipped}\n"
        f"         Style folders          : {len(folders_created)}\n"
        f"         Report → {rp}\n"
        f"{'═'*55}"
    )
    log.info(summary)
    return dict(total=total, success=success, failed=failed_dl, skipped=skipped,
                folders=len(folders_created), report=str(rp))


# ══════════════════════════════════════════════════════════════════════════════
#  9.  GUI  DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
def launch_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import webbrowser

    # ── colours & fonts ───────────────────────────────────────────────────────
    BG     = "#0f0f0f"
    CARD   = "#1e1e1e"
    CARD2  = "#2a2a2a"
    ACCENT = "#ff6b00"
    GREEN  = "#00c875"
    RED    = "#ff4444"
    YELLOW = "#ffc107"
    ORANGE2= "#ff9900"
    FG     = "#f0f0f0"
    FG2    = "#999999"
    F      = ("Segoe UI", 10)
    FB     = ("Segoe UI", 10, "bold")
    MONO   = ("Consolas", 9)

    root = tk.Tk()
    root.title("Psydox — Dashboard")
    root.configure(bg=BG)
    root.geometry("1100x820")
    root.minsize(950, 720)

    # ── shared vars ───────────────────────────────────────────────────────────
    v_excel   = tk.StringVar(value=DEFAULT_INPUT_EXCEL)
    v_out     = tk.StringVar(value=DEFAULT_OUTPUT_FOLDER)
    v_w       = tk.IntVar(value=DEFAULT_TARGET_W)
    v_h       = tk.IntVar(value=DEFAULT_TARGET_H)
    v_qual    = tk.IntVar(value=DEFAULT_JPEG_QUALITY)
    v_retry   = tk.IntVar(value=DEFAULT_MAX_RETRIES)
    v_timeout = tk.IntVar(value=DEFAULT_REQUEST_TIMEOUT)
    v_rembg     = tk.BooleanVar(value=DEFAULT_USE_REMBG)
    v_bg_grey   = tk.IntVar(value=DEFAULT_BG_GREY)
    v_pack_mode = tk.BooleanVar(value=DEFAULT_PACK_MODE)
    v_ratio     = tk.StringVar(value="4:5  (1080×1350)")
    v_bg_preset = tk.StringVar(value="Auto (keep original)")
    v_bg_custom = {"rgb": None}   # mutable store for custom colour tuple
    v_prog      = tk.DoubleVar(value=0.0)
    v_stats     = {k: tk.StringVar(value="—") for k in ["total","success","failed","skipped","folders"]}

    _running    = threading.Event()
    _stop_event = threading.Event()

    def get_cfg():
        # background
        preset_rgb = BG_PRESETS.get(v_bg_preset.get())
        if preset_rgb == "auto":     # Auto — detect from image at process time
            bg_rgb = "auto"
        elif preset_rgb is None:     # "Custom …"
            bg_rgb = v_bg_custom["rgb"]
        else:
            bg_rgb = preset_rgb
        grey = int(sum(bg_rgb) / 3) if isinstance(bg_rgb, tuple) else DEFAULT_BG_GREY
        return dict(
            INPUT_EXCEL=v_excel.get(), OUTPUT_FOLDER=v_out.get(),
            TARGET_W=v_w.get(), TARGET_H=v_h.get(),
            JPEG_QUALITY=v_qual.get(), MAX_RETRIES=v_retry.get(),
            REQUEST_TIMEOUT=v_timeout.get(), USE_REMBG=v_rembg.get(),
            BG_GREY=grey, BG_RGB=bg_rgb,
            PACK_MODE=v_pack_mode.get(),
        )

    # ── helpers ───────────────────────────────────────────────────────────────
    def label(parent, text, color=None, font=None, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"],
                        fg=color or FG2, font=font or F, **kw)

    def section(parent, title):
        """Orange-accented section header + inner frame."""
        outer = tk.Frame(parent, bg=CARD)
        outer.pack(fill="x", padx=0, pady=(0, 6))
        hdr = tk.Frame(outer, bg=CARD)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=ACCENT, width=4).pack(side="left", fill="y")
        tk.Label(hdr, text=f"  {title}", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left",
                 fill="x", pady=6)
        tk.Frame(outer, bg="#333333", height=1).pack(fill="x")
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="x", padx=8, pady=6)
        return inner

    def field_row(parent, lbl_text, widget):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=lbl_text, bg=CARD, fg=FG2, font=F,
                 width=16, anchor="w").pack(side="left")
        widget(row).pack(side="left", fill="x", expand=True)

    def entry_w(parent, var):
        return tk.Entry(parent, textvariable=var, bg=CARD2, fg=FG,
                        insertbackground=FG, relief="flat", font=F)

    def spin_w(parent, var, lo, hi):
        return tk.Spinbox(parent, textvariable=var, from_=lo, to=hi,
                          bg=CARD2, fg=FG, buttonbackground=CARD,
                          relief="flat", font=F, width=9)

    # ══════════════════════════════════════════════════════════════════════════
    #  TOP NAV BAR
    # ══════════════════════════════════════════════════════════════════════════
    nav = tk.Frame(root, bg=ACCENT, height=50)
    nav.pack(fill="x", side="top")
    nav.pack_propagate(False)
    tk.Label(nav, text="  ⚡  Psydox",
             bg=ACCENT, fg="white", font=("Segoe UI", 15, "bold")).pack(side="left", padx=10)
    tk.Label(nav, text="Image Processing Engine",
             bg=ACCENT, fg="#ffe0c0", font=("Segoe UI", 9)).pack(side="left", padx=(0,20))
    tk.Button(nav, text="📖 Docs", bg="#cc5500", fg="white", relief="flat",
              font=F, cursor="hand2", padx=10,
              command=lambda: webbrowser.open("https://pillow.readthedocs.io")
              ).pack(side="right", padx=10, pady=8)

    # ══════════════════════════════════════════════════════════════════════════
    #  FIXED BOTTOM BAR  (RUN · STOP · progress — always visible)
    # ══════════════════════════════════════════════════════════════════════════
    bot = tk.Frame(root, bg="#0a0a0a", height=115)
    bot.pack(fill="x", side="bottom")
    bot.pack_propagate(False)

    prog_lbl = tk.Label(bot, text="Ready — browse for your Excel file, then click ▶ RUN",
                        bg="#0a0a0a", fg=FG2, font=("Segoe UI", 9), anchor="w")
    prog_lbl.pack(fill="x", padx=16, pady=(10, 2))

    sty = ttk.Style()
    sty.theme_use("clam")
    sty.configure("OPB.Horizontal.TProgressbar",
                  troughcolor="#222", background=ACCENT,
                  bordercolor="#222", lightcolor=ACCENT, darkcolor=ACCENT)
    ttk.Progressbar(bot, variable=v_prog, maximum=100,
                    style="OPB.Horizontal.TProgressbar").pack(fill="x", padx=16, pady=(0, 8))

    brow = tk.Frame(bot, bg="#0a0a0a")
    brow.pack(fill="x", padx=16, pady=(0, 10))

    run_btn = tk.Button(brow, text="▶   RUN", bg=GREEN, fg="#000",
                        font=("Segoe UI", 13, "bold"), relief="flat",
                        cursor="hand2", height=2, bd=0, activebackground="#00a85a")
    run_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

    stop_btn = tk.Button(brow, text="⬛  STOP", bg=RED, fg="white",
                         font=("Segoe UI", 13, "bold"), relief="flat",
                         cursor="hand2", height=2, bd=0, state="disabled",
                         activebackground="#cc2222")
    stop_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

    def open_output_folder():
        p = Path(v_out.get()); p.mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))
    tk.Button(brow, text="📁  Open Output Folder", bg=CARD, fg=FG,
              font=("Segoe UI", 11, "bold"), relief="flat", cursor="hand2",
              height=2, bd=0, activebackground="#333",
              command=open_output_folder).pack(side="left", fill="x", expand=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  MAIN BODY  (left settings | right log)
    # ══════════════════════════════════════════════════════════════════════════
    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True)

    # ── LEFT PANEL ────────────────────────────────────────────────────────────
    left = tk.Frame(body, bg=BG, width=420)
    left.pack(side="left", fill="y", padx=(12, 6), pady=10)
    left.pack_propagate(False)

    # §1  File Paths — compact button-only UI
    s1 = section(left, "📂  File Paths")

    def _browse_excel():
        p = filedialog.askopenfilename(title="Select Excel file",
                                       filetypes=[("Excel","*.xlsx *.xls")])
        if p:
            v_excel.set(p)
            excel_name_lbl.config(text=f"📄  {Path(p).name}", fg=GREEN)

    def _browse_out():
        p = filedialog.askdirectory(title="Select download / output folder")
        if p:
            v_out.set(p)
            out_name_lbl.config(text=f"📁  {Path(p).name}", fg=GREEN)

    fp_row1 = tk.Frame(s1, bg=CARD); fp_row1.pack(fill="x", pady=(2, 4))
    tk.Button(fp_row1, text="📄  Select Excel File", bg=ACCENT, fg="white",
              font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2",
              padx=10, pady=6, command=_browse_excel).pack(side="left", fill="x", expand=True)
    excel_name_lbl = tk.Label(fp_row1, text="No file selected", bg=CARD,
                              fg=FG2, font=("Segoe UI", 9), anchor="w")
    excel_name_lbl.pack(side="left", padx=(8, 0), fill="x", expand=True)
    # Pre-fill label if default exists
    if Path(v_excel.get()).exists():
        excel_name_lbl.config(text=f"📄  {Path(v_excel.get()).name}", fg=GREEN)

    fp_row2 = tk.Frame(s1, bg=CARD); fp_row2.pack(fill="x", pady=(0, 2))
    tk.Button(fp_row2, text="📁  Select Download Folder", bg="#444444", fg="white",
              font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2",
              padx=10, pady=6, command=_browse_out).pack(side="left", fill="x", expand=True)
    out_name_lbl = tk.Label(fp_row2, text="No folder selected", bg=CARD,
                            fg=FG2, font=("Segoe UI", 9), anchor="w")
    out_name_lbl.pack(side="left", padx=(8, 0), fill="x", expand=True)
    if Path(v_out.get()).exists():
        out_name_lbl.config(text=f"📁  {Path(v_out.get()).name}", fg=GREEN)

    # §2  Image Settings
    s2 = section(left, "🖼️  Image Settings")

    # ── Ratio presets ─────────────────────────────────────────────────────────
    ratio_row = tk.Frame(s2, bg=CARD); ratio_row.pack(fill="x", pady=2)
    tk.Label(ratio_row, text="Ratio Preset", bg=CARD, fg=FG2, font=F,
             width=16, anchor="w").pack(side="left")
    ratio_menu = tk.OptionMenu(ratio_row, v_ratio, *RATIO_PRESETS.keys())
    ratio_menu.config(bg=CARD2, fg=FG, activebackground=ACCENT,
                      activeforeground="white", relief="flat", font=F,
                      highlightthickness=0, bd=0)
    ratio_menu["menu"].config(bg=CARD2, fg=FG, activebackground=ACCENT,
                               activeforeground="white", font=F)
    ratio_menu.pack(side="left", fill="x", expand=True)

    def _on_ratio_change(*_):
        wh = RATIO_PRESETS.get(v_ratio.get())
        if wh:
            v_w.set(wh[0]); v_h.set(wh[1])
    v_ratio.trace_add("write", _on_ratio_change)

    field_row(s2, "Width  (px)",   lambda p: spin_w(p, v_w,    360, 4320))
    field_row(s2, "Height (px)",   lambda p: spin_w(p, v_h,    450, 5400))
    field_row(s2, "JPEG Quality",  lambda p: spin_w(p, v_qual,  50,   95))

    # §3  Network
    s3 = section(left, "🌐  Network Settings")
    field_row(s3, "Max Retries",   lambda p: spin_w(p, v_retry,   1,  10))
    field_row(s3, "Timeout  (s)",  lambda p: spin_w(p, v_timeout, 5, 120))

    # §4  Advanced
    s4 = section(left, "⚙️  Advanced")

    # ── Background colour picker — visual swatch grid ────────────────────────
    tk.Label(s4, text="Background Color", bg=CARD, fg=FG2, font=F,
             anchor="w").pack(fill="x", pady=(4, 2))

    # All clickable colour swatches
    SWATCH_COLORS = [
        ("Auto",    "auto",              "#888888"),
        ("White",   (255, 255, 255),     "#ffffff"),
        ("Ivory",   (255, 253, 240),     "#fffdf0"),
        ("Cream",   (245, 245, 220),     "#f5f5dc"),
        ("Pearl",   (240, 240, 240),     "#f0f0f0"),
        ("Silver",  (220, 220, 220),     "#dcdcdc"),
        ("Grey",    (200, 200, 200),     "#c8c8c8"),
        ("Ash",     (180, 180, 180),     "#b4b4b4"),
        ("Stone",   (150, 150, 150),     "#969696"),
        ("Slate",   (100, 100, 100),     "#646464"),
        ("Charcoal",(60,  60,  60),      "#3c3c3c"),
        ("Dark",    (30,  30,  30),      "#1e1e1e"),
        ("Black",   (0,   0,   0),       "#000000"),
        ("Blush",   (255, 230, 230),     "#ffe6e6"),
        ("Peach",   (255, 220, 180),     "#ffdcb4"),
        ("Wheat",   (240, 220, 180),     "#f0dcb4"),
        ("Sage",    (200, 220, 190),     "#c8dcbe"),
        ("Sky",     (200, 220, 245),     "#c8dcf5"),
        ("Lavender",(220, 200, 240),     "#dcc8f0"),
        ("Custom",  None,                "#444444"),   # opens colour picker
    ]

    _selected_swatch = [None]   # holds the currently highlighted button

    swatch_grid = tk.Frame(s4, bg=CARD)
    swatch_grid.pack(fill="x", pady=(0, 4))

    selected_lbl = tk.Label(s4, text="Selected: Auto (keep original)", bg=CARD,
                            fg=FG2, font=("Segoe UI", 8), anchor="w")
    selected_lbl.pack(fill="x")

    def _apply_color(name, rgb_val, hex_col, btn):
        # Deselect previous
        if _selected_swatch[0]:
            try: _selected_swatch[0].config(relief="flat", bd=0)
            except Exception: pass
        _selected_swatch[0] = btn
        btn.config(relief="solid", bd=2)

        if rgb_val == "auto":
            v_bg_preset.set("Auto (keep original)")
            v_bg_custom["rgb"] = None
            selected_lbl.config(text="Selected: Auto (keep original)")
        elif rgb_val is None:
            # Custom colour picker
            from tkinter.colorchooser import askcolor
            cur = v_bg_custom.get("rgb") or (235, 235, 235)
            result = askcolor(title="Pick custom background colour",
                              color="#%02x%02x%02x" % cur)
            if result and result[0]:
                r, g, b = (int(c) for c in result[0])
                v_bg_custom["rgb"] = (r, g, b)
                v_bg_preset.set("Custom …")
                hex_picked = "#%02x%02x%02x" % (r, g, b)
                btn.config(bg=hex_picked)
                selected_lbl.config(text=f"Selected: Custom  {hex_picked.upper()}")
        else:
            v_bg_preset.set("Custom …")
            v_bg_custom["rgb"] = rgb_val
            grey = int(sum(rgb_val) / 3)
            v_bg_grey.set(grey)
            selected_lbl.config(text=f"Selected: {name}  {hex_col.upper()}")

    COLS = 10
    for i, (name, rgb_val, hex_col) in enumerate(SWATCH_COLORS):
        col = i % COLS
        row = i // COLS
        display = hex_col if rgb_val != "auto" else "#888888"
        # Determine label colour for contrast
        lbl_fg = "#000" if hex_col in ("#ffffff","#fffdf0","#f5f5dc","#f0f0f0",
                                        "#dcdcdc","#c8c8c8","#b4b4b4","#ffe6e6",
                                        "#ffdcb4","#f0dcb4","#c8dcbe","#c8dcf5",
                                        "#dcc8f0") else "#fff"
        btn = tk.Button(swatch_grid, bg=display, width=3, height=1,
                        relief="flat", bd=0, cursor="hand2",
                        font=("Segoe UI", 6), fg=lbl_fg,
                        activebackground=display)
        btn.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
        swatch_grid.columnconfigure(col, weight=1)
        # Tooltip-style label on hover
        tip = tk.Label(swatch_grid, text="", bg=CARD, fg=FG2, font=("Segoe UI", 7))
        def _enter(e, n=name, b=btn, rv=rgb_val, hx=hex_col):
            selected_lbl.config(text=f"→ {n}  {hx.upper() if rv != 'auto' else '(auto)'}")
        def _leave(e):
            # restore current selected text
            pass
        btn.bind("<Enter>", _enter)
        btn.bind("<Leave>", _leave)
        btn.config(command=lambda n=name, rv=rgb_val, hx=hex_col, b=btn:
                   _apply_color(n, rv, hx, b))
        if name == "Auto":
            # pre-select Auto on startup
            btn.config(relief="solid", bd=2)
            _selected_swatch[0] = btn

    # ── rembg toggle ─────────────────────────────────────────────────────────
    adv_row = tk.Frame(s4, bg=CARD); adv_row.pack(fill="x", pady=2)
    tk.Label(adv_row, text="Use rembg AI", bg=CARD, fg=FG2, font=F,
             width=16, anchor="w").pack(side="left")
    tk.Checkbutton(adv_row, variable=v_rembg, bg=CARD, fg=FG,
                   selectcolor=CARD2, activebackground=CARD,
                   activeforeground=FG).pack(side="left")
    note = "(not installed — pip install rembg)" if not _rembg_available else "(installed ✓)"
    tk.Label(adv_row, text=note, bg=CARD,
             fg=RED if not _rembg_available else GREEN,
             font=("Segoe UI", 8)).pack(side="left", padx=4)

    # ── Pack mode toggle ──────────────────────────────────────────────────────
    pack_row = tk.Frame(s4, bg=CARD); pack_row.pack(fill="x", pady=2)
    tk.Label(pack_row, text="Pack Shot Mode", bg=CARD, fg=FG2, font=F,
             width=16, anchor="w").pack(side="left")
    tk.Checkbutton(pack_row, variable=v_pack_mode, bg=CARD, fg=FG,
                   selectcolor=CARD2, activebackground=CARD,
                   activeforeground=FG).pack(side="left")
    tk.Label(pack_row, text="builds PACK.jpg composite per style",
             bg=CARD, fg=FG2, font=("Segoe UI", 8)).pack(side="left", padx=4)

    # §5  Live Stats
    s5 = section(left, "📊  Live Stats")
    sg = tk.Frame(s5, bg=CARD); sg.pack(fill="x")
    stat_defs = [("Total","total",FG), ("✓ OK","success",GREEN),
                 ("✗ Failed","failed",RED), ("⚠ Skipped","skipped",YELLOW),
                 ("Folders","folders",ORANGE2)]
    for i, (lbl, key, clr) in enumerate(stat_defs):
        c, r = i % 3, i // 3
        sf = tk.Frame(sg, bg=CARD2, padx=6, pady=4)
        sf.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
        sg.columnconfigure(c, weight=1)
        tk.Label(sf, text=lbl, bg=CARD2, fg=FG2, font=("Segoe UI", 8)).pack()
        tk.Label(sf, textvariable=v_stats[key], bg=CARD2,
                 fg=clr, font=("Segoe UI", 16, "bold")).pack()

    # ── RIGHT PANEL — Before / After Preview (full width, scrollable) ─────────
    right = tk.Frame(body, bg=BG)
    right.pack(side="right", fill="both", expand=True, padx=(0, 12), pady=10)

    # Header with nav buttons
    prev_hdr = tk.Frame(right, bg=CARD)
    prev_hdr.pack(fill="x")
    tk.Label(prev_hdr, text="  🖼  Before / After Preview", bg=CARD, fg=ACCENT,
             font=("Segoe UI", 10, "bold")).pack(side="left", padx=6, pady=6)
    nav_lbl = tk.Label(prev_hdr, text="No images yet", bg=CARD, fg=FG2,
                       font=("Segoe UI", 9))
    nav_lbl.pack(side="right", padx=10)
    btn_next = tk.Button(prev_hdr, text=" ❯ ", bg=CARD2, fg=FG, relief="flat",
                         font=("Segoe UI", 11, "bold"), cursor="hand2", padx=6)
    btn_next.pack(side="right", padx=(0, 4), pady=4)
    btn_prev = tk.Button(prev_hdr, text=" ❮ ", bg=CARD2, fg=FG, relief="flat",
                         font=("Segoe UI", 11, "bold"), cursor="hand2", padx=6)
    btn_prev.pack(side="right", padx=(0, 2), pady=4)

    # Scrollable canvas wrapper
    scroll_canvas = tk.Canvas(right, bg=BG, highlightthickness=0)
    v_scroll = tk.Scrollbar(right, orient="vertical", command=scroll_canvas.yview)
    scroll_canvas.configure(yscrollcommand=v_scroll.set)
    v_scroll.pack(side="right", fill="y")
    scroll_canvas.pack(side="left", fill="both", expand=True)

    prev_body = tk.Frame(scroll_canvas, bg=BG)
    scroll_win = scroll_canvas.create_window((0, 0), window=prev_body, anchor="nw")

    def _on_prev_body_resize(event):
        scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
        scroll_canvas.itemconfig(scroll_win, width=scroll_canvas.winfo_width())
    prev_body.bind("<Configure>", _on_prev_body_resize)
    scroll_canvas.bind("<Configure>",
        lambda e: scroll_canvas.itemconfig(scroll_win, width=e.width))

    def _on_mousewheel(event):
        scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel)

    prev_body.columnconfigure(0, weight=1)
    prev_body.columnconfigure(1, weight=0)
    prev_body.columnconfigure(2, weight=1)

    THUMB_W, THUMB_H = 230, 288

    def _make_card(parent, col, title, score_color):
        card = tk.Frame(parent, bg=CARD2, padx=14, pady=10)
        card.grid(row=0, column=col, sticky="nsew", padx=6, pady=8)

        # ── Title + Score at top (always visible) ────────────────────────────
        top = tk.Frame(card, bg=CARD2); top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text=title, bg=CARD2, fg=FG2,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        score_lbl = tk.Label(top, text="—%", bg=CARD2, fg=score_color,
                             font=("Segoe UI", 20, "bold"))
        score_lbl.pack(side="right")
        tk.Label(top, text="Quality:", bg=CARD2, fg=FG2,
                 font=("Segoe UI", 9)).pack(side="right", padx=(0, 4))

        # ── Thumbnail ────────────────────────────────────────────────────────
        img_lbl = tk.Label(card, bg="#1a1a1a", width=THUMB_W, height=THUMB_H,
                           relief="flat")
        img_lbl.pack()

        # ── Info row: pixels | ratio | format ────────────────────────────────
        info = tk.Frame(card, bg=CARD2); info.pack(fill="x", pady=(8, 2))

        px_lbl = tk.Label(info, text="— × —", bg=CARD2, fg="#aaaaaa",
                          font=("Segoe UI", 9))
        px_lbl.pack(side="left")

        fmt_lbl = tk.Label(info, text="—", bg=CARD2, fg="#777777",
                           font=("Segoe UI", 9, "bold"))
        fmt_lbl.pack(side="right")

        ratio_lbl = tk.Label(card, text="Ratio  —", bg=CARD2, fg=ACCENT,
                             font=("Segoe UI", 11, "bold"))
        ratio_lbl.pack(pady=(2, 4))

        return img_lbl, score_lbl, px_lbl, ratio_lbl, fmt_lbl

    before_img_lbl, before_score_lbl, before_px_lbl, before_ratio_lbl, before_fmt_lbl = \
        _make_card(prev_body, 0, "ORIGINAL",  RED)

    arr_frame = tk.Frame(prev_body, bg=BG)
    arr_frame.grid(row=0, column=1, sticky="ns", padx=4)
    tk.Label(arr_frame, text="→", bg=BG, fg=ACCENT,
             font=("Segoe UI", 36, "bold")).pack(expand=True)

    after_img_lbl, after_score_lbl, after_px_lbl, after_ratio_lbl, after_fmt_lbl = \
        _make_card(prev_body, 2, "PROCESSED", GREEN)

    _prev_photo_refs = {}
    _prev_history   = []
    _prev_index     = [-1]

    from math import gcd as _gcd

    def _render_index(idx):
        if not _prev_history: return
        entry = _prev_history[idx]
        before_pil, after_pil, before_score, after_score = entry[:4]
        src_fmt = entry[4] if len(entry) > 4 else "—"
        from PIL import ImageTk
        pairs = [
            ("before", before_pil, before_img_lbl, before_score_lbl,
             before_px_lbl, before_ratio_lbl, before_fmt_lbl, before_score, RED,  src_fmt),
            ("after",  after_pil,  after_img_lbl,  after_score_lbl,
             after_px_lbl,  after_ratio_lbl,  after_fmt_lbl,  after_score,  GREEN, "JPEG"),
        ]
        for key, pil_img, img_lbl, score_lbl, px_lbl, ratio_lbl, fmt_lbl, score_val, clr, fmt in pairs:
            thumb = pil_img.copy()
            thumb.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            _prev_photo_refs[key] = photo
            img_lbl.config(image=photo, width=THUMB_W, height=THUMB_H)
            score_lbl.config(text=f"{score_val}%", fg=clr)
            w, h = pil_img.size
            g = _gcd(w, h)
            px_lbl.config(text=f"{w} × {h} px")
            ratio_lbl.config(text=f"Ratio  {w//g} : {h//g}")
            fmt_lbl.config(text=fmt)
        nav_lbl.config(text=f"Image  {idx+1}  /  {len(_prev_history)}")
        scroll_canvas.yview_moveto(0)

    def _go_prev():
        if _prev_index[0] > 0:
            _prev_index[0] -= 1
            _render_index(_prev_index[0])

    def _go_next():
        if _prev_index[0] < len(_prev_history) - 1:
            _prev_index[0] += 1
            _render_index(_prev_index[0])

    btn_prev.config(command=_go_prev)
    btn_next.config(command=_go_next)

    def _add_preview(before_pil, after_pil, before_score, after_score, src_fmt="—"):
        _prev_history.append((before_pil, after_pil, before_score, after_score, src_fmt))
        _prev_index[0] = len(_prev_history) - 1
        _render_index(_prev_index[0])

    def poll_preview():
        try:
            while True:
                _add_preview(*_preview_queue.get_nowait())
        except queue.Empty:
            pass
        root.after(500, poll_preview)
    root.after(500, poll_preview)

    # Hidden log widget
    log_box = tk.Text(right, height=0)
    log_box.config(state="disabled")

    def append_log(msg):
        if "ERROR" in msg or "✗" in msg:
            root.after(0, prog_lbl.config, {"text": f"⚠ {msg[:120]}"})

    def poll_log():
        for _ in range(50):
            try: append_log(_log_queue.get_nowait())
            except queue.Empty: break
        root.after(200, poll_log)
    root.after(200, poll_log)

    # ══════════════════════════════════════════════════════════════════════════
    #  RUN / STOP LOGIC
    # ══════════════════════════════════════════════════════════════════════════
    def on_progress(done, total_imgs):
        pct = done / total_imgs * 100 if total_imgs else 0
        v_prog.set(pct)
        prog_lbl.config(text=f"Processing…  {done} / {total_imgs}  ({pct:.1f}%)")

    def do_run():
        if _running.is_set(): return
        if not Path(v_excel.get()).exists():
            messagebox.showerror("File not found",
                f"Excel file not found:\n{v_excel.get()}\n\nClick '…' to browse for it.")
            return
        _running.set(); _stop_event.clear()
        run_btn.config(state="disabled", bg="#555", fg="#999")
        stop_btn.config(state="normal")
        v_prog.set(0)
        prog_lbl.config(text="Starting…")
        for k in v_stats: v_stats[k].set("…")

        cfg = get_cfg()
        def worker():
            try:
                res = process_all(cfg,
                                  progress_cb=lambda d,t: root.after(0, on_progress, d, t),
                                  stop_event=_stop_event)
                root.after(0, on_done, res)
            except Exception as ex:
                log.error(f"UNEXPECTED: {ex}", exc_info=True)
                root.after(0, on_done, None)
        threading.Thread(target=worker, daemon=True).start()

    def on_done(res):
        _running.clear()
        run_btn.config(state="normal", bg=GREEN, fg="#000")
        stop_btn.config(state="disabled")
        if res:
            for k in ("total","success","failed","skipped","folders"):
                v_stats[k].set(str(res[k]))
            v_prog.set(100)
            prog_lbl.config(text=f"✓ Done — {res['success']} images processed successfully")
        else:
            prog_lbl.config(text="⚠ Finished with errors — check log above.")

    def do_stop():
        _stop_event.set(); stop_btn.config(state="disabled")
        prog_lbl.config(text="Stopping after current image…")

    run_btn.config(command=do_run)
    stop_btn.config(command=do_stop)

    pass   # welcome message removed (log panel hidden)

    root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    launch_gui()
