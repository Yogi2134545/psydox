"""Tests for Quality Engine, Fidelity Engine, and Auto-Fix Engine."""
import sys
import io
import os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def _make_jpeg(w=512, h=512, color=(200, 200, 200)) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ── Quality Engine ─────────────────────────────────────────────────────────────

def test_quality_engine_approved_good_image():
    from psydox.quality.engine import AIQualityEngine, QualityVerdict
    good = _make_jpeg(1024, 1024, (200, 200, 200))
    qs   = AIQualityEngine().score(good)
    assert qs.score > 0
    assert isinstance(qs.verdict, QualityVerdict)


def test_quality_engine_low_res_scores_low():
    from psydox.quality.engine import AIQualityEngine, QualityVerdict
    tiny = _make_jpeg(64, 64)
    qs   = AIQualityEngine().score(tiny)
    assert not qs.resolution_ok
    assert any("resolution" in i.lower() or "low" in i.lower() for i in qs.issues)


def test_quality_engine_with_reference():
    from psydox.quality.engine import AIQualityEngine
    ref  = _make_jpeg(512, 512, (200, 200, 200))
    same = _make_jpeg(512, 512, (200, 200, 200))
    qs   = AIQualityEngine().score(same, ref)
    assert qs.has_reference
    assert qs.color_match_score > 0


def test_quality_engine_color_shift_detected():
    from psydox.quality.engine import AIQualityEngine
    ref    = _make_jpeg(512, 512, (200, 200, 200))  # grey
    result = _make_jpeg(512, 512, (200, 50, 50))     # reddish
    qs     = AIQualityEngine().score(result, ref)
    assert qs.color_match_score < 0.9


def test_quality_score_badge():
    from psydox.quality.engine import AIQualityEngine
    qs = AIQualityEngine().score(_make_jpeg(1024, 1024))
    badge = qs.badge_text()
    assert "/100" in badge


def test_quality_config_custom_thresholds():
    from psydox.quality.engine import AIQualityEngine, QualityConfig, QualityVerdict
    cfg = QualityConfig(approved_threshold=50, review_threshold=20)
    qs  = AIQualityEngine(cfg).score(_make_jpeg(100, 100))
    # At 100x100 with low threshold, might pass
    assert qs.verdict in (QualityVerdict.APPROVED, QualityVerdict.REVIEW, QualityVerdict.NEEDS_FIX)


# ── Fidelity Engine ─────────────────────────────────────────────────────────────

def test_fidelity_score_identical_images():
    from psydox.quality.fidelity import FidelityEngine
    img = _make_jpeg(256, 256)
    fs  = FidelityEngine().score(img, img)
    assert fs.overall_score > 0.8


def test_fidelity_score_different_colors():
    from psydox.quality.fidelity import FidelityEngine
    orig   = _make_jpeg(256, 256, (200, 200, 200))
    result = _make_jpeg(256, 256, (50, 150, 255))
    fs     = FidelityEngine().score(orig, result)
    assert fs.color_score < 0.9


def test_fidelity_logo_unavailable():
    from psydox.quality.fidelity import FidelityEngine
    img = _make_jpeg(256, 256)
    fs  = FidelityEngine().score(img, img)
    assert fs.logo_score is None


def test_fidelity_text_score_unavailable():
    from psydox.quality.fidelity import FidelityEngine
    img = _make_jpeg(256, 256)
    fs  = FidelityEngine().score(img, img)
    assert fs.text_score is None


def test_fidelity_to_dict_has_note():
    from psydox.quality.fidelity import FidelityEngine
    img = _make_jpeg(128, 128)
    d   = FidelityEngine().score(img, img).to_dict()
    assert "note" in d
    assert "approximation" in d["note"].lower() or "provider" in d["note"].lower()


def test_fidelity_no_crash_on_empty():
    from psydox.quality.fidelity import FidelityEngine
    fs = FidelityEngine().score(b"", b"")
    assert fs.confidence == "unavailable"


# ── Auto-Fix Engine ─────────────────────────────────────────────────────────────

def test_autofix_accepts_on_first_try():
    from psydox.quality.autofix import AutoFixEngine
    good = _make_jpeg(1024, 1024, (200, 200, 200))
    engine = AutoFixEngine(max_retries=3)
    result = engine.run("make background white", generate_fn=lambda p: good)
    assert result.best_result is not None
    assert len(result.attempts) >= 1


def test_autofix_exhausts_retries():
    from psydox.quality.autofix import AutoFixEngine
    bad = _make_jpeg(10, 10)  # tiny → fails quality
    engine = AutoFixEngine(max_retries=2)
    result = engine.run("test", generate_fn=lambda p: bad)
    assert len(result.attempts) == 2
    assert result.best_result == bad


def test_autofix_handles_none_from_generator():
    from psydox.quality.autofix import AutoFixEngine
    engine = AutoFixEngine(max_retries=2)
    result = engine.run("test", generate_fn=lambda p: None)
    assert result.best_result is None
    assert len(result.attempts) == 2


def test_autofix_summary_string():
    from psydox.quality.autofix import AutoFixEngine
    good = _make_jpeg(1024, 1024)
    result = AutoFixEngine(max_retries=1).run("test", generate_fn=lambda p: good)
    s = result.summary()
    assert isinstance(s, str)
    assert "attempt" in s.lower()
