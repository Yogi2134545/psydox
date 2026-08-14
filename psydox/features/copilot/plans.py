"""
Simple Plans manager for Copilot/AI Studio.

This file implements a tiny in-memory Plan model and a PlanManager with a
`load_default()` helper that returns a few preset plans. This is intentionally
lightweight so the feature can be shipped without introducing database
migrations. Replace PlanManager with a DB-backed implementation later.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class Plan:
    id: str
    name: str
    description: str
    monthly_price_cents: int
    ai_minutes_per_month: int
    concurrency: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


class PlanManager:
    """In-memory plan manager. Thread-safe enough for read-only access.

    For the MVP we keep definitions in-code. A future version should persist
    plans and track usage (quotas) per-user in a database.
    """

    def __init__(self, plans: Optional[List[Plan]] = None):
        self._plans = {p.id: p for p in (plans or [])}

    @classmethod
    def load_default(cls) -> "PlanManager":
        plans = [
            Plan(id="free", name="Free", description="Basic access with limited AI minutes.", monthly_price_cents=0, ai_minutes_per_month=100, concurrency=1),
            Plan(id="starter", name="Starter", description="More AI minutes and higher concurrency.", monthly_price_cents=999, ai_minutes_per_month=2000, concurrency=2),
            Plan(id="pro", name="Pro", description="Higher throughput for commercial use.", monthly_price_cents=4999, ai_minutes_per_month=10000, concurrency=5),
        ]
        return cls(plans)

    def list_plans(self) -> List[Plan]:
        return list(self._plans.values())

    def get_plan(self, plan_id: Optional[str]) -> Optional[Plan]:
        if not plan_id:
            return None
        return self._plans.get(plan_id)

    def add_plan(self, plan: Plan) -> None:
        self._plans[plan.id] = plan

    def remove_plan(self, plan_id: str) -> None:
        self._plans.pop(plan_id, None)

    # Placeholder quota checks: real implementation should integrate with a
    # per-user usage tracker in the database.
    def check_quota(self, user_email: str, plan_id: str, minutes_needed: int) -> bool:
        plan = self.get_plan(plan_id)
        if not plan:
            return False
        # For MVP always allow; policy enforcement happens elsewhere.
        return True
