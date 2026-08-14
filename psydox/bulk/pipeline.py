"""
Psydox Bulk AI Pipeline

Full AI processing pipeline for Excel catalog batches:
  Excel rows → download → category detect → mask → AI lifestyle →
  quality gate → marketplace validate → ZIP output + failed Excel

Extends the existing batch processor with AI-powered stages.
Each stage is individually toggleable via BulkAIConfig.

Usage::

    cfg = BulkAIConfig(
        scene_id="casual_street",
        category_id="footwear",       # "" = auto-detect per image
        marketplace_id="amazon_main",  # optional
        run_ai=True,
        run_mask=True,
        run_quality=True,
    )
    result = BulkAIPipeline().run(df, cfg, progress_cb=my_callback)
"""
from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Optional

_log = logging.getLogger("psydox.bulk.pipeline")


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class BulkAIConfig:
    # Canvas / output
    target_w:     int   = 1080
    target_h:     int   = 1350
    jpeg_quality: int   = 92
    max_retries:  int   = 2
    timeout:      int   = 30

    # AI pipeline controls
    scene_id:       str   = "casual_street"
    category_id:    str   = ""      # "" = auto-detect from image
    marketplace_id: Optional[str] = None

    # Stage toggles
    run_mask:        bool = True    # segment product (rembg / opencv)
    run_ai:          bool = True    # AI lifestyle generation
    run_quality:     bool = True    # UnifiedQualityGate check
    run_category_ai: bool = False   # detect category via AI vision (slow/costly)

    # Output options
    include_masked:   bool = False   # add masked PNG to ZIP
    min_quality_pass: int  = 50      # reject items below this overall score


# ── Result ─────────────────────────────────────────────────────────────────────

@dataclass
class BulkAIResult:
    total:   int = 0
    success: int = 0
    failed:  int = 0
    skipped: int = 0

    zip_bytes:          Optional[bytes] = None
    failed_excel_bytes: Optional[bytes] = None

    errors:  list[str] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)  # per-item summary


# ── Pipeline ───────────────────────────────────────────────────────────────────

