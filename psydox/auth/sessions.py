"""Psydox Auth — DB-backed session management."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from psydox.auth.models import Session

_log = logging.getLogger("psydox.auth.sessions")

_SESSION_TTL_SHORT   = 86400       # 1 day (normal login)
_SESSION_TTL_LONG    = 30 * 86400  # 30 days (remember me)


class SessionService:

    def create(self, user_id: str, remember_me: bool = False, user_agent: str = "") -> Session:
        now = time.time()
        ttl = _SESSION_TTL_LONG if remember_me else _SESSION_TTL_SHORT
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            created_at=now,
            expires_at=now + ttl,
            last_activity_at=now,
            remember_me=remember_me,
            user_agent=user_agent[:512],
        )
        db = self._db()
        db.execute(
            """INSERT INTO sessions
               (id, user_id, created_at, expires_at, last_activity_at, user_agent, remember_me)
               VALUES (?,?,?,?,?,?,?)""",
            (session.id, session.user_id, session.created_at,
             session.expires_at, session.last_activity_at,
             session.user_agent, 1 if remember_me else 0),
        )
        db.commit()
        return session

    def get(self, session_id: str) -> Optional[Session]:
        row = self._db().execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return self._row(row)

    def validate(self, session_id: str) -> Optional[Session]:
        """Return the session if it is valid (not expired, not revoked)."""
        session = self.get(session_id)
        if session and session.is_valid():
            self._touch(session_id)
            return session
        return None

    def revoke(self, session_id: str) -> None:
        self._db().execute(
            "UPDATE sessions SET revoked_at=? WHERE id=?",
            (time.time(), session_id),
        )
        self._db().commit()

    def revoke_all(self, user_id: str) -> int:
        """Revoke all non-expired, non-revoked sessions for a user. Returns count."""
        now = time.time()
        cur = self._db().execute(
            "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND expires_at > ?",
            (now, user_id, now),
        )
        self._db().commit()
        return cur.rowcount

    def revoke_others(self, user_id: str, current_session_id: str) -> int:
        """Revoke all sessions for user_id except current_session_id. Returns count."""
        now = time.time()
        cur = self._db().execute(
            "UPDATE sessions SET revoked_at=? "
            "WHERE user_id=? AND id != ? AND revoked_at IS NULL AND expires_at > ?",
            (now, user_id, current_session_id, now),
        )
        self._db().commit()
        return cur.rowcount

    def list_active(self, user_id: str) -> list[Session]:
        now = time.time()
        rows = self._db().execute(
            """SELECT * FROM sessions
               WHERE user_id=? AND revoked_at IS NULL AND expires_at > ?
               ORDER BY last_activity_at DESC""",
            (user_id, now),
        ).fetchall()
        return [self._row(r) for r in rows]

    def cleanup_expired(self) -> int:
        """Remove sessions older than 30 days that are expired or revoked."""
        cutoff = time.time() - 30 * 86400
        cur = self._db().execute(
            "DELETE FROM sessions WHERE created_at < ?", (cutoff,)
        )
        self._db().commit()
        return cur.rowcount

    # ── Internal ──────────────────────────────────────────────────────────────

    def _touch(self, session_id: str) -> None:
        self._db().execute(
            "UPDATE sessions SET last_activity_at=? WHERE id=?",
            (time.time(), session_id),
        )
        self._db().commit()

    def _db(self):
        from psydox.storage.database import get_db
        return get_db()

    def _row(self, row) -> Session:
        r = dict(row)
        return Session(
            id=r["id"],
            user_id=r["user_id"],
            created_at=r["created_at"],
            expires_at=r["expires_at"],
            last_activity_at=r["last_activity_at"],
            remember_me=bool(r.get("remember_me", 0)),
            revoked_at=r.get("revoked_at"),
            user_agent=r.get("user_agent", ""),
        )


_service: SessionService | None = None

def get_session_service() -> SessionService:
    global _service
    if _service is None:
        _service = SessionService()
    return _service
