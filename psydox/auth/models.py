"""Psydox Auth — data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AccountStatus(str, Enum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE               = "active"
    SUSPENDED            = "suspended"
    DISABLED             = "disabled"


@dataclass
class User:
    id:                      str
    full_name:               str
    email:                   str
    password_hash:           str
    email_verified:          bool
    status:                  AccountStatus
    role:                    str    # value from psydox.security.rbac.Role
    created_at:              float
    updated_at:              float

    verification_token_hash: Optional[str]   = None
    verification_expires_at: Optional[float] = None
    verified_at:             Optional[float] = None

    reset_token_hash:        Optional[str]   = None
    reset_expires_at:        Optional[float] = None

    last_login_at:           Optional[float] = None
    terms_accepted_at:       Optional[float] = None
    failed_login_attempts:   int             = 0
    locked_until:            Optional[float] = None

    def is_active(self) -> bool:
        return self.status == AccountStatus.ACTIVE

    def is_locked(self) -> bool:
        import time
        return self.locked_until is not None and self.locked_until > time.time()


@dataclass
class Session:
    id:               str
    user_id:          str
    created_at:       float
    expires_at:       float
    last_activity_at: float
    remember_me:      bool
    revoked_at:       Optional[float] = None
    user_agent:       str             = ""

    def is_valid(self) -> bool:
        import time
        if self.revoked_at is not None:
            return False
        return self.expires_at > time.time()


@dataclass
class AuthResult:
    success:    bool
    user:       Optional[User]    = None
    session_id: Optional[str]     = None
    error:      str               = ""
    error_code: str               = ""    # machine-readable: INVALID_CREDENTIALS, UNVERIFIED, LOCKED, etc.

    @classmethod
    def ok(cls, user: User, session_id: str = "") -> "AuthResult":
        return cls(success=True, user=user, session_id=session_id)

    @classmethod
    def fail(cls, message: str, code: str = "") -> "AuthResult":
        return cls(success=False, error=message, error_code=code)
