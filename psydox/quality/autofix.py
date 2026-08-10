"""
Psydox Auto-Fix Engine

Implements the Generate → QA → Diagnose → Fix → QA → Accept/Reject loop.

Flow:
  1. Generate initial result
  2. Score (quality + fidelity)
  3. If verdict == APPROVED → done
  4. If verdict == NEEDS_FIX and retries remaining:
     a. Diagnose: identify the issue category
     b. Augment prompt with targeted fix instruction
     c. Re-generate
     d. Re-score
     e. Repeat up to max_retries
  5. If still not APPROVED after retries → return best result seen

Max retries: configurable, default 3.  Never infinite loops.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from psydox.quality.engine import AIQualityEngine, QualityScore, QualityVerdict

_log = logging.getLogger("psydox.quality.autofix")

# Map of quality issues → prompt fix instructions
_FIX_HINTS: dict[str, str] = {
    "low resolution":      "Generate at highest possible resolution. Use full detail.",
    "blurry":              "The image must be sharp and in focus. No motion blur. Crisp details.",
    "too dark":            "Increase brightness. Well-lit scene. No underexposure.",
    "too bright":          "Reduce brightness. Natural exposure. No overexposed highlights.",
    "color shift":         "CRITICAL: preserve the EXACT original product colors. Do not change any colors.",
    "color deviation":     "CRITICAL: the product colors must match the original exactly. No color changes.",
    "shape":               "CRITICAL: preserve the exact product shape, silhouette, and proportions.",
    "pattern":             "CRITICAL: preserve the exact product pattern and texture.",
}


@dataclass
class AttemptRecord:
    attempt:       int
    quality_score: QualityScore
    fidelity_score: Optional[object]   # FidelityScore | None
    prompt_used:   str
    duration_s:    float
    result_bytes:  Optional[bytes]     # None if generation failed


@dataclass
class AutoFixResult:
    success:          bool
    best_result:      Optional[bytes]
    best_score:       Optional[QualityScore]
    attempts:         list[AttemptRecord]   = field(default_factory=list)
    final_verdict:    QualityVerdict         = QualityVerdict.NEEDS_FIX
    total_duration_s: float                  = 0.0
    reason:           str                    = ""

    def summary(self) -> str:
        n = len(self.attempts)
        if self.success:
            return f"✅ Approved after {n} attempt(s) ({self.total_duration_s:.1f}s)"
        return f"⚠️ Best result after {n} attempt(s) — {self.final_verdict.value} ({self.total_duration_s:.1f}s)"


GenerateFn = Callable[[str], Optional[bytes]]  # prompt → image bytes | None


class AutoFixEngine:
    """
    Orchestrates the generate → QA → fix loop.
    Caller provides a generate_fn that accepts a prompt string and returns bytes.
    """

    def __init__(self, max_retries: int = 3, quality_config=None):
        self._max_retries = max(1, min(max_retries, 10))
        self._qa = AIQualityEngine(quality_config)

    def run(
        self,
        base_prompt: str,
        generate_fn: GenerateFn,
        original_bytes: Optional[bytes] = None,
        run_fidelity: bool = True,
    ) -> AutoFixResult:
        """
        Run the generate → QA → fix loop.

        Args:
            base_prompt:    The starting prompt.
            generate_fn:    Callable(prompt) → bytes | None.  Never raises.
            original_bytes: The source product image for fidelity comparison.
            run_fidelity:   Whether to run fidelity scoring (requires original_bytes).

        Returns:
            AutoFixResult with the best result found.
        """
        t_start   = time.time()
        attempts  = []
        best      = None
        best_score: Optional[QualityScore] = None
        current_prompt = base_prompt

        for attempt in range(1, self._max_retries + 1):
            _log.info("AutoFix attempt %d/%d", attempt, self._max_retries)
            t0 = time.time()

            result_bytes = None
            try:
                result_bytes = generate_fn(current_prompt)
            except Exception as exc:
                _log.warning("AutoFix generate_fn raised on attempt %d: %s", attempt, exc)

            if not result_bytes:
                attempts.append(AttemptRecord(
                    attempt=attempt,
                    quality_score=QualityScore(
                        score=0, verdict=QualityVerdict.NEEDS_FIX,
                        resolution_ok=False, sharpness_score=0.0,
                        color_match_score=0.0, brightness_ok=False,
                        issues=["Generation returned no image"],
                    ),
                    fidelity_score=None,
                    prompt_used=current_prompt,
                    duration_s=time.time() - t0,
                    result_bytes=None,
                ))
                continue

            # Score quality
            qs = self._qa.score(result_bytes, original_bytes)

            # Score fidelity
            fs = None
            if run_fidelity and original_bytes:
                try:
                    from psydox.quality.fidelity import FidelityEngine
                    fs = FidelityEngine().score(original_bytes, result_bytes)
                except Exception as exc:
                    _log.debug("Fidelity scoring failed on attempt %d: %s", attempt, exc)

            attempts.append(AttemptRecord(
                attempt=attempt,
                quality_score=qs,
                fidelity_score=fs,
                prompt_used=current_prompt,
                duration_s=time.time() - t0,
                result_bytes=result_bytes,
            ))

            # Track best
            if best_score is None or qs.score > best_score.score:
                best       = result_bytes
                best_score = qs

            if qs.verdict == QualityVerdict.APPROVED:
                return AutoFixResult(
                    success=True, best_result=best, best_score=best_score,
                    attempts=attempts, final_verdict=QualityVerdict.APPROVED,
                    total_duration_s=time.time() - t_start,
                    reason="Quality check passed",
                )

            # Diagnose and augment prompt for next attempt
            if attempt < self._max_retries:
                fix_instructions = self._diagnose(qs)
                if fix_instructions:
                    current_prompt = base_prompt + "\n\nFIX INSTRUCTIONS: " + fix_instructions
                    _log.info("AutoFix: augmented prompt with %d fix instruction(s)", len(fix_instructions.split(".")))

        # Exhausted retries
        final_verdict = best_score.verdict if best_score else QualityVerdict.NEEDS_FIX
        return AutoFixResult(
            success=False, best_result=best, best_score=best_score,
            attempts=attempts, final_verdict=final_verdict,
            total_duration_s=time.time() - t_start,
            reason=f"Max retries ({self._max_retries}) reached",
        )

    def _diagnose(self, qs: QualityScore) -> str:
        """Map quality issues to fix instruction text."""
        hints = []
        for issue in qs.issues:
            issue_lower = issue.lower()
            for key, hint in _FIX_HINTS.items():
                if key in issue_lower:
                    hints.append(hint)
                    break
        return " ".join(hints) if hints else ""
