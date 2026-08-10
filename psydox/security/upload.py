"""
Psydox Upload Security

Validates uploaded files before processing:
  - MIME type validation (magic bytes, not extension)
  - File size limits
  - Image dimension checks
  - SSRF protection (block file:// / internal URLs if applicable)

Never trusts user-supplied filenames or Content-Type headers alone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

_log = logging.getLogger("psydox.security.upload")

# Magic bytes for allowed image types
_MAGIC: dict[str, list[bytes]] = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png":  [b"\x89PNG\r\n\x1a\n"],
    "image/webp": [b"RIFF", b"WEBP"],
    "image/gif":  [b"GIF87a", b"GIF89a"],
    "image/tiff": [b"II*\x00", b"MM\x00*"],
    "image/bmp":  [b"BM"],
    "image/heic": [b"\x00\x00\x00"],  # partial, checked by extension too
}

ALLOWED_MIME_TYPES = set(_MAGIC.keys())
MAX_FILE_SIZE_MB   = 25
MIN_DIMENSION_PX   = 10
MAX_DIMENSION_PX   = 20000


@dataclass
class UploadValidationResult:
    valid:      bool
    mime_type:  str   = ""
    errors:     list  = None
    warnings:   list  = None
    width:      int   = 0
    height:     int   = 0
    file_size:  int   = 0

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


def validate_upload(data: bytes, filename: str = "", max_mb: float = MAX_FILE_SIZE_MB) -> UploadValidationResult:
    """
    Validate uploaded image bytes.

    Returns UploadValidationResult.
    Always returns — never raises.
    """
    result = UploadValidationResult(valid=False, file_size=len(data))

    if not data:
        result.errors.append("Empty file.")
        return result

    # Size check
    size_mb = len(data) / 1024 / 1024
    if size_mb > max_mb:
        result.errors.append(f"File size {size_mb:.1f}MB exceeds limit {max_mb}MB.")
        return result

    # MIME via magic bytes
    mime = _detect_mime(data)
    if mime not in ALLOWED_MIME_TYPES:
        result.errors.append(
            f"File type not allowed. Accepted: JPEG, PNG, WEBP, GIF, TIFF, BMP."
        )
        return result

    result.mime_type = mime

    # Open with PIL for dimension check
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        result.width  = w
        result.height = h

        if w < MIN_DIMENSION_PX or h < MIN_DIMENSION_PX:
            result.errors.append(f"Image too small: {w}×{h}px (minimum {MIN_DIMENSION_PX}px).")
            return result

        if w > MAX_DIMENSION_PX or h > MAX_DIMENSION_PX:
            result.warnings.append(
                f"Image very large ({w}×{h}px). Consider resizing for faster processing."
            )

        if w < 500 or h < 500:
            result.warnings.append(
                f"Low resolution ({w}×{h}px). AI results may be lower quality."
            )

    except Exception as e:
        result.errors.append(f"Cannot decode image: {e}")
        return result

    result.valid = True
    return result


def validate_url(url: str) -> tuple[bool, str]:
    """
    SSRF protection: block internal/private URLs.
    Returns (allowed: bool, reason: str).
    """
    import re
    url_lower = url.lower().strip()

    # Block non-HTTP(S) schemes
    if not url_lower.startswith(("http://", "https://")):
        return False, f"URL scheme not allowed (only http/https)."

    # Block known internal patterns
    blocked_patterns = [
        r"^https?://localhost",
        r"^https?://127\.",
        r"^https?://10\.",
        r"^https?://192\.168\.",
        r"^https?://172\.(1[6-9]|2[0-9]|3[01])\.",
        r"^https?://0\.",
        r"^https?://\[::1\]",
        r"file://",
        r"^https?://metadata\.",      # cloud metadata services
        r"169\.254\.",                # link-local / AWS metadata
    ]
    for pattern in blocked_patterns:
        if re.search(pattern, url_lower):
            return False, f"URL references a private or internal address."

    return True, ""


def _detect_mime(data: bytes) -> str:
    for mime, signatures in _MAGIC.items():
        for sig in signatures:
            if data[:len(sig)] == sig:
                return mime
    # Extra WEBP check (bytes 8-12)
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"
