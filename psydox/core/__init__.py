"""Psydox Core — registry, manifest, errors, config."""
from .registry import FeatureModule, FeatureRegistry, get_registry
from .manifest import FeatureManifest, FeatureCategory, FeatureStatus
from .errors import (
    PsydoxError, AIProviderError, AIQuotaError, AIValidationError,
    ProductAnalysisError, QualityError, StorageError, JobError,
    AuthenticationError, AuthorizationError,
)

__all__ = [
    "FeatureModule", "FeatureRegistry", "get_registry",
    "FeatureManifest", "FeatureCategory", "FeatureStatus",
    "PsydoxError", "AIProviderError", "AIQuotaError", "AIValidationError",
    "ProductAnalysisError", "QualityError", "StorageError", "JobError",
    "AuthenticationError", "AuthorizationError",
]
