"""
Tests for psydox.batch.excel_reader — Excel catalog parsing.
All offline, no network calls.
"""
import io
import pytest
import openpyxl

from psydox.batch.excel_reader import (
    read_excel_bytes, resolve_url, _validate_url, ExcelReadResult,
)


def _make_excel(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestReadExcel:
    def test_basic_parse(self):
        data = _make_excel([
            ["STYLE_CODE", "IMAGE1", "IMAGE2"],
            ["ABC001", "https://example.com/a.jpg", "https://example.com/b.jpg"],
            ["ABC002", "https://example.com/c.jpg", ""],
        ])
        result = read_excel_bytes(data)
        assert result.ok
        assert result.total_styles == 2
        assert "ABC001" in result.styles
        assert len(result.styles["ABC001"]) == 2
        assert result.styles["ABC002"] == ["https://example.com/c.jpg"]

    def test_skips_header_row(self):
        data = _make_excel([
            ["Code", "URL1"],
            ["P001", "https://example.com/img.jpg"],
        ])
        result = read_excel_bytes(data)
        assert "Code" not in result.styles
        assert "P001" in result.styles

    def test_empty_excel_returns_error(self):
        data = _make_excel([["STYLE_CODE", "IMAGE1"]])
        result = read_excel_bytes(data)
        assert not result.ok

    def test_deduplicates_urls_within_style(self):
        url = "https://example.com/same.jpg"
        data = _make_excel([
            ["STYLE", "URL1", "URL2"],
            ["X001", url, url],
        ])
        result = read_excel_bytes(data)
        assert len(result.styles["X001"]) == 1

    def test_deduplicates_across_duplicate_rows(self):
        url = "https://example.com/img.jpg"
        data = _make_excel([
            ["STYLE", "URL1"],
            ["X001", url],
            ["X001", "https://example.com/img2.jpg"],
        ])
        result = read_excel_bytes(data)
        assert len(result.styles["X001"]) == 2

    def test_skips_style_with_no_valid_urls(self):
        data = _make_excel([
            ["STYLE", "URL1"],
            ["NOURL", "not-a-url"],
        ])
        result = read_excel_bytes(data)
        assert "NOURL" not in result.styles
        assert any("NOURL" in w for w in result.warnings)

    def test_invalid_bytes_returns_error(self):
        result = read_excel_bytes(b"\x00\x01corrupted")
        assert not result.ok
        assert result.errors

    def test_file_too_large_returns_error(self):
        oversized = b"x" * (51 * 1024 * 1024)
        result = read_excel_bytes(oversized)
        assert not result.ok
        assert "too large" in result.errors[0].lower()

    def test_total_counts(self):
        data = _make_excel([
            ["STYLE", "URL1", "URL2"],
            ["A", "https://example.com/1.jpg", "https://example.com/2.jpg"],
            ["B", "https://example.com/3.jpg", ""],
        ])
        result = read_excel_bytes(data)
        assert result.total_styles == 2
        assert result.total_urls == 3


class TestValidateUrl:
    def test_http_ok(self):
        assert _validate_url("http://example.com/img.jpg") is not None

    def test_https_ok(self):
        assert _validate_url("https://example.com/img.jpg") is not None

    def test_no_scheme_blocked(self):
        assert _validate_url("example.com/img.jpg") is None

    def test_localhost_blocked(self):
        assert _validate_url("http://localhost/img.jpg") is None

    def test_metadata_blocked(self):
        assert _validate_url("http://169.254.169.254/latest/meta-data") is None

    def test_empty_returns_none(self):
        assert _validate_url("") is None

    def test_ftp_blocked(self):
        assert _validate_url("ftp://example.com/img.jpg") is None


class TestResolveUrl:
    def test_google_drive_file_link(self):
        url = "https://drive.google.com/file/d/ABCDEF123/view?usp=sharing"
        resolved = resolve_url(url)
        assert "uc?export=download&id=ABCDEF123" in resolved

    def test_google_drive_open_link(self):
        url = "https://drive.google.com/open?id=XYZ789"
        resolved = resolve_url(url)
        assert "uc?export=download&id=XYZ789" in resolved

    def test_dropbox_link_converted(self):
        url = "https://www.dropbox.com/s/abc123/image.jpg?dl=0"
        resolved = resolve_url(url)
        assert "dl.dropboxusercontent.com" in resolved

    def test_onedrive_link_converted(self):
        url = "https://onedrive.live.com/redir?resid=123"
        resolved = resolve_url(url)
        assert "download?" in resolved

    def test_direct_url_unchanged(self):
        url = "https://example.com/product.jpg"
        assert resolve_url(url) == url
