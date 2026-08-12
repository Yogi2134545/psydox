"""
Nano Banana v2 — improved image generation logic.

Drop-in replacement for nano_banana that delivers:
  - Rich prompt descriptions for all 20 lifestyle styles (not just 4)
  - Product-fidelity instruction in every AI prompt type
  - Complete coverage for all scene/lighting/shadow options
  - Fixed shadows/highlights tone curve (no double-adjustment)
  - Safe transparent-image handling before API calls
  - No dead code or resource leaks

Usage:
    from nano_banana_v2.engine import NanoBananaEngineV2
    engine = NanoBananaEngineV2()
    result = engine.process_single(image, config)
"""
from .engine import NanoBananaEngineV2

__all__ = ["NanoBananaEngineV2"]
__version__ = "2.0.0"
