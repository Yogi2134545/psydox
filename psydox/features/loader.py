"""
Psydox Feature Loader

Uses auto-discovery: scans psydox/features/ for service.py files containing
FeatureModule subclasses and registers them automatically.

To add a new feature:
  1. Create psydox/features/my_feature/service.py
  2. Define a class that extends FeatureModule
  3. Done — the feature appears in the dashboard, router, and permission system
     automatically on next app start.

NEVER edit this file to add a new feature.
"""
import logging
from psydox.core.autodiscovery import bootstrap_with_autodiscovery
from psydox.core.registry import get_registry

_log = logging.getLogger("psydox.features.loader")


def bootstrap_features() -> None:
    """Auto-discover and register all feature modules. Safe to call multiple times."""
    n = bootstrap_with_autodiscovery()
    reg = get_registry()
    _log.info(
        "Feature bootstrap complete — %d new, %d total (%d enabled)",
        n,
        len(reg.all(include_disabled=True)),
        len(reg.all()),
    )


def get_feature_summary() -> list[dict]:
    """Return manifest dicts for all enabled features."""
    return get_registry().summary()
