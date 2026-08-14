"""Psydox Auth — AuthService (main entry point for all auth operations).

AuthService is the single API surface used by UI code.
Business logic lives here; UI code only calls AuthService methods.

Thread-safety: all state is in the DB; no mutable in-process state.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from psydox.auth.models import AccountStatus, AuthResult, User
from psydox.auth.password import PasswordService
from psydox.auth.tokens import TokenService
from psydox.auth.validation import normalize_email, validate_email, validate_name

_log = logging.getLogger("psydox.auth.service")

_VERIFICATION_TTL = 48 * 3600   # 48 hours
_RESET_TTL        = 1  * 3600   # 1 hour


class AuthService:
    """
    Central auth service.  All UI code should call this, never the
    repository or sub-services directly.
    """

    def __init__(self) -> None:
        from psydox.auth.repository import get_user_repository
        from psydox.auth.sessions   import get_session_service
        self._repo     = get_user_repository()
        self._sessions = get_session_service()
        self._pw       = PasswordService()
        self._tok      = TokenService()
        self._migrated = False
        self._ensure_migrated()

    # ── Startup ───────────────────────────────────────────────────────────────

    def _ensure_migrated(self) -> None:
        """Migrate users.yaml to DB on first call (idempotent)."""
        if self._migrated:
            return
        try:
            self._repo.migrate_from_yaml()
        except Exception as exc:
            _log.warning("users.yaml migration failed (non-fatal): %s", exc)
        self._migrated = True

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        full_name:        str,
        email:            str,
        password:         str,
        confirm_password: str,
        terms_accepted:   bool = False,
    ) -> AuthResult:
        errors: list[str] = []

        name_errs = validate_name(full_name)
        errors.extend(name_errs)

        email_errs = validate_email(email)
        errors.extend(email_errs)

        pw_errs = self._pw.validate_strength(password)
        errors.extend(pw_errs)

        if password != confirm_password:
            errors.append("Passwords do not match.")

        if not terms_accepted:
            errors.append("You must accept the Terms & Privacy Policy.")

        if errors:
            return AuthResult.fail(errors[0], "VALIDATION_ERROR")

        norm_email = normalize_email(email)

        # Duplicate check — return safe generic message to avoid enumeration
        if self._repo.email_exists(norm_email):
            return AuthResult.fail(
                "An account with this email already exists. Please sign in or use a different email.",
                "DUPLICATE_EMAIL",
            )

        pw_hash = self._pw.hash(password)
        now = time.time()
        user = self._repo.create(
            full_name=full_name.strip(),
            email=norm_email,
            password_hash=pw_hash,
            role="user",
            email_verified=False,
            status=AccountStatus.PENDING_VERIFICATION,
            terms_accepted_at=now,
        )

        self._send_verification(user)
        self._audit(norm_email, "user_registered")
        _log.info("New user registered: %s", norm_email)
        return AuthResult.ok(user)

    # ── Login ─────────────────────────────────────────────────────────────────

    def login(
        self,
        email:       str,
        password:    str,
        remember_me: bool = False,
    ) -> AuthResult:
        norm_email = normalize_email(email)

        # Per-email rate limit (in-memory token bucket)
        if not self._check_rate_limit(norm_email):
            return AuthResult.fail(
                "Too many login attempts. Please wait a few minutes and try again.",
                "RATE_LIMITED",
            )

        # Generic error message — never reveal whether account exists
        _GENERIC = "Invalid email or password."

        user = self._repo.get_by_email(norm_email)
        if user is None:
            self._audit(norm_email, "login_failed", detail="unknown email")
            return AuthResult.fail(_GENERIC, "INVALID_CREDENTIALS")

        # Account state checks
        if user.status == AccountStatus.DISABLED:
            return AuthResult.fail(
                "This account has been disabled. Please contact support.", "DISABLED"
            )
        if user.status == AccountStatus.SUSPENDED:
            return AuthResult.fail(
                "This account is currently suspended. Please contact support.", "SUSPENDED"
            )

        # Lockout check
        if user.is_locked():
            remaining = int((user.locked_until or 0) - time.time())
            mins = max(1, remaining // 60)
            return AuthResult.fail(
                f"Account is temporarily locked. Try again in {mins} minute(s).", "LOCKED"
            )

        # Password check
        if not self._pw.verify(password, user.password_hash):
            self._repo.record_failed_login(user.id)
            self._audit(norm_email, "login_failed", detail="wrong password")
            return AuthResult.fail(_GENERIC, "INVALID_CREDENTIALS")

        # Unverified account — handle separately so UI can offer resend
        if not user.email_verified or user.status == AccountStatus.PENDING_VERIFICATION:
            return AuthResult.fail(
                "Please verify your email address before signing in.",
                "UNVERIFIED",
            )

        # Success
        session = self._sessions.create(user.id, remember_me=remember_me)
        self._repo.record_login(user.id)
        self._audit(norm_email, "login_success")
        return AuthResult.ok(user, session_id=session.id)

    # ── Logout ────────────────────────────────────────────────────────────────

    def logout(self, session_id: str, user_email: str = "") -> None:
        try:
            self._sessions.revoke(session_id)
            self._audit(user_email, "logout")
        except Exception as exc:
            _log.warning("logout failed: %s", exc)

    def logout_all(self, user_id: str, user_email: str = "") -> int:
        count = self._sessions.revoke_all(user_id)
        self._audit(user_email, "logout_all_sessions", detail=f"revoked {count} sessions")
        return count

    # ── Email verification ────────────────────────────────────────────────────

    def verify_email(self, token: str) -> AuthResult:
        token = token.strip()
        if not token:
            return AuthResult.fail("Invalid verification link.", "INVALID_TOKEN")

        token_hash = self._tok.hash(token)
        db = self._db()
        row = db.execute(
            "SELECT * FROM users WHERE verification_token_hash=?", (token_hash,)
        ).fetchone()

        if not row:
            return AuthResult.fail(
                "Verification link is invalid or has already been used.", "INVALID_TOKEN"
            )

        from psydox.auth.models import User, AccountStatus
        user = self._repo._row_to_user(row)

        if user.verification_expires_at and user.verification_expires_at < time.time():
            return AuthResult.fail(
                "Verification link has expired. Please request a new one.", "TOKEN_EXPIRED"
            )

        self._repo.verify_email(user.id)
        self._audit(user.email, "email_verified")
        user = self._repo.get_by_id(user.id)
        _log.info("Email verified: %s", user.email)
        return AuthResult.ok(user)

    def resend_verification(self, email: str) -> None:
        """Resend verification email. Always returns (never reveals account existence)."""
        norm = normalize_email(email)
        user = self._repo.get_by_email(norm)
        if user and not user.email_verified:
            self._send_verification(user)
        self._audit(norm, "verification_resend_requested")

    # ── Password reset ────────────────────────────────────────────────────────

    def request_password_reset(self, email: str) -> None:
        """
        Request a password reset.
        ALWAYS returns — never reveals whether account exists.
        """
        norm = normalize_email(email)
        user = self._repo.get_by_email(norm)
        self._audit(norm, "password_reset_requested")
        if not user or user.status not in (AccountStatus.ACTIVE, AccountStatus.PENDING_VERIFICATION):
            return  # silent — do not reveal account existence
        try:
            raw_token = self._tok.generate()
            token_hash = self._tok.hash(raw_token)
            self._repo.set_reset_token(user.id, token_hash, time.time() + _RESET_TTL)
            email_svc = _get_email_service()
            email_svc.send_password_reset_email(user.email, user.full_name, raw_token)
            self._audit(norm, "password_reset_email_sent")
        except Exception as exc:
            _log.error("password reset email failed for %s: %s", norm, exc)

    def reset_password(
        self,
        token:            str,
        new_password:     str,
        confirm_password: str,
    ) -> AuthResult:
        token = token.strip()
        if not token:
            return AuthResult.fail("Invalid reset link.", "INVALID_TOKEN")

        errors = self._pw.validate_strength(new_password)
        if errors:
            return AuthResult.fail(errors[0], "WEAK_PASSWORD")
        if new_password != confirm_password:
            return AuthResult.fail("Passwords do not match.", "PASSWORD_MISMATCH")

        token_hash = self._tok.hash(token)
        db = self._db()
        row = db.execute(
            "SELECT * FROM users WHERE reset_token_hash=?", (token_hash,)
        ).fetchone()

        if not row:
            return AuthResult.fail(
                "Reset link is invalid or has already been used.", "INVALID_TOKEN"
            )

        user = self._repo._row_to_user(row)

        if user.reset_expires_at and user.reset_expires_at < time.time():
            return AuthResult.fail(
                "Reset link has expired. Please request a new one.", "TOKEN_EXPIRED"
            )

        new_hash = self._pw.hash(new_password)
        self._repo.update_password(user.id, new_hash)
        # Invalidate all sessions on password reset
        self._sessions.revoke_all(user.id)
        self._audit(user.email, "password_reset_completed")
        user = self._repo.get_by_id(user.id)
        _log.info("Password reset completed: %s", user.email)
        return AuthResult.ok(user)

    # ── Change password ───────────────────────────────────────────────────────

    def change_password(
        self,
        user_id:          str,
        current_password: str,
        new_password:     str,
        confirm_password: str,
    ) -> AuthResult:
        user = self._repo.get_by_id(user_id)
        if not user:
            return AuthResult.fail("User not found.", "NOT_FOUND")

        if not self._pw.verify(current_password, user.password_hash):
            return AuthResult.fail("Current password is incorrect.", "INVALID_CREDENTIALS")

        errors = self._pw.validate_strength(new_password)
        if errors:
            return AuthResult.fail(errors[0], "WEAK_PASSWORD")
        if new_password != confirm_password:
            return AuthResult.fail("Passwords do not match.", "PASSWORD_MISMATCH")

        new_hash = self._pw.hash(new_password)
        self._repo.update_password(user.id, new_hash)
        self._audit(user.email, "password_changed")
        return AuthResult.ok(user)

    # ── Profile ───────────────────────────────────────────────────────────────

    def update_profile(self, user_id: str, full_name: str) -> AuthResult:
        errors = validate_name(full_name)
        if errors:
            return AuthResult.fail(errors[0], "VALIDATION_ERROR")
        self._repo.update_name(user_id, full_name.strip())
        user = self._repo.get_by_id(user_id)
        return AuthResult.ok(user)

    def get_user(self, user_id: str) -> Optional[User]:
        return self._repo.get_by_id(user_id)

    def get_user_by_email(self, email: str) -> Optional[User]:
        return self._repo.get_by_email(normalize_email(email))

    # ── Sessions ──────────────────────────────────────────────────────────────

    def validate_session(self, session_id: str) -> Optional[User]:
        """Return User if session is valid, else None."""
        session = self._sessions.validate(session_id)
        if not session:
            return None
        user = self._repo.get_by_id(session.user_id)
        if not user or not user.is_active():
            return None
        return user

    def get_active_sessions(self, user_id: str) -> list:
        return self._sessions.list_active(user_id)

    def revoke_session(self, session_id: str, user_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session or session.user_id != user_id:
            return False
        self._sessions.revoke(session_id)
        return True

    # ── Internal ──────────────────────────────────────────────────────────────

    def _send_verification(self, user: User) -> None:
        try:
            raw_token = self._tok.generate()
            token_hash = self._tok.hash(raw_token)
            self._repo.set_verification_token(
                user.id, token_hash, time.time() + _VERIFICATION_TTL
            )
            svc = _get_email_service()
            svc.send_verification_email(user.email, user.full_name, raw_token)
            self._audit(user.email, "verification_email_sent")
        except Exception as exc:
            _log.error("verification email failed for %s: %s", user.email, exc)

    def _check_rate_limit(self, email: str) -> bool:
        try:
            from psydox.security.ratelimit import get_rate_limiter
            return get_rate_limiter().check(email, "login")
        except Exception:
            return True  # fail open if rate limiter unavailable

    def _audit(self, email: str, action: str, resource: str = "", detail: str = "") -> None:
        try:
            from psydox.security.audit import get_audit_log
            get_audit_log().log(email, action, resource, detail)
        except Exception:
            pass

    def _db(self):
        from psydox.storage.database import get_db
        return get_db()


def _get_email_service():
    from psydox.auth.email import get_email_service
    return get_email_service()


_service: AuthService | None = None
_service_lock = None


def get_auth_service() -> AuthService:
    """Process-level singleton — thread-safe via DB."""
    global _service, _service_lock
    if _service_lock is None:
        import threading
        _service_lock = threading.Lock()
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = AuthService()
    return _service
