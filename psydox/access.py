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


def require_owner(email: str) -> None:
    """Raise PermissionError if the email is not the bootstrap system owner.

    Prefer checking st.session_state.user_role in ('owner', 'admin') in UI code.
    This guard is kept for deep execution paths that lack session access.
    """
    if not is_owner(email):
        raise PermissionError(
            "AI Studio is restricted to the owner account. "
            f"'{email}' does not have access."
        )
