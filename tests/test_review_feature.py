"""Tests for ReviewFeature."""
import io
import sys
import os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
os.environ["DEBUG_MODE"] = "true"
from PIL import Image


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (600, 600), (180, 180, 180)).save(buf, "JPEG")
    return buf.getvalue()


def _make_review_feature():
    from psydox.features.review.service import ReviewFeature
    return ReviewFeature()


def test_review_manifest():
    f = _make_review_feature()
    assert f.manifest.id == "review"
    assert not f.manifest.requires_ai


def test_score_action_returns_quality():
    f = _make_review_feature()
    result = f.execute({"action": "score", "image_bytes": _jpeg()}, {})
    assert result["success"]
    assert "quality" in result["metadata"]
    assert result["metadata"]["quality"] is not None


def test_score_with_reference():
    f = _make_review_feature()
    img = _jpeg()
    result = f.execute({"action": "score", "image_bytes": img, "original_bytes": img}, {})
    assert result["success"]
    assert result["metadata"].get("fidelity") is not None


def test_approve_records_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_DB_PATH", str(tmp_path / "review.db"))
    import importlib, psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    f = _make_review_feature()
    result = f.execute(
        {"action": "approve", "output_id": "out-001", "job_id": "job-001"},
        {"user_email": "reviewer@x.com"}
    )
    assert result["success"]
    assert result["metadata"]["action"] == "approve"
    assert result["metadata"]["review_id"]


def test_reject_records_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYDOX_DB_PATH", str(tmp_path / "review2.db"))
    import importlib, psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    f = _make_review_feature()
    result = f.execute(
        {"action": "reject", "output_id": "out-002", "job_id": "job-001", "notes": "Wrong color"},
        {"user_email": "reviewer@x.com"}
    )
    assert result["success"]


def test_pending_list_returns_list():
    f = _make_review_feature()
    result = f.execute({"action": "pending"}, {"user_email": "u@x.com"})
    assert result["success"]
    assert "pending" in result["metadata"]
    assert isinstance(result["metadata"]["pending"], list)


def test_invalid_action():
    f = _make_review_feature()
    ok, errors = f.validate_input({"action": "fly"})
    assert not ok
