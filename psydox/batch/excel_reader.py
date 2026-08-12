"""
Psydox Batch — Excel Input Reader

Reads a product catalog Excel file:
  Column 1:  STYLE_CODE (product identifier)
  Column 2+: Image URLs (one per column, up to 12 supported)

Returns a dict: { "STYLE001": ["url1", "url2", ...], ... }

This is the same logic as process_images.read_excel(), lifted into the
psydox package so Studio and batch features can import it directly.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

_log = logging.getLogger("psydox.batch.excel_reader")

_MAX_EXCEL_MB  = 50
_MAX_STYLES    = 500
_MAX_URLS_PER  = 12


@dataclass
class ExcelReadResult:
    styles:   dict[str, list[str]]  # {style_code: [url, ...]}
    total_styles: int
    total_urls:   int
    warnings: list[str] = field(default_factory=list)
    errors:   list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.styles) > 0 and not self.errors


def read_excel_bytes(data: bytes, max_styles: int = _MAX_STYLES) -> ExcelReadResult:
    """
    Parse an Excel file from raw bytes.
    Returns ExcelReadResult with styles dict and any warnings/errors.
    """
    if len(data) > _MAX_EXCEL_MB * 1024 * 1024:
        return ExcelReadResult({}, 0, 0, errors=[f"File too large (max {_MAX_EXCEL_MB} MB)."])

    try:
        import openpyxl
    except ImportError:
        return ExcelReadResult({}, 0, 0, errors=["openpyxl is required for Excel import (pip install openpyxl)."])

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    except Exception as exc:
        return ExcelReadResult({}, 0, 0, errors=[f"Could not read Excel file: {exc}"])

    if not rows or len(rows[0]) < 2:
        return ExcelReadResult({}, 0, 0, errors=["Excel must have at least 2 columns: STYLE_CODE and one image URL column."])

    styles: dict[str, list[str]] = {}
    warnings: list[str] = []

    # Skip the first row if it looks like a header
    start = 1 if _looks_like_header(rows[0]) else 0

    for row in rows[start:]:
        if not row:
            continue
        code = str(row[0]).strip() if row[0] is not None else ""
        if not code or code.lower() in ("nan", "none", "style_code", "code", "sku", "stylecode"):
            continue

        urls: list[str] = []
        seen_urls: set[str] = set()
        for cell in row[1: _MAX_URLS_PER + 1]:
            url = str(cell).strip() if cell is not None else ""
            if url and url.lower() not in ("nan", "none", ""):
                validated = _validate_url(url)
                if validated and validated not in seen_urls:
                    urls.append(validated)
                    seen_urls.add(validated)

        if not urls:
            warnings.append(f"Style '{code}': no valid URLs found, skipped.")
            continue

        if code in styles:
            # Merge duplicates
            for u in urls:
                if u not in styles[code]:
                    styles[code].append(u)
        else:
            styles[code] = urls

        if len(styles) >= max_styles:
            warnings.append(f"Truncated to {max_styles} styles (file had more rows).")
            break

    total_urls = sum(len(v) for v in styles.values())
    return ExcelReadResult(
        styles=styles,
        total_styles=len(styles),
        total_urls=total_urls,
        warnings=warnings,
    )


def _looks_like_header(row: tuple) -> bool:
    """Return True if the first cell looks like a column header, not a style code."""
    if not row or row[0] is None:
        return False
    first = str(row[0]).strip().lower()
    return first in (
        # underscore variants
        "style_code", "stylecode", "code", "sku", "style", "product_code",
        "productcode", "item_code", "itemcode", "article_no", "article_number",
        "image", "images", "url", "urls",
        # space variants (e.g. "Style Code", "Product Code")
        "style code", "product code", "item code", "article no", "article number",
        "product id", "product_id", "item id", "item_id",
    )


def _validate_url(url: str) -> Optional[str]:
    """Return cleaned URL or None if it fails basic validation."""
    url = url.strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return None
        # Basic SSRF: block private/local hosts
        host = parsed.hostname or ""
        if host in ("localhost", "127.0.0.1", "169.254.169.254", "metadata.google.internal"):
            return None
        return url
    except Exception:
        return None


def resolve_url(url: str) -> str:
    """Convert share-page URLs to direct download URLs (Google Drive, Dropbox, OneDrive)."""
    # Google Drive
    m = re.search(r'drive\.google\.com/file/d/([A-Za-z0-9_-]+)', url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    m = re.search(r'drive\.google\.com/open\?id=([A-Za-z0-9_-]+)', url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"

    # Dropbox
    if 'dropbox.com' in url or 'dropboxusercontent.com' in url:
        url = url.replace('dl.dropboxusercontent.com', 'www.dropbox.com')
        parsed = urlparse(url)
        qs = {k: v for k, v in parse_qs(parsed.query, keep_blank_values=True).items()
              if k not in ('dl', 'st')}
        if '/scl/fi/' in parsed.path:
            qs['dl'] = ['1']
            return urlunparse(parsed._replace(
                netloc='www.dropbox.com', query=urlencode(qs, doseq=True)
            ))
        else:
            return urlunparse(parsed._replace(
                netloc='dl.dropboxusercontent.com', query=urlencode(qs, doseq=True)
            ))


    # OneDrive
    if '1drv.ms' in url or 'onedrive.live.com' in url:
        return url.replace('redir?', 'download?').replace('embed?', 'download?')

    return url


def download_image(url: str, timeout: int = 15) -> Optional[bytes]:
    """
    Download a single image URL and return its bytes.
    Returns None on failure.
    Resolves share-page URLs (Drive/Dropbox/OneDrive) automatically.
    """
    try:
        import requests
        direct = resolve_url(url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        resp = requests.get(direct, headers=headers, timeout=timeout, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "image" not in content_type and "octet-stream" not in content_type:
            _log.warning("download_image: unexpected Content-Type '%s' for %s", content_type, url)
        data = b"".join(resp.iter_content(65536))
        return data if data else None
    except Exception as exc:
        _log.debug("download_image failed for %s: %s", url, exc)
        return None
