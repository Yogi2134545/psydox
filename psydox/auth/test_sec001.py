"""SEC-001 regression test — yaml-seeded accounts with empty password_hash must be rejected.

The vulnerability: a non-owner account seeded from users.yaml arrives in the DB with
password_hash="".  The old login() code accepted the FIRST submitted password as the
permanent password, letting any attacker who knows the victim email permanently own
that account.

The fix: login() must return AuthResult.fail(..., "NOT_ACTIVATED") for any non-owner
account whose password_hash is not a valid bcrypt hash.
"""
from __future__ import annotations

import time
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stubs so AuthService can be instantiated without a real DB/config
# ---------------------------------------------------------------------------

def _make_user(email: str, password_hash: str, role: str = "operator") -> MagicMock:
    from psydox.auth.models import AccountStatus, User
    return User(
        id="test-uid-001",
        full_name="Test User",
        email=email,
        password_hash=password_hash,
        email_verified=True,
        status=AccountStatus.ACTIVE,
        role=role,
        created_at=time.time(),
        updated_at=time.time(),
    )


class TestSEC001YamlSeededAccountBlocked(unittest.TestCase):
    """A non-owner account with empty password_hash must never be logged in."""

    def _build_service(self, user_in_db):
        """Return an AuthService whose repo returns *user_in_db* for any get_by_email call."""
        from psydox.auth.service import AuthService
        from psydox.auth.models import AccountStatus

        svc = object.__new__(AuthService)

        # Stub repo
        repo = MagicMock()
        repo.get_by_email.return_value = user_in_db
        repo.migrate_from_yaml.return_value = 0
        repo.list_all.return_value = [user_in_db] if user_in_db else []

        # Stub sessions
        sessions = MagicMock()
        sessions.create.return_value = MagicMock(id="sess-001")

        # Stub PasswordService (real bcrypt, but won't be called for this path)
        from psydox.auth.password import PasswordService
        pw = PasswordService()

        # Stub TokenService
        from psydox.auth.tokens import TokenService
        tok = TokenService()

        svc._repo = repo
        svc._sessions = sessions
        svc._pw = pw
        svc._tok = tok
        svc._migrated = True  # skip _ensure_migrated

        # Stub rate limiter: always allow
        with patch("psydox.security.ratelimit.get_rate_limiter") as rl:
            rl.return_value.check.return_value = True

        # Stub audit log
        with patch("psydox.security.audit.get_audit_log"):
            pass

        return svc

    def _call_login(self, svc, email, password):
        """Call login() with all security side-effects patched out."""
        with patch.object(svc, "_check_rate_limit", return_value=True), \
             patch.object(svc, "_audit"):
            return svc.login(email, password)

    # ------------------------------------------------------------------
    # Core test: empty password_hash -> NOT_ACTIVATED
    # ------------------------------------------------------------------

    def test_empty_password_hash_is_rejected(self):
        """An attacker submitting any password for a yaml-seeded account must be blocked."""
        victim_email = "victim@example.com"
        user = _make_user(victim_email, password_hash="")

        svc = self._build_service(user)
        result = self._call_login(svc, victim_email, "AttackerPw1")

        self.assertFalse(result.success, "Login must fail for empty password_hash")
        self.assertEqual(result.error_code, "NOT_ACTIVATED")
        self.assertIn("not yet activated", result.error.lower())

    def test_no_password_hash_written_on_rejection(self):
        """The repo's update_password_hash must NOT be called when login is blocked."""
        victim_email = "victim2@example.com"
        user = _make_user(victim_email, password_hash="")

        svc = self._build_service(user)
        self._call_login(svc, victim_email, "AttackerPw1")

        svc._repo.update_password_hash.assert_not_called()

    def test_whitespace_only_password_hash_is_rejected(self):
        """A password_hash that is whitespace (not a valid bcrypt hash) must also be blocked."""
        victim_email = "victim3@example.com"
        user = _make_user(victim_email, password_hash="   ")

        svc = self._build_service(user)
        result = self._call_login(svc, victim_email, "AttackerPw1")

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "NOT_ACTIVATED")

    def test_none_password_hash_is_rejected(self):
        """A None password_hash must be blocked too."""
        victim_email = "victim4@example.com"
        user = _make_user(victim_email, password_hash=None)   # type: ignore[arg-type]

        svc = self._build_service(user)
        result = self._call_login(svc, victim_email, "AttackerPw1")

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "NOT_ACTIVATED")

    # ------------------------------------------------------------------
    # Sanity check: real bcrypt hash still works normally
    # ------------------------------------------------------------------

    def test_valid_bcrypt_hash_proceeds_to_password_check(self):
        """A user WITH a real bcrypt hash must proceed past the activation gate."""
        import bcrypt
        victim_email = "legit@example.com"
        real_hash = bcrypt.hashpw(b"LegitPw99", bcrypt.gensalt(rounds=4)).decode()
        user = _make_user(victim_email, password_hash=real_hash)

        svc = self._build_service(user)
        # Wrong password — we just want to confirm we reach the password-check step,
        # not the NOT_ACTIVATED gate.
        result = self._call_login(svc, victim_email, "WrongPw99")

        self.assertFalse(result.success)
        # Must be INVALID_CREDENTIALS, not NOT_ACTIVATED
        self.assertNotEqual(result.error_code, "NOT_ACTIVATED",
                            "A user with a real hash must not be blocked at the activation gate")


if __name__ == "__main__":
    unittest.main()
