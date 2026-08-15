"""
Regression tests for Gemini image-generation provider pipeline.

Tests 1–13 per the production requirement spec.

All tests use mocks — no live API calls.  Credentials not required.
Run: pytest tests/test_gemini_provider.py -v
"""
import io
import sys
import base64
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# diagnostics.py imports streamlit at module level; stub it before any import
# that may transitively pull it in.
sys.modules.setdefault("streamlit", MagicMock())

from PIL import Image


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_png_bytes(w: int = 64, h: int = 64, colour=(200, 100, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes(w: int = 64, h: int = 64) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (180, 120, 60)).save(buf, format="JPEG")
    return buf.getvalue()


def _make_inline_data_part(image_bytes: bytes, mime: str = "image/png"):
    """Return a mock SDK Part with inline_data containing image bytes."""
    part = MagicMock()
    part.inline_data = MagicMock()
    part.inline_data.data = image_bytes
    part.inline_data.mime_type = mime
    return part


def _make_sdk_response(image_bytes: bytes):
    """Build a minimal mock SDK generateContent response carrying image bytes."""
    part = _make_inline_data_part(image_bytes)
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    response = MagicMock()
    response.candidates = [candidate]
    response.parts = []
    return response


def _make_empty_sdk_response():
    """Build a mock SDK response with NO image data (text-only)."""
    text_part = MagicMock()
    text_part.inline_data = None
    content = MagicMock()
    content.parts = [text_part]
    candidate = MagicMock()
    candidate.content = content
    response = MagicMock()
    response.candidates = [candidate]
    response.parts = []
    return response


# ── TEST 1 — Provider uses the configured model ───────────────────────────────

class TestProviderUsesConfiguredModel(unittest.TestCase):
    def test_configured_model_passed_to_client(self):
        """GeminiImageProvider must forward its configured model to GeminiClient."""
        from psydox.ai_core.providers.gemini import GeminiImageProvider
        from nano_banana.api_client import GEMINI_IMAGE_MODEL

        img_bytes = _make_png_bytes()
        mock_client = MagicMock()
        mock_client.api_key = "test-key"
        mock_client._sdk_ok = True
        mock_client._active_model = GEMINI_IMAGE_MODEL
        mock_client._perf = {"retries": 0}
        mock_client.generate_image.return_value = img_bytes

        provider = GeminiImageProvider(model=GEMINI_IMAGE_MODEL)
        provider._client = mock_client

        provider.generate("a red ball", reference_bytes=_make_png_bytes())

        call_kwargs = mock_client.generate_image.call_args
        assert call_kwargs is not None, "generate_image was not called"
        _model_arg = (
            call_kwargs.kwargs.get("model")
            or (call_kwargs.args[2] if len(call_kwargs.args) > 2 else None)
        )
        self.assertEqual(_model_arg, GEMINI_IMAGE_MODEL,
                         f"Provider passed wrong model: {_model_arg!r}")


# ── TEST 2 — Obsolete model is never selected ─────────────────────────────────

class TestObsoleteModelNeverSelected(unittest.TestCase):
    OBSOLETE_MODELS = [
        "gemini-2.0-flash-preview-image-generation",
        "gemini-2.0-flash-exp-image-generation",
    ]

    def test_registry_does_not_use_obsolete_model(self):
        """provider_registry must not configure any obsolete model name."""
        from psydox.ai_core.provider_registry import _CATALOGUE
        gemini_entry = next(e for e in _CATALOGUE if e["id"] == "gemini")
        for obsolete in self.OBSOLETE_MODELS:
            self.assertNotEqual(
                gemini_entry["default_model"], obsolete,
                f"Registry still uses obsolete model: {obsolete}",
            )

    def test_official_model_list_does_not_contain_obsolete(self):
        """_IMAGE_MODELS_OFFICIAL must not include shut-down model names."""
        from nano_banana.api_client import _IMAGE_MODELS_OFFICIAL
        for obsolete in self.OBSOLETE_MODELS:
            self.assertNotIn(obsolete, _IMAGE_MODELS_OFFICIAL,
                             f"Hint list still contains obsolete: {obsolete}")

    def test_authoritative_constant_is_not_obsolete(self):
        """GEMINI_IMAGE_MODEL constant must not be an obsolete model."""
        from nano_banana.api_client import GEMINI_IMAGE_MODEL
        for obsolete in self.OBSOLETE_MODELS:
            self.assertNotEqual(GEMINI_IMAGE_MODEL, obsolete)


# ── TEST 3 — Image input is correctly encoded ─────────────────────────────────

class TestImageInputEncoding(unittest.TestCase):
    def _call_generate(self, ref_bytes):
        """Call GeminiClient.generate_image with a mock SDK and capture Parts."""
        captured_parts = []

        def fake_generate_content(model, contents, config=None):
            captured_parts.extend(contents)
            return _make_sdk_response(_make_png_bytes())

        mock_sdk = MagicMock()
        mock_sdk.models.generate_content.side_effect = fake_generate_content

        mock_types = MagicMock()
        # Make types.Part(inline_data=...) return a distinct sentinel
        sentinel = object()
        mock_types.Part.return_value = sentinel
        mock_types.Blob.return_value = MagicMock()
        mock_types.GenerateContentConfig.return_value = MagicMock()

        from nano_banana.api_client import GeminiClient, GEMINI_IMAGE_MODEL
        client = GeminiClient.__new__(GeminiClient)
        client.api_key = "test-key"
        client._sdk = mock_sdk
        client._types = mock_types
        client._sdk_ok = True
        client._active_model = GEMINI_IMAGE_MODEL
        client._perf = {"requests": 0, "errors": 0, "retries": 0,
                        "total_time": 0.0, "timings": [], "call_count": 0}

        with patch("nano_banana.mock_provider.DEBUG_MODE", False):
            with patch("nano_banana.api_client.GeminiClient._extract_image_bytes",
                       return_value=_make_png_bytes()):
                with patch.object(client, "find_image_model", return_value=GEMINI_IMAGE_MODEL):
                    client.generate_image("test prompt", reference_image_bytes=ref_bytes,
                                          model=GEMINI_IMAGE_MODEL)

        return mock_types, captured_parts

    def test_pil_object_not_in_parts(self):
        """generate_image must NOT pass a raw PIL Image object in contents."""
        from PIL import Image as _PIL
        mock_types, captured_parts = self._call_generate(_make_png_bytes())
        for part in captured_parts:
            self.assertNotIsInstance(
                part, _PIL.Image,
                "PIL Image object found in contents — SDK may not serialise it correctly",
            )

    def test_types_part_called_for_image(self):
        """generate_image must call types.Part() to build the image part."""
        mock_types, _ = self._call_generate(_make_png_bytes())
        mock_types.Part.assert_called()

    def test_types_blob_called_with_jpeg_mime(self):
        """generate_image must create a Blob with mime_type image/jpeg."""
        mock_types, _ = self._call_generate(_make_png_bytes())
        mock_types.Blob.assert_called()
        call_kwargs = mock_types.Blob.call_args
        mime = (call_kwargs.kwargs.get("mime_type") or
                (call_kwargs.args[0] if call_kwargs.args else None))
        self.assertIn("jpeg", str(mime).lower(),
                      f"Blob MIME type was {mime!r}, expected image/jpeg")


# ── TEST 4 — Text-to-image response parsed ────────────────────────────────────

class TestTextToImageResponseParsed(unittest.TestCase):
    def test_extract_from_candidates_parts(self):
        """_extract_image_bytes must return bytes from candidates[].content.parts."""
        from nano_banana.api_client import GeminiClient
        img = _make_png_bytes()
        response = _make_sdk_response(img)
        result = GeminiClient._extract_image_bytes(response)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    def test_extracted_bytes_open_with_pil(self):
        """Bytes returned by _extract_image_bytes must be a valid image."""
        from nano_banana.api_client import GeminiClient
        img = _make_png_bytes()
        result = GeminiClient._extract_image_bytes(_make_sdk_response(img))
        pil_img = Image.open(io.BytesIO(result))
        w, h = pil_img.size
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)


