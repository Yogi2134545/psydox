"""Tests for persistent storage (SQLite)."""
import sys
import os
import tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def _setup_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("PSYDOX_DB_PATH", db_path)
    # Force re-import to pick up new env var
    import importlib
    import psydox.storage.database as _m
    # Reset thread-local connection
    _m._conn_tls.conn = None
    importlib.reload(_m)
    return _m


def test_init_creates_tables(tmp_path, monkeypatch):
    _m = _setup_db(tmp_path, monkeypatch)
    _m.init_db()
    conn = _m.get_db()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for expected in ["jobs", "outputs", "audit_logs", "dashboard_prefs", "product_profiles"]:
        assert expected in tables, f"Table '{expected}' not found in {tables}"


def test_schema_version_tracked(tmp_path, monkeypatch):
    _m = _setup_db(tmp_path, monkeypatch)
    _m.init_db()
    conn = _m.get_db()
    row  = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    assert row[0] >= 1


def test_insert_and_read_audit_log(tmp_path, monkeypatch):
    _m = _setup_db(tmp_path, monkeypatch)
    _m.init_db()
    db = _m.get_db()
    import time
    db.execute(
        "INSERT INTO audit_logs (user_email, action, resource, detail, ip_address, created_at) VALUES (?,?,?,?,?,?)",
        ("test@x.com", "login", "", "", "", time.time()),
    )
    db.commit()
    rows = db.execute("SELECT action FROM audit_logs WHERE user_email='test@x.com'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "login"


def test_job_persist_and_retrieve(tmp_path, monkeypatch):
    _m = _setup_db(tmp_path, monkeypatch)
    _m.init_db()
    import time, json
    db = _m.get_db()
    data = json.dumps({"id": "abc123", "feature_id": "background", "label": "test",
                       "status": "queued", "user_email": "u@x.com",
                       "project_id": "", "progress": 0, "outputs": [], "errors": [],
                       "metadata": {}, "created_at": time.time(),
                       "updated_at": time.time(), "completed_at": None})
    db.execute(
        "INSERT INTO jobs (id, feature_id, label, status, user_email, project_id, progress, data, created_at, updated_at, completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("abc123", "background", "test", "queued", "u@x.com", "", 0, data, time.time(), time.time(), None),
    )
    db.commit()
    row = db.execute("SELECT data FROM jobs WHERE id='abc123'").fetchone()
    assert row is not None
    parsed = json.loads(row[0])
    assert parsed["feature_id"] == "background"
