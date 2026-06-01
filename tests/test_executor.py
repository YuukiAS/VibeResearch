from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.compiler import compile_reviewed_plan
from vibe_research.executor import run_execution_manifest, validate_result_manifest, validate_scientific_boundary
from vibe_research.io import read_json, write_json
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_plan
from vibe_research.reviewer import review_draft_plan, write_review_outputs


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
    return paths, compile_reviewed_plan(paths, read_json(outputs["reviewed_manifest"], {}))


def test_executor_rejects_missing_manifest(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0

    result = invoke("executor", "run", str(tmp_path / "missing.json"), "--target", str(tmp_path))

    assert result.exit_code == 1
    assert "execution manifest not found" in result.output


def test_executor_rejects_scientific_goal_mutation(tmp_path: Path):
    _, manifest = accepted_manifest(tmp_path)

    issues = validate_scientific_boundary(manifest, {"mechanism": "different route"})

    assert "Executor cannot modify scientific decision field: mechanism" in issues


def test_executor_missing_artifact_writes_blocker_report(tmp_path: Path):
    paths, manifest = accepted_manifest(tmp_path)
    manifest["commands"]["local"] = "python -c 'print(\"ran without artifact\")'"

    result = run_execution_manifest(paths, manifest)

    assert result["status"] == "blocked_missing_expected_artifact"
    assert result["issues"]
    assert (tmp_path / ".vibe" / "executor" / "blocker_report.md").exists()
    assert (tmp_path / ".vibe" / "executor" / "result_report.md").exists()


def test_executor_success_writes_inventory_log_and_reflector_readable_report(tmp_path: Path):
    paths, manifest = accepted_manifest(tmp_path)
    manifest_path = paths.kernel / "execution_manifest.json"
    write_json(manifest_path, manifest)

    run = invoke("executor", "run", str(manifest_path), "--target", str(tmp_path))

    assert run.exit_code == 0
    result = read_json(tmp_path / ".vibe" / "executor" / "result_manifest.json", {})
    assert result["status"] == "completed"
    assert validate_result_manifest(paths, result) == []
    assert read_json(tmp_path / ".vibe" / "executor" / "artifact_inventory.json", [])[0]["exists"] is True
    assert (tmp_path / ".vibe" / "executor" / "execution_log.jsonl").exists()
    report = (tmp_path / ".vibe" / "executor" / "result_report.md").read_text()
    assert "## Result Summary" in report
    assert "## Provenance" in report
    validate = invoke("executor", "validate-result", "--target", str(tmp_path))
    assert validate.exit_code == 0
