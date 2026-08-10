"""Tests for RBAC."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def test_owner_has_all_permissions():
    from psydox.security.rbac import RBACService, Role, Permission
    svc = RBACService()
    for perm in Permission:
        assert svc.can(Role.OWNER, perm), f"Owner should have {perm}"


def test_viewer_only_download():
    from psydox.security.rbac import RBACService, Role, Permission
    svc = RBACService()
    assert svc.can(Role.VIEWER, Permission.DOWNLOAD)
    assert not svc.can(Role.VIEWER, Permission.AI)
    assert not svc.can(Role.VIEWER, Permission.UPLOAD)
    assert not svc.can(Role.VIEWER, Permission.ADMIN)


def test_editor_has_ai():
    from psydox.security.rbac import RBACService, Role, Permission
    svc = RBACService()
    assert svc.can(Role.EDITOR, Permission.AI)
    assert not svc.can(Role.EDITOR, Permission.ADMIN)


def test_manager_has_analytics():
    from psydox.security.rbac import RBACService, Role, Permission
    svc = RBACService()
    assert svc.can(Role.MANAGER, Permission.ANALYTICS)
    assert not svc.can(Role.MANAGER, Permission.ADMIN)


def test_get_role_defaults_to_viewer():
    from psydox.security.rbac import RBACService, Role
    svc = RBACService()
    role = svc.get_role({}, "unknown@example.com")
    assert role == Role.VIEWER


def test_get_role_reads_yaml_field():
    from psydox.security.rbac import RBACService, Role
    svc = RBACService()
    users = {"admin@test.com": {"role": "admin"}}
    role = svc.get_role(users, "admin@test.com")
    assert role == Role.ADMIN


def test_can_use_feature_background_classic():
    from psydox.security.rbac import RBACService, Role
    svc = RBACService()
    assert svc.can_use_feature(Role.EDITOR, "background")


def test_can_use_feature_lifestyle_requires_ai():
    from psydox.security.rbac import RBACService, Role
    svc = RBACService()
    assert svc.can_use_feature(Role.EDITOR, "lifestyle")
    assert not svc.can_use_feature(Role.VIEWER, "lifestyle")


def test_require_raises_on_insufficient_role():
    import pytest
    from psydox.security.rbac import RBACService, Role, Permission
    from psydox.core.errors import AuthorizationError
    svc = RBACService()
    with pytest.raises(AuthorizationError):
        svc.require(Role.VIEWER, Permission.AI)


def test_require_passes_for_sufficient_role():
    from psydox.security.rbac import RBACService, Role, Permission
    svc = RBACService()
    svc.require(Role.ADMIN, Permission.AI)   # should not raise


def test_invalid_role_string_defaults_to_viewer():
    from psydox.security.rbac import RBACService, Role
    svc = RBACService()
    users = {"x@x.com": {"role": "superuser_invalid"}}
    role = svc.get_role(users, "x@x.com")
    assert role == Role.VIEWER
