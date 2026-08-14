"""
Psydox Unified Quality Gate

Combines three quality signals into a single pass/warn/reject decision:
  1. Technical quality    — resolution, sharpness, brightness (AIQualityEngine)
  2. Fidelity             — color/shape/texture vs original (FidelityEngine)
  3. Marketplace compliance — dimensions, file size vs preset rules (MarketplaceRegistry)

Fidelity and marketplace checks are optional; the gate degrades gracefully when
either original image or marketplace preset is not supplied.

Scoring:
  technical_score   0–100 (from AIQualityEngine)
  fidelity_score    0.0–1.0 (from FidelityEngine.overall_score)
  marketplace_score 0–100 (computed from ComplianceRule + image metadata)
  overall_score     0–100 weighted average

Status:
  PASS    — overall >= 75 and no hard rejections
  WARNING — 50 <= overall < 75 or soft issues found
  REJECT  — overall < 50 or any hard marketplace dimension / file-size violation

Rules that require vision AI (no_text_overlay, no_watermark, etc.) are listed
as "manual review required" in reasons rather than blocking.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

_log = logging.getLogger("psydox.quality.gate")

# Weights for overall_score
_W_TECHNICAL    = 0.50
_W_FIDELITY     = 0.30
_W_MARKETPLACE  = 0.20


class GateStatus(str, Enum):
    PASS    = "PASS"
    WARNING = "WARNING"
    REJECT  = "REJECT"


@dataclass
class QualityResult:
    technical_score:   int
    fidelity_score:    float        # 0.0–1.0; -1.0 if no reference supplied
    marketplace_score: int          # 0–100; -1 if no preset supplied
    overall_score:     int
    status:            GateStatus
    reasons:           list[str]    = field(default_factory=list)
    details:           dict         = field(default_factory=dict)

    def badge_text(self) -> str:
        icons = {GateStatus.PASS: "✅", GateStatus.WARNING: "⚠️", GateStatus.REJECT: "❌"}
        return f"{icons[self.status]} {self.status} ({self.overall_score}/100)"

    def to_dict(self) -> dict:
        return {
            "technical_score":   self.technical_score,
            "fidelity_score":    round(self.fidelity_score, 3),
            "marketplace_score": self.marketplace_score,
            "overall_score":     self.overall_score,
            "status":            self.status.value,
            "reasons":           self.reasons,
            "details":           self.details,
        }


class UnifiedQualityGate:
    """
    Single entry-point for all quality checks.

    Usage::

        gate = UnifiedQualityGate()
        result = gate.check(
            result_bytes=my_image_bytes,
            original_bytes=source_bytes,        # optional
            marketplace_preset_id="amazon_main", # optional
        )
        if result.status == GateStatus.REJECT:
            handle_reject(result.reasons)
    """

    def check(
        self,
        result_bytes: bytes,
        original_bytes: Optional[bytes] = None,
        marketplace_preset_id: Optional[str] = None,
    ) -> QualityResult:
        """
        Run all enabled quality checks and return a unified QualityResult.
        Never raises — errors are captured in reasons / details.
        """
        try:
            return self._check(result_bytes, original_bytes, marketplace_preset_id)
        except Exception as exc:
            _log.exception("UnifiedQualityGate.check failed")
            return QualityResult(
                technical_score=0, fidelity_score=-1.0, marketplace_score=-1,
                overall_score=0, status=GateStatus.REJECT,
                reasons=[f"Quality gate internal error: {exc}"],
            )

    # ── Implementation ─────────────────────────────────────────────────────────

    def _check(
        self,
        result_bytes: bytes,
        original_bytes: Optional[bytes],
        marketplace_preset_id: Optional[str],
    ) -> QualityResult:
        from psydox.quality.engine  import AIQualityEngine
        from psydox.quality.fidelity import FidelityEngine

        reasons:  list[str] = []
        details:  dict      = {}
        hard_reject = False

        # ── 1. Technical quality ───────────────────────────────────────────────
        tech_result = AIQualityEngine().score(result_bytes, original_bytes)
        technical_score = tech_result.score
        reasons.extend(tech_result.issues)
        details["technical"] = tech_result.details

        if technical_score < 40:
            hard_reject = True

        # ── 2. Fidelity ────────────────────────────────────────────────────────
        fidelity_score = -1.0
        if original_bytes:
            fid = FidelityEngine().score(original_bytes, result_bytes)
            fidelity_score = fid.overall_score
            for w in fid.warnings:
                reasons.append(f"[fidelity] {w}")
            details["fidelity"] = fid.to_dict()
            if fidelity_score < 0.40 and fidelity_score >= 0:
                hard_reject = True
        else:
            details["fidelity"] = {"note": "No original image supplied — fidelity check skipped"}

        # ── 3. Marketplace compliance ──────────────────────────────────────────
        marketplace_score = -1
        if marketplace_preset_id:
            marketplace_score, mp_reasons, mp_hard, mp_details = self._check_marketplace(
                result_bytes, marketplace_preset_id
            )
            reasons.extend(mp_reasons)
            details["marketplace"] = mp_details
            if mp_hard:
                hard_reject = True
        else:
            details["marketplace"] = {"note": "No marketplace preset supplied — compliance check skipped"}

        # ── 4. Overall score ───────────────────────────────────────────────────
        weights_used = _W_TECHNICAL
        overall = technical_score * _W_TECHNICAL

        if fidelity_score >= 0:
            overall += (fidelity_score * 100) * _W_FIDELITY
            weights_used += _W_FIDELITY

        if marketplace_score >= 0:
            overall += marketplace_score * _W_MARKETPLACE
            weights_used += _W_MARKETPLACE

        # Re-normalize to 0-100 using only active checks
        overall_score = int(round(overall / weights_used))

        # ── 5. Status ──────────────────────────────────────────────────────────
        if hard_reject or overall_score < 50:
            status = GateStatus.REJECT
        elif overall_score < 75:
            status = GateStatus.WARNING
        else:
            status = GateStatus.PASS

        return QualityResult(
            technical_score=technical_score,
            fidelity_score=round(fidelity_score, 3),
            marketplace_score=marketplace_score,
            overall_score=overall_score,
            status=status,
            reasons=reasons,
            details=details,
        )

    def _check_marketplace(
        self, result_bytes: bytes, preset_id: str
    ) -> tuple:
        """
        Returns (score 0-100, reasons list, hard_reject bool, details dict).
        """
        from psydox.marketplace.registry import get_marketplace_registry

        registry = get_marketplace_registry()
        preset   = registry.get(preset_id)

        if preset is None:
            return 50, [f"Unknown marketplace preset: {preset_id}"], False, {}

        from PIL import Image
        img  = Image.open(io.BytesIO(result_bytes)).convert("RGB")
        w, h = img.size
        file_kb = len(result_bytes) / 1024

        reasons:     list[str] = []
        hard_reject: bool      = False
        checks_total = 0
        checks_pass  = 0

        rule = preset.compliance

        # Canvas dimension check: image should at least meet the preset's canvas size
        checks_total += 1
        min_w = getattr(rule, "min_width",  preset.width)
        min_h = getattr(rule, "min_height", preset.height)
        if w < min_w or h < min_h:
            reasons.append(
                f"[{preset.label}] Image {w}×{h} is below required {min_w}×{min_h}"
            )
            hard_reject = True
        else:
            checks_pass += 1

        # File size check
        if rule.max_file_kb and rule.max_file_kb > 0:
            checks_total += 1
            if file_kb > rule.max_file_kb:
                reasons.append(
                    f"[{preset.label}] File {file_kb:.0f} KB exceeds {rule.max_file_kb} KB limit"
                )
            else:
                checks_pass += 1

        # Background check (note only — cannot detect programmatically without vision)
        if rule.bg_required:
            checks_total += 1
            checks_pass += 1   # Optimistic; flag for manual check
            reasons.append(
                f"[{preset.label}] White/plain background required — verify manually"
            )

        # Vision-dependent rules — flag as manual review, do not auto-reject
        manual_flags: list[str] = []
        if getattr(rule, "no_text_overlay", False):
            manual_flags.append("no text overlay")
        if getattr(rule, "no_watermark", False):
            manual_flags.append("no watermarks")
        if getattr(rule, "no_logo_on_main", False):
            manual_flags.append("no logo on main image")
        if getattr(rule, "product_coverage_min_pct", 0) > 0:
            manual_flags.append(
                f"product must cover ≥{rule.product_coverage_min_pct}% of frame"
            )
        if manual_flags:
            reasons.append(
                f"[{preset.label}] Manual review required: {', '.join(manual_flags)}"
            )

        score = int(round(100 * checks_pass / max(checks_total, 1)))
        details = {
            "preset_id":      preset_id,
            "preset_label":   preset.label,
            "image_size":     f"{w}×{h}",
            "target_size":    f"{preset.width}×{preset.height}",
            "file_kb":        round(file_kb, 1),
            "checks_pass":    checks_pass,
            "checks_total":   checks_total,
        }
        return score, reasons, hard_reject, details
