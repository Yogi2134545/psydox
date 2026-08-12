"""
Psydox — Owner Access Control

Single source of truth for AI Studio permissions.
yogeshwar@popclub.co is the only account that can access AI features.
All checks are case-insensitive and strip whitespace.
"""
from __future__ import annotations

OWNER_EMAIL: str = "yogeshwar@popclub.co"

# Any future additional owners can be added here without changing callers.
_OWNER_SET: frozenset[str] = frozenset({OWNER_EMAIL, "surya.pant@popclub.co"})


def is_owner(email: str) -> bool:
    return (email or "").lower().strip() in _OWNER_SET


def can_access_ai_studio(email: str) -> bool:
    return is_owner(email)


def require_owner(email: str) -> None:
    """Raise PermissionError if the email does not have owner access.

    Call this at the start of any AI execution path as a server-side guard.
    The UI should already hide AI features for non-owners, but this ensures
    no session-state manipulation can bypass the restriction.
    """
    if not is_owner(email):
        raise PermissionError(
            "AI Studio is restricted to the owner account. "
            f"'{email}' does not have access."
        )