# ── TEST 5 — Image-edit generation with reference image parsed ────────────────

class TestImageEditResponseParsed(unittest.TestCase):
    def test_extract_from_flat_parts_path(self):
        """_extract_image_bytes must also check response.parts (flat path)."""
        from nano_banana.api_client import GeminiClient
        img = _make_png_bytes(32, 32, (0, 128, 255))

        # Build response where only the flat path has the image
        part = _make_inline_data_part(img)
        response = MagicMock()
        response.candidates = []      # no standard candidates
        response.parts = [part]       # only flat path

        result = GeminiClient._extract_image_bytes(response)
        self.assertIsNotNone(result, "Flat response.parts path not handled")
        self.assertIsInstance(result, bytes)

    def test_base64_data_decoded(self):
        """_extract_image_bytes must decode base64-encoded data strings."""
        from nano_banana.api_client import GeminiClient
        img = _make_png_bytes(16, 16)
        b64_str = base64.b64encode(img).decode()

        part = MagicMock()
        part.inline_data = MagicMock()
        part.inline_data.data = b64_str  # string, not bytes

        content = MagicMock()
        content.parts = [part]
        candidate = MagicMock()
        candidate.content = content
        response = MagicMock()
        response.candidates = [candidate]
        response.parts = []

        result = GeminiClient._extract_image_bytes(response)
        self.assertIsNotNone(result, "base64 string data not decoded")
        self.assertIsInstance(result, bytes)
        self.assertEqual(result, img)


