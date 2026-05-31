from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.dual_track import create_track_experiment, parallel_comparison_plan, track_budget_audit, track_memo, track_transition_audit
from vibe_research.io import write_yaml
from vibe_research.paths import VibePaths
from vibe_research.research_manager import add_evidence, create_experiment, create_hypothesis


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "generic dual track", "--background", "toy downstream repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def experiment_with_evidence(paths: VibePaths) -> tuple[str, str]:
    hypothesis = create_hypothesis(paths, "Dual-track toy hypothesis")
    experiment = create_experiment(paths, hypothesis["hypothesis_id"], "toy experiment")
    evidence = add_evidence(paths, experiment["experiment_id"], trusted=True, schema_valid=True, summary="trusted")
    return experiment["experiment_id"], evidence["evidence_id"]


def test_v092_external_internal_hybrid_track_creation(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    exp1, ev1 = experiment_with_evidence(paths)
    exp2, ev2 = experiment_with_evidence(paths)
    exp3, ev3 = experiment_with_evidence(paths)
    external = create_track_experiment(paths, experiment_id=exp1, track="external", resource_units={"gpu_hours": 1})
    internal = create_track_experiment(paths, experiment_id=exp2, track="internal", internalization_level="shadow_internal", external_baseline_asset_id="asset_001", metrics_comparable=True, design_diff={"module": "changed"}, trusted_evidence_ids=[ev2])
    hybrid = create_track_experiment(paths, experiment_id=exp3, track="hybrid", internalization_level="hybrid_internal", external_baseline_asset_id="asset_001", metrics_comparable=True, design_diff={"pipeline": "combined"}, trusted_evidence_ids=[ev3])
    assert external["track"] == "external"
    assert internal["track"] == "internal"
    assert hybrid["track"] == "hybrid"


def test_v092_internal_missing_baseline_or_design_diff_blocks_promotion(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    experiment_id, evidence_id = experiment_with_evidence(paths)
    record = create_track_experiment(paths, experiment_id=experiment_id, track="internal", trusted_evidence_ids=[evidence_id], metrics_comparable=True)
    audit = track_transition_audit(paths, record["track_record_id"], target_level="hybrid_internal")
    assert audit["can_transition"] is False
    assert "missing_external_baseline" in audit["blockers"]
    assert "missing_external_to_internal_design_diff" in audit["blockers"]


def test_v092_shadow_internal_warns_and_comparison_plan_requires_baseline(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    experiment_id, evidence_id = experiment_with_evidence(paths)
    record = create_track_experiment(paths, experiment_id=experiment_id, track="internal", internalization_level="shadow_internal", external_baseline_asset_id="asset_001", metrics_comparable=True, design_diff={"loss": "changed"}, trusted_evidence_ids=[evidence_id])
    audit = track_transition_audit(paths, record["track_record_id"], target_level="shadow_internal")
    plan = parallel_comparison_plan(paths, record["track_record_id"])
    assert audit["can_transition"] is True
    assert "shadow_internal_may_run_but_must_not_replace_external_baseline_by_default" in audit["warnings"]
    assert plan["required"] is True
    assert plan["blocked"] is False


def test_v092_protected_metric_regression_and_pseudo_internalization_block(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    experiment_id, evidence_id = experiment_with_evidence(paths)
    record = create_track_experiment(
        paths,
        experiment_id=experiment_id,
        track="internal",
        internalization_level="shadow_internal",
        external_baseline_asset_id="asset_001",
        metrics_comparable=True,
        design_diff={"wrapper": "thin"},
        protected_metric_gate={"passed": False, "reason": "protected regression"},
        trusted_evidence_ids=[evidence_id],
        pseudo_internalization=True,
        pseudo_internalization_reason="only wraps external core",
    )
    audit = track_transition_audit(paths, record["track_record_id"], target_level="hybrid_internal")
    assert "protected_metric_regression" in audit["blockers"]
    assert "pseudo_internalization_detected" in audit["blockers"]


def test_v092_track_budget_ratio_blocks_overallocated_track(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    write_yaml(paths.policies / "track_budget.yaml", {"max_ratio": {"internal": 0.25}})
    exp1, _ = experiment_with_evidence(paths)
    exp2, _ = experiment_with_evidence(paths)
    create_track_experiment(paths, experiment_id=exp1, track="external", resource_units={"gpu_hours": 1})
    create_track_experiment(paths, experiment_id=exp2, track="internal", resource_units={"gpu_hours": 3})
    audit = track_budget_audit(paths)
    assert "internal" in audit["blocked_tracks"]


def test_v092_track_memo_renders_parallel_tracks(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    experiment_id, evidence_id = experiment_with_evidence(paths)
    record = create_track_experiment(paths, experiment_id=experiment_id, track="internal", external_baseline_asset_id="asset_001", metrics_comparable=True, design_diff={"module": "changed"}, trusted_evidence_ids=[evidence_id])
    track_transition_audit(paths, record["track_record_id"], target_level="shadow_internal")
    memo = track_memo(paths)
    text = (tmp_path / ".vibe" / "research" / "tracks" / "memo.md").read_text()
    assert "External Track" in text
    assert "Internal Track" in text
    assert "Hybrid Track" in text
    assert memo["by_track"]["internal"][0]["track_record_id"] == record["track_record_id"]


def test_v092_track_cli_roundtrip(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    experiment_id, evidence_id = experiment_with_evidence(paths)
    result = invoke(
        "portfolio",
        "track-plan",
        experiment_id,
        "--target",
        str(tmp_path),
        "--track",
        "internal",
        "--internalization-level",
        "shadow_internal",
        "--external-baseline-asset-id",
        "asset_001",
        "--metrics-comparable",
        "--design-diff",
        "module changed",
        "--trusted-evidence-id",
        evidence_id,
        "--gpu-hours",
        "1.5",
    )
    assert result.exit_code == 0
    record = json.loads(result.output)
    assert record["track"] == "internal"
    audit = invoke("portfolio", "track-audit", record["track_record_id"], "--target", str(tmp_path), "--target-level", "shadow_internal")
    assert audit.exit_code == 0
