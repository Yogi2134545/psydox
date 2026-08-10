"""
Psydox Feature — Review Center

The Review Center is not an image processor — it is a decision-making feature.
It retrieves pending outputs from the job system, runs quality/fidelity checks,
and records human decisions (approve / reject / request fix).

Every review decision is stored in the `reviews` table.

This feature auto-discovers and appears in the dashboard like any other.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from psydox.core.registry import FeatureModule
from psydox.core.manifest import FeatureManifest, FeatureCategory, FeatureStatus, ProcessingType

_log = logging.getLogger("psydox.features.review")

_MANIFEST = FeatureManifest(
    id="review",
    name="Review Center",
    description="Review generated outputs, check quality and fidelity, approve or reject",
    category=FeatureCategory.WORKFLOW,
    icon="👁️",
    status=FeatureStatus.STABLE,
    requires_ai=False,
    supports_batch=True,
    supports_reference=True,
    supports_brand=False,
    supports_quality_check=True,
    processing_type=ProcessingType.INSTANT,
    version="1.0.0",
    tags=["review", "approve", "reject", "quality", "fidelity"],
    required_permission="review",
)


class ReviewFeature(FeatureModule):
    """Review center: human decision + optional auto-fix trigger."""

    @property
    def manifest(self) -> FeatureManifest:
        return _MANIFEST

    def validate_input(self, inputs: dict) -> tuple[bool, list[str]]:
        errors = []
        action = inputs.get("action", "score")
        valid  = {"score", "approve", "reject", "request_fix", "pending"}
        if action not in valid:
            errors.append(f"Unknown review action '{action}'.")
        return len(errors) == 0, errors

    def execute(self, inputs: dict, context: dict) -> dict:
        action      = inputs.get("action", "score")
        image_bytes = inputs.get("image_bytes")
        orig_bytes  = inputs.get("original_bytes")
        output_id   = inputs.get("output_id", "")
        job_id      = inputs.get("job_id", "")
        reviewer    = context.get("user_email", "")
        notes       = inputs.get("notes", "")

        if action == "score":
            return self._score_output(image_bytes, orig_bytes, output_id, job_id)
        elif action in ("approve", "reject", "request_fix"):
            return self._record_decision(action, output_id, job_id, reviewer, notes)
        elif action == "pending":
            return self._list_pending(reviewer)
        else:
            return {"success": False, "outputs": [], "errors": ["Unknown action"], "metadata": {}}

    def _score_output(self, image_bytes: Optional[bytes], orig_bytes: Optional[bytes],
                      output_id: str, job_id: str) -> dict:
        """Run quality + fidelity checks and return scores."""
        if not image_bytes:
            return {"success": False, "outputs": [], "errors": ["Image required for scoring"], "metadata": {}}

        quality_result = None
        fidelity_result = None

        try:
            from psydox.quality.engine import AIQualityEngine
            quality_result = AIQualityEngine().score(image_bytes, orig_bytes).to_dict() \
                if hasattr(AIQualityEngine().score(image_bytes, orig_bytes), "to_dict") \
                else _quality_to_dict(AIQualityEngine().score(image_bytes, orig_bytes))
        except Exception as e:
            _log.debug("Quality scoring error: %s", e)
            quality_result = {"error": str(e)}

        if orig_bytes:
            try:
                from psydox.quality.fidelity import FidelityEngine
                fidelity_result = FidelityEngine().score(orig_bytes, image_bytes).to_dict()
            except Exception as e:
                _log.debug("Fidelity scoring error: %s", e)
                fidelity_result = {"error": str(e)}

        return {
            "success":  True,
            "outputs":  [],
            "errors":   [],
            "metadata": {
                "action":          "score",
                "output_id":       output_id,
                "job_id":          job_id,
                "quality":         quality_result,
                "fidelity":        fidelity_result,
                "scored_at":       time.time(),
            },
        }

    def _record_decision(self, decision: str, output_id: str, job_id: str,
                         reviewer: str, notes: str) -> dict:
        review_id = str(uuid.uuid4())
        try:
            from psydox.storage.database import get_db
            db = get_db()
            db.execute(
                """INSERT OR REPLACE INTO reviews
                   (id, output_id, job_id, decision, reviewer, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (review_id, output_id, job_id, decision, reviewer, notes, time.time())
            )
            db.commit()
        except Exception as e:
            _log.warning("ReviewFeature._record_decision DB error: %s", e)

        try:
            from psydox.security.audit import record_audit
            record_audit(reviewer, f"review_{decision}", output_id, f"job={job_id}")
        except Exception:
            pass

        return {
            "success":  True,
            "outputs":  [],
            "errors":   [],
            "metadata": {
                "action":     decision,
                "review_id":  review_id,
                "output_id":  output_id,
                "job_id":     job_id,
                "reviewer":   reviewer,
                "decided_at": time.time(),
            },
        }

    def _list_pending(self, reviewer: str) -> dict:
        """Return a list of outputs pending review (verdict == REVIEW)."""
        pending = []
        try:
            from psydox.storage.database import get_db
            db = get_db()
            rows = db.execute(
                """SELECT id, job_id, feature_id, label, quality_verdict, quality_score, fidelity_score, created_at
                   FROM outputs
                   WHERE status='pending_review'
                   ORDER BY created_at DESC LIMIT 100"""
            ).fetchall()
            for row in rows:
                pending.append({
                    "output_id":       row[0],
                    "job_id":          row[1],
                    "feature_id":      row[2],
                    "label":           row[3],
                    "quality_verdict": row[4],
                    "quality_score":   row[5],
                    "fidelity_score":  row[6],
                    "created_at":      row[7],
                })
        except Exception as e:
            _log.debug("ReviewFeature._list_pending error: %s", e)

        return {
            "success":  True,
            "outputs":  [],
            "errors":   [],
            "metadata": {"action": "pending", "pending": pending, "count": len(pending)},
        }


def _quality_to_dict(qs) -> dict:
    return {
        "score":           qs.score,
        "verdict":         qs.verdict.value if hasattr(qs.verdict, "value") else str(qs.verdict),
        "resolution_ok":   qs.resolution_ok,
        "sharpness_score": qs.sharpness_score,
        "color_match_score": qs.color_match_score,
        "brightness_ok":   qs.brightness_ok,
        "issues":          qs.issues,
    }
