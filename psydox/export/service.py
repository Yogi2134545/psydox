"""
Psydox Export Service

Packages job outputs into downloadable archives (ZIP) with optional manifest.
Supports per-output format conversion at export time.
"""
from __future__ import annotations

import io
import json
import logging
import time
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

_log = logging.getLogger("psydox.export")


class ExportFormat(str, Enum):
    ORIGINAL = "original"
    JPEG     = "jpeg"
    PNG      = "png"
    WEBP     = "webp"


@dataclass
class ExportResult:
    zip_bytes:    bytes
    file_count:   int
    total_bytes:  int
    manifest:     dict = field(default_factory=dict)
    errors:       list = field(default_factory=list)


class ExportService:
    """
    Packages outputs into a ZIP archive.

    If `format` != ORIGINAL, images are converted at export time.
    A JSON manifest is always included in the ZIP.
    """

    def export_outputs(
        self,
        outputs: list[dict],
        fmt: ExportFormat = ExportFormat.ORIGINAL,
        job_label: str = "export",
        include_manifest: bool = True,
    ) -> ExportResult:
        buf  = io.BytesIO()
        manifest_entries = []
        errors: list[str] = []
        count = 0

        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, output in enumerate(outputs):
                raw = output.get("bytes")
                if not raw:
                    errors.append(f"Output {i}: no bytes")
                    continue

                label = output.get("label", f"output_{i}").replace(" ", "_")
                mime  = output.get("mime", "image/jpeg")

                try:
                    final_bytes, ext = self._convert(raw, fmt, mime)
                    filename = f"{label}.{ext}"
                    zf.writestr(filename, final_bytes)
                    manifest_entries.append({
                        "file":    filename,
                        "label":   output.get("label", ""),
                        "size":    len(final_bytes),
                        "format":  ext.upper(),
                    })
                    count += 1
                except Exception as e:
                    errors.append(f"Output {i} ({label}): {e}")

            if include_manifest:
                manifest = {
                    "job_label":   job_label,
                    "exported_at": time.time(),
                    "format":      fmt.value,
                    "files":       manifest_entries,
                    "errors":      errors,
                }
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        zip_bytes = buf.getvalue()
        return ExportResult(
            zip_bytes=zip_bytes,
            file_count=count,
            total_bytes=len(zip_bytes),
            manifest={"files": manifest_entries},
            errors=errors,
        )

    def _convert(self, raw: bytes, fmt: ExportFormat, original_mime: str) -> tuple[bytes, str]:
        if fmt == ExportFormat.ORIGINAL:
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(original_mime, "jpg")
            return raw, ext

        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        out = io.BytesIO()

        if fmt == ExportFormat.JPEG:
            img.save(out, format="JPEG", quality=92, optimize=True)
            return out.getvalue(), "jpg"
        elif fmt == ExportFormat.PNG:
            img.save(out, format="PNG", optimize=True)
            return out.getvalue(), "png"
        elif fmt == ExportFormat.WEBP:
            img.save(out, format="WEBP", quality=90)
            return out.getvalue(), "webp"
        else:
            img.save(out, format="JPEG", quality=92)
            return out.getvalue(), "jpg"


_SERVICE: Optional[ExportService] = None


def export_job_outputs(
    outputs: list[dict],
    fmt: ExportFormat = ExportFormat.ORIGINAL,
    job_label: str = "export",
) -> ExportResult:
    """Convenience function."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ExportService()
    return _SERVICE.export_outputs(outputs, fmt, job_label)