# ── TEST 6 — No-image response produces structured failure ────────────────────

class TestNoImageResponseFailure(unittest.TestCase):
    def test_empty_response_raises_runtime_error(self):
        """generate_image must raise RuntimeError (not return None) on no-image response."""
        from nano_banana.api_client import GeminiClient, GEMINI_IMAGE_MODEL
        mock_sdk = MagicMock()
        mock_sdk.models.generate_content.return_value = _make_empty_sdk_response()
        mock_types = MagicMock()
        mock_types.GenerateContentConfig.return_value = MagicMock()
        mock_types.Part.return_value = MagicMock()
        mock_types.Blob.return_value = MagicMock()

        client = GeminiClient.__new__(GeminiClient)
        client.api_key = "test-key"
        client._sdk = mock_sdk
        client._types = mock_types
        client._sdk_ok = True
        client._active_model = GEMINI_IMAGE_MODEL
        client._perf = {"requests": 0, "errors": 0, "retries": 0,
                        "total_time": 0.0, "timings": [], "call_count": 0}

        with patch("nano_banana.mock_provider.DEBUG_MODE", False):
            with patch.object(client, "find_image_model", return_value=GEMINI_IMAGE_MODEL):
                with self.assertRaises(RuntimeError) as ctx:
                    client.generate_image("test", model=GEMINI_IMAGE_MODEL)

        self.assertIn("no image data", str(ctx.exception).lower(),
                      "RuntimeError message must mention 'no image data'")

    def test_provider_returns_failure_result_on_no_image(self):
        """GeminiImageProvider.generate must return ProviderResult(success=False) on RuntimeError."""
        from psydox.ai_core.providers.gemini import GeminiImageProvider
        from nano_banana.api_client import GEMINI_IMAGE_MODEL

        mock_client = MagicMock()
        mock_client.api_key = "test-key"
        mock_client._sdk_ok = True
        mock_client._active_model = GEMINI_IMAGE_MODEL
        mock_client._perf = {"retries": 0}
        mock_client.generate_image.side_effect = RuntimeError("Gemini returned no image data.")

        provider = GeminiImageProvider(model=GEMINI_IMAGE_MODEL)
        provider._client = mock_client

        result = provider.generate("test")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)


# ── TEST 7 — Invalid API key produces authentication failure ──────────────────

