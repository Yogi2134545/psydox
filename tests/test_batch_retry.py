"""
Regression tests: retry logic in run_batch().

Retryable errors (429, 5xx, timeout, network error) should be retried up to
max_retries times with exponential backoff. Permanent errors (404, 403, etc.)
must NOT be retried.
"""
import io
import time
from unittest.mock import patch, call
from PIL import Image
import pytest

from psydox.batch.processor import (
    run_batch, BatchConfig, _is_retryable_reason,
    _RETRYABLE_HTTP_CODES, _PERMANENT_HTTP_CODES,
)


def _fake_image_bytes() -> bytes:
    img = Image.new("RGB", (100, 125), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def cfg():
    return BatchConfig(target_w=800, target_h=1000, max_retries=3)


class TestIsRetryableReason:
    def test_all_retryable_codes(self):
        for code in _RETRYABLE_HTTP_CODES:
            assert _is_retryable_reason(f"HTTP {code} error"), f"HTTP {code} should be retryable"

    def test_all_permanent_codes(self):
        for code in _PERMANENT_HTTP_CODES:
            assert not _is_retryable_reason(f"HTTP {code} error"), f"HTTP {code} should be permanent"

    def test_timeout_retryable(self):
        assert _is_retryable_reason("Connection timeout after 30s")

    def test_network_error_retryable(self):
        assert _is_retryable_reason("Network error: connection refused")

    def test_connection_reset_retryable(self):
        assert _is_retryable_reason("Connection reset by peer")

    def test_invalid_image_permanent(self):
        assert not _is_retryable_reason("Invalid image content: cannot identify image file")

    def test_html_permanent(self):
        assert not _is_retryable_reason("Download failed: unexpected Content-Type text/html")

    def test_empty_string_permanent(self):
        assert not _is_retryable_reason("")


class TestRetryBehavior:
    def test_retryable_error_retries_up_to_max(self, monkeypatch, cfg):
        """A transient 429 should trigger max_retries attempts total."""
        call_count = [0]
        def fake_dl(url, timeout):
            call_count[0] += 1
            return None, "HTTP 429 Too Many Requests"

        monkeypatch.setattr("psydox.batch.processor._download_with_reason", fake_dl)
        monkeypatch.setattr("time.sleep", lambda s: None)

        styles = {"X": ["https://x.com/1.jpg"]}
        result = run_batch(styles, cfg)
        assert call_count[0] == cfg.max_retries, (
            f"Expected {cfg.max_retries} attempts for retryable error, got {call_count[0]}"
        )
        assert result.failed == 1

    def test_permanent_error_does_not_retry(self, monkeypatch, cfg):
        """A 404 must not trigger any retries — only one attempt."""
        call_count = [0]
        def fake_dl(url, timeout):
            call_count[0] += 1
            return None, "HTTP 404 Not Found"

        monkeypatch.setattr("psydox.batch.processor._download_with_reason", fake_dl)

        styles = {"X": ["https://x.com/1.jpg"]}
        result = run_batch(styles, cfg)
        assert call_count[0] == 1, (
            f"Expected 1 attempt for permanent error (404), got {call_count[0]}"
        )
        assert result.failed == 1

    def test_success_on_second_attempt(self, monkeypatch, cfg):
        """If first attempt fails with a retryable error but second succeeds,
        the item must be counted as success."""
        call_count = [0]
        def fake_dl(url, timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                return None, "HTTP 503 Service Unavailable"
            return _fake_image_bytes(), ""

        monkeypatch.setattr("psydox.batch.processor._download_with_reason", fake_dl)
        monkeypatch.setattr("time.sleep", lambda s: None)

        styles = {"X": ["https://x.com/1.jpg"]}
        result = run_batch(styles, cfg)
        assert call_count[0] == 2
        assert result.success == 1
        assert result.failed == 0

    def test_mixed_retry_and_permanent_per_item(self, monkeypatch, cfg):
        """One URL is transient (eventually succeeds), another is permanent (fails once)."""
        counters: dict = {}
        def fake_dl(url, timeout):
            counters[url] = counters.get(url, 0) + 1
            if "good.com" in url:
                if counters[url] <= 1:
                    return None, "HTTP 502 Bad Gateway"
                return _fake_image_bytes(), ""
            return None, "HTTP 404 Not Found"

        monkeypatch.setattr("psydox.batch.processor._download_with_reason", fake_dl)
        monkeypatch.setattr("time.sleep", lambda s: None)

        styles = {
            "TRANSIENT": ["https://good.com/1.jpg"],
            "PERMANENT": ["https://dead.com/1.jpg"],
        }
        result = run_batch(styles, cfg)
        assert result.success == 1
        assert result.failed == 1
        assert counters["https://good.com/1.jpg"] == 2
        assert counters["https://dead.com/1.jpg"] == 1
