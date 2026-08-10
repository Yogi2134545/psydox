"""Tests for Psydox feature registry and manifest system."""
import os
import sys
import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


# ── Registry basics ───────────────────────────────────────────────────────────

def test_get_registry_returns_singleton():
    from psydox.core.registry import get_registry, FeatureRegistry
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2


def test_register_and_retrieve():
    from psydox.core.registry import FeatureRegistry, FeatureModule
    from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType

    reg = FeatureRegistry()

    class _Stub(FeatureModule):
        @property
        def manifest(self):
            return FeatureManifest(
                id="stub", name="Stub", description="test",
                category=FeatureCategory.UTILITY,
                icon="🧪", status=FeatureStatus.STABLE,
                requires_ai=False, processing_type=ProcessingType.INSTANT,
                version="1.0.0",
            )
        def validate_input(self, inputs): return True, []
        def execute(self, inputs, context): return {"success": True, "outputs": [], "errors": [], "metadata": {}}

    reg.register(_Stub())
    feat = reg.get("stub")
    assert feat is not None
    assert feat.manifest.id == "stub"


def test_duplicate_register_is_idempotent_or_raises():
    """Registry either silently ignores or raises on duplicate — just must not crash badly."""
    from psydox.core.registry import FeatureRegistry, FeatureModule
    from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType

    reg = FeatureRegistry()

    class _Dup(FeatureModule):
        @property
        def manifest(self):
            return FeatureManifest(
                id="dup2", name="Dup2", description="d",
                category=FeatureCategory.UTILITY,
                icon="🔁", status=FeatureStatus.STABLE,
                requires_ai=False, processing_type=ProcessingType.INSTANT,
                version="1.0.0",
            )
        def validate_input(self, i): return True, []
        def execute(self, i, c): return {}

    reg.register(_Dup())
    # Second register should either raise ValueError or succeed silently
    try:
        reg.register(_Dup())
    except (ValueError, KeyError):
        pass  # acceptable
    # Either way, registry must still hold the feature
    assert reg.get("dup2") is not None


def test_all_returns_only_enabled():
    from psydox.core.registry import FeatureRegistry, FeatureModule
    from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType

    reg = FeatureRegistry()

    def _make(fid, status):
        class _F(FeatureModule):
            @property
            def manifest(self):
                return FeatureManifest(
                    id=fid, name=fid.capitalize(), description="d",
                    category=FeatureCategory.UTILITY,
                    icon="•", status=status,
                    requires_ai=False, processing_type=ProcessingType.INSTANT,
                    version="1.0.0",
                )
            def validate_input(self, i): return True, []
            def execute(self, i, c): return {}
        return _F()

    reg.register(_make("active1", FeatureStatus.STABLE))
    reg.register(_make("disabled1", FeatureStatus.DISABLED))

    enabled = [f.manifest.id for f in reg.all()]
    all_f   = [f.manifest.id for f in reg.all(include_disabled=True)]
    assert "active1" in enabled
    assert "disabled1" not in enabled
    assert "disabled1" in all_f


def test_feature_flag_disables_feature(monkeypatch):
    from psydox.core.registry import FeatureRegistry, FeatureModule
    from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType

    monkeypatch.setenv("PSYDOX_FEAT_FLAG_FLAGGED", "false")
    reg = FeatureRegistry()

    class _Flagged(FeatureModule):
        @property
        def manifest(self):
            return FeatureManifest(
                id="flagged", name="Flagged", description="d",
                category=FeatureCategory.UTILITY,
                icon="🚩", status=FeatureStatus.STABLE,
                requires_ai=False, processing_type=ProcessingType.INSTANT,
                version="1.0.0",
                feature_flag="PSYDOX_FEAT_FLAG_FLAGGED",
            )
        def validate_input(self, i): return True, []
        def execute(self, i, c): return {}

    reg.register(_Flagged())
    assert not reg.get("flagged").is_enabled()


# ── Background feature ────────────────────────────────────────────────────────

def test_background_feature_registers():
    from psydox.features.background import BackgroundFeature
    f = BackgroundFeature()
    assert f.manifest.id == "background"
    assert not f.manifest.requires_ai


def test_background_validate_input_missing_image():
    from psydox.features.background import BackgroundFeature
    ok, errors = BackgroundFeature().validate_input({"bg_type": "solid"})
    assert not ok
    assert errors


# ── Demo feature ──────────────────────────────────────────────────────────────

def test_demo_feature_disabled_by_default():
    os.environ.pop("ENABLE_DEMO_FEATURE", None)
    from psydox.features.demo import DemoFeature
    import importlib, psydox.features.demo
    importlib.reload(psydox.features.demo)
    from psydox.features.demo import DemoFeature as DF2
    f = DF2()
    assert not f.is_enabled()


def test_demo_feature_enabled_when_flag_set(monkeypatch):
    monkeypatch.setenv("ENABLE_DEMO_FEATURE", "true")
    from psydox.features.demo import DemoFeature
    import importlib, psydox.features.demo
    importlib.reload(psydox.features.demo)
    from psydox.features.demo import DemoFeature as DF2
    f = DF2()
    assert f.is_enabled()


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def test_bootstrap_does_not_raise():
    """bootstrap_features() should succeed (or log warnings) but never raise."""
    from psydox.features.loader import bootstrap_features
    bootstrap_features()  # may re-register but loader catches ValueError


def test_bootstrap_registers_background():
    from psydox.features.loader import bootstrap_features
    from psydox.core.registry import get_registry
    bootstrap_features()
    r = get_registry()
    assert r.get("background") is not None
