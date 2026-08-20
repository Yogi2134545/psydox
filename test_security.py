"""
Security regression tests for SEC-002 (SSRF) and SEC-003 (local file read).
Run: python -m pytest test_security.py -v --no-header
"""
import sys, pathlib, types, unittest.mock

# ── make imports available without installing heavy deps ──────────────────────
_HERE = pathlib.Path(__file__).parent

# Stub heavy optional imports so process_images.py loads in a plain test env
for _mod in ("numpy", "pandas", "PIL", "PIL.Image", "PIL.ImageFilter",
             "requests", "requests.adapters", "cv2", "rembg"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

# Give numpy a minimal array stub (only ndarray and concatenate are used at import time)
import numpy as _real_np_or_stub
if not hasattr(sys.modules["numpy"], "ndarray"):
    sys.modules["numpy"].ndarray = object
    sys.modules["numpy"].concatenate = lambda *a, **k: None

# Stub requests.adapters.HTTPAdapter
_ra = sys.modules["requests.adapters"]
if not hasattr(_ra, "HTTPAdapter"):
    class _FakeAdapter:
        def __init__(self, **kw): pass
    _ra.HTTPAdapter = _FakeAdapter

# Stub requests.Session so module-level _SESSION construction works
_rq = sys.modules["requests"]
if not hasattr(_rq, "Session"):
    class _FakeSession:
        verify = True
        headers = {}
        def update(self, *a, **k): pass
        def mount(self, *a, **k): pass
    _rq.Session = _FakeSession
if not hasattr(_rq, "adapters"):
    _rq.adapters = _ra

# Stub PIL.Image
_pil_image = sys.modules.setdefault("PIL.Image", types.ModuleType("PIL.Image"))
if not hasattr(_pil_image, "LANCZOS"):
    _pil_image.LANCZOS = None
_pil = sys.modules.setdefault("PIL", types.ModuleType("PIL"))
_pil.Image = _pil_image
if not hasattr(_pil_image, "Image"):
    class _FakeImage: pass
    _pil_image.Image = _FakeImage

# pandas stub
_pd = sys.modules["pandas"]
if not hasattr(_pd, "read_excel"):
    _pd.read_excel = lambda *a, **k: None

# Now import the module under test
sys.path.insert(0, str(_HERE))
import importlib
import process_images as _pi

# ─────────────────────────────────────────────────────────────────────────────
import pathlib, tempfile
import pytest


# ── SEC-002: SSRF ─────────────────────────────────────────────────────────────

def test_ssrf_block_aws_metadata():
    """AWS IMDSv1 metadata URL must be blocked."""
    result = _pi.download_image(
        "http://169.254.169.254/latest/meta-data/",
        pathlib.Path(tempfile.gettempdir()),
        {"MAX_RETRIES": 1, "REQUEST_TIMEOUT": 5,
         "_url_cache": None, "_url_cache_lock": None},
    )
    assert result == "FAIL:SSRF_BLOCKED", f"Expected FAIL:SSRF_BLOCKED, got {result!r}"


def test_ssrf_block_rfc1918_192():
    """RFC-1918 address 192.168.x.x must be blocked."""
    result = _pi.download_image(
        "http://192.168.1.1/",
        pathlib.Path(tempfile.gettempdir()),
        {"MAX_RETRIES": 1, "REQUEST_TIMEOUT": 5,
         "_url_cache": None, "_url_cache_lock": None},
    )
    assert result == "FAIL:SSRF_BLOCKED", f"Expected FAIL:SSRF_BLOCKED, got {result!r}"


def test_ssrf_block_loopback():
    """Loopback 127.x address must be blocked."""
    result = _pi.download_image(
        "http://127.0.0.1:8080/admin",
        pathlib.Path(tempfile.gettempdir()),
        {"MAX_RETRIES": 1, "REQUEST_TIMEOUT": 5,
         "_url_cache": None, "_url_cache_lock": None},
    )
    assert result == "FAIL:SSRF_BLOCKED", f"Expected FAIL:SSRF_BLOCKED, got {result!r}"


def test_ssrf_validate_passes_public_url():
    """A public HTTPS URL must pass _validate_url_safe without raising."""
    _pi._validate_url_safe("https://httpbin.org/get")   # must not raise


def test_ssrf_block_rfc1918_10():
    """RFC-1918 address 10.x.x.x must be blocked."""
    result = _pi.download_image(
        "http://10.0.0.1/secret",
        pathlib.Path(tempfile.gettempdir()),
        {"MAX_RETRIES": 1, "REQUEST_TIMEOUT": 5,
         "_url_cache": None, "_url_cache_lock": None},
    )
    assert result == "FAIL:SSRF_BLOCKED"


def test_ssrf_block_172_16():
    """RFC-1918 address 172.16.x.x must be blocked."""
    result = _pi.download_image(
        "http://172.16.0.1/",
        pathlib.Path(tempfile.gettempdir()),
        {"MAX_RETRIES": 1, "REQUEST_TIMEOUT": 5,
         "_url_cache": None, "_url_cache_lock": None},
    )
    assert result == "FAIL:SSRF_BLOCKED"


def test_ssrf_block_localhost():
    """'localhost' host must be blocked."""
    with pytest.raises(ValueError, match="internal/metadata"):
        _pi._validate_url_safe("http://localhost/config")


def test_ssrf_block_gcp_metadata():
    """GCP metadata endpoint must be blocked."""
    with pytest.raises(ValueError, match="internal/metadata"):
        _pi._validate_url_safe("http://metadata.google.internal/computeMetadata/v1/")


# ── SEC-003: local file read ──────────────────────────────────────────────────

def test_local_path_blocked_by_default():
    """collect_image with a local path and ALLOW_LOCAL_FILES absent returns FAIL:LOCAL_PATH_NOT_ALLOWED."""
    result = _pi.collect_image(
        "/etc/passwd",
        pathlib.Path(tempfile.gettempdir()),
        {},   # ALLOW_LOCAL_FILES defaults to False
    )
    assert result == "FAIL:LOCAL_PATH_NOT_ALLOWED", f"got {result!r}"


def test_local_path_blocked_explicit_false():
    """collect_image with ALLOW_LOCAL_FILES=False must block local paths."""
    result = _pi.collect_image(
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        pathlib.Path(tempfile.gettempdir()),
        {"ALLOW_LOCAL_FILES": False},
    )
    assert result == "FAIL:LOCAL_PATH_NOT_ALLOWED", f"got {result!r}"


def test_local_path_allowed_when_flag_set(tmp_path):
    """collect_image with ALLOW_LOCAL_FILES=True proceeds to copy_local (non-existent file → None)."""
    result = _pi.collect_image(
        str(tmp_path / "nonexistent_image.jpg"),
        tmp_path,
        {"ALLOW_LOCAL_FILES": True},
    )
    # copy_local returns None for a missing file — confirms the gate was passed
    assert result is None, f"got {result!r}"


def test_invalid_url_still_blocked():
    """Empty / nan sources return FAIL:INVALID_URL regardless of flags."""
    result = _pi.collect_image("nan", pathlib.Path(tempfile.gettempdir()), {})
    assert result == "FAIL:INVALID_URL"
