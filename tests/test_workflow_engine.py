"""Tests for Workflow Engine."""
import sys
import io
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

import os
os.environ["DEBUG_MODE"] = "true"


def _white_jpeg(w=256, h=256) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 200, 200)).save(buf, "JPEG")
    return buf.getvalue()


def test_workflow_with_quality_check():
    from psydox.workflows.engine import WorkflowEngine, WorkflowStatus
    engine = WorkflowEngine()
    defn   = {"name": "Test QA", "steps": ["quality_check"], "stop_on_error": False}
    run    = engine.run(defn, _white_jpeg())
    assert run.status == WorkflowStatus.COMPLETED
    assert run.steps_done == 1


def test_workflow_with_fidelity_check():
    from psydox.workflows.engine import WorkflowEngine, WorkflowStatus
    engine = WorkflowEngine()
    defn   = {"name": "Test Fidelity", "steps": ["fidelity_check"], "stop_on_error": False}
    run    = engine.run(defn, _white_jpeg())
    assert run.status == WorkflowStatus.COMPLETED


def test_workflow_multi_step():
    from psydox.workflows.engine import WorkflowEngine, WorkflowStatus
    engine = WorkflowEngine()
    defn   = {
        "name": "Multi",
        "steps": ["quality_check", "fidelity_check", "export"],
        "stop_on_error": False,
    }
    run = engine.run(defn, _white_jpeg())
    assert run.steps_done == 3
    assert run.status == WorkflowStatus.COMPLETED


def test_workflow_export_produces_output():
    from psydox.workflows.engine import WorkflowEngine
    engine = WorkflowEngine()
    defn   = {"name": "Export", "steps": ["export"]}
    run    = engine.run(defn, _white_jpeg())
    assert len(run.final_outputs) > 0
    assert "bytes" in run.final_outputs[0]


def test_workflow_unknown_feature_step_fails_gracefully():
    from psydox.workflows.engine import WorkflowEngine, WorkflowStatus
    engine = WorkflowEngine()
    defn   = {"name": "Bad", "steps": ["nonexistent_feature_xyz"], "stop_on_error": False}
    run    = engine.run(defn, _white_jpeg())
    # Should not raise, but step should fail
    assert run.steps_done >= 1


def test_workflow_stop_on_error():
    from psydox.workflows.engine import WorkflowEngine, WorkflowStatus
    engine = WorkflowEngine()
    defn   = {
        "name": "StopOnErr",
        "steps": ["nonexistent_xyz", "quality_check"],
        "stop_on_error": True,
    }
    run = engine.run(defn, _white_jpeg())
    assert run.status == WorkflowStatus.FAILED
    assert run.steps_done < 2


def test_workflow_from_yaml():
    from psydox.workflows.engine import WorkflowEngine, WorkflowStatus
    engine = WorkflowEngine()
    yaml_str = """
name: YAML Test
steps:
  - quality_check
  - export
stop_on_error: false
"""
    run = engine.run_from_yaml(yaml_str, _white_jpeg())
    assert run.status == WorkflowStatus.COMPLETED
    assert run.name == "YAML Test"


def test_workflow_progress_tracking():
    from psydox.workflows.engine import WorkflowEngine
    engine = WorkflowEngine()
    defn   = {"name": "Progress", "steps": ["quality_check", "export"]}
    run    = engine.run(defn, _white_jpeg())
    assert run.progress_pct() == 100
