"""Tests for ExportService."""
import io
import sys
import zipfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from PIL import Image


def _jpeg(color=(100, 150, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), color).save(buf, "JPEG")
    return buf.getvalue()


def _outputs(n=3):
    return [{"bytes": _jpeg((i*80, i*40, 200)), "label": f"output_{i}", "mime": "image/jpeg"}
            for i in range(1, n + 1)]


def test_export_produces_zip():
    from psydox.export.service import ExportService, ExportFormat
    result = ExportService().export_outputs(_outputs(2))
    assert result.zip_bytes
    assert zipfile.is_zipfile(io.BytesIO(result.zip_bytes))


def test_export_file_count():
    from psydox.export.service import ExportService
    result = ExportService().export_outputs(_outputs(3))
    assert result.file_count == 3


def test_export_includes_manifest():
    from psydox.export.service import ExportService
    result = ExportService().export_outputs(_outputs(2), include_manifest=True)
    with zipfile.ZipFile(io.BytesIO(result.zip_bytes)) as zf:
        names = zf.namelist()
    assert "manifest.json" in names


def test_export_convert_to_png():
    from psydox.export.service import ExportService, ExportFormat
    result = ExportService().export_outputs(_outputs(1), fmt=ExportFormat.PNG)
    with zipfile.ZipFile(io.BytesIO(result.zip_bytes)) as zf:
        names = zf.namelist()
    assert any(n.endswith(".png") for n in names)


def test_export_convert_to_webp():
    from psydox.export.service import ExportService, ExportFormat
    result = ExportService().export_outputs(_outputs(1), fmt=ExportFormat.WEBP)
    with zipfile.ZipFile(io.BytesIO(result.zip_bytes)) as zf:
        names = zf.namelist()
    assert any(n.endswith(".webp") for n in names)


def test_export_empty_outputs_no_crash():
    from psydox.export.service import ExportService
    result = ExportService().export_outputs([])
    assert result.file_count == 0
    assert zipfile.is_zipfile(io.BytesIO(result.zip_bytes))


def test_export_skips_missing_bytes():
    from psydox.export.service import ExportService
    outputs = [{"bytes": None, "label": "bad"}, {"bytes": _jpeg(), "label": "good", "mime": "image/jpeg"}]
    result = ExportService().export_outputs(outputs)
    assert result.file_count == 1
    assert result.errors


def test_export_convenience_fn():
    from psydox.export.service import export_job_outputs
    result = export_job_outputs(_outputs(2), job_label="test_job")
    assert result.file_count == 2
