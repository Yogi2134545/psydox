"""
Psydox Health Check

Checks the health of all subsystems.
Used by: admin UI, deployment health endpoint, monitoring.

Never raises. Returns a structured report so callers can act on individual
component status without parsing error messages.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

_log = logging.getLogger("psydox.health")


class ComponentStatus(str, Enum):
    HEALTHY     = "healthy"
    DEGRADED    = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass
class ComponentHealth:
    name:     str
    status:   ComponentStatus
    message:  str  = ""
    latency_ms: Optional[float] = None
    detail:   dict = field(default_factory=dict)

    def is_ok(self) -> bool:
        return self.status == ComponentStatus.HEALTHY

    def icon(self) -> str:
        return {"healthy": "✅", "degraded": "⚠️", "unavailable": "❌"}.get(self.status.value, "❓")

    def to_dict(self) -> dict:
        return {
            "name":       self.name,
            "status":     self.status.value,
            "message":    self.message,
            "latency_ms": self.latency_ms,
            "detail":     self.detail,
        }


@dataclass
class HealthReport:
    components: list[ComponentHealth] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)

    @property
    def overall(self) -> ComponentStatus:
        statuses = {c.status for c in self.components}
        if ComponentStatus.UNAVAILABLE in statuses:
            return ComponentStatus.UNAVAILABLE
        if ComponentStatus.DEGRADED in statuses:
            return ComponentStatus.DEGRADED
        return ComponentStatus.HEALTHY

    def to_dict(self) -> dict:
        return {
            "overall":     self.overall.value,
            "checked_at":  self.checked_at,
            "components":  [c.to_dict() for c in self.components],
        }


class HealthChecker:
    """Run health checks for all Psydox subsystems."""

    def check_all(self) -> HealthReport:
        report = HealthReport()
        for check_fn in [
            self._check_database,
            self._check_ai_provider,
            self._check_feature_registry,
            self._check_job_system,
            self._check_ai_cache,
        ]:
            try:
                component = check_fn()
            except Exception as e:
                component = ComponentHealth(
                    name=check_fn.__name__.replace("_check_", ""),
                    status=ComponentStatus.UNAVAILABLE,
                    message=f"Check crashed: {e}",
                )
            report.components.append(component)
        return report

    def _check_database(self) -> ComponentHealth:
        t0 = time.time()
        try:
            from psydox.storage.database import get_db, init_db
            init_db()
            db = get_db()
            db.execute("SELECT COUNT(*) FROM jobs").fetchone()
            ms = (time.time() - t0) * 1000
            return ComponentHealth("database", ComponentStatus.HEALTHY,
                                   "SQLite responding", latency_ms=round(ms, 1))
        except Exception as e:
            return ComponentHealth("database", ComponentStatus.UNAVAILABLE, str(e))

    def _check_ai_provider(self) -> ComponentHealth:
        t0 = time.time()
        try:
            from psydox.ai_core.orchestrator import get_orchestrator
            orch = get_orchestrator()
            provider_name = type(orch._provider).__name__ if hasattr(orch, "_provider") else "unknown"
            ms = (time.time() - t0) * 1000
            status = ComponentStatus.HEALTHY
            msg = f"Provider: {provider_name}"

            import os
            if os.environ.get("DEBUG_MODE", "").lower() in ("1", "true"):
                msg += " (mock — set DEBUG_MODE=false for production AI)"
                status = ComponentStatus.DEGRADED

            return ComponentHealth("ai_provider", status, msg, latency_ms=round(ms, 1),
                                   detail={"provider": provider_name})
        except Exception as e:
            return ComponentHealth("ai_provider", ComponentStatus.UNAVAILABLE, str(e))

    def _check_feature_registry(self) -> ComponentHealth:
        try:
            from psydox.core.registry import get_registry
            registry = get_registry()
            features = registry.all()
            return ComponentHealth(
                "feature_registry",
                ComponentStatus.HEALTHY if features else ComponentStatus.DEGRADED,
                f"{len(features)} features registered",
                detail={"feature_ids": [f.manifest.id for f in features]},
            )
        except Exception as e:
            return ComponentHealth("feature_registry", ComponentStatus.UNAVAILABLE, str(e))

    def _check_job_system(self) -> ComponentHealth:
        t0 = time.time()
        try:
            from psydox.jobs.manager import get_job_manager
            mgr = get_job_manager()
            stats = mgr.stats("")
            ms = (time.time() - t0) * 1000
            return ComponentHealth("job_system", ComponentStatus.HEALTHY,
                                   f"{stats.get('total', 0)} total jobs",
                                   latency_ms=round(ms, 1), detail=stats)
        except Exception as e:
            return ComponentHealth("job_system", ComponentStatus.UNAVAILABLE, str(e))

    def _check_ai_cache(self) -> ComponentHealth:
        try:
            from psydox.ai_core.cache import AICache
            cache = AICache()
            stats = cache.stats()
            msg = f"hit_rate={stats.get('hit_rate', 'n/a')}" if stats.get("enabled") else "disabled"
            return ComponentHealth("ai_cache",
                                   ComponentStatus.HEALTHY if stats.get("enabled") else ComponentStatus.DEGRADED,
                                   msg, detail=stats)
        except Exception as e:
            return ComponentHealth("ai_cache", ComponentStatus.DEGRADED, str(e))


_CHECKER: HealthChecker | None = None


def get_health_checker() -> HealthChecker:
    global _CHECKER
    if _CHECKER is None:
        _CHECKER = HealthChecker()
    return _CHECKER


def check_health() -> HealthReport:
    """Convenience function — run all health checks."""
    return get_health_checker().check_all()
