"""
Jadu Ka Ghar — Ideogram AI REST client.

Covers all major Ideogram endpoints:
  V3 remix, replace-background, generate, remove-background, describe

API reference: https://developer.ideogram.ai/api-reference
Auth header  : Api-Key: <IDEOGRAM_API_KEY>
Response URLs: ephemeral — downloaded immediately and returned as bytes
"""
from __future__ import annotations

import io
import os
import logging
import time

import requests
from PIL import Image

_log = logging.getLogger("jadu_ka_ghar.client")

BASE_URL     = "https://api.ideogram.ai"
API_KEY_ENV  = "IDEOGRAM_API_KEY"
_TIMEOUT     = 90  # seconds — Ideogram can be slow on STANDARD speed

# ── Option constants (kept here as single source of truth) ────────────────────

# V3 style_type values
STYLE_TYPES = ["AUTO", "GENERAL", "REALISTIC", "DESIGN", "FICTION"]

# V3 style_preset values (subset — most useful for product photography)
STYLE_PRESETS = [
    "NONE",
    "PRODUCT_PHOTOGRAPHY",
    "CINEMATIC",
    "WATERCOLOR",
    "OIL_PAINTING",
    "PENCIL_SKETCH",
    "INK_SKETCH",
    "POP_ART",
    "COMIC_BOOK",
    "ILLUSTRATION",
    "ANIME",
    "FANTASY",
    "NEON",
    "POSTER",
    "GRUNGE",
    "ABSTRACT",
    "STICKER",
    "MAGAZINE",
    "ANALOG_FILM",
    "SURREAL_COLLAGE",
]

# V3 aspect_ratio values (same notation as Ideogram API)
ASPECT_RATIOS = [
    "AUTO", "1x1", "4x5", "5x4", "3x4", "4x3",
    "2x3", "3x2", "9x16", "16x9", "10x16", "16x10",
    "1x2", "2x1", "3x1", "1x3",
]

MAGIC_PROMPT_OPTIONS = ["AUTO", "ON", "OFF"]
RENDERING_SPEEDS     = ["STANDARD", "TURBO"]

# Color palette presets
COLOR_PALETTES = [
    "NONE", "EMBER", "FRESH", "JUNGLE", "MAGIC",
    "MELON", "MOSAIC", "PASTEL", "ULTRAMARINE",
]


