"""Tests for nano_banana.mock_provider."""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nano_banana.mock_provider import MockProvider, get_provider, _wrap
from PIL import Image


class TestMockProvider:
    def setup_method(self):
        self.provider = MockProvider()

    def test_generate_image_returns_bytes(self):
        result = self.provider.generate_image("a red shoe on white background")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_output_is_valid_jpeg(self):
        result = self.provider.generate_image("test prompt")
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_output_size_is_1024(self):
        result = self.provider.generate_image("test prompt")
        img = Image.open(io.BytesIO(result))
        assert img.size == (1024, 1024)

    def test_with_reference_image(self):
        ref = io.BytesIO()
        Image.new("RGB", (200, 200), (100, 150, 200)).save(ref, format="JPEG")
        result = self.provider.generate_image("test", reference_image_bytes=ref.getvalue())
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_edit_image(self):
        ref = io.BytesIO()
        Image.new("RGB", (300, 300), (50, 100, 50)).save(ref, format="JPEG")
        result = self.provider.edit_image(ref.getvalue(), "make background white")
        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_empty_prompt(self):
        result = self.provider.generate_image("")
        assert isinstance(result, bytes)

    def test_long_prompt_truncated(self):
        long_prompt = "word " * 500
        result = self.provider.generate_image(long_prompt)
        assert isinstance(result, bytes)


class TestGetProvider:
    def test_returns_real_client_when_debug_off(self, monkeypatch):
        monkeypatch.setenv("DEBUG_MODE", "false")
        # Reload to pick up env change
        import importlib
        import nano_banana.mock_provider as mp
        importlib.reload(mp)
        mp.DEBUG_MODE = False

        class FakeClient:
            pass
        client = FakeClient()
        result = mp.get_provider(client)
        assert result is client

    def test_returns_mock_when_debug_on(self, monkeypatch):
        import nano_banana.mock_provider as mp
        mp.DEBUG_MODE = True
        result = mp.get_provider(object())
        assert isinstance(result, mp.MockProvider)
        mp.DEBUG_MODE = False  # reset


class TestWrap:
    def test_short_line_no_wrap(self):
        lines = _wrap("hello world", 80)
        assert lines == ["hello world"]

    def test_long_line_wraps(self):
        text = "a " * 50
        lines = _wrap(text.strip(), 20)
        assert all(len(l) <= 20 for l in lines)

    def test_empty_returns_empty(self):
        assert _wrap("", 40) == []
