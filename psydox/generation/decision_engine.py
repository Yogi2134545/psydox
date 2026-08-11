"""
Psydox Decision Engine

After generation + validation, decide the outcome:

    APPROVED   — all checks passed, image is ready
    RETRY      — fixable issue detected, retry with adjusted prompt
    REVIEW     — ambiguous / low-confidence, requires human review
    HARD_FAIL  — critical product property changed, do NOT retry

Decision hierarchy:
  1. Hard product failures → HARD_FAIL (no retry)
  2. Quality fail         → RETRY (quality/exposure issue)
  3. Fidelity fail        → RETRY with product-lock strengthened
  4. Angle fail           → RETRY with angle strengthened
  5. All PASS             → APPROVED
  6. APPROXIMATION angle  → REVIEW (cannot auto-approve)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

_log = logging.getLogger("psydox.generation.decision_engine")


class DecisionOutcome(str, Enum):
    APPROVED   = "APPROVED"
    RETRY      = "RETRY"
    REVIEW     = "REVIEW"
    HARD_FAIL  = "HARD_FAIL"


_HARD_FAIL_FIDELITY_THRESHOLD = 0.35  # below this → product identity is lost


@dataclass
class GenerationDecision:
    outcome:       DecisionOutcome
    reason:        str
    retry_hint:    str = ""  # what the SmartRetry engine should strengthen
    can_retry:     bool = True

    def is_approved(self) -> bool:
        return self.outcome == DecisionOutcome.APPROVED

    def to_dict(self) -> dict:
        return {
            "outcome":    self.outcome.value,
            "reason":     self.reason,
            "retry_hint": self.retry_hint,
            "can_retry":  self.can_retry,
        }


class DecisionEngine:
    """
    Makes the final APPROVED / RETRY / REVIEW / HARD_FAIL decision.
    Takes quality, fidelity, and angle validation results.
    """

    def decide(
        self,
        quality_score,       # QualityScore from AIQualityEngine
        fidelity_score,      # FidelityScore from FidelityEngine
        angle_result,        # AngleValidationResult from AngleValidator
        cost_inr: float,
        quality_threshold: int   = 85,
        fidelity_threshold: float = 0.65,
        angle_threshold: float   = 0.70,
    ) -> GenerationDecision:
        """
        Determine outcome from validation results.
        Checks in order: hard fail → quality → fidelity → angle → approve.
        """
        q_score   = quality_score.score       if quality_score   else 0
        q_verdict = quality_score.verdict      if quality_score   else None
        f_overall = fidelity_score.overall_score if fidelity_score else 0.0
        f_conf    = getattr(fidelity_score, "confidence", "unavailable")

        # ── HARD FAIL: critical product identity changed ────────────────────
        if (fidelity_score and
                f_conf != "unavailable" and
                f_overall < _HARD_FAIL_FIDELITY_THRESHOLD):
            _log.warning(
                "DecisionEngine: HARD_FAIL — fidelity %.2f < %.2f (critical identity change)",
                f_overall, _HARD_FAIL_FIDELITY_THRESHOLD,
            )
            return GenerationDecision(
                outcome=DecisionOutcome.HARD_FAIL,
                reason=(
                    f"Critical product identity failure: fidelity {f_overall:.0%} — "
                    f"product shape, color, or major features appear to have changed."
                ),
                can_retry=False,
            )

        # ── QUALITY FAIL ───────────────────────────────────────────────────
        from psydox.quality.engine import QualityVerdict
        if quality_score and q_score < quality_threshold:
            issues_str = "; ".join(quality_score.issues[:3]) if quality_score.issues else "unspecified"
            _log.info("DecisionEngine: RETRY — quality %d < %d  issues=%s", q_score, quality_threshold, issues_str)
            return GenerationDecision(
                outcome=DecisionOutcome.RETRY,
                reason=f"Quality score {q_score}/100 below threshold {quality_threshold}. Issues: {issues_str}.",
                retry_hint="quality",
                can_retry=True,
            )

        # ── FIDELITY FAIL (soft) ───────────────────────────────────────────
        if (fidelity_score and
                f_conf != "unavailable" and
                f_overall < fidelity_threshold):
            warnings_str = "; ".join(fidelity_score.warnings[:2]) if fidelity_score.warnings else ""
            _log.info(
                "DecisionEngine: RETRY — fidelity %.2f < %.2f  warnings=%s",
                f_overall, fidelity_threshold, warnings_str,
            )
            return GenerationDecision(
                outcome=DecisionOutcome.RETRY,
                reason=f"Fidelity {f_overall:.0%} below threshold {fidelity_threshold:.0%}. {warnings_str}",
                retry_hint="fidelity",
                can_retry=True,
            )

        # ── ANGLE FAIL ─────────────────────────────────────────────────────
        if angle_result:
            if angle_result.verdict == "FAIL":
                _log.info(
                    "DecisionEngine: RETRY — angle FAIL, detected=%s requested=%s",
                    angle_result.detected_angle, angle_result.requested_angle,
                )
                return GenerationDecision(
                    outcome=DecisionOutcome.RETRY,
                    reason=angle_result.reason,
                    retry_hint="angle",
                    can_retry=True,
                )

            if angle_result.verdict in ("REVIEW", "APPROXIMATION"):
                _log.info("DecisionEngine: REVIEW — angle verdict=%s", angle_result.verdict)
                return GenerationDecision(
                    outcome=DecisionOutcome.REVIEW,
                    reason=f"Angle could not be auto-verified: {angle_result.reason}",
                    can_retry=False,
                )

        # ── ALL CHECKS PASS ────────────────────────────────────────────────
        _log.info(
            "DecisionEngine: APPROVED — quality=%d fidelity=%.2f cost=₹%.2f",
            q_score, f_overall, cost_inr,
        )
        return GenerationDecision(
            outcome=DecisionOutcome.APPROVED,
            reason=f"All checks passed: quality {q_score}/100, fidelity {f_overall:.0%}.",
            can_retry=False,
        )
