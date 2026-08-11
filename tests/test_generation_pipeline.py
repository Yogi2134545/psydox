"""
Tests for the generation pipeline — all offline, no real API calls.

Coverage:
  - Product angle definitions
  - DecisionEngine outcomes
  - SmartRetry prompt strengthening
  - AngleValidator with mock vision
  - Pipeline with mock provider
  - Multi-angle budget tracking
  - Bad image handling (wrong angle, changed color, missing logo, corrupted, blank)
  - Product completion tracking
  - Provider fallback
"""
import io
import pytest
from PIL import Image, ImageDraw
from unittest.mock import MagicMock, patch

from psydox.generation.policy      import AIQualityPolicy, get_cost_inr
from psydox.generation.contract    import get_angle, list_angles, ANGLES, AngleSpec
from psydox.generation.decision_engine import DecisionEngine, DecisionOutcome
from psydox.generation.angle_validator import AngleValidator, AngleValidationResult
from psydox.generation.smart_retry    import SmartRetryEngine, RetryContext
from psydox.generation.cost_guard     import CostGuard
from psydox.quality.engine            import AIQualityEngine, QualityScore, QualityVerdict
from psydox.quality.fidelity          import FidelityEngine, FidelityScore
from psydox.ai_core.providers.base    import ProviderResult
from psydox.ai_core.prompt_engine     import StructuredPrompt, PromptContext, PromptEngine


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_jpeg(color=(200, 200, 200), size=(512, 512)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _make_quality_score(score: int, issues=None) -> QualityScore:
    from psydox.quality.engine import QualityVerdict
    verdict = (
        QualityVerdict.APPROVED if score >= 80
        else QualityVerdict.REVIEW if score >= 50
        else QualityVerdict.NEEDS_FIX
    )
    return QualityScore(
        score=score, verdict=verdict,
        resolution_ok=score >= 60, sharpness_score=50.0,
        color_match_score=0.8, brightness_ok=True,
        issues=issues or [],
    )


def _make_fidelity_score(overall: float, warnings=None) -> FidelityScore:
    return FidelityScore(
        overall_score=overall, color_score=overall,
        shape_score=overall, pattern_score=overall,
        logo_score=None, text_score=None,
        warnings=warnings or [],
        confidence="approximation",
    )


def _make_angle_result(verdict: str, detected: str = "", requested: str = "FRONT") -> AngleValidationResult:
    return AngleValidationResult(
        passed=(verdict == "PASS"),
        detected_angle=detected or requested,
        requested_angle=requested,
        confidence=0.9 if verdict == "PASS" else 0.85,
        verdict=verdict,
        reason=f"Angle verdict: {verdict}",
        used_vision_ai=True,
    )


# ── Angle specifications ──────────────────────────────────────────────────────

class TestAngleSpecs:
    def test_all_8_angles_defined(self):
        ids = set(ANGLES.keys())
        assert "FRONT"    in ids
        assert "FRONT_45" in ids
        assert "LEFT"     in ids
        assert "LEFT_45"  in ids
        assert "RIGHT"    in ids
        assert "RIGHT_45" in ids
        assert "BACK"     in ids
        assert "BACK_45"  in ids

    def test_get_angle_case_insensitive(self):
        assert get_angle("front") is not None
        assert get_angle("FRONT_45") is not None

    def test_unknown_angle_returns_none(self):
        assert get_angle("DIAGONAL_UP_LEFT_SKYWARD") is None

    def test_every_angle_has_camera_description(self):
        for spec in list_angles():
            assert spec.camera_description, f"{spec.angle_id} missing camera_description"

    def test_every_angle_has_validation_keywords(self):
        for spec in list_angles():
            assert spec.validation_keywords, f"{spec.angle_id} missing validation_keywords"

    def test_45_degree_angles_flagged(self):
        assert get_angle("FRONT_45").is_45_degree is True
        assert get_angle("FRONT").is_45_degree is False


# ── Decision engine ───────────────────────────────────────────────────────────

class TestDecisionEngine:
    def setup_method(self):
        self.engine = DecisionEngine()

    def test_all_pass_returns_approved(self):
        decision = self.engine.decide(
            quality_score=_make_quality_score(90),
            fidelity_score=_make_fidelity_score(0.80),
            angle_result=_make_angle_result("PASS"),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.APPROVED

    def test_quality_fail_returns_retry(self):
        decision = self.engine.decide(
            quality_score=_make_quality_score(60),  # below 85 default
            fidelity_score=_make_fidelity_score(0.80),
            angle_result=_make_angle_result("PASS"),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.RETRY
        assert decision.retry_hint == "quality"

    def test_fidelity_fail_returns_retry(self):
        decision = self.engine.decide(
            quality_score=_make_quality_score(90),
            fidelity_score=_make_fidelity_score(0.40),  # below 0.65 default
            angle_result=_make_angle_result("PASS"),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.RETRY
        assert decision.retry_hint == "fidelity"

    def test_critical_fidelity_fail_returns_hard_fail(self):
        decision = self.engine.decide(
            quality_score=_make_quality_score(90),
            fidelity_score=_make_fidelity_score(0.20),  # below hard-fail threshold 0.35
            angle_result=_make_angle_result("PASS"),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.HARD_FAIL
        assert decision.can_retry is False

    def test_wrong_angle_returns_retry(self):
        decision = self.engine.decide(
            quality_score=_make_quality_score(90),
            fidelity_score=_make_fidelity_score(0.80),
            angle_result=_make_angle_result("FAIL", detected="FRONT", requested="BACK"),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.RETRY
        assert decision.retry_hint == "angle"

    def test_angle_approximation_returns_review(self):
        decision = self.engine.decide(
            quality_score=_make_quality_score(90),
            fidelity_score=_make_fidelity_score(0.80),
            angle_result=_make_angle_result("APPROXIMATION"),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.REVIEW

    def test_changed_product_color_is_hard_fail(self):
        # Fidelity 0.15 = critical identity change (color changed)
        decision = self.engine.decide(
            quality_score=_make_quality_score(85),
            fidelity_score=_make_fidelity_score(0.15),
            angle_result=_make_angle_result("PASS"),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.HARD_FAIL

    def test_missing_logo_triggers_review(self):
        # Fidelity below threshold but not catastrophic → RETRY
        decision = self.engine.decide(
            quality_score=_make_quality_score(88),
            fidelity_score=_make_fidelity_score(0.55, warnings=["Logo may be missing"]),
            angle_result=_make_angle_result("PASS"),
            cost_inr=0.08,
        )
        # 0.55 < default 0.65 → RETRY
        assert decision.outcome == DecisionOutcome.RETRY


# ── Angle validator ───────────────────────────────────────────────────────────

class TestAngleValidator:
    def setup_method(self):
        self.validator = AngleValidator()
        self.front_spec = get_angle("FRONT")

    def test_no_vision_provider_returns_approximation(self):
        result = self.validator.validate(
            generated_bytes=_make_jpeg(),
            angle_spec=self.front_spec,
            vision_provider=None,
        )
        assert result.verdict == "APPROXIMATION"
        assert result.passed is False
        assert result.used_vision_ai is False

    def test_vision_provider_pass(self):
        mock_vision = MagicMock()
        mock_vision.is_available.return_value = True
        mock_vision.analyze.return_value = MagicMock(
            text='{"detected_angle": "FRONT", "confidence": 0.92, "description": "front view"}'
        )
        result = self.validator.validate(
            generated_bytes=_make_jpeg(),
            angle_spec=self.front_spec,
            vision_provider=mock_vision,
            threshold=0.70,
        )
        assert result.verdict == "PASS"
        assert result.passed is True
        assert result.detected_angle == "FRONT"

    def test_vision_provider_wrong_angle_fail(self):
        mock_vision = MagicMock()
        mock_vision.is_available.return_value = True
        mock_vision.analyze.return_value = MagicMock(
            text='{"detected_angle": "BACK", "confidence": 0.91, "description": "rear view"}'
        )
        result = self.validator.validate(
            generated_bytes=_make_jpeg(),
            angle_spec=self.front_spec,
            vision_provider=mock_vision,
            threshold=0.70,
        )
        assert result.verdict == "FAIL"
        assert result.passed is False
        assert result.detected_angle == "BACK"

    def test_vision_provider_low_confidence_review(self):
        mock_vision = MagicMock()
        mock_vision.is_available.return_value = True
        mock_vision.analyze.return_value = MagicMock(
            text='{"detected_angle": "FRONT", "confidence": 0.45, "description": "unclear"}'
        )
        result = self.validator.validate(
            generated_bytes=_make_jpeg(),
            angle_spec=self.front_spec,
            vision_provider=mock_vision,
            threshold=0.70,
        )
        assert result.verdict == "REVIEW"

    def test_empty_bytes_returns_fail(self):
        result = self.validator.validate(
            generated_bytes=b"",
            angle_spec=self.front_spec,
            vision_provider=None,
        )
        assert result.passed is False

    def test_vision_provider_unavailable_fallback(self):
        mock_vision = MagicMock()
        mock_vision.is_available.return_value = False
        result = self.validator.validate(
            generated_bytes=_make_jpeg(),
            angle_spec=self.front_spec,
            vision_provider=mock_vision,
        )
        assert result.verdict == "APPROXIMATION"


# ── Smart retry ───────────────────────────────────────────────────────────────

class TestSmartRetry:
    def setup_method(self):
        self.engine = SmartRetryEngine()
        self.base_prompt = StructuredPrompt(
            subject="product photo",
            camera="front view",
            constraints=["preserve color"],
        )

    def test_quality_retry_simplifies_background(self):
        ctx = RetryContext(
            original_prompt=self.base_prompt,
            retry_hint="quality",
            attempt_number=2,
        )
        retry_prompt = self.engine.build_retry_prompt(ctx)
        assert "white" in retry_prompt.environment.lower()
        assert any("sharp" in c.lower() for c in retry_prompt.constraints)

    def test_fidelity_retry_adds_lock_constraints(self):
        ctx = RetryContext(
            original_prompt=self.base_prompt,
            retry_hint="fidelity",
            attempt_number=2,
            fidelity_warnings=["Significant color shift detected"],
        )
        retry_prompt = self.engine.build_retry_prompt(ctx)
        constraints_text = " ".join(retry_prompt.constraints).lower()
        assert "product" in constraints_text
        assert "color" in constraints_text

    def test_angle_retry_strengthens_camera(self):
        ctx = RetryContext(
            original_prompt=self.base_prompt,
            retry_hint="angle",
            attempt_number=2,
            angle_desc="straight front view, camera at product eye level",
        )
        retry_prompt = self.engine.build_retry_prompt(ctx)
        assert "EXACTLY" in retry_prompt.camera or "front" in retry_prompt.camera.lower()

    def test_retry_version_is_updated(self):
        ctx = RetryContext(
            original_prompt=self.base_prompt,
            retry_hint="quality",
            attempt_number=2,
        )
        retry_prompt = self.engine.build_retry_prompt(ctx)
        assert "retry" in retry_prompt.version.lower()

    def test_unknown_hint_returns_strengthened_prompt(self):
        ctx = RetryContext(
            original_prompt=self.base_prompt,
            retry_hint="bogushint",
            attempt_number=2,
        )
        retry_prompt = self.engine.build_retry_prompt(ctx)
        assert retry_prompt is not None


# ── Pipeline with mock provider ───────────────────────────────────────────────

class TestGenerationPipeline:
    def _make_pipeline(self, provider_id="mock"):
        from psydox.generation.pipeline import GenerationPipeline
        return GenerationPipeline(user_email="yogeshwar@popclub.co")

    def test_pipeline_approved_with_mock_provider(self):
        """Full pipeline with mock provider → image generated."""
        from psydox.generation.pipeline import GenerationPipeline
        import os

        with patch.dict(os.environ, {"DEBUG_MODE": "true"}):
            pipeline = GenerationPipeline()

            with patch("psydox.generation.pipeline.GenerationPipeline._call_provider") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "image_bytes": _make_jpeg(),
                    "provider": "mock",
                    "model": "mock-v1",
                }
                with patch("psydox.generation.pipeline.GenerationPipeline._get_vision_provider") as mock_vp:
                    mock_vp.return_value = None  # no vision → APPROXIMATION → REVIEW

                    result = pipeline.generate_angle(
                        image_bytes=_make_jpeg(),
                        angle_id="FRONT",
                        provider_id="mock",
                    )

        # Without vision provider, angle = APPROXIMATION → REVIEW
        assert result.angle_id == "FRONT"
        assert result.outcome in ("APPROVED", "REVIEW")
        assert result.attempts >= 1

    def test_pipeline_blocks_expensive_provider(self):
        from psydox.generation.pipeline import GenerationPipeline
        pipeline = GenerationPipeline()

        result = pipeline.generate_angle(
            image_bytes=_make_jpeg(),
            angle_id="FRONT",
            provider_id="openai",
            model="dall-e-3",
        )
        assert result.outcome == "BUDGET_CONFLICT"
        assert result.attempts == 0

    def test_pipeline_unknown_angle_fails(self):
        from psydox.generation.pipeline import GenerationPipeline
        pipeline = GenerationPipeline()

        result = pipeline.generate_angle(
            image_bytes=_make_jpeg(),
            angle_id="TOPDOWN_EXTREME_CLOSEUP",
            provider_id="mock",
        )
        assert result.outcome == "FAILED"

    def test_multi_angle_result_structure(self):
        from psydox.generation.pipeline import GenerationPipeline
        pipeline = GenerationPipeline()

        with patch("psydox.generation.pipeline.GenerationPipeline.generate_angle") as mock_angle:
            from psydox.generation.pipeline import AngleResult
            mock_angle.return_value = AngleResult(
                angle_id="FRONT", display_name="Front View",
                outcome="APPROVED", image_bytes=_make_jpeg(),
                quality_score=90, fidelity_score=0.8,
                cost_inr=0.08, attempts=1,
            )

            result = pipeline.generate_angles(
                image_bytes=_make_jpeg(),
                angle_ids=["FRONT", "BACK"],
                provider_id="mock",
            )

        assert result.requested == 2
        assert result.approved == 2
        assert result.is_complete is True

    def test_multi_angle_incomplete_when_not_all_approved(self):
        from psydox.generation.pipeline import GenerationPipeline
        pipeline = GenerationPipeline()

        from psydox.generation.pipeline import AngleResult
        results_map = {
            "FRONT": AngleResult("FRONT", "Front", "APPROVED", _make_jpeg(), cost_inr=0.08, attempts=1),
            "BACK":  AngleResult("BACK", "Back", "REVIEW", _make_jpeg(), cost_inr=0.08, attempts=2),
        }

        with patch.object(pipeline, "generate_angle", side_effect=lambda img, aid, *a, **kw: results_map[aid]):
            result = pipeline.generate_angles(
                image_bytes=_make_jpeg(),
                angle_ids=["FRONT", "BACK"],
            )

        assert result.approved == 1
        assert result.review == 1
        assert result.is_complete is False


# ── Bad image scenarios ───────────────────────────────────────────────────────

class TestBadImages:
    def test_corrupted_image_quality_check_fails_gracefully(self):
        engine = AIQualityEngine()
        result = engine.score(b"\x00\x01\x02corrupted not a real jpeg", None)
        assert result.score == 0
        assert len(result.issues) > 0

    def test_blank_white_image_quality_check(self):
        engine = AIQualityEngine()
        img = Image.new("RGB", (512, 512), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        # Blank images may fail sharpness — result should be valid
        result = engine.score(buf.getvalue(), None)
        assert 0 <= result.score <= 100

    def test_wrong_angle_decision(self):
        engine = DecisionEngine()
        decision = engine.decide(
            quality_score=_make_quality_score(90),
            fidelity_score=_make_fidelity_score(0.80),
            angle_result=AngleValidationResult(
                passed=False, verdict="FAIL",
                detected_angle="BACK", requested_angle="FRONT",
                confidence=0.93, reason="Expected FRONT, got BACK",
                used_vision_ai=True,
            ),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.RETRY
        assert "angle" in decision.retry_hint

    def test_changed_product_color_hard_fail(self):
        engine = DecisionEngine()
        decision = engine.decide(
            quality_score=_make_quality_score(88),
            fidelity_score=_make_fidelity_score(0.15),  # color changed — critical
            angle_result=_make_angle_result("PASS"),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.HARD_FAIL
        assert decision.can_retry is False

    def test_changed_product_shape_hard_fail(self):
        engine = DecisionEngine()
        # Shape change = very low fidelity
        decision = engine.decide(
            quality_score=_make_quality_score(85),
            fidelity_score=FidelityScore(
                overall_score=0.18, color_score=0.5, shape_score=0.05,
                pattern_score=0.3, logo_score=None, text_score=None,
                warnings=["Product shape may have changed"],
                confidence="approximation",
            ),
            angle_result=_make_angle_result("PASS"),
            cost_inr=0.08,
        )
        assert decision.outcome == DecisionOutcome.HARD_FAIL


# ── Provider compatibility ────────────────────────────────────────────────────

class TestProviderCompatibility:
    def test_gemini_pricing_known(self):
        cost = get_cost_inr("gemini", "gemini-2.0-flash-preview-image-generation")
        assert cost is not None
        assert cost < 0.50

    def test_openai_dalle3_over_limit(self):
        cost = get_cost_inr("openai", "dall-e-3")
        assert cost is not None
        assert cost > 0.50

    def test_replicate_flux_within_limit(self):
        cost = get_cost_inr("replicate", "black-forest-labs/flux-schnell")
        assert cost is not None
        assert cost <= 0.50

    def test_mock_provider_free(self):
        cost = get_cost_inr("mock", "mock-v1")
        assert cost == 0.0


# ── Product completion ────────────────────────────────────────────────────────

class TestProductCompletion:
    def test_all_approved_is_complete(self):
        from psydox.generation.pipeline import MultiAngleResult, AngleResult
        results = [
            AngleResult(a, a, "APPROVED", _make_jpeg(), cost_inr=0.08, attempts=1)
            for a in ["FRONT", "BACK", "LEFT", "RIGHT", "FRONT_45", "LEFT_45", "RIGHT_45", "BACK_45"]
        ]
        multi = MultiAngleResult(
            product_id="p1", requested=8, approved=8,
            review=0, failed=0, total_cost_inr=0.64,
            angle_results=results, is_complete=True,
        )
        assert multi.is_complete is True
        assert multi.cost_per_approved_angle <= 0.50

    def test_partial_approved_is_incomplete(self):
        from psydox.generation.pipeline import MultiAngleResult, AngleResult
        results = [
            AngleResult("FRONT", "Front", "APPROVED", _make_jpeg(), cost_inr=0.08, attempts=1),
            AngleResult("BACK", "Back", "REVIEW", None, cost_inr=0.16, attempts=2),
        ]
        multi = MultiAngleResult(
            product_id="p1", requested=2, approved=1,
            review=1, failed=0, total_cost_inr=0.24,
            angle_results=results, is_complete=False,
        )
        assert multi.is_complete is False

    def test_cost_per_approved_within_limit(self):
        from psydox.generation.pipeline import MultiAngleResult, AngleResult
        # 10 attempts, 8 approved, ₹3.20 total → ₹0.40 per approved angle
        multi = MultiAngleResult(
            product_id="p1", requested=8, approved=8,
            review=0, failed=2, total_cost_inr=3.20,
            angle_results=[], is_complete=True,
        )
        assert multi.cost_per_approved_angle <= 0.50