class IdeogramClient:
    """Low-level Ideogram REST client. All methods return bytes or raise RuntimeError."""

    def __init__(self):
        self.api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not self.api_key:
            _log.warning(
                "%s not set — Jadu Ka Ghar (Ideogram) is disabled", API_KEY_ENV
            )

    def is_available(self) -> bool:
        return bool(self.api_key)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Api-Key": self.api_key}

    def _download_url(self, url: str) -> bytes:
        """Download an ephemeral Ideogram result URL and return raw bytes."""
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content

    def _to_jpeg_bytes(self, image_bytes: bytes, quality: int = 90) -> bytes:
        """Ensure image is JPEG bytes (Ideogram accepts JPEG/PNG/WebP ≤10 MB)."""
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    def _post_multipart(self, endpoint: str, fields: dict, files: dict) -> dict:
        """POST multipart/form-data and return parsed JSON response."""
        if not self.api_key:
            raise RuntimeError(
                "IDEOGRAM_API_KEY not set. "
                "Get a key at https://ideogram.ai/manage-api and add it to Railway env vars."
            )
        url = BASE_URL + endpoint
        t0  = time.time()
        try:
            resp = requests.post(
                url,
                headers=self._headers(),
                data=fields,
                files=files,
                timeout=_TIMEOUT,
            )
        except requests.Timeout:
            raise RuntimeError(
                f"Ideogram API timed out after {_TIMEOUT}s. "
                "Try using TURBO rendering speed."
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Ideogram API request failed: {e}") from e

        elapsed = time.time() - t0
        _log.info("Ideogram %s  status=%s  elapsed=%.2fs", endpoint, resp.status_code, elapsed)

        if resp.status_code == 401:
            raise RuntimeError("Ideogram: invalid API key (401). Check IDEOGRAM_API_KEY.")
        if resp.status_code == 402:
            raise RuntimeError("Ideogram: insufficient credits (402). Top up at ideogram.ai.")
        if resp.status_code == 422:
            raise RuntimeError(
                "Ideogram: content policy violation (422). "
                "Try a different prompt or image."
            )
        if resp.status_code == 429:
            raise RuntimeError("Ideogram: rate limited (429). Wait a moment and try again.")

        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:300]
            raise RuntimeError(f"Ideogram API error {resp.status_code}: {detail}")

        try:
            return resp.json()
        except Exception as e:
            raise RuntimeError(f"Ideogram response not JSON: {resp.text[:300]}") from e

    def _extract_image_bytes(self, body: dict) -> bytes:
        """Extract the first result URL from a response body and download it."""
        data = body.get("data") or []
        if not data:
            raise RuntimeError(
                "Ideogram returned no images. "
                "The prompt may have been blocked by safety filters."
            )
        item = data[0]
        if not item.get("is_image_safe", True):
            raise RuntimeError(
                "Ideogram flagged the result as unsafe. Try adjusting the prompt."
            )
        url = item.get("url")
        if not url:
            raise RuntimeError("Ideogram response missing image URL.")
        return self._download_url(url)

    # ── V3 Remix ──────────────────────────────────────────────────────────────

    def remix(
        self,
        image_bytes: bytes,
        prompt: str,
        style_type: str = "GENERAL",
        style_preset: str = "NONE",
        aspect_ratio: str = "AUTO",
        magic_prompt: str = "AUTO",
        negative_prompt: str = "",
        image_weight: int = 50,
        rendering_speed: str = "STANDARD",
        num_images: int = 1,
        color_palette: str = "NONE",
        seed: int | None = None,
    ) -> bytes:
        """
        Remix: keep the product essence from the reference image and
        apply a new style/scene via prompt.

        image_weight controls how closely the output follows the reference
        (0 = ignore, 100 = copy). Default 50 (balanced).
        """
        fields: dict = {"prompt": prompt}
        if style_type and style_type != "AUTO":
            fields["style_type"] = style_type
        if style_preset and style_preset != "NONE":
            fields["style_preset"] = style_preset
        if aspect_ratio and aspect_ratio != "AUTO":
            fields["aspect_ratio"] = aspect_ratio
        if magic_prompt:
            fields["magic_prompt"] = magic_prompt
        if negative_prompt:
            fields["negative_prompt"] = negative_prompt
        if image_weight != 50:
            fields["image_weight"] = str(image_weight)
        if rendering_speed and rendering_speed != "STANDARD":
            fields["rendering_speed"] = rendering_speed
        if num_images > 1:
            fields["num_images"] = str(num_images)
        if color_palette and color_palette != "NONE":
            fields["color_palette"] = f'{{"members": [{{"color": "{color_palette}"}}]}}'
        if seed is not None:
            fields["seed"] = str(seed)

        img_bytes = self._to_jpeg_bytes(image_bytes)
        files = {"image": ("product.jpg", img_bytes, "image/jpeg")}
        body  = self._post_multipart("/v1/ideogram-v3/remix", fields, files)
        return self._extract_image_bytes(body)

    # ── V3 Replace Background ─────────────────────────────────────────────────

    def replace_background(
        self,
        image_bytes: bytes,
        prompt: str,
        magic_prompt: str = "AUTO",
        style_preset: str = "NONE",
        rendering_speed: str = "STANDARD",
        num_images: int = 1,
        seed: int | None = None,
    ) -> bytes:
        """
        Replace the background of the product image using Ideogram AI.
        The product (foreground) is preserved; only the background changes.
        """
        fields: dict = {"prompt": prompt, "magic_prompt": magic_prompt}
        if style_preset and style_preset != "NONE":
            fields["style_preset"] = style_preset
        if rendering_speed and rendering_speed != "STANDARD":
            fields["rendering_speed"] = rendering_speed
        if num_images > 1:
            fields["num_images"] = str(num_images)
        if seed is not None:
            fields["seed"] = str(seed)

        img_bytes = self._to_jpeg_bytes(image_bytes)
        files = {"image": ("product.jpg", img_bytes, "image/jpeg")}
        body  = self._post_multipart("/v1/ideogram-v3/replace-background", fields, files)
        return self._extract_image_bytes(body)

    # ── Remove Background ─────────────────────────────────────────────────────

    def remove_background(self, image_bytes: bytes) -> bytes:
        """
        Remove the background from a product image.
        Returns PNG bytes with transparent background.
        """
        img_bytes = self._to_jpeg_bytes(image_bytes)
        files = {"image": ("product.jpg", img_bytes, "image/jpeg")}
        body  = self._post_multipart("/v1/remove-background", {}, files)
        raw   = self._extract_image_bytes(body)
        # Ensure PNG output to preserve transparency
        img   = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGBA", "LA"):
            # API may return RGBA already — normalise to RGBA PNG
            img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # ── V3 Generate ───────────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        style_type: str = "REALISTIC",
        style_preset: str = "PRODUCT_PHOTOGRAPHY",
        aspect_ratio: str = "1x1",
        magic_prompt: str = "AUTO",
        negative_prompt: str = "",
        rendering_speed: str = "STANDARD",
        num_images: int = 1,
        color_palette: str = "NONE",
        seed: int | None = None,
    ) -> bytes:
        """
        Text-to-image generation.
        Generates a brand-new product-style image from a text prompt.
        """
        fields: dict = {
            "prompt":          prompt,
            "magic_prompt":    magic_prompt,
        }
        if style_type and style_type != "AUTO":
            fields["style_type"] = style_type
        if style_preset and style_preset != "NONE":
            fields["style_preset"] = style_preset
        if aspect_ratio and aspect_ratio != "AUTO":
            fields["aspect_ratio"] = aspect_ratio
        if negative_prompt:
            fields["negative_prompt"] = negative_prompt
        if rendering_speed and rendering_speed != "STANDARD":
            fields["rendering_speed"] = rendering_speed
        if num_images > 1:
            fields["num_images"] = str(num_images)
        if color_palette and color_palette != "NONE":
            fields["color_palette"] = color_palette
        if seed is not None:
            fields["seed"] = str(seed)

        body = self._post_multipart("/v1/ideogram-v3/generate", fields, {})
        return self._extract_image_bytes(body)

    # ── Describe ──────────────────────────────────────────────────────────────

    def describe(self, image_bytes: bytes) -> str:
        """
        Reverse-engineer an image into a reusable text prompt.
        Returns the description string.
        """
        img_bytes = self._to_jpeg_bytes(image_bytes)
        files = {"image_file": ("product.jpg", img_bytes, "image/jpeg")}
        body  = self._post_multipart("/describe", {}, files)
        descriptions = body.get("descriptions") or []
        if not descriptions:
            return ""
        return descriptions[0].get("text", "")

    # ── Magic Prompt ──────────────────────────────────────────────────────────

    def enhance_prompt(self, text: str, aspect_ratio: str = "AUTO") -> str:
        """
        Use Ideogram's magic-prompt LLM to improve a text prompt.
        Returns the enhanced prompt string.
        """
        fields: dict = {"text_prompt": text}
        if aspect_ratio and aspect_ratio != "AUTO":
            fields["aspect_ratio"] = aspect_ratio
        body = self._post_multipart("/v1/ideogram-v4/magic-prompt", fields, {})
        # V4 magic-prompt returns a json_prompt object; extract high-level description
        jp = body.get("json_prompt") or {}
        return jp.get("high_level_description", text)
