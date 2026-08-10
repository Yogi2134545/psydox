"""
Psydox AI Core — Provider Interfaces

Providers are replaceable. Psydox is not coupled to any single AI company.
To add a new provider: implement these interfaces and register with the router.

Provider → ProviderResult → AIOrchestrator → Feature → UI
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class ProviderCapability(str, Enum):
    IMAGE_GENERATION = "IMAGE_GENERATION"
    IMAGE_EDITING    = "IMAGE_EDITING"
    VISION           = "VISION"
    ENHANCEMENT      = "ENHANCEMENT"
    UPSCALE          = "UPSCALE"
    BACKGROUND_REMOVAL = "BACKGROUND_REMOVAL"


@dataclass
class ProviderResult:
    success:        bool
    image_bytes:    bytes | None = None
    text:           str | None = None
    model:          str = ""
    provider:       str = ""
    latency_ms:     int = 0
    cost_estimate:  float = 0.0
    retry_count:    int = 0
    error:          str | None = None
    metadata:       dict = field(default_factory=dict)


class ImageGenerationProvider(ABC):
    """Generates images from a text prompt + optional reference image."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> list[ProviderCapability]: ...

    @abstractmethod
    def generate(
        self,
        prompt: str,
        reference_bytes: bytes | None = None,
        model: str | None = None,
        **kwargs,
    ) -> ProviderResult:
        """Generate an image. Returns ProviderResult — never raises."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is configured and reachable."""
        ...

    def estimate_cost(self, prompt: str, reference_bytes: bytes | None = None) -> float:
        """Estimate USD cost for this generation. Override with provider-specific pricing."""
        return 0.04


class VisionProvider(ABC):
    """Analyzes images using a vision model."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def analyze(
        self,
        image_bytes: bytes,
        prompt: str,
        model: str | None = None,
    ) -> ProviderResult:
        """Analyze an image. Returns ProviderResult with text — never raises."""
        ...

    @abstractmethod
    def is_available(self) -> bool: ...
