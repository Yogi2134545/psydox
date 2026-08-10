"""
Psydox Audit Log

Records security-relevant events to the database.
Never raises — audit failures are logged but never block the request.

Tracked events:
  login, logout, login_failed
  project_created, project_deleted
  generation, batch_generation
  output_approved, output_rejected
  download
  settings_changed, admin_action
  feature_accessed
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

_log = logging.getLogger("psydox.security.audit")


class AuditLog:

    def log(
        self,
        user_email: str,
        action:     str,
        resource:   str = "",
        detail:     str = "",
        ip_address: str = "",
    ) -> None:
        """Write an audit entry.  Never raises."""
        try:
            self._write(user_email, action, resource, detail, ip_address)
        except Exception as exc:
            _log.warning("AuditLog.log failed: %s", exc)

    def _write(self, user_email: str, action: str,
                resource: str, detail: str, ip_address: str) -> None:
        try:
            from psydox.storage.database import get_db
            db = get_db()
            db.execute(
                """INSERT INTO audit_logs
                   (user_email, action, resource, detail, ip_address, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (user_email, action, resource, detail, ip_address, time.time()),
            )
            db.commit()
        except Exception as exc:
            _log.debug("AuditLog DB write failed: %s", exc)

    def recent(self, user_email: str = "", limit: int = 50) -> list[dict]:
        """Return recent audit entries."""
        try:
            from psydox.storage.database import get_db
            db = get_db()
            if user_email:
                rows = db.execute(
                    "SELECT user_email,action,resource,detail,created_at "
                    "FROM audit_logs WHERE user_email=? ORDER BY created_at DESC LIMIT ?",
                    (user_email, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT user_email,action,resource,detail,created_at "
                    "FROM audit_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


_audit: Optional[AuditLog] = None

def get_audit_log() -> AuditLog:
    global _audit
    if _audit is None:
        _audit = AuditLog()
    return _audit
