"""Psydox Job Manager — in-memory job/project tracking (Railway-safe, no persistence needed)."""
import time
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import streamlit as st

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
    id:          str
    feature_id:  str
    label:       str
    status:      JobStatus     = JobStatus.QUEUED
    created_at:  float         = field(default_factory=time.time)
    updated_at:  float         = field(default_factory=time.time)
    completed_at: Optional[float] = None
    outputs:     list          = field(default_factory=list)
    errors:      list          = field(default_factory=list)
    metadata:    dict          = field(default_factory=dict)
    progress:    int           = 0
    user_email:  str           = ""

    def status_icon(self) -> str:
        return _STATUS_ICON.get(self.status, "•")

    def duration_s(self) -> Optional[float]:
        if self.completed_at:
            return round(self.completed_at - self.created_at, 1)
        return None

    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.PARTIAL,
                               JobStatus.FAILED, JobStatus.CANCELLED)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "feature_id":  self.feature_id,
            "label":       self.label,
            "status":      self.status.value,
            "created_at":  self.created_at,
            "progress":    self.progress,
            "errors":      self.errors,
            "metadata":    self.metadata,
        }


class JobManager:
    """Session-scoped job store (backed by st.cache_resource for cross-rerun durability)."""

    def __init__(self, store: dict):
        self._store = store  # shared dict from st.cache_resource

    def create(self, feature_id: str, label: str, user_email: str = "") -> Job:
        job = Job(
            id=str(uuid.uuid4())[:8],
            feature_id=feature_id,
            label=label,
            user_email=user_email,
        )
        self._store[job.id] = job
        _log.info("Job created: %s [%s] %s", job.id, feature_id, label)
        return job

    def update(self, job_id: str, **kwargs) -> Optional[Job]:
        job = self._store.get(job_id)
        if not job:
            return None
        for k, v in kwargs.items():
            if hasattr(job, k):
                setattr(job, k, v)
        job.updated_at = time.time()
        if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED):
            job.completed_at = job.completed_at or time.time()
        return job

    def finish(self, job_id: str, outputs: list, errors: list, metadata: dict) -> Optional[Job]:
        status = JobStatus.COMPLETED if not errors else (
            JobStatus.PARTIAL if outputs else JobStatus.FAILED
        )
        return self.update(
            job_id,
            status=status,
            outputs=outputs,
            errors=errors,
            metadata=metadata,
            progress=100,
            completed_at=time.time(),
        )

    def cancel(self, job_id: str) -> Optional[Job]:
        job = self._store.get(job_id)
        if job and not job.is_terminal():
            return self.update(job_id, status=JobStatus.CANCELLED)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._store.get(job_id)

    def all(self, user_email: str = "", limit: int = 50) -> list[Job]:
        jobs = list(self._store.values())
        if user_email:
            jobs = [j for j in jobs if j.user_email == user_email]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]

    def recent(self, user_email: str = "", n: int = 10) -> list[Job]:
        return self.all(user_email=user_email, limit=n)

    def stats(self, user_email: str = "") -> dict:
        jobs = self.all(user_email=user_email, limit=500)
        return {
            "total":     len(jobs),
            "completed": sum(1 for j in jobs if j.status == JobStatus.COMPLETED),
            "failed":    sum(1 for j in jobs if j.status == JobStatus.FAILED),
            "active":    sum(1 for j in jobs if not j.is_terminal()),
        }


@st.cache_resource
def _job_store() -> dict:
    return {}


def get_job_manager() -> JobManager:
    return JobManager(_job_store())
