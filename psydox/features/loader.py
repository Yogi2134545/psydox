"""
Psydox Feature Loader
Discovers and registers all built-in features with the global FeatureRegistry.
Call bootstrap_features() once at app startup.

To add a new feature:
  1. Create psydox/features/my_feature/service.py with MyFeature(FeatureModule)
  2. Add register(MyFeature()) here
  3. Done — dashboard discovers it automatically

Never edit core dashboard code to add a feature.
"""
import logging
from psydox.core.registry import get_registry

_log = logging.getLogger("psydox.features.loader")


def bootstrap_features() -> None:
    """Register all built-in feature modules."""
    registry = get_registry()

    # ── Background ────────────────────────────────────────────────────────────
    try:
        from psydox.features.background import BackgroundFeature
        registry.register(BackgroundFeature())
        _log.info("Registered: BackgroundFeature")
    except Exception as e:
        _log.warning("Could not register BackgroundFeature: %s", e)

    # ── Lifestyle ─────────────────────────────────────────────────────────────
    try:
        from psydox.features.lifestyle import LifestyleFeature
        registry.register(LifestyleFeature())
        _log.info("Registered: LifestyleFeature")
    except Exception as e:
        _log.warning("Could not register LifestyleFeature: %s", e)

    # ── Model Generation ──────────────────────────────────────────────────────
    try:
        from psydox.features.model_gen import ModelGenFeature
        registry.register(ModelGenFeature())
        _log.info("Registered: ModelGenFeature")
    except Exception as e:
        _log.warning("Could not register ModelGenFeature: %s", e)

    # ── Demo Feature (extensibility test — disabled by default) ───────────────
    try:
        from psydox.features.demo import DemoFeature
        f = DemoFeature()
        registry.register(f)
        status = "enabled" if f.is_enabled() else "registered but disabled (ENABLE_DEMO_FEATURE not set)"
        _log.info("Registered DemoFeature: %s", status)
    except Exception as e:
        _log.warning("Could not register DemoFeature: %s", e)

    _log.info(
        "Feature bootstrap complete. Registry: %d features, %d enabled",
        len(registry.all(include_disabled=True)),
        len(registry.all()),
    )


def get_feature_summary() -> list[dict]:
    """Return manifest dicts for all enabled features."""
    return get_registry().summary()
