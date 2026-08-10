"""
Psydox Projects Service

Projects are the top-level organizational unit.
Each project contains products, jobs, outputs, and reviews.

Projects persist to SQLite.  The in-memory cache is keyed by project ID.
All operations are user-scoped: a user can never access another user's projects.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

_log = logging.getLogger("psydox.projects")


class ProjectStatus(str, Enum):
    ACTIVE     = "active"
    PAUSED     = "paused"
    COMPLETED  = "completed"
    ARCHIVED   = "archived"


@dataclass
class Project:
    id:           str
    name:         str
    owner_email:  str
    status:       ProjectStatus = ProjectStatus.ACTIVE
    description:  str           = ""
    product_count: int          = 0
    job_count:    int           = 0
    approved_count: int         = 0
    review_count: int           = 0
    avg_quality:  float         = 0.0
    brand_id:     Optional[str] = None
    created_at:   float         = field(default_factory=time.time)
    updated_at:   float         = field(default_factory=time.time)
    metadata:     dict          = field(default_factory=dict)

    def status_icon(self) -> str:
        icons = {
            ProjectStatus.ACTIVE:    "🟢",
            ProjectStatus.PAUSED:    "🟡",
            ProjectStatus.COMPLETED: "✅",
            ProjectStatus.ARCHIVED:  "📦",
        }
        return icons.get(self.status, "⚪")

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "name":          self.name,
            "owner_email":   self.owner_email,
            "status":        self.status.value,
            "description":   self.description,
            "product_count": self.product_count,
            "job_count":     self.job_count,
            "approved_count": self.approved_count,
            "review_count":  self.review_count,
            "avg_quality":   self.avg_quality,
            "brand_id":      self.brand_id,
            "created_at":    self.created_at,
            "updated_at":    self.updated_at,
            "metadata":      self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> "Project":
        return Project(
            id            = d["id"],
            name          = d["name"],
            owner_email   = d["owner_email"],
            status        = ProjectStatus(d.get("status", "active")),
            description   = d.get("description", ""),
            product_count = d.get("product_count", 0),
            job_count     = d.get("job_count", 0),
            approved_count = d.get("approved_count", 0),
            review_count  = d.get("review_count", 0),
            avg_quality   = d.get("avg_quality", 0.0),
            brand_id      = d.get("brand_id"),
            created_at    = d.get("created_at", time.time()),
            updated_at    = d.get("updated_at", time.time()),
            metadata      = d.get("metadata", {}),
        )


class ProjectService:
    """CRUD for projects. Write-through to SQLite; read from cache first."""

    def __init__(self, cache: dict):
        self._cache = cache  # keyed by project_id

    def create(self, name: str, owner_email: str, description: str = "", brand_id: Optional[str] = None) -> Project:
        project = Project(
            id=str(uuid.uuid4()),
            name=name,
            owner_email=owner_email,
            description=description,
            brand_id=brand_id,
        )
        self._cache[project.id] = project
        self._persist(project)
        _log.info("Project created: %s (%s)", project.id, name)
        return project

    def get(self, project_id: str, owner_email: str) -> Optional[Project]:
        if project_id in self._cache:
            p = self._cache[project_id]
            if p.owner_email != owner_email:
                return None  # user isolation
            return p
        return self._load(project_id, owner_email)

    def list(self, owner_email: str, include_archived: bool = False) -> list[Project]:
        """Return projects owned by this user, newest first."""
        try:
            from psydox.storage.database import get_db
            db = get_db()
            rows = db.execute(
                "SELECT data FROM projects WHERE owner_email=? ORDER BY created_at DESC",
                (owner_email,)
            ).fetchall()
            projects = []
            for (data_json,) in rows:
                try:
                    p = Project.from_dict(json.loads(data_json))
                    if not include_archived and p.status == ProjectStatus.ARCHIVED:
                        continue
                    self._cache[p.id] = p
                    projects.append(p)
                except Exception:
                    pass
            return projects
        except Exception as exc:
            _log.debug("ProjectService.list DB error: %s", exc)
            return [p for p in self._cache.values()
                    if p.owner_email == owner_email
                    and (include_archived or p.status != ProjectStatus.ARCHIVED)]

    def update(self, project_id: str, owner_email: str, **kwargs) -> Optional[Project]:
        project = self.get(project_id, owner_email)
        if not project:
            return None
        for k, v in kwargs.items():
            if hasattr(project, k):
                setattr(project, k, v)
        project.updated_at = time.time()
        self._cache[project.id] = project
        self._persist(project)
        return project

    def delete(self, project_id: str, owner_email: str) -> bool:
        """Soft-delete by archiving."""
        return bool(self.update(project_id, owner_email, status=ProjectStatus.ARCHIVED))

    def increment_counts(self, project_id: str, owner_email: str,
                         jobs: int = 0, products: int = 0,
                         approved: int = 0, review: int = 0) -> None:
        project = self.get(project_id, owner_email)
        if not project:
            return
        project.job_count      += jobs
        project.product_count  += products
        project.approved_count += approved
        project.review_count   += review
        project.updated_at = time.time()
        self._cache[project.id] = project
        self._persist(project)

    def _persist(self, project: Project) -> None:
        try:
            from psydox.storage.database import get_db
            db = get_db()
            db.execute(
                """INSERT OR REPLACE INTO projects
                   (id, owner_email, name, status, data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project.id, project.owner_email, project.name, project.status.value,
                 json.dumps(project.to_dict()), project.created_at, project.updated_at)
            )
            db.commit()
        except Exception as exc:
            _log.debug("ProjectService._persist failed: %s", exc)

    def _load(self, project_id: str, owner_email: str) -> Optional[Project]:
        try:
            from psydox.storage.database import get_db
            db = get_db()
            row = db.execute(
                "SELECT data FROM projects WHERE id=? AND owner_email=?",
                (project_id, owner_email)
            ).fetchone()
            if not row:
                return None
            project = Project.from_dict(json.loads(row[0]))
            self._cache[project.id] = project
            return project
        except Exception as exc:
            _log.debug("ProjectService._load failed: %s", exc)
            return None


def get_project_service() -> ProjectService:
    try:
        import streamlit as st
        @st.cache_resource
        def _store():
            return {}
        return ProjectService(_store())
    except ImportError:
        return ProjectService({})
