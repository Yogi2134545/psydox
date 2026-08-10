"""Tests for upload security — MIME validation and SSRF protection."""
import io
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from PIL import Image


def _jpeg_bytes(w=100, h=100) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (128, 128, 128)).save(buf, "JPEG")
    return buf.getvalue()


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (128, 128, 128)).save(buf, "PNG")
    return buf.getvalue()


def test_valid_jpeg_passes():
    from psydox.security.upload import validate_upload
    r = validate_upload(_jpeg_bytes(800, 800))
    assert r.valid
    assert r.mime_type == "image/jpeg"


def test_valid_png_passes():
    from psydox.security.upload import validate_upload
    r = validate_upload(_png_bytes())
    assert r.valid
    assert r.mime_type == "image/png"


def test_random_bytes_rejected():
    from psydox.security.upload import validate_upload
    r = validate_upload(b"not an image at all x y z")
    assert not r.valid
    assert r.errors


def test_empty_bytes_rejected():
    from psydox.security.upload import validate_upload
    r = validate_upload(b"")
    assert not r.valid


def test_oversized_file_rejected():
    from psydox.security.upload import validate_upload
    big = _jpeg_bytes() * 1000  # force oversized
    r = validate_upload(big, max_mb=0.001)
    assert not r.valid
    assert any("size" in e.lower() for e in r.errors)


def test_tiny_image_rejected():
    from psydox.security.upload import validate_upload
    buf = io.BytesIO()
    Image.new("RGB", (5, 5), (0, 0, 0)).save(buf, "JPEG")
    r = validate_upload(buf.getvalue())
    assert not r.valid


def test_ssrf_localhost_blocked():
    from psydox.security.upload import validate_url
    ok, reason = validate_url("http://localhost/internal")
    assert not ok


def test_ssrf_internal_ip_blocked():
    from psydox.security.upload import validate_url
    for url in ["http://192.168.1.1/", "http://10.0.0.1/", "http://172.16.0.1/"]:
        ok, reason = validate_url(url)
        assert not ok, f"Should have blocked {url}"


def test_ssrf_file_scheme_blocked():
    from psydox.security.upload import validate_url
    ok, _ = validate_url("file:///etc/passwd")
    assert not ok


def test_ssrf_metadata_blocked():
    from psydox.security.upload import validate_url
    ok, _ = validate_url("http://169.254.169.254/latest/meta-data/")
    assert not ok


def test_valid_external_url_allowed():
    from psydox.security.upload import validate_url
    ok, _ = validate_url("https://images.example.com/product.jpg")
    assert ok


def test_low_resolution_warning():
    from psydox.security.upload import validate_upload
    r = validate_upload(_jpeg_bytes(200, 200))
    assert r.valid  # valid but with warning
    assert r.warnings