class TestInvalidApiKeyAuthFailure(unittest.TestCase):
    def test_no_api_key_raises_runtime_error(self):
        """generate_image must raise RuntimeError immediately when api_key is empty."""
        from nano_banana.api_client import GeminiClient, GEMINI_IMAGE_MODEL

        client = GeminiClient.__new__(GeminiClient)
        client.api_key = ""
        client._sdk_ok = False
        client._active_model = None
        client._perf = {"requests": 0, "errors": 0, "retries": 0,
                        "total_time": 0.0, "timings": [], "call_count": 0}

        with patch("nano_banana.mock_provider.DEBUG_MODE", False):
            with patch("nano_banana.api_client.GeminiClient._extract_image_bytes"):
                with self.assertRaises(RuntimeError) as ctx:
                    client.generate_image("test", model=GEMINI_IMAGE_MODEL)

        self.assertIn("GOOGLE_API_KEY", str(ctx.exception))

    def test_permission_denied_not_retried(self):
        """PERMISSION_DENIED error from API must not be retried (fail fast)."""
        from nano_banana.api_client import GeminiClient, GEMINI_IMAGE_MODEL

        calls = []
        def fake_generate(model, contents, config=None):
            calls.append(1)
            raise Exception("PERMISSION_DENIED: API key not authorised")

        mock_sdk = MagicMock()
        mock_sdk.models.generate_content.side_effect = fake_generate
        mock_types = MagicMock()
        mock_types.GenerateContentConfig.return_value = MagicMock()
        mock_types.Part.return_value = MagicMock()
        mock_types.Blob.return_value = MagicMock()

        client = GeminiClient.__new__(GeminiClient)
        client.api_key = "bad-key"
        client._sdk = mock_sdk
        client._types = mock_types
        client._sdk_ok = True
        client._active_model = GEMINI_IMAGE_MODEL
        client._perf = {"requests": 0, "errors": 0, "retries": 0,
                        "total_time": 0.0, "timings": [], "call_count": 0}

        with patch("nano_banana.mock_provider.DEBUG_MODE", False):
            with patch.object(client, "find_image_model", return_value=GEMINI_IMAGE_MODEL):
                with self.assertRaises(RuntimeError):
                    client.generate_image("test", model=GEMINI_IMAGE_MODEL)

        self.assertEqual(len(calls), 1, "PERMISSION_DENIED must not be retried")


# ── TEST 8 — Unsupported model produces model failure ─────────────────────────

class TestUnsupportedModelFailure(unittest.TestCase):
    def test_404_not_retried(self):
        """HTTP 404 (unknown model) must fail immediately, not retry."""
        from nano_banana.api_client import GeminiClient, GEMINI_IMAGE_MODEL

        calls = []
        def fake_generate(model, contents, config=None):
            calls.append(1)
            raise Exception("404 Model not found")

        mock_sdk = MagicMock()
        mock_sdk.models.generate_content.side_effect = fake_generate
        mock_types = MagicMock()
        mock_types.GenerateContentConfig.return_value = MagicMock()
        mock_types.Part.return_value = MagicMock()
        mock_types.Blob.return_value = MagicMock()

        client = GeminiClient.__new__(GeminiClient)
        client.api_key = "valid-key"
        client._sdk = mock_sdk
        client._types = mock_types
        client._sdk_ok = True
        client._active_model = GEMINI_IMAGE_MODEL
        client._perf = {"requests": 0, "errors": 0, "retries": 0,
                        "total_time": 0.0, "timings": [], "call_count": 0}

        with patch("nano_banana.mock_provider.DEBUG_MODE", False):
            with patch.object(client, "find_image_model", return_value="nonexistent-model"):
                with self.assertRaises(RuntimeError):
                    client.generate_image("test", model="nonexistent-model")

        self.assertEqual(len(calls), 1, "404 must not be retried")


# ── TEST 9 — AI Studio Lifestyle calls the canonical orchestrator path ─────────

