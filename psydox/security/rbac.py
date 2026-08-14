"""
Psydox RBAC — Role-Based Access Control

Roles (hierarchical): OWNER > ADMIN > MANAGER > EDITOR > VIEWER

Permissions:
  upload        — upload product images
  classic       — classic batch processing
  ai            — AI generation features
  batch         — batch / bulk operations
  review        — approve / reject outputs
  download      — download outputs and ZIPs
  analytics     — view analytics and usage data
  admin         — user management, system settings

Feature permissions are declared in FeatureManifest.required_permission.
The executor checks: user_role.can(feature.required_permission).

Role definitions are read from users.yaml (same as existing auth).
No hardcoded email checks anywhere.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

_log = logging.getLogger("psydox.security.rbac")


class Role(str, Enum):
    OWNER            = "owner"
    ADMIN            = "admin"
    MANAGER          = "manager"
    EDITOR           = "editor"
    VIEWER           = "viewer"
    OPERATOR         = "operator"          # maps users.yaml "operator" role
    CATALOG_OPERATOR = "catalog_operator"
    CREATIVE         = "creative"
    REVIEWER         = "reviewer"
    USER             = "user"              # default for self-registered accounts


class Permission(str, Enum):
    UPLOAD    = "upload"
    CLASSIC   = "classic"
    AI        = "ai"
    BATCH     = "batch"
    REVIEW    = "review"
    DOWNLOAD  = "download"
    ANALYTICS = "analytics"
    ADMIN     = "admin"


# Permission matrix: role → set of allowed permissions
_MATRIX: dict[Role, set[Permission]] = {
    Role.OWNER: set(Permission),                                          # all
    Role.ADMIN: set(Permission),                                          # all
    Role.MANAGER: {
        Permission.UPLOAD, Permission.CLASSIC, Permission.AI,
        Permission.BATCH,  Permission.REVIEW,  Permission.DOWNLOAD,
        Permission.ANALYTICS,
    },
    Role.EDITOR: {
        Permission.UPLOAD, Permission.CLASSIC, Permission.AI,
        Permission.DOWNLOAD,
    },
    Role.VIEWER: {
        Permission.DOWNLOAD,
    },
    Role.OPERATOR: {
        Permission.UPLOAD, Permission.CLASSIC, Permission.BATCH,
        Permission.DOWNLOAD,
    },
    Role.CATALOG_OPERATOR: {
        Permission.UPLOAD, Permission.CLASSIC, Permission.DOWNLOAD,
    },
    Role.CREATIVE: {
        Permission.UPLOAD, Permission.CLASSIC, Permission.AI,
        Permission.DOWNLOAD,
    },
    Role.REVIEWER: {
        Permission.REVIEW, Permission.DOWNLOAD, Permission.ANALYTICS,
    },
    Role.USER: {
        Permission.DOWNLOAD,
    },
}

# Feature-ID → minimum required permission
_FEATURE_PERMISSION: dict[str, Permission] = {
    "background":    Permission.CLASSIC,
    "lifestyle":     Permission.AI,
    "model_gen":     Permission.AI,
    "demo":          Permission.AI,
    "demo_watermark": Permission.AI,
    # Classic processing (app.py)
    "classic":       Permission.CLASSIC,
    "batch":         Permission.BATCH,
    # Admin
    "diagnostics":   Permission.ADMIN,
    "analytics":     Permission.ANALYTICS,
}


class RBACService:

    def get_role(self, users_dict: dict, email: str) -> Role:
        """Read role from users.yaml dict.  Defaults to VIEWER."""
        udata = users_dict.get(email.lower().strip(), {})
        role_str = udata.get("role", "viewer").lower()
        try:
            return Role(role_str)
        except ValueError:
            return Role.VIEWER

    def can(self, role: Role, permission: Permission | str) -> bool:
        """Return True if role has the given permission."""
        if isinstance(permission, str):
            try:
                permission = Permission(permission)
            except ValueError:
                return False
        return permission in _MATRIX.get(role, set())

    def can_use_feature(self, role: Role, feature_id: str) -> bool:
        """Check if a role is allowed to use a specific feature."""
        required = _FEATURE_PERMISSION.get(feature_id)
        if required is None:
            # Unknown feature — check manifest
            try:
                from psydox.core.registry import get_registry
                feat = get_registry().get(feature_id)
                if feat:
                    perm_str = feat.manifest.required_permission or "classic"
                    required = Permission(perm_str)
            except Exception:
                return False  # fail closed for unknown features
        if required is None:
            return False  # fail closed — no permission mapping found
        return self.can(role, required)

    def require(self, role: Role, permission: Permission) -> None:
        """Raise AuthorizationError if role lacks permission."""
        if not self.can(role, permission):
            from psydox.core.errors import AuthorizationError
            raise AuthorizationError(
                f"Role '{role.value}' does not have permission '{permission.value}'"
            )


_service: Optional[RBACService] = None

def get_rbac() -> RBACService:
    global _service
    if _service is None:
        _service = RBACService()
    return _service
