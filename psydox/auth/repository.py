"""Psydox Auth — user repository (DB CRUD + YAML migration).

All methods take/return User dataclasses.
Never return password_hash or token fields to calling code beyond
what AuthService explicitly needs.

Migration: migrate_from_yaml() reads users.yaml and inserts users that
don't yet exist in the DB.  Existing users (by email) are skipped.
Migrated users get email_verified=True and status=ACTIVE so they can
log in immediately without going through the verification flow.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from psydox.auth.models import User, AccountStatus

_log = logging.getLogger("psydox.auth.repository")

# Map roles that exist in users.yaml but not in original RBAC enum
_ROLE_NORMALISE: dict[str, str] = {
    "operator":          "operator",
    "catalog_operator":  "catalog_operator",
    "creative":          "creative",
    "reviewer":          "reviewer",
    "editor":            "editor",
    "owner":             "owner",
    "admin":             "admin",
    "manager":           "manager",
    "viewer":            "viewer",
    "user":              "user",
}


class UserRepository:

    # ── Create ────────────────────────────────────────────────────────────────

    def create(
        self,
        full_name:         str,
        email:             str,
        password_hash:     str,
        role:              str           = "user",
        email_verified:    bool          = False,
        status:            AccountStatus = AccountStatus.PENDING_VERIFICATION,
        terms_accepted_at: Optional[float] = None,
    ) -> User:
        now = time.time()
        uid = str(uuid.uuid4())
        norm_role = _ROLE_NORMALISE.get(role.lower(), "user")
        db = self._db()
        db.execute(
            """INSERT INTO users
               (id, full_name, email, password_hash, email_verified, status, role,
                created_at, updated_at, terms_accepted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (uid, full_name, email.lower().strip(), password_hash,
             1 if email_verified else 0,
             status.value, norm_role, now, now, terms_accepted_at),
        )
        db.commit()
        return self.get_by_id(uid)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_id(self, user_id: str) -> Optional[User]:
        row = self._db().execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
        return self._row_to_user(row) if row else None

    def get_by_email(self, email: str) -> Optional[User]:
        row = self._db().execute(
            "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
        ).fetchone()
        return self._row_to_user(row) if row else None

    def email_exists(self, email: str) -> bool:
        row = self._db().execute(
            "SELECT 1 FROM users WHERE email=?", (email.lower().strip(),)
        ).fetchone()
        return row is not None

    def list_all(self) -> list[User]:
        rows = self._db().execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [self._row_to_user(r) for r in rows]

    # ── Update ────────────────────────────────────────────────────────────────

    def update_name(self, user_id: str, full_name: str) -> None:
        self._db().execute(
            "UPDATE users SET full_name=?, updated_at=? WHERE id=?",
            (full_name, time.time(), user_id),
        )
        self._db().commit()

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        self._db().execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
            (password_hash, time.time(), user_id),
        )
        self._db().commit()

    def set_verification_token(
        self, user_id: str, token_hash: str, expires_at: float
    ) -> None:
        self._db().execute(
            "UPDATE users SET verification_token_hash=?, verification_expires_at=?, updated_at=? WHERE id=?",
            (token_hash, expires_at, time.time(), user_id),
        )
        self._db().commit()

    def verify_email(self, user_id: str) -> None:
        now = time.time()
        self._db().execute(
            """UPDATE users
               SET email_verified=1, verified_at=?, status=?,
                   verification_token_hash=NULL, verification_expires_at=NULL, updated_at=?
               WHERE id=?""",
            (now, AccountStatus.ACTIVE.value, now, user_id),
        )
        self._db().commit()

    def set_reset_token(
        self, user_id: str, token_hash: str, expires_at: float
    ) -> None:
        self._db().execute(
            "UPDATE users SET reset_token_hash=?, reset_expires_at=?, updated_at=? WHERE id=?",
            (token_hash, expires_at, time.time(), user_id),
        )
        self._db().commit()

    def clear_reset_token(self, user_id: str) -> None:
        self._db().execute(
            "UPDATE users SET reset_token_hash=NULL, reset_expires_at=NULL, updated_at=? WHERE id=?",
            (time.time(), user_id),
        )
        self._db().commit()

    def update_password(self, user_id: str, new_hash: str) -> None:
        self._db().execute(
            "UPDATE users SET password_hash=?, reset_token_hash=NULL, reset_expires_at=NULL, updated_at=? WHERE id=?",
            (new_hash, time.time(), user_id),
        )
        self._db().commit()

    def record_login(self, user_id: str) -> None:
        now = time.time()
        self._db().execute(
            """UPDATE users
               SET last_login_at=?, failed_login_attempts=0, locked_until=NULL, updated_at=?
               WHERE id=?""",
            (now, now, user_id),
        )
        self._db().commit()

    def record_failed_login(self, user_id: str, lockout_threshold: int = 5, lockout_seconds: int = 900) -> None:
        row = self._db().execute(
            "SELECT failed_login_attempts FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not row:
            return
        new_attempts = (row[0] or 0) + 1
        locked_until = None
        if new_attempts >= lockout_threshold:
            locked_until = time.time() + lockout_seconds
            new_attempts = 0  # reset counter after lockout applied
        self._db().execute(
            "UPDATE users SET failed_login_attempts=?, locked_until=?, updated_at=? WHERE id=?",
            (new_attempts, locked_until, time.time(), user_id),
        )
        self._db().commit()

    def update_status(self, user_id: str, status: AccountStatus) -> None:
        self._db().execute(
            "UPDATE users SET status=?, updated_at=? WHERE id=?",
            (status.value, time.time(), user_id),
        )
        self._db().commit()

    def update_role(self, user_id: str, role: str) -> None:
        norm = _ROLE_NORMALISE.get(role.lower())
        if norm is None:
            _log.warning("update_role: unknown role %r — rejected", role)
            return   # refuse unknown roles silently rather than silently downgrading
        self._db().execute(
            "UPDATE users SET role=?, updated_at=? WHERE id=?",
            (norm, time.time(), user_id),
        )
        self._db().commit()

    def update_email(self, user_id: str, new_email: str) -> None:
        self._db().execute(
            """UPDATE users SET email=?, email_verified=0, verified_at=NULL,
               verification_token_hash=NULL, verification_expires_at=NULL,
               status=?, updated_at=? WHERE id=?""",
            (new_email.lower().strip(), AccountStatus.PENDING_VERIFICATION.value,
             time.time(), user_id),
        )
        self._db().commit()

    # ── YAML migration ────────────────────────────────────────────────────────

    def migrate_from_yaml(self, yaml_path: Optional[str] = None) -> int:
        """
        Import users from users.yaml into the DB.
        Existing users (by email) are skipped.
        Returns the number of users inserted.
        """
        import yaml

        path = Path(yaml_path or "users.yaml")
        if not path.exists():
            return 0
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception as exc:
            _log.warning("migrate_from_yaml: could not read %s: %s", path, exc)
            return 0

        inserted = 0
        now = time.time()
        for email, udata in data.items():
            email = email.lower().strip()
            if not email or not isinstance(udata, dict):
                continue
            if self.email_exists(email):
                continue
            raw_role = udata.get("role", "viewer")
            norm_role = _ROLE_NORMALISE.get(raw_role.lower(), "viewer")
            uid = str(uuid.uuid4())
            try:
                self._db().execute(
                    """INSERT INTO users
                       (id, full_name, email, password_hash, email_verified, status, role,
                        created_at, updated_at, last_login_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (uid, udata.get("name", email), email,
                     udata.get("password_hash", ""),
                     1, AccountStatus.ACTIVE.value, norm_role,
                     now, now, None),
                )
                inserted += 1
            except Exception as exc:
                _log.warning("migrate_from_yaml: skipped %s: %s", email, exc)

        if inserted:
            self._db().commit()
            _log.info("Migrated %d user(s) from %s to DB", inserted, path)
        return inserted

    # ── Internal ──────────────────────────────────────────────────────────────

    def _db(self):
        from psydox.storage.database import get_db
        return get_db()

    def _row_to_user(self, row) -> User:
        r = dict(row)
        return User(
            id=r["id"],
            full_name=r.get("full_name", ""),
            email=r["email"],
            password_hash=r["password_hash"],
            email_verified=bool(r.get("email_verified", 0)),
            status=AccountStatus(r.get("status", "pending_verification")),
            role=r.get("role", "viewer"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            verification_token_hash=r.get("verification_token_hash"),
            verification_expires_at=r.get("verification_expires_at"),
            verified_at=r.get("verified_at"),
            reset_token_hash=r.get("reset_token_hash"),
            reset_expires_at=r.get("reset_expires_at"),
            last_login_at=r.get("last_login_at"),
            terms_accepted_at=r.get("terms_accepted_at"),
            failed_login_attempts=int(r.get("failed_login_attempts", 0)),
            locked_until=r.get("locked_until"),
        )


_repo: UserRepository | None = None

def get_user_repository() -> UserRepository:
    global _repo
    if _repo is None:
        _repo = UserRepository()
    return _repo
