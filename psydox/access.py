"""
Psydox — Owner Access Control (legacy shim)

Access is now driven entirely by the DB role stored in session_state.
This module is kept for backward-compatibility with older call-sites;
new code should read st.session_state.user_role directly.

The only remaining use of a hardcoded email is OWNER_EMAIL, which is the
bootstrap system owner used during the DB migration that assigns the
'owner' role on first run.
"""
from __future__ import annotations

OWNER_EMAIL: str = "yogeshwar@popclub.co"

# Kept for bootstrap/migration purposes only — not used for live access control.
_OWNER_SET: frozenset[str] = frozenset({OWNER_EMAIL})


def is_owner(email: str) -> bool:
    return (email or "").lower().strip() in _OWNER_SET


def can_access_ai_studio(email: str) -> bool:
    return is_owner(email)


def require_ai_permission(email: str) -> None:
    """Raise PermissionError if the user lacks AI execution permission.

    Checks DB role first (owner/admin/manager/editor/creative may use AI).
    Falls back to hardcoded bootstrap owner email if the DB is unavailable.
    """
    try:
        from psydox.auth.service import get_auth_service
        user = get_auth_service().get_user_by_email(email)
        if user and user.role in ("owner", "admin", "manager", "editor", "creative"):
            return
    except Exception:
        pass
    # Fallback: bootstrap owner always has access
    if is_owner(email):
        return
    raise PermissionError(
        f"AI tools require at least editor or manager role. '{email}' does not have access."
    )


def require_owner(email: str) -> None:
    """Raise PermissionError if the user does not have the 'owner' role."""
    try:
        from psydox.auth.service import get_auth_service
        user = get_auth_service().get_user_by_email(email)
        if user and user.role == "owner":
            return
    except Exception:
        pass
    if is_owner(email):
        return
    raise PermissionError(
        f"This action requires the owner role. '{email}' does not have access."
    )


def require_admin(email: str) -> None:
    """Raise PermissionError if the user lacks owner or admin role."""
    try:
        from psydox.auth.service import get_auth_service
        user = get_auth_service().get_user_by_email(email)
        if user and user.role in ("owner", "admin"):
            return
    except Exception:
        pass
    if is_owner(email):
        return
    raise PermissionError(
        f"This action requires admin role or higher. '{email}' does not have access."
    )
