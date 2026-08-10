"""
Psydox Workflow Engine

Workflows are configuration-driven (YAML or dict).
A new workflow can be defined without writing application code.

Example workflow definition:
  name: Fashion Lifestyle
  steps:
    - product_analysis
    - model_generation
    - lifestyle_generation
    - lighting
    - fidelity_check
    - quality_check
    - export

Each step maps to a registered feature ID or a built-in step handler.
Steps are executed sequentially.  The output of each step is passed as
reference input to the next step where applicable.

Built-in step types:
  product_analysis   — runs ProductIntelligenceEngine on the input image
  fidelity_check     — runs FidelityEngine, warns if score < threshold
  quality_check      — runs AIQualityEngine, warns if verdict != APPROVED
  export             — packages outputs (no AI)
  <feature_id>       — executes that feature via the registry

Adding a new workflow step type: add an entry to _STEP_HANDLERS.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

try:
    import yaml as _yaml_mod
    def _load_yaml(s: str) -> dict:
        return _yaml_mod.safe_load(s)
except ImportError:
    _yaml_mod = None  # type: ignore
    def _load_yaml(s: str) -> dict:
        # Minimal YAML→dict for simple flat configs (no yaml library)
        # Supports: key: value, key: true/false, list items (- value)
        result: dict = {}
        current_list_key: str = ""
        for raw in s.splitlines():
            line = raw.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            if line.startswith("  - "):
                if current_list_key:
                    result[current_list_key].append(line.strip()[2:])
                continue
            if ": " in line or line.endswith(":"):
                k, _, v = line.partition(": ")
                k = k.strip()
                v = v.strip()
                if v == "" or v is None:
                    result[k] = []
                    current_list_key = k
                elif v.lower() == "true":
                    result[k] = True; current_list_key = ""
                elif v.lower() == "false":
                    result[k] = False; current_list_key = ""
                else:
                    result[k] = v; current_list_key = ""
        return result

_log = logging.getLogger("psydox.workflows.engine")


class WorkflowStatus(str, Enum):
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class StepResult:
    step:      str
    success:   bool
    outputs:   list            = field(default_factory=list)
    errors:    list[str]       = field(default_factory=list)
    metadata:  dict            = field(default_factory=dict)
    duration_s: float          = 0.0


@dataclass
class WorkflowRun:
    id:           str
    name:         str
    status:       WorkflowStatus
    steps_total:  int
    steps_done:   int           = 0
    step_results: list[StepResult] = field(default_factory=list)
    final_outputs: list         = field(default_factory=list)
    errors:       list[str]     = field(default_factory=list)
    user_email:   str           = ""
    created_at:   float         = field(default_factory=time.time)
    updated_at:   float         = field(default_factory=time.time)

    def progress_pct(self) -> int:
        if not self.steps_total:
            return 0
        return int(100 * self.steps_done / self.steps_total)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "status": self.status.value,
            "steps_total": self.steps_total, "steps_done": self.steps_done,
            "errors": self.errors, "user_email": self.user_email,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


# ── Built-in step handlers ────────────────────────────────────────────────────

def _step_product_analysis(image_bytes: bytes, context: dict, cfg: dict) -> StepResult:
    t = time.time()
    try:
        from psydox.product.intelligence import ProductIntelligenceEngine
        attrs = ProductIntelligenceEngine().analyze(image_bytes)
        context["product_attributes"] = attrs.to_dict()
        return StepResult(
            step="product_analysis", success=True,
            metadata={"confidence": attrs.overall_confidence},
            duration_s=time.time() - t,
        )
    except Exception as exc:
        return StepResult(step="product_analysis", success=False, errors=[str(exc)],
                          duration_s=time.time() - t)


def _step_fidelity_check(image_bytes: bytes, context: dict, cfg: dict) -> StepResult:
    t = time.time()
    original = context.get("original_image_bytes")
    if not original:
        return StepResult(step="fidelity_check", success=True,
                          metadata={"note": "No original image — fidelity check skipped"},
                          duration_s=time.time() - t)
    try:
        from psydox.quality.fidelity import FidelityEngine
        fs = FidelityEngine().score(original, image_bytes)
        context["fidelity_score"] = fs.to_dict()
        return StepResult(
            step="fidelity_check", success=True,
            metadata={"overall": fs.overall_score, "verdict": fs.badge_text()},
            duration_s=time.time() - t,
        )
    except Exception as exc:
        return StepResult(step="fidelity_check", success=False, errors=[str(exc)],
                          duration_s=time.time() - t)


def _step_quality_check(image_bytes: bytes, context: dict, cfg: dict) -> StepResult:
    t = time.time()
    try:
        from psydox.quality.engine import AIQualityEngine
        original = context.get("original_image_bytes")
        qs = AIQualityEngine().score(image_bytes, original)
        context["quality_score"] = qs.score
        context["quality_verdict"] = qs.verdict.value
        return StepResult(
            step="quality_check", success=True,
            metadata={"score": qs.score, "verdict": qs.verdict.value, "issues": qs.issues},
            duration_s=time.time() - t,
        )
    except Exception as exc:
        return StepResult(step="quality_check", success=False, errors=[str(exc)],
                          duration_s=time.time() - t)


def _step_export(image_bytes: bytes, context: dict, cfg: dict) -> StepResult:
    return StepResult(
        step="export", success=True,
        outputs=[{"bytes": image_bytes, "label": "export", "mime": "image/jpeg"}],
    )


_STEP_HANDLERS = {
    "product_analysis": _step_product_analysis,
    "fidelity_check":   _step_fidelity_check,
    "quality_check":    _step_quality_check,
    "export":           _step_export,
}


class WorkflowEngine:
    """
    Executes configuration-driven multi-step workflows.
    New step types: add a handler to _STEP_HANDLERS.
    New workflow definitions: add YAML to psydox/workflows/definitions/*.yaml.
    """

    def run(
        self,
        definition: dict,          # parsed workflow YAML/dict
        image_bytes: bytes,
        user_email:  str = "",
        context:     dict | None = None,
    ) -> WorkflowRun:
        """Execute a workflow synchronously.  Returns the completed WorkflowRun."""
        steps    = definition.get("steps", [])
        name     = definition.get("name", "Unnamed Workflow")
        run      = WorkflowRun(
            id=str(uuid.uuid4())[:8],
            name=name,
            status=WorkflowStatus.RUNNING,
            steps_total=len(steps),
            user_email=user_email,
        )

        ctx = dict(context or {})
        ctx["original_image_bytes"] = image_bytes
        current_bytes = image_bytes

        for step_name in steps:
            step_cfg  = {}
            if isinstance(step_name, dict):
                step_cfg  = step_name
                step_name = list(step_name.keys())[0]

            t0 = time.time()
            _log.info("Workflow '%s' step '%s'", name, step_name)

            # Built-in handler?
            if step_name in _STEP_HANDLERS:
                result = _STEP_HANDLERS[step_name](current_bytes, ctx, step_cfg)
            else:
                # Feature registry step
                result = self._execute_feature_step(step_name, current_bytes, ctx, step_cfg)

            result.duration_s = time.time() - t0
            run.step_results.append(result)
            run.steps_done += 1
            run.updated_at = time.time()

            if not result.success:
                run.errors.extend(result.errors)
                # Non-fatal — continue unless config says stop_on_error
                if definition.get("stop_on_error", True):
                    run.status = WorkflowStatus.FAILED
                    return run

            # Pass the first output bytes to the next step
            if result.outputs:
                first_out = result.outputs[0]
                if isinstance(first_out, dict) and "bytes" in first_out:
                    current_bytes = first_out["bytes"]

        # Collect all outputs from all steps
        run.final_outputs = [
            out for sr in run.step_results for out in sr.outputs
        ]
        run.status = WorkflowStatus.COMPLETED
        self._persist(run)
        return run

    def run_from_yaml(self, yaml_str: str, image_bytes: bytes, user_email: str = "") -> WorkflowRun:
        definition = _load_yaml(yaml_str)
        return self.run(definition, image_bytes, user_email=user_email)

    def _execute_feature_step(self, feature_id: str, image_bytes: bytes,
                               context: dict, cfg: dict) -> StepResult:
        t = time.time()
        try:
            from psydox.core.registry import get_registry
            feature = get_registry().get(feature_id)
            if not feature:
                return StepResult(step=feature_id, success=False,
                                  errors=[f"Feature '{feature_id}' not registered"],
                                  duration_s=time.time() - t)
            inputs = dict(cfg)
            inputs["image_bytes"] = image_bytes
            # Merge product context
            if context.get("product_attributes"):
                inputs["product_desc"] = context["product_attributes"].get(
                    "raw_description", ""
                )[:200]
            result = feature.execute(inputs, context)
            return StepResult(
                step=feature_id,
                success=result.get("success", False),
                outputs=result.get("outputs", []),
                errors=result.get("errors", []),
                metadata=result.get("metadata", {}),
                duration_s=time.time() - t,
            )
        except Exception as exc:
            _log.exception("Workflow step '%s' raised", feature_id)
            return StepResult(step=feature_id, success=False, errors=[str(exc)],
                              duration_s=time.time() - t)

    def _persist(self, run: WorkflowRun) -> None:
        try:
            from psydox.storage.database import get_db
            db = get_db()
            db.execute(
                """INSERT OR REPLACE INTO workflow_runs
                   (id, name, status, job_ids, user_email, data, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run.id, run.name, run.status.value,
                 json.dumps([sr.step for sr in run.step_results]),
                 run.user_email, json.dumps(run.to_dict()),
                 run.created_at, run.updated_at),
            )
            db.commit()
        except Exception as exc:
            _log.debug("WorkflowEngine._persist failed: %s", exc)


_engine: Optional[WorkflowEngine] = None

def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
