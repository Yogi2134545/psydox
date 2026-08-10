"""Tests for ProductLock."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def test_from_feature_background_locks_color():
    from psydox.product.lock import ProductLock, LockedProperty
    lock = ProductLock.from_feature("background")
    assert lock.is_locked(LockedProperty.COLOR)


def test_from_feature_background_locks_logo():
    from psydox.product.lock import ProductLock, LockedProperty
    lock = ProductLock.from_feature("background")
    assert lock.is_locked(LockedProperty.LOGO)


def test_lighting_allows_soft_color():
    from psydox.product.lock import ProductLock, LockedProperty, LockLevel
    lock = ProductLock.from_feature("lighting")
    assert lock.get_level(LockedProperty.COLOR) == LockLevel.SOFT


def test_strict_all_locks_everything():
    from psydox.product.lock import ProductLock, LockedProperty
    lock = ProductLock.strict_all()
    for prop in LockedProperty:
        assert lock.is_locked(prop), f"{prop} should be locked"


def test_override_frees_a_property():
    from psydox.product.lock import ProductLock, LockedProperty, LockLevel
    lock = ProductLock.from_feature("background")
    lock.override(LockedProperty.COLOR, LockLevel.FREE)
    assert not lock.is_locked(LockedProperty.COLOR)


def test_constraint_text_mentions_strict_properties():
    from psydox.product.lock import ProductLock
    lock = ProductLock.from_feature("background")
    text = lock.constraint_text()
    assert "MUST PRESERVE" in text
    assert "color" in text.lower()


def test_free_properties_empty_for_background():
    from psydox.product.lock import ProductLock
    lock = ProductLock.from_feature("background")
    free = lock.free_properties()
    assert len(free) == 0


def test_unknown_feature_defaults_to_strict():
    from psydox.product.lock import ProductLock, LockedProperty
    lock = ProductLock.from_feature("nonexistent_feature_xyz")
    for prop in LockedProperty:
        assert lock.is_locked(prop)
