"""
Tests for owner access control (Phase A of the studio rebuild).

Verifies:
  - Only yogeshwar@popclub.co can access AI Studio
  - Non-owner accounts are blocked at both UI and backend level
  - Case insensitivity and whitespace trimming
  - require_owner() raises PermissionError for non-owners
"""
import pytest
from psydox.access import is_owner, can_access_ai_studio, require_owner, OWNER_EMAIL


# ── is_owner ──────────────────────────────────────────────────────────────────

def test_owner_email_is_owner():
    assert is_owner(OWNER_EMAIL)


def test_owner_email_case_insensitive():
    assert is_owner(OWNER_EMAIL.upper())
    assert is_owner(OWNER_EMAIL.title())


def test_owner_email_strips_whitespace():
    assert is_owner(f"  {OWNER_EMAIL}  ")


def test_non_owner_not_owner():
    assert not is_owner("ankit@popclub.co")
    assert not is_owner("bhargavi.kt@popclub.co")
    assert not is_owner("devesh@popclub.co")
    assert not is_owner("random@example.com")


def test_empty_email_not_owner():
    assert not is_owner("")
    assert not is_owner("   ")


# ── can_access_ai_studio ──────────────────────────────────────────────────────

def test_owner_can_access_ai_studio():
    assert can_access_ai_studio(OWNER_EMAIL)


def test_non_owner_cannot_access_ai_studio():
    for email in ["ankit@popclub.co", "bhargavi.kt@popclub.co", "devesh@popclub.co"]:
        assert not can_access_ai_studio(email), f"{email} should not have AI Studio access"


def test_empty_email_cannot_access_ai_studio():
    assert not can_access_ai_studio("")


# ── require_owner ─────────────────────────────────────────────────────────────

def test_require_owner_passes_for_owner():
    # Should not raise
    require_owner(OWNER_EMAIL)


def test_require_owner_raises_for_non_owner():
    with pytest.raises(PermissionError):
        require_owner("ankit@popclub.co")


def test_require_owner_raises_for_empty():
    with pytest.raises(PermissionError):
        require_owner("")


def test_require_owner_error_message_contains_email():
    with pytest.raises(PermissionError, match="ankit@popclub.co"):
        require_owner("ankit@popclub.co")


# ── Backend enforcement: AI tool execution blocked for non-owner ──────────────

def test_ai_lifestyle_blocked_for_non_owner():
    """Studio execute_tool must block AI features regardless of UI state."""
    from psydox.studio.executor import execute_tool as _execute_tool
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (200, 150, 100)).save(buf, "JPEG")
    img_bytes = buf.getvalue()

    result = _execute_tool(
        "ai_lifestyle",
        {"image_bytes": img_bytes, "style": "Casual", "product_desc": "test"},
        user_email="ankit@popclub.co",
    )
    assert result is not None
    assert not result["success"]
    assert any("owner" in e.lower() or "permission" in e.lower() or "restricted" in e.lower()
               for e in result.get("errors", []))


def test_ai_background_blocked_for_non_owner():
    """Studio execute_tool must block AI background for non-owner."""
    from psydox.studio.executor import execute_tool as _execute_tool
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (200, 150, 100)).save(buf, "JPEG")
    img_bytes = buf.getvalue()

    result = _execute_tool(
        "ai_background",
        {"image_bytes": img_bytes, "bg_type": "studio"},
        user_email="devesh@popclub.co",
    )
    assert result is not None
    assert not result["success"]


def test_ai_model_blocked_for_non_owner():
    from psydox.studio.executor import execute_tool as _execute_tool
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, "JPEG")

    result = _execute_tool(
        "ai_model",
        {"image_bytes": buf.getvalue(), "gender": "Female"},
        user_email="bhargavi.kt@popclub.co",
    )
    assert result is not None
    assert not result["success"]


# ── Classic tools remain accessible to all users ──────────────────────────────

def test_classic_background_accessible_to_non_owner():
    from psydox.studio.executor import execute_tool as _execute_tool
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (100, 150, 200)).save(buf, "JPEG")

    result = _execute_tool(
        "background",
        {"image_bytes": buf.getvalue(), "bg_type": "solid", "color_name": "White"},
        user_email="ankit@popclub.co",
    )
    assert result is not None
    assert result["success"], f"Classic background failed: {result.get('errors')}"


def test_resize_accessible_to_non_owner():
    from psydox.studio.executor import execute_tool as _execute_tool
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (500, 500), (200, 200, 200)).save(buf, "JPEG")

    result = _execute_tool(
        "resize",
        {"image_bytes": buf.getvalue(), "target_w": 200, "target_h": 200},
        user_email="ankit@popclub.co",
    )
    assert result is not None
    assert result["success"], f"Resize failed: {result.get('errors')}"
