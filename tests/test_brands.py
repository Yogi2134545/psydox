"""Tests for BrandService."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
import os
os.environ["DEBUG_MODE"] = "true"


def _make_service(tmp_path, monkeypatch):
    db_path = str(tmp_path / "brands_test.db")
    monkeypatch.setenv("PSYDOX_DB_PATH", db_path)
    import importlib, psydox.storage.database as _db
    _db._conn_tls.conn = None
    importlib.reload(_db)
    _db.init_db()
    from psydox.brands.service import BrandService
    return BrandService({})


def test_create_brand(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    b = svc.create("alice@x.com", "Nike Air")
    assert b.id
    assert b.name == "Nike Air"


def test_brand_isolation(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    b = svc.create("alice@x.com", "Private Brand")
    assert svc.get(b.id, "alice@x.com") is not None
    assert svc.get(b.id, "bob@x.com") is None


def test_list_brands(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    svc.create("u@x.com", "Brand A")
    svc.create("u@x.com", "Brand B")
    svc.create("other@x.com", "Brand C")
    brands = svc.list("u@x.com")
    assert len(brands) == 2


def test_update_brand(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    b = svc.create("u@x.com", "Original")
    updated = svc.update(b.id, "u@x.com", name="Updated", primary_color="#FF0000")
    assert updated.name == "Updated"
    assert updated.primary_color == "#FF0000"


def test_delete_brand(tmp_path, monkeypatch):
    svc = _make_service(tmp_path, monkeypatch)
    b = svc.create("u@x.com", "ToDelete")
    svc.delete(b.id, "u@x.com")
    assert svc.get(b.id, "u@x.com") is None


def test_brand_serialization(tmp_path, monkeypatch):
    from psydox.brands.service import BrandProfile
    svc = _make_service(tmp_path, monkeypatch)
    b = svc.create("u@x.com", "Test", primary_color="#123456", preferred_ratios=["1:1", "16:9"])
    d = b.to_dict()
    restored = BrandProfile.from_dict(d)
    assert restored.primary_color == "#123456"
    assert "1:1" in restored.preferred_ratios
