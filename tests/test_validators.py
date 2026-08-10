"""Tests for nano_banana.validators — SSRF protection and upload validation."""
import pytest
import sys
from pathlib import Path

# Make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nano_banana.validators import (
    validate_url,
    validate_image_upload,
    validate_excel_upload,
    URLValidationError,
)


# ── validate_url ──────────────────────────────────────────────────────────────

class TestValidateUrl:
    def test_valid_https(self):
        result = validate_url("https://example.com/image.jpg")
        assert result == "https://example.com/image.jpg"

    def test_valid_http(self):
        result = validate_url("http://cdn.example.com/img.png")
        assert result == "http://cdn.example.com/img.png"

    def test_strips_whitespace(self):
        result = validate_url("  https://example.com/a.jpg  ")
        assert result == "https://example.com/a.jpg"

    def test_empty_raises(self):
        with pytest.raises(URLValidationError, match="empty"):
            validate_url("")

    def test_whitespace_only_raises(self):
        with pytest.raises(URLValidationError, match="empty"):
            validate_url("   ")

    def test_ftp_scheme_blocked(self):
        with pytest.raises(URLValidationError, match="scheme"):
            validate_url("ftp://example.com/file.jpg")

    def test_file_scheme_blocked(self):
        with pytest.raises(URLValidationError, match="scheme"):
            validate_url("file:///etc/passwd")

    def test_localhost_blocked(self):
        with pytest.raises(URLValidationError):
            validate_url("http://localhost/admin")

    def test_loopback_ip_blocked(self):
        with pytest.raises(URLValidationError):
            validate_url("http://127.0.0.1/secret")

    def test_private_ip_10_blocked(self):
        with pytest.raises(URLValidationError):
            validate_url("http://10.0.0.1/internal")

    def test_private_ip_192_blocked(self):
        with pytest.raises(URLValidationError):
            validate_url("http://192.168.1.100/data")

    def test_private_ip_172_blocked(self):
        with pytest.raises(URLValidationError):
            validate_url("http://172.16.5.10/api")

    def test_link_local_blocked(self):
        with pytest.raises(URLValidationError):
            validate_url("http://169.254.169.254/metadata")

    def test_metadata_google_blocked(self):
        with pytest.raises(URLValidationError):
            validate_url("http://metadata.google.internal/computeMetadata/v1/")

    def test_internal_hostname_blocked(self):
        with pytest.raises(URLValidationError):
            validate_url("http://myservice.internal/api")

    def test_local_hostname_blocked(self):
        with pytest.raises(URLValidationError):
            validate_url("http://printer.local/status")

    def test_public_ip_allowed(self):
        result = validate_url("http://8.8.8.8/check")
        assert "8.8.8.8" in result

    def test_cdn_url_allowed(self):
        result = validate_url("https://images.unsplash.com/photo-123.jpg")
        assert "unsplash.com" in result


# ── validate_image_upload ─────────────────────────────────────────────────────

class TestValidateImageUpload:
    def test_valid_jpeg(self):
        # Minimal JPEG header
        jpeg = b"\xff\xd8\xff" + b"\x00" * 100
        validate_image_upload(jpeg, "photo.jpg")  # no exception

    def test_valid_png(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        validate_image_upload(png, "image.png")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_image_upload(b"", "image.jpg")

    def test_too_large_raises(self):
        big = b"\xff\xd8\xff" + b"\x00" * (21 * 1024 * 1024)
        with pytest.raises(ValueError, match="large"):
            validate_image_upload(big, "big.jpg")

    def test_wrong_extension_raises(self):
        with pytest.raises(ValueError, match="type"):
            validate_image_upload(b"\xff\xd8\xff" + b"\x00" * 10, "script.php")

    def test_executable_magic_raises(self):
        elf_bytes = b"\x7fELF" + b"\x00" * 100
        with pytest.raises(ValueError, match="executable"):
            validate_image_upload(elf_bytes, "evil.jpg")


# ── validate_excel_upload ─────────────────────────────────────────────────────

class TestValidateExcelUpload:
    def test_valid_xlsx(self):
        # Minimal xlsx is a ZIP — fake it
        xlsx = b"PK\x03\x04" + b"\x00" * 100
        validate_excel_upload(xlsx, "data.xlsx")  # no exception

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_excel_upload(b"", "data.xlsx")

    def test_wrong_extension_raises(self):
        with pytest.raises(ValueError, match="type"):
            validate_excel_upload(b"PK\x03\x04" + b"\x00" * 100, "data.csv")
