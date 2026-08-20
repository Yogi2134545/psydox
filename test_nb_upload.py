"""Tests for nano_banana upload validation (validate_image_upload)."""
import sys
import os
import pytest

# Add project root to path so we can import nano_banana.validators directly
sys.path.insert(0, os.path.dirname(__file__))
from nano_banana.validators import validate_image_upload


# ── Minimal valid JPEG bytes (SOI + APP0 marker prefix) ──────────────────────
_VALID_JPEG = (
    b"\xff\xd8\xff\xe0"           # SOI + APP0 marker
    + b"\x00\x10JFIF\x00"        # APP0 length + "JFIF\0"
    + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00"  # minimal JFIF header
)

# ── Minimal valid PNG bytes (magic + IHDR chunk stub) ────────────────────────
_VALID_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

# ── Minimal valid WebP bytes ──────────────────────────────────────────────────
_VALID_WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 8


class TestValidImageUpload:
    def test_valid_jpeg_passes(self):
        """A small JPEG with correct magic bytes should not raise."""
        validate_image_upload(_VALID_JPEG, "product.jpg")

    def test_valid_png_passes(self):
        validate_image_upload(_VALID_PNG, "product.png")

    def test_valid_webp_passes(self):
        validate_image_upload(_VALID_WEBP, "product.webp")


class TestOversizedFile:
    def test_oversized_file_raises(self):
        """A file larger than 20 MB must be rejected."""
        big = b"\xff\xd8\xff" + b"\x00" * (20 * 1024 * 1024 + 1)
        with pytest.raises(ValueError, match="too large"):
            validate_image_upload(big, "huge.jpg")

    def test_exactly_at_limit_passes(self):
        """Exactly 20 MB should pass (boundary check)."""
        # 20 MB minus the magic bytes we prepend
        body = b"\x00" * (20 * 1024 * 1024 - len(_VALID_JPEG))
        at_limit = _VALID_JPEG + body
        validate_image_upload(at_limit, "atlimit.jpg")

    def test_one_byte_over_limit_fails(self):
        body = b"\x00" * (20 * 1024 * 1024 - len(_VALID_JPEG) + 1)
        over = _VALID_JPEG + body
        with pytest.raises(ValueError, match="too large"):
            validate_image_upload(over, "over.jpg")


class TestBadFileType:
    def test_python_script_rejected_by_extension(self):
        """A .py file must be rejected even if content looks benign."""
        with pytest.raises(ValueError, match="not supported"):
            validate_image_upload(b"print('hello')", "evil.py")

    def test_html_file_rejected(self):
        with pytest.raises(ValueError, match="not supported"):
            validate_image_upload(b"<html></html>", "page.html")

    def test_elf_binary_rejected_by_magic(self):
        """ELF binary must be rejected regardless of extension."""
        elf = b"\x7fELF" + b"\x00" * 20
        with pytest.raises(ValueError, match="executable"):
            validate_image_upload(elf, "renamed.jpg")

    def test_pe_binary_rejected(self):
        """Windows PE executable must be rejected."""
        pe = b"MZ\x90\x00" + b"\x00" * 20
        with pytest.raises(ValueError, match="executable"):
            validate_image_upload(pe, "malware.png")

    def test_empty_file_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            validate_image_upload(b"", "empty.jpg")
