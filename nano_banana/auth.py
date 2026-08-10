"""
Nano Banana — RBAC helpers.
Roles are stored in users.yaml under a 'role' key per user.
All feature-gate checks go through can().
"""
from enum import Enum


class Role(str, Enum):
    ADMIN    = "admin"     # full access: AI Studio, diagnostics, production validation
    MANAGER  = "manager"   # AI Studio + Classic + batch AI; no raw diagnostics
    OPERATOR = "operator"  # AI Studio + Classic; no batch AI
    VIEWER   = "viewer"    # Classic only; read-only results


# Feature → minimum required roles
_FEATURE_ROLES: dict[str, set] = {
    "ai_studio":             {Role.ADMIN, Role.MANAGER, Role.OPERATOR},
    "batch_ai":              {Role.ADMIN, Role.MANAGER},
    "diagnostics":           {Role.ADMIN},
    "production_validation": {Role.ADMIN},
    "cost_tracking":         {Role.ADMIN, Role.MANAGER},
    "classic_processing":    {Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER},
    "export":                {Role.ADMIN, Role.MANAGER, Role.OPERATOR},
}


def get_role(user_data: dict) -> Role:
    """
    Return the Role for a user dict loaded from users.yaml.
    Defaults to VIEWER when the 'role' key is absent or unrecognised
    (safe fallback — never grants extra access).
    """
    raw = (user_data.get("role") or "").lower().strip()
    try:
        return Role(raw)
    except ValueError:
        return Role.VIEWER


def can(role: Role, feature: str) -> bool:
    """Return True if the role is permitted to use the given feature."""
    return role in _FEATURE_ROLES.get(feature, set())
