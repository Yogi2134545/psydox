"""
Jadu Ka Ghar — Ideogram AI image generation for Psydox Studio.

"Jadu Ka Ghar" (House of Magic) integrates Ideogram AI's full API:
  - Remix        : use product image as visual reference + style prompt
  - Replace BG   : AI-powered background replacement
  - Remove BG    : one-click transparent background cutout
  - Generate     : pure text-to-image with style/preset control
  - Describe     : reverse-engineer an image into a reusable prompt

Environment variable required:
  IDEOGRAM_API_KEY  — obtain at https://ideogram.ai/manage-api

This package does NOT modify any existing Psydox or Nano Banana code.
"""
from .engine import IdeogramEngine

__all__ = ["IdeogramEngine"]
__version__ = "1.0.0"
