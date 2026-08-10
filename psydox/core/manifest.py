"""
Psydox Core — Feature Manifest
Every feature declares its identity, capabilities, and UI metadata here.
The registry and dashboard read manifests to build menus, permissions, and cards
without knowing feature implementation details.
"""
from dataclasses import dataclass, field
from enum import Enum


class FeatureCategory(str, Enum):
    BACKGROUND  = "background"
    CREATIVE    = "creative"
    MODEL       = "model"
    SCENE       = "scene"
    EDITING     = "editing"
    ENHANCEMENT = "enhancement"
    LIGHTING    = "lighting"
    SHADOW      = "shadow"
    EXPORT      = "export"
    WORKFLOW    = "workflow"
    UTILITY     = "utility"


class FeatureStatus(str, Enum):
    STABLE       = "stable"
    BETA         = "beta"
    EXPERIMENTAL = "experimental"
    DISABLED     = "disabled"


class ProcessingType(str, Enum):
    INSTANT      = "instant"       # deterministic, no AI
    FAST         = "fast"          # <5 s
    STANDARD     = "standard"      # 5–30 s
    SLOW         = "slow"          # 30–120 s


@dataclass
class FeatureManifest:
    """
    Declarative description of a feature module.
    Used by: FeatureRegistry, Dashboard, RBAC, Workflow Engine, Cost Router.
    """
    id:                   str
    name:                 str
    description:          str
    category:             FeatureCategory
    icon:                 str                    = "✨"
    status:               FeatureStatus          = FeatureStatus.STABLE
    requires_ai:          bool                   = False
    supports_batch:       bool                   = False
    supports_reference:   bool                   = True
    supports_brand:       bool                   = False
    supports_quality_check: bool                 = False
    processing_type:      ProcessingType         = ProcessingType.STANDARD
    version:              str                    = "1.0.0"
    tags:                 list                   = field(default_factory=list)
    required_permission:  str                    = "ai_studio"
    feature_flag:         str | None             = None

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "name":         self.name,
            "description":  self.description,
            "category":     self.category.value,
            "icon":         self.icon,
            "status":       self.status.value,
            "requires_ai":  self.requires_ai,
            "supports_batch": self.supports_batch,
            "processing_type": self.processing_type.value,
            "version":      self.version,
            "tags":         self.tags,
        }
