"""
Psydox Persistent Job Manager

Jobs survive browser refresh, app restart, and worker restart.
Primary storage: SQLite (psydox.storage.database).
Session cache: st.cache_resource dict for fast in-memory access.
Fallback: pure in-memory if DB unavailable (jobs lost on restart).
"""
from __future__ import annotations

import json
import time
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

try:
    import streamlit as st
    _HAS_ST = True
except ImportError:
    st = None  # type: ignore
    _HAS_ST = False

_log = logging.getLogger("psydox.jobs")


class JobStatus(str, Enum):
    QUEUED      = "queued"
    PROCESSING  = "processing"
    QA          = "qa"
    AUTO_FIX    = "auto_fix"
    REVIEW      = "review"
    COMPLETED   = "completed"
    PARTIAL     = "partial"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


_STATUS_ICON = {
    JobStatus.QUEUED:     "⏳",
    JobStatus.PROCESSING: "⚙️",
    JobStatus.QA:         "🔍",
    JobStatus.AUTO_FIX:   "🔧",
    JobStatus.REVIEW:     "👁️",
    JobStatus.COMPLETED:  "✅",
    JobStatus.PARTIAL:    "⚠️",
    JobStatus.FAILED:     "❌",
    JobStatus.CANCELLED:  "🚫",
}


@dataclass
class Job:
    id:           str
    feature_id:   str
    label:        str
    status:       JobStatus      = JobStatus.QUEUED
    created_at:   float          = field(default_factory=time.time)
    updated_at:   float          = field(default_factory=time.time)
    completed_at: Optional[float] = None
    outputs:      list           = field(default_factory=list)
    errors:       list           = field(default_factory=list)
    metadata:     dict           = field(default_factory=dict)
    progress:     int            = 0
    user_email:   str            = ""
    project_id:   str            = ""

    def status_icon(self) -> str:
        return _STATUS_ICON.get(self.status, "•")

    def duration_s(self) -> Optional[float]:
        if self.completed_at:
            return round(self.completed_at - self.created_at, 1)
        return None

    def is_terminal(self) -> bool:
        return self.status in (
            JobStatus.COMPLETED, JobStatus.PARTIAL,
            JobStatus.FAILED, JobStatus.CANCELLED,
        )

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "feature_id":  self.feature_id,
            "label":       self.label,
            "status":      self.status.value,
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
            "completed_at": self.completed_at,
            "outputs":     self.outputs,
            "errors":      self.errors,
            "metadata":    self.metadata,
            "progress":    self.progress,
            "user_email":  self.user_email,
            "project_id":  self.project_id,
        }

    @staticmethod
    def from_dict(d: dict) -> "Job":
        j = Job(id=d["id"], feature_id=d["feature_id"], label=d["label"])
        j.status       = JobStatus(d.get("status", "queued"))
        j.created_at   = d.get("created_at", time.time())
        j.updated_at   = d.get("updated_at", time.time())
        j.completed_at = d.get("completed_at")
        j.outputs      = d.get("outputs", [])
        j.errors       = d.get("errors", [])
        j.metadata     = d.get("metadata", {})
        j.progress     = d.get("progress", 0)
        j.user_email   = d.get("user_email", "")
        j.project_id   = d.get("project_id", "")
        return j


