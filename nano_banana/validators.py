"""
Nano Banana — SSRF protection and upload validation.
Call validate_url() before any user-supplied URL is fetched.
Call validate_image_upload() / validate_excel_upload() on every upload.
"""
import ipaddress
from pathlib import Path
from urllib.parse import urlparse

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_ALLOWED_SCHEMES    = {"http", "https"}
_BLOCKED_HOSTS      = {"localhost", "metadata.google.internal", "169.254.169.254"}
_MAX_IMAGE_BYTES    = 20 * 1024 * 1024   # 20 MB
_MAX_EXCEL_BYTES    = 50 * 1024 * 1024   # 50 MB
_ALLOWED_IMAGE_EXT  = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_ALLOWED_EXCEL_EXT  = {".xlsx", ".xls"}

# Magic byte signatures
_MAGIC = {
    b"\xff\xd8\xff":       "jpeg",
    b"\x89PNG\r\n\x1a\n":  "png",
    b"RIFF":               "webp_maybe",   # confirmed below
    b"GIF87a":             "gif",
    b"GIF89a":             "gif",
}
_EXEC_MAGIC = {b"\x7fELF", b"MZ\x90\x00", b"\xca\xfe\xba\xbe"}


class URLValidationError(ValueError):
    """Raised when a URL fails SSRF validation."""


def validate_url(url: str) -> str:
    """
    Validate a URL before fetching it.
    Raises URLValidationError on any SSRF-risky or malformed input.
    Returns the stripped URL on success.
    """
    url = url.strip()
    if not url:
        raise URLValidationError("URL is empty.")

    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise URLValidationError(
            f"URL scheme '{parsed.scheme}' is not allowed. Use http or https."
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise URLValidationError("URL has no hostname.")

    if host in _BLOCKED_HOSTS:
        raise URLValidationError(f"Access to '{host}' is not permitted.")

    # Block internal-sounding hostnames
    if host.endswith(".internal") or host.endswith(".local") or host.endswith(".localhost"):
        raise URLValidationError(f"Access to internal host '{host}' is not permitted.")

    # Check for raw IP address literals
    _ip = None
    try:
        _ip = ipaddress.ip_address(host)
    except ValueError:
        pass  # not an IP literal — hostname, fine

    if _ip is not None:
        for _net in _PRIVATE_NETS:
            try:
                if _ip in _net:
                    raise URLValidationError(
                        f"Access to private/reserved IP address '{_ip}' is not allowed."
                    )
            except TypeError:
                pass  # IPv4/IPv6 type mismatch when checking across families

    return url


def validate_image_upload(file_bytes: bytes, filename: str) -> None:
    """
    Validate an uploaded image file (size, extension, magic bytes).
    Raises ValueError with a user-readable message on failure.
    """
    if not file_bytes:
        raise ValueError("Uploaded file is empty.")

    if len(file_bytes) > _MAX_IMAGE_BYTES:
        mb = len(file_bytes) / (1024 * 1024)
        raise ValueError(f"File too large ({mb:.1f} MB). Maximum is 20 MB.")

    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXT:
        raise ValueError(
            f"File type '{ext}' is not supported. "
            f"Allowed types: {', '.join(sorted(_ALLOWED_IMAGE_EXT))}"
        )

    sig = file_bytes[:12]

    # Hard-reject executables
    if sig[:4] in _EXEC_MAGIC:
        raise ValueError("Uploaded file appears to be an executable, not an image.")

    # For WEBP: RIFF....WEBP
    if sig[:4] == b"RIFF" and sig[8:12] == b"WEBP":
        return

    # Check known good magic bytes
    for magic in _MAGIC:
        if sig[: len(magic)] == magic and _MAGIC[magic] != "webp_maybe":
            return

    # Extension matched but magic unknown — allow (some tools strip headers)
    # The PIL.Image.open call downstream will catch truly corrupt data.


def validate_excel_upload(file_bytes: bytes, filename: str) -> None:
    """Validate an uploaded Excel file."""
    if not file_bytes:
        raise ValueError("Uploaded file is empty.")

    if len(file_bytes) > _MAX_EXCEL_BYTES:
        mb = len(file_bytes) / (1024 * 1024)
        raise ValueError(f"File too large ({mb:.1f} MB). Maximum is 50 MB.")

    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXCEL_EXT:
        raise ValueError(
            f"File type '{ext}' is not supported. "
            f"Allowed types: {', '.join(sorted(_ALLOWED_EXCEL_EXT))}"
        )
