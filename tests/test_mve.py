from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.compiler import compile_reviewed_plan
from vibe_research.io import read_json
from vibe_research.mve import promotion_debt_for_success, validate_mve_completion, validate_mve_contract
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_plan
from vibe_research.reviewer import review_draft_plan, write_review_outputs


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def reviewed_manifest(tmp_path: Path, **overrides: str) -> tuple[VibePaths, dict]:
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    (paths.kernel / "FAILURE_SIGNATURES.md").write_text("# Failure Signatures\n\nremote false positives persist after baseline filtering\n")
    plan = {
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
    plan.update(overrides)
    draft = build_draft_plan(paths, **plan)
    outputs = write_review_outputs(paths, review_draft_plan(paths, draft))
    return paths, read_json(outputs["reviewed_manifest"], {})


def test_execution_manifest_without_mve_is_rejected():
    manifest = {
        "session_role": "compiler",
        "accepted_plan_id": "plan",
        "review_approval_id": "review",
        "expected_artifacts": [".vibe/runs/r001/metrics.json"],
        "evaluation_commands": [{"reader": "json"}],
        "stop_conditions": ["negative evidence"],
        "fallbacks": [{"command": "echo fallback"}],
        "safety_checks": {"review_verdict": "ACCEPT", "allow_compiler": True},
    }

    assert "mve_contract is required" in validate_mve_contract(manifest)


def test_one_case_success_generates_subset_debt(tmp_path: Path):
    paths, reviewed = reviewed_manifest(tmp_path)
    manifest = compile_reviewed_plan(paths, reviewed)

    debt = promotion_debt_for_success(manifest)

    assert debt["current_level"] == "component_dataset"
    assert "subset" in debt["next_debt"]
    assert debt["must_not_declare_mainline_success"] is True


def test_big_training_requires_mve_or_human_approval():
    manifest = {
        "safety_checks": {"review_verdict": "ACCEPT", "allow_compiler": True},
        "mve_contract": {},
        "commands": {"local": "large training 5-fold"},
    }
    assert validate_mve_contract(manifest) == ["mve_contract is required"]
    manifest["safety_checks"]["user_approved_mve_exception"] = True
    assert validate_mve_contract(manifest) == []


def test_missing_mve_artifact_cannot_close_execution(tmp_path: Path):
    paths, reviewed = reviewed_manifest(tmp_path)
    manifest = compile_reviewed_plan(paths, reviewed)

    issues = validate_mve_completion(tmp_path, manifest)

    assert any("MVE artifact missing" in issue for issue in issues)


def test_mve_cli_validates_and_records_promotion_debt(tmp_path: Path):
    paths, reviewed = reviewed_manifest(tmp_path)
    manifest = compile_reviewed_plan(paths, reviewed)
    manifest_path = paths.kernel / "execution_manifest.json"
    from vibe_research.io import write_json

    write_json(manifest_path, manifest)
    assert invoke("mve", "validate", str(manifest_path), "--target", str(tmp_path)).exit_code == 0
    result = invoke("mve", "promote-success", str(manifest_path), "--target", str(tmp_path))
    assert result.exit_code == 0
    debt = read_json(tmp_path / ".vibe" / "kernel" / "mve_promotion_debt.json", {})
    assert debt["source"] == "mve_success"
