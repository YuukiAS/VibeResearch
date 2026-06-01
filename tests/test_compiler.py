from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.compiler import compile_reviewed_plan, validate_execution_manifest
from vibe_research.io import read_json
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


def accepted_reviewed_manifest(tmp_path: Path, **overrides: str) -> tuple[VibePaths, dict]:
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    (paths.kernel / "FAILURE_SIGNATURES.md").write_text("# Failure Signatures\n\nremote false positives persist after baseline filtering\n")
    kwargs = plan_kwargs()
    kwargs.update(overrides)
    draft = build_draft_plan(paths, **kwargs)
    review = review_draft_plan(paths, draft)
    outputs = write_review_outputs(paths, review)
    return paths, read_json(outputs["reviewed_manifest"], {})


def test_compiler_requires_accepted_review_approval(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    rejected = {"review": {"verdict": "REJECT", "allow_compiler": False}, "draft_plan": {}}

    with pytest.raises(ValueError, match="review approval"):
        compile_reviewed_plan(paths, rejected)


def test_compiler_rejects_missing_concrete_artifact_or_metric_reader(tmp_path: Path):
    paths, reviewed = accepted_reviewed_manifest(tmp_path, expected_artifact="artifact-without-reader")

    with pytest.raises(ValueError, match="concrete repo-local path"):
        compile_reviewed_plan(paths, reviewed)

    paths, reviewed = accepted_reviewed_manifest(tmp_path / "repo2", expected_artifact=".vibe/runs/r001/artifact.bin")
    with pytest.raises(ValueError, match="metric reader"):
        compile_reviewed_plan(paths, reviewed)


def test_compiler_preserves_reviewer_constraints(tmp_path: Path):
    paths, reviewed = accepted_reviewed_manifest(tmp_path)

    manifest = compile_reviewed_plan(paths, reviewed)

    assert manifest["safety_checks"]["review_verdict"] == "ACCEPT"
    assert manifest["safety_checks"]["reviewer_criteria"]
    assert manifest["review_approval_id"] == reviewed["review"]["created_at"]
    assert manifest["expected_artifacts"] == [".vibe/runs/r001/component_veto_metrics.json"]


def test_compiler_cli_writes_valid_execution_package(tmp_path: Path):
    paths, _ = accepted_reviewed_manifest(tmp_path)

    result = invoke("compiler", "compile", "--target", str(tmp_path))

    assert result.exit_code == 0
    manifest_path = paths.kernel / "execution_manifest.json"
    manifest = read_json(manifest_path, {})
    assert validate_execution_manifest(manifest) == []
    assert (tmp_path / ".vibe" / "executor" / "scripts" / "component-veto-with-shape-prior.sh").exists()
    validate = invoke("compiler", "validate", str(manifest_path))
    assert validate.exit_code == 0
