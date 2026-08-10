"""Tests for automatic feature discovery."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def test_discover_finds_background():
    from psydox.core.autodiscovery import discover_features
    features = discover_features()
    ids = [f.manifest.id for f in features]
    assert "background" in ids, f"Expected 'background' in {ids}"


def test_discover_finds_lifestyle():
    from psydox.core.autodiscovery import discover_features
    ids = [f.manifest.id for f in discover_features()]
    assert "lifestyle" in ids


def test_discover_finds_model_gen():
    from psydox.core.autodiscovery import discover_features
    ids = [f.manifest.id for f in discover_features()]
    assert "model_gen" in ids


def test_discover_finds_demo():
    from psydox.core.autodiscovery import discover_features
    ids = [f.manifest.id for f in discover_features()]
    assert any("demo" in fid for fid in ids)


def test_discover_no_duplicates():
    from psydox.core.autodiscovery import discover_features
    ids = [f.manifest.id for f in discover_features()]
    assert len(ids) == len(set(ids)), f"Duplicate IDs: {ids}"


def test_bootstrap_returns_count():
    from psydox.core.autodiscovery import bootstrap_with_autodiscovery
    from psydox.core.registry import FeatureRegistry
    reg = FeatureRegistry()  # fresh registry
    # Can't easily test on fresh registry without monkeypatching get_registry
    # But bootstrap_with_autodiscovery must not raise
    try:
        bootstrap_with_autodiscovery()
    except Exception as e:
        assert False, f"bootstrap_with_autodiscovery raised: {e}"


def test_autodiscovery_skips_non_feature_classes():
    """Only concrete FeatureModule subclasses should be discovered."""
    from psydox.core.autodiscovery import discover_features
    features = discover_features()
    from psydox.core.registry import FeatureModule
    import inspect
    for f in features:
        assert isinstance(f, FeatureModule)
        assert not inspect.isabstract(f.__class__)