class TestLifestyleUsesOrchestrator(unittest.TestCase):
    def test_lifestyle_feature_calls_orchestrator(self):
        """LifestyleFeature.execute must use AIOrchestrator, not LifestyleGenerator."""
        from psydox.features.lifestyle.service import LifestyleFeature

        captured = []

        class FakeOrchestrator:
            def generate(self, request, run_quality=False):
                captured.append(request)
                result = MagicMock()
                result.success = True
                result.image_bytes = _make_jpeg_bytes()
                result.provider = "gemini"
                result.model = "gemini-3.1-flash-image"
                result.quality_score = 80
                result.quality_verdict = "approved"
                result.cost_estimate = 0.04
                return result

        # get_orchestrator is imported inside the function body; patch it at the
        # source module so the import picks up the replacement.
        with patch("psydox.ai_core.orchestrator.get_orchestrator",
                   return_value=FakeOrchestrator()):
            feature = LifestyleFeature()
            result = feature.execute(
                {"image_bytes": _make_png_bytes(), "style": "Casual Street Style"},
                {},
            )

        self.assertTrue(result["success"], f"Lifestyle execute failed: {result.get('errors')}")
        self.assertEqual(len(captured), 1, "Orchestrator.generate was not called exactly once")


# ── TEST 10 — Lifestyle does not call the legacy direct provider path ──────────

class TestLifestyleNotLegacyPath(unittest.TestCase):
    def test_lifestyle_feature_does_not_use_lifestyle_generator(self):
        """LifestyleFeature must not import or call nano_banana.lifestyle_generator.LifestyleGenerator."""
        import inspect
        from psydox.features.lifestyle import service as ls_svc

        source = inspect.getsource(ls_svc)
        # The class itself must not be imported or instantiated.
        # (Docstring or comments mentioning the name as historical context are OK.)
        self.assertNotIn(
            "from nano_banana.lifestyle_generator import", source,
            "LifestyleFeature must not import LifestyleGenerator",
        )
        self.assertNotIn(
            "LifestyleGenerator()", source,
            "LifestyleFeature must not instantiate LifestyleGenerator",
        )

    def test_executor_lifestyle_calls_feature_not_generator(self):
        """executor._exec_lifestyle must route through LifestyleFeature, not LifestyleGenerator."""
        import inspect
        from psydox.studio import executor
        source = inspect.getsource(executor._exec_lifestyle)
        self.assertIn("LifestyleFeature", source)
        self.assertNotIn("LifestyleGenerator", source)


# ── TEST 11 — Successful generation produces valid image bytes ─────────────────

class TestSuccessfulGenerationValidBytes(unittest.TestCase):
    def test_generate_image_returns_valid_jpeg(self):
        """generate_image must return bytes that PIL can open as a valid image."""
        from nano_banana.api_client import GeminiClient, GEMINI_IMAGE_MODEL

        expected_img = _make_jpeg_bytes(128, 128)
        mock_sdk = MagicMock()
        mock_sdk.models.generate_content.return_value = _make_sdk_response(expected_img)
        mock_types = MagicMock()
        mock_types.GenerateContentConfig.return_value = MagicMock()
        mock_types.Part.return_value = MagicMock()
        mock_types.Blob.return_value = MagicMock()

        client = GeminiClient.__new__(GeminiClient)
        client.api_key = "test-key"
        client._sdk = mock_sdk
        client._types = mock_types
        client._sdk_ok = True
        client._active_model = GEMINI_IMAGE_MODEL
        client._perf = {"requests": 0, "errors": 0, "retries": 0,
                        "total_time": 0.0, "timings": [], "call_count": 0}

        with patch("nano_banana.mock_provider.DEBUG_MODE", False):
            with patch.object(client, "find_image_model", return_value=GEMINI_IMAGE_MODEL):
                result = client.generate_image("test prompt", model=GEMINI_IMAGE_MODEL)

        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)
        pil_img = Image.open(io.BytesIO(result))
        w, h = pil_img.size
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)


# ── TEST 12 — Failed generation does not produce false success ────────────────

