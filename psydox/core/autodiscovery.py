"""
Psydox Auto-Discovery

Scans psydox/features/ for packages that contain a service.py with a FeatureModule
subclass and registers them automatically.

A developer adding a new feature only needs to:
  1. Create psydox/features/my_feature/service.py
  2. Define a class that extends FeatureModule

Nothing else — no edits to loader.py, app.py, core, or dashboard.

Discovery rules:
  - Each sub-directory of psydox/features/ that is a Python package (has __init__.py
    OR has service.py directly) is a candidate.
  - The candidate must have service.py.
  - service.py is imported; all FeatureModule subclasses that are NOT abstract are
    collected.
  - Each subclass is instantiated (zero-arg) and registered.
  - Duplicate IDs: second registration is skipped with a warning, never a crash.
  - Any import/instantiation error is logged and skipped — one bad feature never
    prevents the rest from loading.
"""
import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Type

_log = logging.getLogger("psydox.core.autodiscovery")

# Sentinel so we don't import registry at module level (avoids circular imports)
_FeatureModule = None


def _get_base():
    global _FeatureModule
    if _FeatureModule is None:
        from psydox.core.registry import FeatureModule
        _FeatureModule = FeatureModule
    return _FeatureModule


def _is_concrete_feature(obj) -> bool:
    base = _get_base()
    return (
        inspect.isclass(obj)
        and issubclass(obj, base)
        and obj is not base
        and not inspect.isabstract(obj)
    )


def discover_features(features_pkg: str = "psydox.features") -> list:
    """
    Import every sub-package of `features_pkg`, find FeatureModule subclasses,
    instantiate them, and return the list.  Never raises.
    """
    base = _get_base()
    features_path = Path(__file__).parent.parent / "features"
    collected: list = []
    seen_ids: set[str] = set()

    for item in sorted(features_path.iterdir()):
        if not item.is_dir():
            continue
        if item.name.startswith("_"):
            continue

        service_path = item / "service.py"
        if not service_path.exists():
            continue

        module_name = f"{features_pkg}.{item.name}.service"
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            _log.warning("Auto-discovery: could not import %s — %s", module_name, exc)
            continue

        for _name, obj in inspect.getmembers(mod, _is_concrete_feature):
            try:
                instance = obj()
                fid = instance.manifest.id
                if fid in seen_ids:
                    _log.debug("Auto-discovery: duplicate id '%s' in %s — skipped", fid, module_name)
                    continue
                seen_ids.add(fid)
                collected.append(instance)
                _log.debug("Auto-discovery: found %s (%s)", fid, _name)
            except Exception as exc:
                _log.warning("Auto-discovery: could not instantiate %s.%s — %s", module_name, _name, exc)

    _log.info("Auto-discovery complete: %d feature(s) found in %s", len(collected), features_pkg)
    return collected


def bootstrap_with_autodiscovery() -> int:
    """
    Auto-discover all features and register them with the global FeatureRegistry.
    Returns number of newly registered features.  Never raises.
    """
    from psydox.core.registry import get_registry
    registry = get_registry()
    registered = 0

    for feature in discover_features():
        try:
            registry.register(feature)
            registered += 1
            _log.info("Registered: %s (%s)", feature.manifest.name, feature.manifest.id)
        except ValueError:
            _log.debug("Already registered: %s — skipped", feature.manifest.id)
        except Exception as exc:
            _log.warning("Failed to register %s: %s", feature.manifest.id, exc)

    return registered
