"""Tests for Psydox AI Model Router."""
import sys
import os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def test_router_solid_bg_is_deterministic():
    from psydox.ai_core.router import AIModelRouter, TaskType
    router = AIModelRouter()
    assert router.is_deterministic(TaskType.SOLID_BACKGROUND)


def test_router_build_debug_uses_mock(monkeypatch):
    monkeypatch.setenv("DEBUG_MODE", "true")
    from psydox.ai_core.router import build_router
    from psydox.ai_core.providers.mock import MockImageProvider
    router = build_router()
    assert isinstance(router._image, MockImageProvider)


def test_router_all_task_types_have_tier():
    from psydox.ai_core.router import TaskType, _ROUTING
    for task in TaskType:
        assert task in _ROUTING, f"TaskType.{task.name} missing from _ROUTING"


def test_router_lifestyle_maps_to_premium_ai():
    from psydox.ai_core.router import AIModelRouter, TaskType, TaskRequirement, _ROUTING
    assert _ROUTING[TaskType.LIFESTYLE] == TaskRequirement.PREMIUM_AI


def test_router_model_generation_maps_to_premium_ai():
    from psydox.ai_core.router import TaskType, TaskRequirement, _ROUTING
    assert _ROUTING[TaskType.MODEL_GENERATION] == TaskRequirement.PREMIUM_AI
