from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional

from psydox.core.registry import FeatureModule
from psydox.core.manifest import (
    FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType,
)

from .plans import Plan, PlanManager

_log = logging.getLogger("psydox.features.copilot")


_MANIFEST = FeatureManifest(
    id="copilot",
    name="Copilot / AI Studio",
    description="AI Studio entrypoint and subscription/plan gating for Copilot features.",
    category=FeatureCategory.CREATIVE,
    icon="🤖",
    status=FeatureStatus.BETA,
    requires_ai=True,
    supports_batch=False,
    supports_reference=True,
    supports_brand=True,
    supports_quality_check=False,
    processing_type=ProcessingType.SLOW,
    version="0.1.0",
    tags=["ai","studio","copilot","plans"],
    required_permission="ai_studio",
)


class CopilotFeature(FeatureModule):

    def __init__(self):
        # Simple plan manager instance — replaceable with a DB-backed manager later
        self._plans = PlanManager.load_default()

    @property
    def manifest(self) -> FeatureManifest:
        return _MANIFEST

    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        # Copilot feature itself is an entrypoint; actual AI tasks live in ai_core.
        # Validate optional plan selection when present.
        errors = []
        plan_id = inputs.get("plan_id")
        if plan_id:
            if not self._plans.get_plan(plan_id):
                errors.append(f"Unknown plan: {plan_id}")
        return len(errors) == 0, errors

    def execute(self, inputs: dict, context: dict) -> dict:
        # This feature does not perform generation directly. Return a descriptor
        # that the Studio UI or orchestrator can use to open the Copilot workspace.
        try:
            plan_id = inputs.get("plan_id")
            plan = self._plans.get_plan(plan_id) if plan_id else None
            return {
                "success": True,
                "outputs": [],
                "errors": [],
                "metadata": {
                    "feature_id": self.manifest.id,
                    "plan": asdict(plan) if plan else None,
                },
            }
        except Exception as exc:
            _log.exception("CopilotFeature.execute failed")
            return {"success": False, "outputs": [], "errors": [str(exc)], "metadata": {}}

    def get_ui_config(self) -> dict:
        # Expose plan list to the dashboard/studio. UI can present these to users.
        plans = [p.to_dict() for p in self._plans.list_plans()]
        return {
            "inputs": [
                {"name": "plan_id", "type": "select", "label": "Subscription plan", "options": [p["id"] for p in plans], "default": plans[0]["id"] if plans else None},
            ],
            "options": [],
            "plans": plans,
        }


# Module-level instance for quick manual registration if desired by importers
feature = CopilotFeature()
