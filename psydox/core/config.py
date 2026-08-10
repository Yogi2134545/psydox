"""
Psydox Core — Centralized configuration.
All settings come from environment variables with sane defaults.
Never hardcode credentials or machine-specific paths here.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PsydoxConfig:
    # ── Environment ───────────────────────────────────────────────────────────
    app_env:            str   = "development"
    debug_mode:         bool  = False

    # ── AI Provider ───────────────────────────────────────────────────────────
    google_api_key:     str   = ""
    ai_default_model:   str   = "gemini-2.5-flash-image"
    ai_text_model:      str   = "gemini-2.0-flash"

    # ── AI Quality thresholds ─────────────────────────────────────────────────
    quality_approved_threshold:  int = 70
    quality_review_threshold:    int = 40
    fidelity_low_threshold:      float = 30.0

    # ── AI Retries and timeouts ───────────────────────────────────────────────
    ai_max_retries:      int  = 3
    ai_retry_delay_s:    float = 2.0
    ai_timeout_s:        int  = 120
    ai_max_fix_attempts: int  = 3

    # ── Batch processing ──────────────────────────────────────────────────────
    batch_concurrency:   int  = 8
    batch_max_images:    int  = 500

    # ── Upload limits ─────────────────────────────────────────────────────────
    max_image_mb:        int  = 20
    max_excel_mb:        int  = 50

    # ── Feature flags ─────────────────────────────────────────────────────────
    enable_ai_video:          bool = False
    enable_workflow_builder:  bool = False
    enable_experimental:      bool = False


def load_config() -> PsydoxConfig:
    """Load configuration from environment variables."""
    env = os.environ.get
    return PsydoxConfig(
        app_env             = env("APP_ENV", "development"),
        debug_mode          = env("DEBUG_MODE", "false").lower() in ("1", "true", "yes"),

        google_api_key      = env("GOOGLE_API_KEY", ""),
        ai_default_model    = env("AI_DEFAULT_MODEL", "gemini-2.5-flash-image"),
        ai_text_model       = env("AI_TEXT_MODEL", "gemini-2.0-flash"),

        quality_approved_threshold = int(env("QUALITY_APPROVED_THRESHOLD", "70")),
        quality_review_threshold   = int(env("QUALITY_REVIEW_THRESHOLD", "40")),
        fidelity_low_threshold     = float(env("FIDELITY_LOW_THRESHOLD", "30.0")),

        ai_max_retries      = int(env("AI_MAX_RETRIES", "3")),
        ai_retry_delay_s    = float(env("AI_RETRY_DELAY_S", "2.0")),
        ai_timeout_s        = int(env("AI_TIMEOUT_S", "120")),
        ai_max_fix_attempts = int(env("AI_MAX_FIX_ATTEMPTS", "3")),

        batch_concurrency   = int(env("BATCH_CONCURRENCY", "8")),
        batch_max_images    = int(env("BATCH_MAX_IMAGES", "500")),

        max_image_mb        = int(env("MAX_IMAGE_MB", "20")),
        max_excel_mb        = int(env("MAX_EXCEL_MB", "50")),

        enable_ai_video         = env("ENABLE_AI_VIDEO", "false").lower() in ("1", "true", "yes"),
        enable_workflow_builder = env("ENABLE_WORKFLOW_BUILDER", "false").lower() in ("1", "true", "yes"),
        enable_experimental     = env("ENABLE_EXPERIMENTAL", "false").lower() in ("1", "true", "yes"),
    )


# Module-level singleton
_config: PsydoxConfig | None = None


def get_config() -> PsydoxConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
