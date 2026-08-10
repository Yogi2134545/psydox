"""Tests for nano_banana.auth — RBAC role and feature gates."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nano_banana.auth import Role, get_role, can


class TestGetRole:
    def test_admin_role(self):
        assert get_role({"role": "admin"}) == Role.ADMIN

    def test_manager_role(self):
        assert get_role({"role": "manager"}) == Role.MANAGER

    def test_operator_role(self):
        assert get_role({"role": "operator"}) == Role.OPERATOR

    def test_viewer_role(self):
        assert get_role({"role": "viewer"}) == Role.VIEWER

    def test_missing_role_defaults_to_viewer(self):
        assert get_role({}) == Role.VIEWER

    def test_unknown_role_defaults_to_viewer(self):
        assert get_role({"role": "superuser"}) == Role.VIEWER

    def test_case_insensitive(self):
        assert get_role({"role": "ADMIN"}) == Role.ADMIN
        assert get_role({"role": "Manager"}) == Role.MANAGER

    def test_strips_whitespace(self):
        assert get_role({"role": "  admin  "}) == Role.ADMIN


class TestCan:
    def test_admin_can_all(self):
        for feature in [
            "ai_studio", "batch_ai", "diagnostics",
            "production_validation", "cost_tracking",
            "classic_processing", "export",
        ]:
            assert can(Role.ADMIN, feature), f"admin should be able to: {feature}"

    def test_viewer_only_classic(self):
        assert can(Role.VIEWER, "classic_processing")
        assert not can(Role.VIEWER, "ai_studio")
        assert not can(Role.VIEWER, "batch_ai")
        assert not can(Role.VIEWER, "diagnostics")
        assert not can(Role.VIEWER, "export")

    def test_operator_ai_studio_no_batch(self):
        assert can(Role.OPERATOR, "ai_studio")
        assert not can(Role.OPERATOR, "batch_ai")
        assert not can(Role.OPERATOR, "diagnostics")

    def test_manager_ai_studio_and_batch(self):
        assert can(Role.MANAGER, "ai_studio")
        assert can(Role.MANAGER, "batch_ai")
        assert not can(Role.MANAGER, "diagnostics")
        assert not can(Role.MANAGER, "production_validation")

    def test_unknown_feature_returns_false(self):
        assert not can(Role.ADMIN, "nonexistent_feature")
