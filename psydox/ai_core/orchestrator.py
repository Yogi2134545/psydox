"""
Psydox AI Core — AI Orchestrator

Central coordinator for all AI generation operations.
Features call the orchestrator — they never call providers directly.
This ensures consistent: retries, quality checks, cost tracking, observability.

Flow:
  Feature → AIOrchestrator.generate() → Router → Provider → QA → Result
"""
import time
import logging
import uuid
from dataclasses import dataclass, field

from .router import AIModelRouter, TaskType, build_router
from .providers.base import ProviderResult

_log = logging.getLogger("psydox.ai_core.orchestrator")


@dataclass
class AIRequest:
    """Input to the orchestrator."""
    task:            TaskType
    prompt:          str
    reference_bytes: bytes | None = None
    reference_bytes_extra: list   = field(default_factory=list)
    job_id:          str          = ""
    project_id:      str          = ""
    user_id:         str          = ""
    feature_id:      str          = ""
    context:         dict         = field(default_factory=dict)


@dataclass
class AIResult:
    """Output from the orchestrator."""
    success:        bool
    image_bytes:    bytes | None = None
    provider:       str          = ""
    model:          str          = ""
    request_id:     str          = ""
    latency_ms:     int          = 0
    cost_estimate:  float        = 0.0
    retry_count:    int          = 0
    quality_score:  int | None   = None
    quality_verdict: str | None  = None
    error:          str | None   = None
    user_message:   str | None   = None
    metadata:       dict         = field(default_factory=dict)


class AIOrchestrator:
    """
    Central AI generation coordinator.

    Responsibilities:
    - Select provider via router
    - Execute generation
    - Track cost and observability
    - Optionally run quality checks
    - Return structured AIResult

    One instance per app (use get_orchestrator()).
    """

    def __init__(self, router: AIModelRouter | None = None):
        self._router = router or build_router()
        self._total_cost = 0.0
        self._total_calls = 0

    def generate(self, request: AIRequest, run_quality: bool = False) -> AIResult:
        """
        Generate an image for the given AIRequest.
        Never raises — errors are captured in AIResult.error.
        """
        request_id = str(uuid.uuid4())[:8]
        t0 = time.monotonic()

        _log.info(
            "orchestrator.generate  id=%s  task=%s  feature=%s  job=%s",
            request_id, request.task.value, request.feature_id, request.job_id,
        )

        # Deterministic short-circuit
        if self._router.is_deterministic(request.task):
            return AIResult(
                success=False,
                request_id=request_id,
                error="Deterministic task — use classic processing, not AI orchestrator.",
            )

        provider = self._router.get_image_provider(request.task)
        if provider is None:
            _log.warning("orchestrator: no provider for task=%s", request.task)
            return AIResult(
                success=False,
                request_id=request_id,
                error="No AI provider available.",
                user_message=(
                    "AI is not available. Check that GOOGLE_API_KEY is set and "
                    "image generation is enabled."
                ),
            )

        result: ProviderResult = provider.generate(
            prompt=request.prompt,
            reference_bytes=request.reference_bytes,
        )

        latency = int((time.monotonic() - t0) * 1000)
        self._total_cost  += result.cost_estimate
        self._total_calls += 1

        if not result.success:
            _log.error(
                "orchestrator: provider failure  id=%s  provider=%s  error=%s",
                request_id, result.provider, result.error,
            )
            return AIResult(
                success=False,
                provider=result.provider,
                model=result.model,
                request_id=request_id,
                latency_ms=latency,
                error=result.error,
                user_message="AI generation failed. Please retry.",
            )

        # Optional quality check
        quality_score, quality_verdict = None, None
        if run_quality and result.image_bytes:
            try:
                from nano_banana.quality_engine import AIQualityEngine
                engine = AIQualityEngine()
                qs = engine.score(result.image_bytes, request.reference_bytes)
                quality_score   = qs.score
                quality_verdict = qs.verdict.value
            except Exception as qe:
                _log.warning("orchestrator: quality check failed: %s", qe)

        _log.info(
            "orchestrator: success  id=%s  provider=%s  model=%s  "
            "latency=%dms  cost=%.4f  quality=%s",
            request_id, result.provider, result.model,
            latency, result.cost_estimate, quality_score,
        )

        return AIResult(
            success=True,
            image_bytes=result.image_bytes,
            provider=result.provider,
            model=result.model,
            request_id=request_id,
            latency_ms=latency,
            cost_estimate=result.cost_estimate,
            retry_count=result.retry_count,
            quality_score=quality_score,
            quality_verdict=quality_verdict,
        )

    def get_stats(self) -> dict:
        return {
            "total_calls": self._total_calls,
            "total_cost_usd": round(self._total_cost, 4),
        }

    def is_ai_available(self) -> bool:
        """Quick check: is any AI image provider reachable?"""
        for task in (TaskType.CREATIVE_BACKGROUND, TaskType.LIFESTYLE):
            prov = self._router.get_image_provider(task)
            if prov and prov.is_available():
                return True
        return False


# ── Singleton (Streamlit-compatible) ─────────────────────────────────────────

_ORCHESTRATOR: AIOrchestrator | None = None


def get_orchestrator() -> AIOrchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = AIOrchestrator()
    return _ORCHESTRATOR


def reset_orchestrator() -> None:
    """Force a new orchestrator on next get_orchestrator() call (e.g. after env vars change)."""
    global _ORCHESTRATOR
    _ORCHESTRATOR = None
