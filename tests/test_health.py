"""Tests for health check system."""
import sys
import os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
os.environ["DEBUG_MODE"] = "true"


def test_health_report_has_components():
    from psydox.health import check_health
    report = check_health()
    assert report.components
    assert len(report.components) >= 4


def test_health_report_has_overall_status():
    from psydox.health import check_health, ComponentStatus
    report = check_health()
    assert report.overall in (ComponentStatus.HEALTHY, ComponentStatus.DEGRADED, ComponentStatus.UNAVAILABLE)


def test_health_to_dict():
    from psydox.health import check_health
    d = check_health().to_dict()
    assert "overall" in d
    assert "components" in d
    assert "checked_at" in d


def test_component_health_icons():
    from psydox.health import ComponentHealth, ComponentStatus
    assert ComponentHealth("x", ComponentStatus.HEALTHY).icon() == "✅"
    assert ComponentHealth("x", ComponentStatus.DEGRADED).icon() == "⚠️"
    assert ComponentHealth("x", ComponentStatus.UNAVAILABLE).icon() == "❌"


def test_feature_registry_component_present():
    from psydox.health import check_health
    from psydox.features.loader import bootstrap_features
    bootstrap_features()
    report = check_health()
    names = [c.name for c in report.components]
    assert "feature_registry" in names


def test_health_never_raises():
    from psydox.health import HealthChecker
    checker = HealthChecker()
    # Should never raise even if subsystems are misconfigured
    try:
        checker.check_all()
    except Exception as e:
        assert False, f"check_all() raised: {e}"
