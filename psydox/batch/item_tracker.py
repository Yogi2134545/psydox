"""
Psydox Batch Item Tracker

Thin write-through to the job_items table for per-URL progress tracking
during a batch run.

All operations are best-effort — a DB failure never interrupts the batch.
When no job_id is provided (legacy callers), NoopTracker is returned and
every call silently does nothing.
"""
from __future__ import annotations

import hashlib
import logging
import time

_log = logging.getLogger("psydox.batch.item_tracker")

PENDING     = "pending"
DOWNLOADING = "downloading"
PROCESSING  = "processing"
COMPLETED   = "completed"
FAILED      = "failed"
RETRYING    = "retrying"


def make_item_id(job_id: str, style_code: str, url_index: int) -> str:
    """
    Deterministic 16-char item id.  Stable across retries, unique per
    (job, sku, url position) — no UUID randomness needed.
    """
    key = f"{job_id}:{style_code}:{url_index}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


class JobItemTracker:
    """Writes per-URL progress to job_items for a specific batch job."""

    def __init__(self, job_id: str):
        self._job_id = job_id
        self._db = None
        self._ok = False
        try:
            from psydox.storage.database import get_db
            self._db = get_db()
            self._ok = True
        except Exception as exc:
            _log.warning(
                "JobItemTracker: DB unavailable, per-item tracking disabled — %s", exc
            )

    def create(
        self, item_id: str, source_url: str, product_sku: str, row_index: int
    ) -> None:
        """Register an item as pending before processing starts."""
        if not self._ok:
            return
        now = time.time()
        try:
            self._db.execute(
                """INSERT OR IGNORE INTO job_items
                   (id, job_id, source_url, product_sku, row_index,
                    status, error, output_id, retry_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, '', '', 0, ?, ?)""",
                (item_id, self._job_id, source_url, product_sku,
                 row_index, PENDING, now, now),
            )
            self._db.commit()
        except Exception as exc:
            _log.debug("job_items.create failed: %s", exc)

    def update(
        self,
        item_id: str,
        status: str,
        error: str = "",
        output_id: str = "",
        retry_count: int = 0,
    ) -> None:
        """Update item status immediately (not batched — per the spec)."""
        if not self._ok:
            return
        try:
            self._db.execute(
                """UPDATE job_items
                   SET status=?, error=?, output_id=?, retry_count=?, updated_at=?
                   WHERE id=?""",
                (status, (error or "")[:500], output_id,
                 retry_count, time.time(), item_id),
            )
            self._db.commit()
        except Exception as exc:
            _log.debug("job_items.update failed: %s", exc)

    def stats(self) -> dict:
        """
        Return {status: count} for this job via a single GROUP BY query.
        Suitable for dashboard polling without loading image data into memory.
        """
        if not self._ok:
            return {}
        try:
            rows = self._db.execute(
                "SELECT status, COUNT(*) FROM job_items WHERE job_id=? GROUP BY status",
                (self._job_id,),
            ).fetchall()
            return {row[0]: int(row[1]) for row in rows}
        except Exception as exc:
            _log.debug("job_items.stats failed: %s", exc)
            return {}

    def aggregate(self) -> dict:
        """
        Return a structured aggregate suitable for the dashboard:
            total, pending, downloading, processing, completed, failed
        """
        raw = self.stats()
        total = sum(raw.values())
        return {
            "total":       total,
            "pending":     raw.get(PENDING, 0),
            "downloading": raw.get(DOWNLOADING, 0),
            "processing":  raw.get(PROCESSING, 0),
            "completed":   raw.get(COMPLETED, 0),
            "failed":      raw.get(FAILED, 0),
        }


class _NoopTracker:
    """Drop-in no-op used when no job_id is provided."""
    def create(self, *a, **kw) -> None: pass
    def update(self, *a, **kw) -> None: pass
    def stats(self) -> dict: return {}
    def aggregate(self) -> dict:
        return {"total": 0, "pending": 0, "downloading": 0,
                "processing": 0, "completed": 0, "failed": 0}


_NOOP = _NoopTracker()


def get_tracker(job_id: str | None) -> "JobItemTracker | _NoopTracker":
    """Return a live tracker when job_id is given, a no-op otherwise."""
    return JobItemTracker(job_id) if job_id else _NOOP
