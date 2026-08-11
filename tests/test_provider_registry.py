"""
Tests for the multi-provider registry.

These tests NEVER make real API calls.
They verify configuration detection, status reporting, and safety guarantees.
"""
import os
import pytest

from psydox.ai_core.provider_registry import (
    ProviderRegistry, ProviderStatus, get_provider_registry, reset_registry,
)


# ── Registry status detection ─────────────────────────────────────────────────

def test_registry_lists_all_providers():
    reg = ProviderRegistry()
    ids = {p.id for p in reg.list()}
    assert "gemini"     in ids
    assert "openai"     in ids
    assert "openrouter" in ids
    assert "replicate"  in ids
    assert "stability"  in ids


def test_unconfigured_provider_has_not_configured_status(monkeypatch):
    # Clear all API keys
    for var in ["GOOGLE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                "REPLICATE_API_TOKEN", "STABILITY_API_KEY"]:
        monkeypatch.delenv(var, raising=False)
    reg = ProviderRegistry()
    for info in reg.list():
        assert info.status == ProviderStatus.NOT_CONFIGURED, (
            f"{info.id} should be NOT_CONFIGURED when env var '{info.env_var}' is absent"
        )


def test_configured_provider_detected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    reg = ProviderRegistry()
    openai_info = reg.get_info("openai")
    assert openai_info is not None
    assert openai_info.status == ProviderStatus.CONFIGURED


def test_gemini_detected_when_key_present(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-gemini-key")
    reg = ProviderRegistry()
    info = reg.get_info("gemini")
    assert info.status == ProviderStatus.CONFIGURED


def test_replicate_detected(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_faketoken")
    reg = ProviderRegistry()
    assert reg.get_info("replicate").status == ProviderStatus.CONFIGURED


def test_stability_detected(monkeypatch):
    monkeypatch.setenv("STABILITY_API_KEY", "sk-fakekey")
    reg = ProviderRegistry()
    assert reg.get_info("stability").status == ProviderStatus.CONFIGURED


def test_openrouter_detected(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fakekey")
    reg = ProviderRegistry()
    assert reg.get_info("openrouter").status == ProviderStatus.CONFIGURED


# ── Safety: app starts with zero providers configured ─────────────────────────

def test_registry_initialises_with_no_providers(monkeypatch):
    for var in ["GOOGLE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                "REPLICATE_API_TOKEN", "STABILITY_API_KEY"]:
        monkeypatch.delenv(var, raising=False)
    reg = ProviderRegistry()
    assert reg.configured() == []
    assert reg.first_available() is None


def test_build_router_with_no_providers(monkeypatch):
    for var in ["GOOGLE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                "REPLICATE_API_TOKEN", "STABILITY_API_KEY", "DEBUG_MODE"]:
        monkeypatch.delenv(var, raising=False)
    reg = ProviderRegistry()
    # Must not raise
    router = reg.build_router()
    assert router is not None


def test_build_router_debug_uses_mock(monkeypatch):
    monkeypatch.setenv("DEBUG_MODE", "true")
    reg = ProviderRegistry()
    router = reg.build_router()
    assert router is not None
    # Mock provider always available in debug mode
    from psydox.ai_core.router import TaskType
    prov = router.get_image_provider(TaskType.LIFESTYLE)
    assert prov is not None


# ── provider_id selection ─────────────────────────────────────────────────────

def test_first_available_returns_configured_provider(monkeypatch):
    for var in ["GOOGLE_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fakekey")
    reg = ProviderRegistry()
    assert reg.first_available() == "openrouter"


def test_get_provider_returns_none_for_unconfigured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reg = ProviderRegistry()
    assert reg.get_provider("openai") is None


def test_get_provider_returns_instance_when_configured(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-test")
    reg = ProviderRegistry()
    prov = reg.get_provider("openai")
    assert prov is not None
    assert prov.name == "openai"
    assert prov.is_available()


# ── Status labels + colors are well-formed ────────────────────────────────────

def test_status_labels_all_defined():
    reg = ProviderRegistry()
    for info in reg.list():
        assert info.status_label  # not empty
        assert info.status_color.startswith("#")


# ── env_var_table ─────────────────────────────────────────────────────────────

def test_env_var_table_contains_all_providers():
    reg   = ProviderRegistry()
    table = reg.env_var_table()
    vars_ = {row["env_var"] for row in table}
    assert "GOOGLE_API_KEY"        in vars_
    assert "OPENAI_API_KEY"        in vars_
    assert "OPENROUTER_API_KEY"    in vars_
    assert "REPLICATE_API_TOKEN"   in vars_
    assert "STABILITY_API_KEY"     in vars_


# ── Singleton reset ───────────────────────────────────────────────────────────

def test_reset_registry_forces_refresh(monkeypatch):
    reset_registry()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reg1 = get_provider_registry()
    assert reg1.get_info("openai").status == ProviderStatus.NOT_CONFIGURED

    reset_registry()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-new-key")
    reg2 = get_provider_registry()
    assert reg2.get_info("openai").status == ProviderStatus.CONFIGURED


# ── API keys NEVER logged ─────────────────────────────────────────────────────

def test_provider_status_does_not_expose_key(monkeypatch, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-test-key")
    import logging
    with caplog.at_level(logging.DEBUG):
        reg = ProviderRegistry()
        _ = reg.list()
    for record in caplog.records:
        assert "sk-super-secret-test-key" not in record.message, (
            "API key was leaked into logs!"
        )