class JobManager:
    """
    Persistent job store.
    Write-through to SQLite; reads from session cache first.
    """

    def __init__(self, store: dict):
        self._store = store
        self._db_ok = False
        try:
            from psydox.storage.database import get_db
            self._db = get_db()
            self._db_ok = True
        except Exception as exc:
            _log.warning("JobManager: DB unavailable, using in-memory only — %s", exc)
            self._db = None

    # ── CRUD ───────────────────────────────────────────────────────────────────

    def create(self, feature_id: str, label: str,
               user_email: str = "", project_id: str = "") -> Job:
        job = Job(
            id=str(uuid.uuid4())[:8],
            feature_id=feature_id,
            label=label,
            user_email=user_email,
            project_id=project_id,
        )
        self._store[job.id] = job
        self._persist(job)
        _log.info("Job created: %s [%s] %s", job.id, feature_id, label)
        return job

    def update(self, job_id: str, **kwargs) -> Optional[Job]:
        job = self._load(job_id)
        if not job:
            return None
        for k, v in kwargs.items():
            if hasattr(job, k):
                setattr(job, k, v)
        job.updated_at = time.time()
        if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED):
            if not job.completed_at:
                job.completed_at = time.time()
        self._store[job.id] = job
        self._persist(job)
        return job

    def finish(self, job_id: str, outputs: list, errors: list, metadata: dict) -> Optional[Job]:
        status = (
            JobStatus.COMPLETED if not errors else
            JobStatus.PARTIAL   if outputs else
            JobStatus.FAILED
        )
        return self.update(
            job_id, status=status, outputs=outputs, errors=errors,
            metadata=metadata, progress=100, completed_at=time.time(),
        )

    def cancel(self, job_id: str) -> Optional[Job]:
        job = self._load(job_id)
        if job and not job.is_terminal():
            return self.update(job_id, status=JobStatus.CANCELLED)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._load(job_id)

    def all(self, user_email: str = "", limit: int = 50) -> list[Job]:
        # Try DB first for cross-session persistence
        if self._db_ok:
            try:
                if user_email:
                    rows = self._db.execute(
                        "SELECT data FROM jobs WHERE user_email=? ORDER BY created_at DESC LIMIT ?",
                        (user_email, limit),
                    ).fetchall()
                else:
                    rows = self._db.execute(
                        "SELECT data FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                    ).fetchall()
                jobs = []
                for row in rows:
                    try:
                        j = Job.from_dict(json.loads(row[0]))
                        self._store[j.id] = j  # warm cache
                        jobs.append(j)
                    except Exception:
                        pass
                return jobs
            except Exception as exc:
                _log.debug("JobManager.all DB query failed: %s", exc)

        # Fallback: session cache
        jobs = list(self._store.values())
        if user_email:
            jobs = [j for j in jobs if j.user_email == user_email]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]

    def recent(self, user_email: str = "", n: int = 10) -> list[Job]:
        return self.all(user_email=user_email, limit=n)

    def stats(self, user_email: str = "") -> dict:
        if self._db_ok:
            try:
                _sql = """
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                        SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END) AS failed,
                        SUM(CASE WHEN status NOT IN
                            ('completed','partial','failed','cancelled')
                            THEN 1 ELSE 0 END) AS active
                    FROM jobs
                """
                if user_email:
                    row = self._db.execute(_sql + " WHERE user_email=?", (user_email,)).fetchone()
                else:
                    row = self._db.execute(_sql).fetchone()
                return {
                    "total":     int(row[0] or 0),
                    "completed": int(row[1] or 0),
                    "failed":    int(row[2] or 0),
                    "active":    int(row[3] or 0),
                }
            except Exception as exc:
                _log.debug("JobManager.stats SQL failed: %s", exc)
        # In-memory fallback
        jobs = list(self._store.values())
        if user_email:
            jobs = [j for j in jobs if j.user_email == user_email]
        return {
            "total":     len(jobs),
            "completed": sum(1 for j in jobs if j.status == JobStatus.COMPLETED),
            "failed":    sum(1 for j in jobs if j.status == JobStatus.FAILED),
            "active":    sum(1 for j in jobs if not j.is_terminal()),
        }

    # ── Internal ───────────────────────────────────────────────────────────────

    def _load(self, job_id: str) -> Optional[Job]:
        if job_id in self._store:
            return self._store[job_id]
        if self._db_ok:
            try:
                row = self._db.execute(
                    "SELECT data FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                if row:
                    j = Job.from_dict(json.loads(row[0]))
                    self._store[j.id] = j
                    return j
            except Exception as exc:
                _log.debug("JobManager._load DB failed: %s", exc)
        return None

    def _persist(self, job: Job) -> None:
        if not self._db_ok:
            return
        try:
            data = json.dumps(job.to_dict())
            self._db.execute("""
                INSERT OR REPLACE INTO jobs
                  (id, feature_id, label, status, user_email, project_id,
                   progress, data, created_at, updated_at, completed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                job.id, job.feature_id, job.label, job.status.value,
                job.user_email, job.project_id, job.progress, data,
                job.created_at, job.updated_at, job.completed_at,
            ))
            self._db.commit()
        except Exception as exc:
            _log.debug("JobManager._persist failed: %s", exc)


def _job_store() -> dict:
    if _HAS_ST:
        @st.cache_resource
        def _store():
            return {}
        return _store()
    return {}


def get_job_manager() -> JobManager:
    if _HAS_ST:
        @st.cache_resource
        def _make_manager():
            return JobManager(_job_store())
        return _make_manager()
    return JobManager(_job_store())
