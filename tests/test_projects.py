"""Tests for ProjectService."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
import os
os.environ["DEBUG_MODE"] = "true"


def _make_service(tmp_path, monkeypatch):
    db_path = str(tmp_path / "proj_test.db")
    monkeypatch.setenv("PSYDOX_DB_PATH", db_path)
    import importlib, psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    from psydox.projects.service import ProjectService
    return ProjectService({})


def test_create_project(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    p = svc.create("My Collection", "owner@x.com", description="Test project")
    assert p.id
    assert p.name == "My Collection"
    assert p.owner_email == "owner@x.com"


def test_get_project_isolation(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    p = svc.create("Private", "alice@x.com")
    assert svc.get(p.id, "alice@x.com") is not None
    assert svc.get(p.id, "bob@x.com") is None  # isolation


def test_list_projects(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    svc.create("P1", "u@x.com")
    svc.create("P2", "u@x.com")
    svc.create("Other", "other@x.com")
    projects = svc.list("u@x.com")
    assert len(projects) == 2
    assert all(p.owner_email == "u@x.com" for p in projects)


def test_update_project(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    p = svc.create("Old Name", "u@x.com")
    updated = svc.update(p.id, "u@x.com", name="New Name")
    assert updated.name == "New Name"
    fetched = svc.get(p.id, "u@x.com")
    assert fetched.name == "New Name"


def test_delete_archives_project(tmp_path, monkeypatch):
    from psydox.projects.service import ProjectStatus
    svc = _make_service(tmp_path, monkeypatch)
    p = svc.create("ToDelete", "u@x.com")
    svc.delete(p.id, "u@x.com")
    archived = svc.get(p.id, "u@x.com")
    assert archived.status == ProjectStatus.ARCHIVED


def test_increment_counts(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    p = svc.create("Counter", "u@x.com")
    svc.increment_counts(p.id, "u@x.com", jobs=3, approved=2)
    p2 = svc.get(p.id, "u@x.com")
    assert p2.job_count == 3
    assert p2.approved_count == 2


def test_project_survives_new_service_instance(tmp_path, monkeypatch):
    db_path = str(tmp_path / "persist.db")
    monkeypatch.setenv("PSYDOX_DB_PATH", db_path)
    import importlib, psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    from psydox.projects.service import ProjectService
    svc1 = ProjectService({})
    p = svc1.create("Persist", "u@x.com")
    pid = p.id
    _db._conn_tls.conn = None
    svc2 = ProjectService({})
    assert svc2.get(pid, "u@x.com") is not None
