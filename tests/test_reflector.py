from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.compiler import compile_reviewed_plan
from vibe_research.executor import run_execution_manifest
from vibe_research.io import read_json, read_jsonl, write_json
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_plan
from vibe_research.reflector import reflect_executor_result, validate_reflection
from vibe_research.reviewer import review_draft_plan, write_review_outputs
from vibe_research.session_budget_guard import refresh_budget_from_status


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def plan_kwargs() -> dict[str, str]:
    return {
        "mode": "invent",
        "failure_anchor": "remote false positives persist after baseline filtering",
        "hypothesis": "a component veto can remove remote false positives",
        "mechanism": "component-veto-with-shape-prior",
        "minimum_experiment": "one-case component veto MVE with saved mask artifact",
        "expected_artifact": ".vibe/runs/r001/component_veto_metrics.json",
        "expected_belief_update": "decide whether component veto has mechanism evidence",
        "compute_cost": "local cpu under 5 minutes",
        "risk": "may over-remove true positives",
        "fallback": "record negative evidence and try route-level filter",
        "stop_condition": "no component-level precision gain",
        "confidence": "speculative_mechanism",
    }


def accepted_manifest(tmp_path: Path) -> tuple[VibePaths, dict]:
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    (paths.kernel / "FAILURE_SIGNATURES.md").write_text("# Failure Signatures\n\nremote false positives persist after baseline filtering\n")
    draft = build_draft_plan(paths, **plan_kwargs())
    outputs = write_review_outputs(paths, review_draft_plan(paths, draft))
    manifest = compile_reviewed_plan(paths, read_json(outputs["reviewed_manifest"], {}))
    write_json(paths.kernel / "execution_manifest.json", manifest)
    return paths, manifest


def completed_result(tmp_path: Path) -> tuple[VibePaths, dict, dict]:
    paths, manifest = accepted_manifest(tmp_path)
    result = run_execution_manifest(paths, manifest, manifest_path=paths.kernel / "execution_manifest.json")
    return paths, manifest, result


def test_reflector_missing_artifact_stops_or_refines(tmp_path: Path):
    paths, manifest = accepted_manifest(tmp_path)
    result = {
        "session_role": "executor",
        "status": "blocked_missing_expected_artifact",
        "source_manifest": str(paths.kernel / "execution_manifest.json"),
        "expected_artifacts": manifest["expected_artifacts"],
        "artifact_inventory": [{"path": manifest["expected_artifacts"][0], "required": True, "exists": False}],
    }
    write_json(paths.executor / "result_manifest.json", result)

    reflection = reflect_executor_result(paths)

    assert reflection["verdict"] in {"STOP", "REFINE"}
    assert reflection["evidence"]["type"] == "missing_artifact"
    assert validate_reflection(reflection) == []


def test_reflector_one_case_positive_generates_subset_promotion_debt(tmp_path: Path):
    paths, manifest, _ = completed_result(tmp_path)
    artifact = tmp_path / manifest["expected_artifacts"][0]
    artifact.write_text(json.dumps({"trusted": True, "primary": 0.8, "guardrail": "ok"}) + "\n")

    reflection = reflect_executor_result(paths)

    assert reflection["verdict"] == "PROCEED"
    assert reflection["next_action"]["type"] == "promotion_debt"
    assert "subset" in reflection["next_action"]["next_debt"]
    assert "not mainline success" in reflection["belief_update"]


def test_reflector_guardrail_regression_pivots_and_updates_negative_memory(tmp_path: Path):
    paths, manifest, _ = completed_result(tmp_path)
    artifact = tmp_path / manifest["expected_artifacts"][0]
    artifact.write_text(json.dumps({"trusted": True, "primary": 0.81, "guardrail_regression": True}) + "\n")

    reflection = reflect_executor_result(paths)

    assert reflection["verdict"] == "PIVOT"
    assert reflection["next_action"]["type"] == "negative_memory"
    assert "guardrails regressed" in (tmp_path / ".vibe" / "kernel" / "NEGATIVE_MEMORY.md").read_text()


def test_reflector_smoke_success_is_feasibility_not_proceed(tmp_path: Path):
    paths, manifest, result = completed_result(tmp_path)
    smoke_path = ".vibe/runs/r001/smoke_status.json"
    (tmp_path / smoke_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / smoke_path).write_text(json.dumps({"trusted": True, "evidence_type": "feasibility"}) + "\n")
    manifest["expected_artifacts"] = [smoke_path]
    result["expected_artifacts"] = [smoke_path]
    result["artifact_inventory"] = [{"path": smoke_path, "required": True, "exists": True}]
    write_json(paths.kernel / "execution_manifest.json", manifest)
    write_json(paths.executor / "result_manifest.json", result)

    reflection = reflect_executor_result(paths)

    assert reflection["verdict"] == "REFINE"
    assert reflection["evidence"]["type"] == "feasibility"


def test_reflector_report_updates_registry_and_evidence_ledger(tmp_path: Path):
    paths, _, _ = completed_result(tmp_path)

    run = invoke("reflector", "reflect", "--target", str(tmp_path))

    assert run.exit_code == 0
    assert (tmp_path / ".vibe" / "kernel" / "reflect_report.md").exists()
    assert read_jsonl(tmp_path / ".vibe" / "kernel" / "REFLECTION_REGISTRY.jsonl")
    assert read_jsonl(tmp_path / ".vibe" / "kernel" / "EVIDENCE_LEDGER.jsonl")[-1]["session_role"] == "reflector"
    validate = invoke("reflector", "validate", str(tmp_path / ".vibe" / "kernel" / "reflect_manifest.json"))
    assert validate.exit_code == 0


def test_reflector_low_quota_writes_partial_reflect_and_resume(tmp_path: Path):
    paths, _, _ = completed_result(tmp_path)
    refresh_budget_from_status(
        paths,
        status_text="5h limit: 5% left\nweekly limit: 60% left",
        session_name="s-reflect",
        role="reflector",
        resume_command="vibe reflector reflect",
    )

    reflection = reflect_executor_result(paths)

    assert reflection["verdict"] == "ASK_HUMAN"
    assert reflection["evidence"]["type"] == "partial_reflect"
    assert (tmp_path / "RESUME.md").exists()
    assert "Partial: true" in (tmp_path / ".vibe" / "kernel" / "reflect_report.md").read_text()
