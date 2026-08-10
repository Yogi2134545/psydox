"""
Psydox Core — Feature Registry

The central plugin system. Features register here; the dashboard and other
consumers discover them through this interface.

THE KEY PRINCIPLE:
  Adding a new feature never requires editing core code.
  Register → Appears automatically everywhere.

Usage:
    registry = get_registry()
    registry.register(BackgroundFeature())

    # Discover
    ai_features = registry.by_category(FeatureCategory.BACKGROUND)
    feature     = registry.get("ai_background")
    result      = feature.execute(inputs, context)
"""
import os
from abc import ABC, abstractmethod
from typing import Optional

from .manifest import FeatureManifest, FeatureCategory, FeatureStatus


class FeatureModule(ABC):
    """
    Abstract base for all Psydox feature modules.

    Every feature implements this interface. The system calls features only
    through this contract — no feature-specific imports in core code.
    """

    @property
    @abstractmethod
    def manifest(self) -> FeatureManifest:
        """Return the feature's manifest (static metadata)."""
        ...

    @abstractmethod
    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        """
        Validate inputs before execution.
        Returns: (valid: bool, errors: list[str])
        Errors are user-friendly messages shown in the UI.
        """
        ...

    @abstractmethod
    def execute(self, inputs: dict, context: dict) -> dict:
        """
        Execute the feature.

        inputs:  validated user inputs (image bytes, options, product desc, etc.)
        context: shared runtime context (user, job_id, ratio, etc.)

        Returns dict with at minimum:
            success:  bool
            outputs:  list of {"bytes": bytes, "label": str, "mime": str}
            errors:   list[str]  (user-friendly)
            metadata: dict       (prompt, model, cost estimate, etc.)
        """
        ...

    def validate_output(self, outputs: dict) -> tuple[bool, list[str]]:
        """
        Validate outputs after execution.
        Default: pass-through. Override for feature-specific QA.
        Returns: (valid: bool, warnings: list[str])
        """
        return True, []

    def get_ui_config(self) -> dict:
        """
        Return UI configuration for the dashboard widget.
        Override to declare input fields, options, defaults.
        """
        return {"inputs": [], "options": []}

    def is_enabled(self) -> bool:
        """
        Check if the feature is currently enabled (status + feature flag).
        """
        m = self.manifest
        if m.status == FeatureStatus.DISABLED:
            return False
        if m.feature_flag:
            env_val = os.environ.get(m.feature_flag, "").lower()
            return env_val in ("1", "true", "yes")
        return True


class FeatureRegistry:
    """
    Central registry for all Psydox features.
    One singleton per process (see get_registry()).

    Thread-safe for reads. Registration should happen at startup only.
    """

    def __init__(self):
        self._features: dict[str, FeatureModule] = {}

    def register(self, feature: FeatureModule) -> None:
        """Register a feature. Re-registration replaces the previous instance."""
        self._features[feature.manifest.id] = feature

    def unregister(self, feature_id: str) -> None:
        """Remove a feature from the registry."""
        self._features.pop(feature_id, None)

    def get(self, feature_id: str) -> Optional[FeatureModule]:
        """Return a feature by ID, or None if not found."""
        return self._features.get(feature_id)

    def all(self, include_disabled: bool = False) -> list[FeatureModule]:
        """Return all registered features (enabled by default)."""
        if include_disabled:
            return list(self._features.values())
        return [f for f in self._features.values() if f.is_enabled()]

    def by_category(self, category: FeatureCategory) -> list[FeatureModule]:
        """Return enabled features in a specific category."""
        return [f for f in self.all() if f.manifest.category == category]

    def ai_features(self) -> list[FeatureModule]:
        """Return enabled features that require AI."""
        return [f for f in self.all() if f.manifest.requires_ai]

    def classic_features(self) -> list[FeatureModule]:
        """Return enabled features that do not require AI."""
        return [f for f in self.all() if not f.manifest.requires_ai]

    def ids(self) -> list[str]:
        return list(self._features.keys())

    def summary(self) -> list[dict]:
        """Return manifest dicts for all enabled features."""
        return [f.manifest.to_dict() for f in self.all()]

    def __len__(self) -> int:
        return len(self._features)

    def __repr__(self) -> str:
        ids = ", ".join(self.ids())
        return f"<FeatureRegistry [{len(self)} features]: {ids}>"


# ── Singleton ─────────────────────────────────────────────────────────────────

_REGISTRY: FeatureRegistry | None = None


def get_registry() -> FeatureRegistry:
    """Return the global FeatureRegistry singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = FeatureRegistry()
    return _REGISTRY