class TestFailedGenerationNoFalseSuccess(unittest.TestCase):
    def test_provider_result_success_false_on_exception(self):
        """ProviderResult.success must be False when an exception occurs."""
        from psydox.ai_core.providers.gemini import GeminiImageProvider
        from nano_banana.api_client import GEMINI_IMAGE_MODEL

        mock_client = MagicMock()
        mock_client.api_key = "test-key"
        mock_client._sdk_ok = True
        mock_client._active_model = GEMINI_IMAGE_MODEL
        mock_client._perf = {"retries": 0}
        mock_client.generate_image.side_effect = RuntimeError("API error")

        provider = GeminiImageProvider(model=GEMINI_IMAGE_MODEL)
        provider._client = mock_client
        result = provider.generate("test prompt")

        self.assertFalse(result.success)
        self.assertIsNone(result.image_bytes)
        self.assertIsNotNone(result.error)

    def test_orchestrator_result_success_false_on_provider_failure(self):
        """AIOrchestrator.generate must return AIResult(success=False) when provider fails."""
        from psydox.ai_core.orchestrator import AIOrchestrator, AIRequest
        from psydox.ai_core.router import TaskType

        mock_provider = MagicMock()
        mock_provider.is_available.return_value = True
        mock_provider.generate.return_value = MagicMock(
            success=False, error="provider error", image_bytes=None
        )
        mock_router = MagicMock()
        mock_router.is_deterministic.return_value = False
        mock_router.get_image_provider.return_value = mock_provider

        orch = AIOrchestrator(router=mock_router)
        ai_result = orch.generate(AIRequest(task=TaskType.LIFESTYLE, prompt="test"))

        self.assertFalse(ai_result.success)
        self.assertIsNone(ai_result.image_bytes)


# ── TEST 13 — Failed generation does not permanently charge the user ───────────

class TestFailedGenerationNoCharge(unittest.TestCase):
    def _run_lifecycle_feature(self, fail: bool):
        """Run LifestyleFeature and return the billing-relevant metadata."""
        from psydox.features.lifestyle.service import LifestyleFeature

        mock_result = MagicMock()
        mock_result.success = not fail
        mock_result.image_bytes = None if fail else _make_jpeg_bytes()
        mock_result.error = "provider error" if fail else None
        mock_result.user_message = "AI generation failed." if fail else None
        mock_result.provider = "gemini"
        mock_result.model = "gemini-3.1-flash-image"
        mock_result.quality_score = None
        mock_result.quality_verdict = None
        mock_result.cost_estimate = 0.04  # provider always reports cost

        class FakeOrch:
            def generate(self, req, run_quality=False):
                return mock_result

        # get_orchestrator is imported lazily inside execute(); patch the source module.
        with patch("psydox.ai_core.orchestrator.get_orchestrator",
                   return_value=FakeOrch()):
            feature = LifestyleFeature()
            return feature.execute(
                {"image_bytes": _make_png_bytes(), "style": "Casual Street Style"},
                {},
            )

    def test_success_metadata_has_cost(self):
        """Successful generation carries cost metadata (billing is permitted)."""
        result = self._run_lifecycle_feature(fail=False)
        self.assertTrue(result["success"])
        cost = result.get("metadata", {}).get("cost_estimate")
        self.assertIsNotNone(cost, "Successful result must include cost_estimate")

    def test_failure_result_has_no_cost_in_outputs(self):
        """Failed generation must not produce outputs (nothing to bill for)."""
        result = self._run_lifecycle_feature(fail=True)
        self.assertFalse(result["success"])
        self.assertEqual(result.get("outputs", []), [],
                         "Failed generation must not produce any outputs")

    def test_failure_has_error_message(self):
        """Failed generation must surface an error message."""
        result = self._run_lifecycle_feature(fail=True)
        self.assertFalse(result["success"])
        self.assertGreater(len(result.get("errors", [])), 0,
                           "Failed generation must produce at least one error message")


if __name__ == "__main__":
    unittest.main(verbosity=2)
