"""Tests for persistent Job Manager."""
import sys
import os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def _make_manager(tmp_path, monkeypatch):
    db_path = str(tmp_path / "jobs_test.db")
    monkeypatch.setenv("PSYDOX_DB_PATH", db_path)
    import importlib
    import psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    from psydox.jobs.manager import JobManager
    return JobManager({})


def test_create_job(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path, monkeypatch)
    job = mgr.create("background", "Test job", user_email="u@x.com")
    assert job.id
    assert job.feature_id == "background"


def test_get_job_roundtrip(tmp_path, monkeypatch):
    mgr = _make_manager(tmp_path, monkeypatch)
    job = mgr.create("lifestyle", "LS job", user_email="a@b.com")
    fetched = mgr.get(job.id)
    assert fetched is not None
    assert fetched.feature_id == "lifestyle"


def test_update_job_status(tmp_path, monkeypatch):
    from psydox.jobs.manager import JobStatus
    mgr = _make_manager(tmp_path, monkeypatch)
    job = mgr.create("bg", "Update test")
    mgr.update(job.id, status=JobStatus.PROCESSING)
    updated = mgr.get(job.id)
    assert updated.status == JobStatus.PROCESSING


def test_finish_job_completed(tmp_path, monkeypatch):
    from psydox.jobs.manager import JobStatus
    mgr = _make_manager(tmp_path, monkeypatch)
    job = mgr.create("bg", "Finish test")
    mgr.finish(job.id, outputs=[{"bytes": b"x"}], errors=[], metadata={})
    finished = mgr.get(job.id)
    assert finished.status == JobStatus.COMPLETED
    assert finished.completed_at is not None


def test_finish_job_failed_when_no_outputs(tmp_path, monkeypatch):
    from psydox.jobs.manager import JobStatus
    mgr = _make_manager(tmp_path, monkeypatch)
    job = mgr.create("bg", "Fail test")
    mgr.finish(job.id, outputs=[], errors=["AI error"], metadata={})
    failed = mgr.get(job.id)
    assert failed.status == JobStatus.FAILED


def test_cancel_job(tmp_path, monkeypatch):
    from psydox.jobs.manager import JobStatus
    mgr = _make_manager(tmp_path, monkeypatch)
    job = mgr.create("bg", "Cancel test")
    mgr.cancel(job.id)
    cancelled = mgr.get(job.id)
    assert cancelled.status == JobStatus.CANCELLED


def test_job_survives_new_manager_instance(tmp_path, monkeypatch):
    """Simulates app restart — new JobManager reads from DB."""
    db_path = str(tmp_path / "survive.db")
    monkeypatch.setenv("PSYDOX_DB_PATH", db_path)
    import importlib
    import psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()

    from psydox.jobs.manager import JobManager
    mgr1 = JobManager({})
    job  = mgr1.create("background", "Persistent", user_email="p@x.com")
    jid  = job.id

    # New manager instance (simulates restart) — empty session cache
    _db._conn_tls.conn = None
    mgr2 = JobManager({})
    fetched = mgr2.get(jid)
    assert fetched is not None
    assert fetched.label == "Persistent"