class BulkAIPipeline:
    """
    AI-powered bulk processing pipeline.
    Builds on run_batch() infrastructure (same DataFrame contract),
    adds AI stages between download and ZIP packaging.
    """

    def run(
        self,
        df,                              # pandas DataFrame from Excel
        config: BulkAIConfig,
        progress_cb: Optional[Callable] = None,
        job_id: Optional[str] = None,
    ) -> BulkAIResult:
        """
        Process all rows in df through the AI pipeline.

        df must have columns "URL" and "Style Code" (or "StyleCode").
        progress_cb(current, total, label) is called per item if provided.
        job_id enables per-item job_items tracking.
        """
        from psydox.batch.item_tracker import get_tracker, make_item_id
        from psydox.batch.item_tracker import DOWNLOADING, PROCESSING, COMPLETED, FAILED

        tracker = get_tracker(job_id)
        result  = BulkAIResult()
        zip_buf = io.BytesIO()
        failed_rows: list[dict] = []

        df = _normalise_df(df)
        rows = list(df.iterrows())
        result.total = len(rows)

        with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for global_idx, (_, row) in enumerate(rows):
                style_code = str(row.get("style_code", row.get("Style Code", f"item_{global_idx:04d}")))
                url        = str(row.get("url", row.get("URL", "")))
                url_idx    = int(row.get("url_index", global_idx))
                item_id    = make_item_id(job_id or "", style_code, url_idx)

                tracker.create(
                    item_id=item_id,
                    source_url=url,
                    product_sku=style_code,
                    row_index=url_idx,
                )

                label = f"{style_code} [{global_idx+1}/{result.total}]"
                if progress_cb:
                    progress_cb(global_idx + 1, result.total, label)

                if not url or url.lower() in ("nan", "none", ""):
                    tracker.update(item_id, status=FAILED, error="No URL")
                    failed_rows.append({**row.to_dict(), "Error": "No URL"})
                    result.failed += 1
                    result.errors.append(f"{style_code}: No URL")
                    continue

                try:
                    tracker.update(item_id, status=DOWNLOADING)
                    image_bytes = _download(url, config.timeout, config.max_retries)

                    tracker.update(item_id, status=PROCESSING)
                    output_bytes, item_detail = self._process_item(
                        image_bytes, row, config, style_code
                    )

                    if output_bytes is None:
                        # Quality gate rejection
                        reason = item_detail.get("rejection_reason", "Quality gate reject")
                        tracker.update(item_id, status=FAILED, error=reason)
                        failed_rows.append({**row.to_dict(), "Error": reason})
                        result.failed += 1
                        result.errors.append(f"{style_code}: {reason}")
                    else:
                        zip_path = f"{style_code}/{style_code}_{url_idx + 1:02d}.jpg"
                        zf.writestr(zip_path, output_bytes)

                        # Optionally include masked PNG
                        if config.include_masked and item_detail.get("masked_bytes"):
                            mask_path = f"{style_code}/{style_code}_{url_idx + 1:02d}_mask.png"
                            zf.writestr(mask_path, item_detail["masked_bytes"])

                        tracker.update(item_id, status=COMPLETED)
                        result.success += 1

                    result.details.append(item_detail)

                except Exception as exc:
                    _log.warning("BulkAI item %s failed: %s", style_code, exc)
                    tracker.update(item_id, status=FAILED, error=str(exc))
                    failed_rows.append({**row.to_dict(), "Error": str(exc)})
                    result.failed += 1
                    result.errors.append(f"{style_code}: {exc}")

        result.zip_bytes = zip_buf.getvalue() if result.success > 0 else None

        if failed_rows:
            result.failed_excel_bytes = _make_failed_excel(failed_rows)

        return result

    # ── Per-item pipeline ──────────────────────────────────────────────────────

    def _process_item(
        self,
        image_bytes: bytes,
        row,
        config: BulkAIConfig,
        style_code: str,
    ) -> tuple:
        """
        Run the AI pipeline for one image.
        Returns (output_bytes | None, detail_dict).
        None output_bytes = quality rejected.
        """
        detail: dict = {"style_code": style_code, "stages": {}}

        # ── Stage 1: Category detection ────────────────────────────────────────
        category_id = config.category_id
        if not category_id:
            try:
                if config.run_category_ai:
                    from psydox.category.detector import CategoryDetector
                    cat, conf = CategoryDetector().detect_from_image(image_bytes)
                else:
                    # Fall back to text-based detection from row data
                    raw = str(row.get("category", row.get("Category", row.get("type", ""))))
                    from psydox.category.detector import CategoryDetector
                    cat, conf = CategoryDetector().detect_from_text(raw)
                category_id = cat.id
                detail["stages"]["category"] = {"id": category_id, "confidence": conf}
            except Exception as exc:
                _log.warning("Category detection failed for %s: %s", style_code, exc)
                category_id = "generic"
                detail["stages"]["category"] = {"id": "generic", "error": str(exc)}
        else:
            detail["stages"]["category"] = {"id": category_id, "source": "config"}

        # ── Stage 2: Masking ───────────────────────────────────────────────────
        masked_bytes: Optional[bytes] = None
        if config.run_mask:
            try:
                from psydox.masking.engine import MaskingEngine
                from PIL import Image

                engine = MaskingEngine()
                img    = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                seg    = engine.segment(img)
                masked_bytes = seg.image_rgba
                detail["stages"]["masking"] = {
                    "method": seg.method,
                    "bbox":   seg.bbox.as_tuple(),
                    "conf":   seg.bbox.confidence,
                }
            except Exception as exc:
                _log.warning("Masking failed for %s: %s", style_code, exc)
                detail["stages"]["masking"] = {"error": str(exc)}

        # ── Stage 3: AI lifestyle generation ──────────────────────────────────
        ai_output_bytes: Optional[bytes] = None
        if config.run_ai:
            try:
                from psydox.lifestyle.engine import LifestyleEngine, LifestyleRequest

                req = LifestyleRequest(
                    image_bytes=image_bytes,
                    scene_id=config.scene_id,
                    category_id=category_id,
                    product_desc=str(row.get("product_desc", row.get("Description", ""))),
                    marketplace_id=config.marketplace_id,
                )
                ai_result = LifestyleEngine().generate(req)
                if ai_result.success and ai_result.image_bytes:
                    ai_output_bytes = ai_result.image_bytes
                    detail["stages"]["ai_lifestyle"] = {
                        "success":  True,
                        "scene_id": config.scene_id,
                        "provider": ai_result.provider,
                        "model":    ai_result.model,
                        "cost":     ai_result.cost_estimate,
                    }
                else:
                    detail["stages"]["ai_lifestyle"] = {
                        "success": False,
                        "error":   ai_result.error,
                    }
            except Exception as exc:
                _log.warning("AI lifestyle failed for %s: %s", style_code, exc)
                detail["stages"]["ai_lifestyle"] = {"error": str(exc)}

        # Use AI output if available, otherwise fall back to original
        output_bytes = ai_output_bytes or image_bytes

        # ── Stage 4: Quality gate ──────────────────────────────────────────────
        if config.run_quality:
            try:
                from psydox.quality.gate import UnifiedQualityGate

                gate_result = UnifiedQualityGate().check(
                    result_bytes=output_bytes,
                    original_bytes=image_bytes,
                    marketplace_preset_id=config.marketplace_id,
                )
                detail["stages"]["quality"] = gate_result.to_dict()
                detail["quality_score"]     = gate_result.overall_score
                detail["quality_status"]    = gate_result.status.value

                if gate_result.overall_score < config.min_quality_pass:
                    detail["rejection_reason"] = (
                        f"Quality {gate_result.overall_score}/100 < "
                        f"threshold {config.min_quality_pass}"
                    )
                    return None, detail
            except Exception as exc:
                _log.warning("Quality gate failed for %s: %s", style_code, exc)
                detail["stages"]["quality"] = {"error": str(exc)}

        # ── Stage 5: Resize to target canvas ──────────────────────────────────
        try:
            from psydox.batch.processor import convert_image, BatchConfig
            from PIL import Image

            img    = Image.open(io.BytesIO(output_bytes)).convert("RGB")
            cfg    = BatchConfig(target_w=config.target_w, target_h=config.target_h,
                                 jpeg_quality=config.jpeg_quality)
            result = convert_image(img, cfg)
            buf    = io.BytesIO()
            result.save(buf, "JPEG", quality=config.jpeg_quality)
            output_bytes = buf.getvalue()
        except Exception as exc:
            _log.warning("Canvas resize failed for %s: %s", style_code, exc)

        detail["masked_bytes"] = masked_bytes
        return output_bytes, detail


# ── Utilities ──────────────────────────────────────────────────────────────────

def _normalise_df(df):
    """Lowercase column names for safe access."""
    df = df.copy()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    return df


def _download(url: str, timeout: int, max_retries: int) -> bytes:
    import urllib.request
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            if attempt == max_retries - 1:
                raise exc


def _make_failed_excel(failed_rows: list[dict]) -> bytes:
    try:
        import pandas as pd
        buf = io.BytesIO()
        pd.DataFrame(failed_rows).to_excel(buf, index=False, engine="openpyxl")
        return buf.getvalue()
    except Exception:
        return b""
