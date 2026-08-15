"""AI provider implementations."""
from .base import ImageGenerationProvider, VisionProvider, ProviderResult
from .gemini import GeminiImageProvider, GeminiVisionProvider
from .mock import MockImageProvider, MockVisionProvider

__all__ = [
    "ImageGenerationProvider", "VisionProvider", "ProviderResult",
    "GeminiImageProvider", "GeminiVisionProvider",
    "MockImageProvider", "MockVisionProvider",
    "IdeogramImageProvider",
    "OpenAIImageProvider",
    "OpenRouterImageProvider",
    "ReplicateImageProvider",
    "StabilityImageProvider",
]


def __getattr__(name: str):
    """Lazy-import non-default providers so missing optional deps don't crash at import."""
    _lazy = {
        "IdeogramImageProvider":    (".ideogram",             "IdeogramImageProvider"),
        "OpenAIImageProvider":      (".openai_provider",      "OpenAIImageProvider"),
        "OpenRouterImageProvider":  (".openrouter",           "OpenRouterImageProvider"),
        "ReplicateImageProvider":   (".replicate_provider",   "ReplicateImageProvider"),
        "StabilityImageProvider":   (".stability",            "StabilityImageProvider"),
    }
    if name in _lazy:
        module_path, class_name = _lazy[name]
        import importlib
        mod = importlib.import_module(module_path, package=__name__)
        return getattr(mod, class_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
