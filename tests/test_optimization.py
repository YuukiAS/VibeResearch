from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.optimization import external_deemphasis_plan, plan_ablation, promote_champion, record_optimization_memory, record_regression_suite, register_challenger
from vibe_research.paths import VibePaths
from vibe_research.research_manager import add_evidence, create_experiment, create_hypothesis


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "generic optimization", "--background", "toy downstream repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def trusted_evidence(paths: VibePaths) -> str:
    hypothesis = create_hypothesis(paths, "Champion candidate")
    experiment = create_experiment(paths, hypothesis["hypothesis_id"], "trusted experiment")
    evidence = add_evidence(paths, experiment["experiment_id"], trusted=True, schema_valid=True, summary="trusted")
    return evidence["evidence_id"]


def test_v0101_champion_promotion_requires_trusted_evidence_and_policy(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    blocked = promote_champion(paths, stage="shadow", candidate_id="owned-a", budget_policy_ok=True, rationale="good")
    assert blocked["promoted"] is False
    assert "missing_trusted_evidence" in blocked["blockers"]
    evidence_id = trusted_evidence(paths)
    promoted = promote_champion(paths, stage="shadow", candidate_id="owned-a", evidence_ids=[evidence_id], protected_metric_gate={"passed": True}, budget_policy_ok=True, rationale="trusted evidence")
    assert promoted["promoted"] is True
    challenger = register_challenger(paths, stage="shadow", candidate_id="owned-b", against_champion_id="owned-a", rationale="try bounded improvement")
    assert challenger["challenger_id"] == "challenger_001"


def test_v0101_protected_metric_regression_blocks_champion(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    evidence_id = trusted_evidence(paths)
    result = promote_champion(paths, stage="shadow", candidate_id="owned-a", evidence_ids=[evidence_id], protected_metric_gate={"passed": False}, budget_policy_ok=True, rationale="primary improved")
    assert result["promoted"] is False
    assert "protected_metric_regression" in result["blockers"]


def test_v0101_ablation_requires_hypothesis_and_records_memory_warning(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    record_optimization_memory(paths, ablation_key="remove-postprocess", outcome="failed", rationale="hurt protected metric")
    ablation = plan_ablation(paths, candidate_id="owned-a", ablation_key="remove-postprocess", hypothesis="test smaller postprocess", expected_effect="reduce false positives", metrics_target="primary", protected_metric_risk="boundary metric may regress", rollback_plan="restore postprocess")
    assert ablation["memory_warning"] == "repeated_failed_ablation_requires_new_rationale"
    with pytest.raises(ValueError):
        plan_ablation(paths, candidate_id="owned-a", ablation_key="bad", hypothesis="", expected_effect="x", metrics_target="primary", protected_metric_risk="risk", rollback_plan="rollback")


def test_v0101_regression_failure_blocks_larger_stage(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    result = record_regression_suite(paths, candidate_id="owned-a", stage="shadow", checks={"smoke": True, "metrics_schema": True, "artifact_output": False, "protected_metrics": True, "champion_comparison": True})
    assert result["passed"] is False
    assert result["blocks_larger_stage"] is True


def test_v0101_external_deemphasis_requires_policy_and_periodic_regression(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    blocked = external_deemphasis_plan(paths, proposed_external_ratio=0.2, policy_allowed=False, rationale="owned improving", keep_periodic_regression=True)
    assert blocked["approved"] is False
    assert "policy_does_not_allow_external_deemphasis" in blocked["blockers"]
    blocked_drop = external_deemphasis_plan(paths, proposed_external_ratio=0.2, policy_allowed=True, rationale="owned improving", keep_periodic_regression=False)
    assert "external_baseline_regression_must_remain_scheduled" in blocked_drop["blockers"]
    approved = external_deemphasis_plan(paths, proposed_external_ratio=0.2, policy_allowed=True, rationale="owned improving", keep_periodic_regression=True)
    assert approved["approved"] is True


def test_v0101_optimize_cli_roundtrip(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    evidence_id = trusted_evidence(paths)
    champion = invoke(
        "optimize",
        "champion",
        "--target",
        str(tmp_path),
        "--stage",
        "shadow",
        "--candidate-id",
        "owned-a",
        "--evidence-id",
        evidence_id,
        "--budget-policy-ok",
        "--rationale",
        "trusted evidence",
    )
    assert champion.exit_code == 0
    assert json.loads(champion.output)["promoted"] is True
    regression = invoke("optimize", "regression", "--target", str(tmp_path), "--candidate-id", "owned-a", "--stage", "shadow")
    assert regression.exit_code == 0
