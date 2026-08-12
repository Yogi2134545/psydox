"""
Jadu Ka Ghar — Ideogram AI engine.

Thin orchestration layer over IdeogramClient.
All methods return the standard Psydox result dict:
  {"success": bool, "outputs": [{"bytes", "label", "mime"}], "errors": [], "metadata": {}}

Modes:
  remix            — reference image + style prompt
  replace_bg       — swap background, preserve product
  remove_bg        — transparent cutout
  generate         — text-to-image
  describe         — image → prompt text (no output bytes)
"""
from __future__ import annotations

import io
import logging
from PIL import Image

from .client import IdeogramClient

_log = logging.getLogger("jadu_ka_ghar.engine")


class IdeogramEngine:

    def __init__(self):
        self.client = IdeogramClient()

    def is_available(self) -> bool:
        return self.client.is_available()

    def run(self, config: dict) -> dict:
        """
        Dispatch to the correct mode based on config["mode"].
        Returns standard Psydox result dict — never raises.
        """
        mode = config.get("mode", "remix")
        image_bytes: bytes | None = config.get("image_bytes")

        try:
            if mode == "remix":
                return self._run_remix(config, image_bytes)
            elif mode == "replace_bg":
                return self._run_replace_bg(config, image_bytes)
            elif mode == "remove_bg":
                return self._run_remove_bg(image_bytes)
            elif mode == "generate":
                return self._run_generate(config)
            elif mode == "describe":
                return self._run_describe(image_bytes)
            else:
                return _err(f"Unknown Jadu Ka Ghar mode: {mode}")
        except RuntimeError as e:
            _log.warning("IdeogramEngine.run mode=%s error=%s", mode, e)
            return _err(str(e))
        except Exception as e:
            _log.exception("IdeogramEngine.run unexpected error mode=%s", mode)
            return _err(f"Unexpected error: {e}")

    # ── Remix ─────────────────────────────────────────────────────────────────

    def _run_remix(self, cfg: dict, image_bytes: bytes | None) -> dict:
        if not image_bytes:
            return _err("Remix requires an input image.")
        prompt = cfg.get("prompt", "").strip()
        if not prompt:
            return _err("Remix requires a prompt describing the desired style or scene.")

        result_bytes = self.client.remix(
            image_bytes=image_bytes,
            prompt=prompt,
            style_type=cfg.get("style_type", "GENERAL"),
            style_preset=cfg.get("style_preset", "NONE"),
            aspect_ratio=cfg.get("aspect_ratio", "AUTO"),
            magic_prompt=cfg.get("magic_prompt", "AUTO"),
            negative_prompt=cfg.get("negative_prompt", ""),
            image_weight=int(cfg.get("image_weight", 50)),
            rendering_speed=cfg.get("rendering_speed", "STANDARD"),
            num_images=int(cfg.get("num_images", 1)),
            color_palette=cfg.get("color_palette", "NONE"),
            seed=cfg.get("seed"),
        )
        return _ok(result_bytes, "Ideogram Remix", "image/jpeg")

    # ── Replace Background ────────────────────────────────────────────────────

    def _run_replace_bg(self, cfg: dict, image_bytes: bytes | None) -> dict:
        if not image_bytes:
            return _err("Replace Background requires an input image.")
        prompt = cfg.get("prompt", "").strip()
        if not prompt:
            return _err("Replace Background requires a background description prompt.")

        result_bytes = self.client.replace_background(
            image_bytes=image_bytes,
            prompt=prompt,
            magic_prompt=cfg.get("magic_prompt", "AUTO"),
            style_preset=cfg.get("style_preset", "NONE"),
            rendering_speed=cfg.get("rendering_speed", "STANDARD"),
            num_images=int(cfg.get("num_images", 1)),
            seed=cfg.get("seed"),
        )
        return _ok(result_bytes, "Ideogram Replace BG", "image/jpeg")

    # ── Remove Background ─────────────────────────────────────────────────────

    def _run_remove_bg(self, image_bytes: bytes | None) -> dict:
        if not image_bytes:
            return _err("Remove Background requires an input image.")
        result_bytes = self.client.remove_background(image_bytes)
        # result is PNG with transparency
        return _ok(result_bytes, "Ideogram Remove BG", "image/png")

    # ── Generate ──────────────────────────────────────────────────────────────

    def _run_generate(self, cfg: dict) -> dict:
        prompt = cfg.get("prompt", "").strip()
        if not prompt:
            return _err("Generate requires a text prompt.")

        result_bytes = self.client.generate(
            prompt=prompt,
            style_type=cfg.get("style_type", "REALISTIC"),
            style_preset=cfg.get("style_preset", "PRODUCT_PHOTOGRAPHY"),
            aspect_ratio=cfg.get("aspect_ratio", "1x1"),
            magic_prompt=cfg.get("magic_prompt", "AUTO"),
            negative_prompt=cfg.get("negative_prompt", ""),
            rendering_speed=cfg.get("rendering_speed", "STANDARD"),
            num_images=int(cfg.get("num_images", 1)),
            color_palette=cfg.get("color_palette", "NONE"),
            seed=cfg.get("seed"),
        )
        return _ok(result_bytes, "Ideogram Generate", "image/jpeg")

    # ── Describe ──────────────────────────────────────────────────────────────

    def _run_describe(self, image_bytes: bytes | None) -> dict:
        if not image_bytes:
            return _err("Describe requires an input image.")
        description = self.client.describe(image_bytes)
        return {
            "success":  True,
            "outputs":  [],
            "errors":   [],
            "metadata": {"description": description},
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ok(image_bytes: bytes, label: str, mime: str) -> dict:
    return {
        "success":  True,
        "outputs":  [{"bytes": image_bytes, "label": label, "mime": mime}],
        "errors":   [],
        "metadata": {"provider": "ideogram"},
    }


def _err(message: str) -> dict:
    return {
        "success":  False,
        "outputs":  [],
        "errors":   [message],
        "metadata": {"provider": "ideogram"},
    }
