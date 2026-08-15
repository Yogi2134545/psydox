"""
Regression tests: BatchResult.total_styles vs total_items must be consistent.

total_styles = number of unique style codes
total_items  = total number of URLs (images) across all styles
total        = alias for total_items (backwards-compat)

These are unit tests against run_batch() with mocked downloads — no real HTTP.
"""
import io
import zipfile
from unittest.mock import patch, MagicMock
from PIL import Image
import pytest

from psydox.batch.processor import run_batch, BatchConfig, BatchResult


def _fake_image_bytes(w=100, h=125) -> bytes:
    img = Image.new("RGB", (w, h), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def _patch_download(monkeypatch, success: bool = True, reason: str = ""):
    """Patch _download_with_reason to return a fake image or failure."""
    fake = _fake_image_bytes() if success else None
    monkeypatch.setattr(
        "psydox.batch.processor._download_with_reason",
        lambda url, timeout: (fake, reason),
    )


@pytest.fixture
def cfg():
    return BatchConfig(target_w=800, target_h=1000, max_retries=1)


class TestBatchTotals:
    def test_total_styles_and_total_items(self, monkeypatch, cfg):
        styles = {
            "STYLE_A": ["https://a.com/1.jpg", "https://a.com/2.jpg"],
            "STYLE_B": ["https://b.com/1.jpg"],
            "STYLE_C": ["https://c.com/1.jpg", "https://c.com/2.jpg", "https://c.com/3.jpg"],
        }
        _patch_download(monkeypatch, success=True)
        result = run_batch(styles, cfg)
        assert result.total_styles == 3
        assert result.total_items == 6
        assert result.total == 6  # backwards-compat alias
        assert result.success == 6
        assert result.failed == 0

    def test_total_with_failures(self, monkeypatch, cfg):
        styles = {
            "OK": ["https://a.com/1.jpg", "https://a.com/2.jpg"],
            "BAD": ["https://b.com/1.jpg"],
        }
        call_count = [0]
        def fake_dl(url, timeout):
            call_count[0] += 1
            if "b.com" in url:
                return None, "HTTP 404 Not Found"
            return _fake_image_bytes(), ""
        monkeypatch.setattr("psydox.batch.processor._download_with_reason", fake_dl)
        result = run_batch(styles, cfg)
        assert result.total_styles == 2
        assert result.total_items == 3
        assert result.total == 3
        assert result.success == 2
        assert result.failed == 1

    def test_single_style_single_url(self, monkeypatch, cfg):
        styles = {"X": ["https://x.com/1.jpg"]}
        _patch_download(monkeypatch, success=True)
        result = run_batch(styles, cfg)
        assert result.total_styles == 1
        assert result.total_items == 1
        assert result.total == 1
        assert result.success == 1

    def test_progress_callback_uses_style_count(self, monkeypatch, cfg):
        styles = {
            "A": ["https://a.com/1.jpg"],
            "B": ["https://b.com/1.jpg", "https://b.com/2.jpg"],
        }
        _patch_download(monkeypatch, success=True)

        calls = []
        def cb(done, total, style):
            calls.append((done, total, style))

        run_batch(styles, cfg, progress_cb=cb)
        # All callbacks must pass total == total_styles (2), not total_items (3)
        for done, total, style in calls:
            assert total == 2, f"progress total should be style count (2), got {total}"

    def test_skipped_style_when_all_urls_fail(self, monkeypatch, cfg):
        styles = {
            "GOOD": ["https://a.com/1.jpg"],
            "BAD":  ["https://b.com/1.jpg", "https://b.com/2.jpg"],
        }
        def fake_dl(url, timeout):
            if "b.com" in url:
                return None, "HTTP 404 Not Found"
            return _fake_image_bytes(), ""
        monkeypatch.setattr("psydox.batch.processor._download_with_reason", fake_dl)
        result = run_batch(styles, cfg)
        assert result.skipped == 1
        assert result.success == 1
        assert result.failed == 2
