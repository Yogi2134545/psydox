"""
Psydox AI Core — Provider Registry

Single source of truth for all configured AI providers.

Usage:
    registry = get_provider_registry()
    for info in registry.list():
        print(info.display_name, info.status_label)

    provider = registry.get_provider("gemini")
    router   = registry.build_router(preferred_id="gemini")

The application starts cleanly even if zero providers are configured.
NEVER logs or exposes API key values.
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .providers.base import ImageGenerationProvider

_log = logging.getLogger("psydox.ai_core.provider_registry")


class ProviderStatus(str, Enum):
    CONFIGURED     = "configured"
    NOT_CONFIGURED = "not_configured"
    DEGRADED       = "degraded"


@dataclass
class ProviderInfo:
    id:              str
    display_name:    str
    env_var:         str
    default_model:   str
    status:          ProviderStatus
    description:     str = ""
    icon:            str = "🤖"

    @property
    def status_label(self) -> str:
        labels = {
            ProviderStatus.CONFIGURED:     "● Connected",
            ProviderStatus.NOT_CONFIGURED: "○ Not configured",
            ProviderStatus.DEGRADED:       "⚠ Degraded",
        }
        return labels.get(self.status, self.status.value)

    @property
    def status_color(self) -> str:
        colors = {
            ProviderStatus.CONFIGURED:     "#22c55e",
            ProviderStatus.NOT_CONFIGURED: "#6b7280",
            ProviderStatus.DEGRADED:       "#f59e0b",
        }
        return colors.get(self.status, "#888")


# ── Provider catalogue ────────────────────────────────────────────────────────

_CATALOGUE: list[dict] = [
    {
        "id": "gemini", "display_name": "Google Gemini",
        "env_var": "GOOGLE_API_KEY",
        "default_model": "gemini-2.0-flash-preview-image-generation",
        "description": "Google's multimodal AI — excellent image editing and understanding",
        "icon": "🔵",
    },
    {
        "id": "openai", "display_name": "OpenAI DALL-E",
        "env_var": "OPENAI_API_KEY",
        "default_model": "dall-e-3",
        "description": "DALL-E 3 — high-quality photorealistic images",
        "icon": "⚫",
    },
    {
        "id": "openrouter", "display_name": "OpenRouter",
        "env_var": "OPENROUTER_API_KEY",
        "default_model": "google/gemini-2.0-flash-exp:free",
        "description": "Aggregator — access 200+ models through one API",
        "icon": "🌐",
    },
    {
        "id": "replicate", "display_name": "Replicate",
        "env_var": "REPLICATE_API_TOKEN",
        "default_model": "black-forest-labs/flux-schnell",
        "description": "Open-source models — Flux, SDXL, and more",
        "icon": "🔁",
    },
    {
        "id": "stability", "display_name": "Stability AI",
        "env_var": "STABILITY_API_KEY",
        "default_model": "stable-image-core",
        "description": "Stable Diffusion — fine-tuned for product photography",
        "icon": "🟣",
    },
]


class ProviderRegistry:
    """Manages all known AI providers and their configuration status."""

    def __init__(self) -> None:
        self._infos: list[ProviderInfo] = []
        self._providers: dict[str, ImageGenerationProvider] = {}
        self._refresh()

    def _refresh(self) -> None:
        """Check env vars and build provider instances. Safe to call at startup."""
        self._infos.clear()
        self._providers.clear()

        for entry in _CATALOGUE:
            pid      = entry["id"]
            env_var  = entry["env_var"]
            key_set  = bool(os.environ.get(env_var, "").strip())
            status   = ProviderStatus.CONFIGURED if key_set else ProviderStatus.NOT_CONFIGURED

            self._infos.append(ProviderInfo(
                id=pid,
                display_name=entry["display_name"],
                env_var=env_var,
                default_model=entry["default_model"],
                status=status,
                description=entry.get("description", ""),
                icon=entry.get("icon", "🤖"),
            ))

            if key_set:
                try:
                    self._providers[pid] = self._instantiate(pid)
                    _log.info("Provider '%s' configured (%s is set)", pid, env_var)
                except Exception as e:
                    _log.warning("Provider '%s' failed to instantiate: %s", pid, e)
                    # Mark as degraded — key is set but provider broken
                    for info in self._infos:
                        if info.id == pid:
                            info.status = ProviderStatus.DEGRADED

    def _instantiate(self, pid: str) -> ImageGenerationProvider:
        if pid == "gemini":
            from .providers.gemini import GeminiImageProvider
            return GeminiImageProvider()
        if pid == "openai":
            from .providers.openai_provider import OpenAIImageProvider
            return OpenAIImageProvider()
        if pid == "openrouter":
            from .providers.openrouter import OpenRouterImageProvider
            return OpenRouterImageProvider()
        if pid == "replicate":
            from .providers.replicate_provider import ReplicateImageProvider
            return ReplicateImageProvider()
        if pid == "stability":
            from .providers.stability import StabilityImageProvider
            return StabilityImageProvider()
        raise ValueError(f"Unknown provider: {pid}")

    def list(self) -> list[ProviderInfo]:
        return list(self._infos)

    def configured(self) -> list[ProviderInfo]:
        return [p for p in self._infos if p.status == ProviderStatus.CONFIGURED]

    def get_info(self, provider_id: str) -> Optional[ProviderInfo]:
        return next((p for p in self._infos if p.id == provider_id), None)

    def get_provider(self, provider_id: str) -> Optional[ImageGenerationProvider]:
        """Return the instantiated provider, or None if not configured/found."""
        return self._providers.get(provider_id)

    def first_available(self) -> Optional[str]:
        """Return the id of the first configured provider, or None."""
        for info in self._infos:
            if info.status == ProviderStatus.CONFIGURED:
                return info.id
        return None

    def build_router(self, preferred_id: str | None = None):
        """Build an AIModelRouter using the preferred (or first available) provider."""
        from .router import AIModelRouter
        from .providers.mock import MockImageProvider, MockVisionProvider

        debug = os.environ.get("DEBUG_MODE", "").lower() in ("1", "true", "yes")
        if debug:
            _log.info("build_router: DEBUG_MODE — using mock providers")
            return AIModelRouter(
                image_provider=MockImageProvider(),
                vision_provider=MockVisionProvider(),
            )

        pid = preferred_id if (preferred_id and preferred_id in self._providers) \
            else self.first_available()

        if not pid:
            _log.warning("build_router: no provider configured — AI generation unavailable")
            return AIModelRouter()

        image_prov = self._providers[pid]

        # Gemini can also provide vision — wire it up
        vision_prov = None
        if pid == "gemini":
            try:
                from .providers.gemini import GeminiVisionProvider
                vision_prov = GeminiVisionProvider()
            except Exception:
                pass

        return AIModelRouter(image_provider=image_prov, vision_provider=vision_prov)

    def env_var_table(self) -> list[dict]:
        """Return a list of {env_var, configured} for documentation/display."""
        return [
            {"env_var": info.env_var, "provider": info.display_name,
             "configured": info.status == ProviderStatus.CONFIGURED}
            for info in self._infos
        ]


# ── Singleton (process-level) ─────────────────────────────────────────────────

_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def reset_registry() -> None:
    """Force a re-check of environment variables (useful in tests)."""
    global _registry
    _registry = None
