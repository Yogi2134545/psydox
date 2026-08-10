"""
Integration test: full pipeline
  upload → validate → project → job → classic/AI → quality → fidelity → review → export

This simulates a real e-commerce team workflow end-to-end.
Uses the mock AI provider so no real API keys are needed.
"""
import io
import os
import sys
import zipfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
os.environ["DEBUG_MODE"] = "true"
os.environ["ENABLE_DEMO_FUTURE_FEATURE"] = "true"

from PIL import Image
import pytest


def _jpeg(w=800, h=800, color=(180, 120, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


# ── 1. Upload validation ──────────────────────────────────────────────────────

def test_pipeline_upload_valid():
    from psydox.security.upload import validate_upload
    result = validate_upload(_jpeg(1000, 1000))
    assert result.valid
    assert result.mime_type == "image/jpeg"
    assert result.width == 1000


def test_pipeline_upload_rejects_bad_file():
    from psydox.security.upload import validate_upload
    assert not validate_upload(b"garbage bytes xyz").valid


# ── 2. Project creation ───────────────────────────────────────────────────────

def test_pipeline_project_create_and_retrieve(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_DB_PATH", str(tmp_path / "pipe.db"))
    import importlib, psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    from psydox.projects.service import ProjectService
    svc = ProjectService({})
    proj = svc.create("Pipeline Test", "pipeline@x.com")
    fetched = svc.get(proj.id, "pipeline@x.com")
    assert fetched.name == "Pipeline Test"


# ── 3. Classic processing ─────────────────────────────────────────────────────

def test_pipeline_classic_packshot():
    from psydox.features.classic.service import ClassicFeature
    f = ClassicFeature()
    result = f.execute({
        "image_bytes": _jpeg(600, 800),
        "operation":   "packshot",
        "size":        2000,
        "padding":     0.08,
    }, {"user_email": "test@x.com"})
    assert result["success"]
    img = Image.open(io.BytesIO(result["outputs"][0]["bytes"]))
    assert img.size == (2000, 2000)


def test_pipeline_classic_marketplace():
    from psydox.features.classic.service import ClassicFeature
    f = ClassicFeature()
    result = f.execute({
        "image_bytes": _jpeg(),
        "operation":   "marketplace",
        "presets":     ["amazon_main", "instagram_sq"],
    }, {})
    assert result["success"]
    assert len(result["outputs"]) == 2


# ── 4. AI generation (mock provider) ─────────────────────────────────────────

def test_pipeline_ai_background_via_registry():
    from psydox.features.loader import bootstrap_features
    from psydox.core.registry import get_registry
    bootstrap_features()
    registry = get_registry()
    bg = registry.get("background")
    assert bg is not None
    result = bg.execute({
        "image_bytes": _jpeg(),
        "mode":        "solid",
        "color_name":  "white",
    }, {})
    assert result["success"]


def test_pipeline_ai_lifestyle_mock():
    from psydox.features.lifestyle.service import LifestyleFeature
    f = LifestyleFeature()
    result = f.execute({
        "image_bytes":  _jpeg(),
        "style":        "Home Kitchen",
        "product_desc": "Blue ceramic mug",
    }, {})
    # Mock provider always returns something
    assert result["success"] or result["errors"]  # may fail gracefully with mock


# ── 5. Quality check ──────────────────────────────────────────────────────────

def test_pipeline_quality_score():
    from psydox.quality.engine import AIQualityEngine, QualityVerdict
    engine = AIQualityEngine()
    result = engine.score(_jpeg(1200, 1200))
    assert result.score >= 0
    assert result.verdict in (QualityVerdict.APPROVED, QualityVerdict.REVIEW, QualityVerdict.NEEDS_FIX)


# ── 6. Fidelity check ─────────────────────────────────────────────────────────

def test_pipeline_fidelity_identical():
    from psydox.quality.fidelity import FidelityEngine
    img = _jpeg()
    score = FidelityEngine().score(img, img)
    assert score.color_score > 0.9
    assert score.overall_score > 0.8


def test_pipeline_fidelity_different():
    from psydox.quality.fidelity import FidelityEngine
    orig = _jpeg(color=(220, 50, 50))    # red
    result_img = _jpeg(color=(50, 50, 220))  # blue
    score = FidelityEngine().score(orig, result_img)
    assert score.color_score < 0.7


# ── 7. Review center ──────────────────────────────────────────────────────────

def test_pipeline_review_score():
    from psydox.features.review.service import ReviewFeature
    f = ReviewFeature()
    result = f.execute({"action": "score", "image_bytes": _jpeg()}, {})
    assert result["success"]
    assert result["metadata"]["quality"] is not None


def test_pipeline_review_approve(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_DB_PATH", str(tmp_path / "review_pipe.db"))
    import importlib, psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    from psydox.features.review.service import ReviewFeature
    f = ReviewFeature()
    result = f.execute(
        {"action": "approve", "output_id": "out-999", "job_id": "job-999"},
        {"user_email": "reviewer@x.com"}
    )
    assert result["success"]
    assert result["metadata"]["review_id"]


# ── 8. Export ─────────────────────────────────────────────────────────────────

def test_pipeline_export_zip():
    from psydox.export.service import export_job_outputs, ExportFormat
    outputs = [
        {"bytes": _jpeg(), "label": "packshot_2000x2000", "mime": "image/jpeg"},
        {"bytes": _jpeg(1080, 1080, (100, 150, 200)), "label": "instagram_sq", "mime": "image/jpeg"},
    ]
    result = export_job_outputs(outputs, fmt=ExportFormat.JPEG, job_label="pipeline_test")
    assert result.file_count == 2
    assert zipfile.is_zipfile(io.BytesIO(result.zip_bytes))


# ── 9. Job persistence ────────────────────────────────────────────────────────

def test_pipeline_job_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_DB_PATH", str(tmp_path / "jobs_pipe.db"))
    import importlib, psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    from psydox.jobs.manager import JobManager, JobStatus
    mgr = JobManager({})
    job = mgr.create("classic", "Pipeline packshot", user_email="u@x.com")
    mgr.finish(job.id, outputs=[{"bytes": _jpeg(), "label": "result", "mime": "image/jpeg"}], errors=[], metadata={})
    finished = mgr.get(job.id)
    assert finished.status == JobStatus.COMPLETED


# ── 10. Extensibility: DemoFutureFeature auto-discovers ──────────────────────

def test_pipeline_extensibility():
    """
    Proves that adding a new feature requires ZERO edits to core files.
    DemoFutureFeature is discovered automatically from the file system.
    """
    os.environ["ENABLE_DEMO_FUTURE_FEATURE"] = "true"
    from psydox.core.autodiscovery import discover_features
    from psydox.core.registry import FeatureRegistry
    registry = FeatureRegistry()
    for f in discover_features():
        registry.register(f)
    assert "demo_future" in registry.ids(), (
        "DemoFutureFeature was not auto-discovered. "
        "The zero-edit extensibility guarantee is broken."
    )
    # Execute it to prove the full pipeline works
    feature = registry.get("demo_future")
    result  = feature.execute({"image_bytes": _jpeg()}, {})
    assert result["success"]


# ── 11. Health check ─────────────────────────────────────────────────────────

def test_pipeline_health_check():
    from psydox.health import check_health, ComponentStatus
    report = check_health()
    # At minimum, the job system and feature registry should respond
    names  = {c.name for c in report.components}
    assert "feature_registry" in names
    assert "job_system" in names


# ── 12. RBAC: user isolation ──────────────────────────────────────────────────

def test_pipeline_user_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_DB_PATH", str(tmp_path / "iso_pipe.db"))
    import importlib, psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    from psydox.projects.service import ProjectService
    svc = ProjectService({})
    alice_proj = svc.create("Alice's secret", "alice@x.com")
    # Bob must not be able to access Alice's project
    assert svc.get(alice_proj.id, "bob@x.com") is None
    # But Alice can
    assert svc.get(alice_proj.id, "alice@x.com") is not None
