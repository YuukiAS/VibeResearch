from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.internalization import add_external_asset, create_framework_proposal
from vibe_research.io import ensure_dir, read_json, write_json
from vibe_research.optimization import external_deemphasis_plan, plan_ablation, promote_champion
from vibe_research.paths import VibePaths
from vibe_research.presentation import build_framework_spec, build_narrative, build_presentation_package, build_reproducibility_package, export_presentation_tables
from vibe_research.research_manager import add_evidence, create_experiment, create_hypothesis, load_evidence, save_evidence, update_hypothesis
from vibe_research.scout import add_scout_finding, create_scout_claim, triage_scout_finding


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "presentation package", "--background", "generic downstream repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def trusted_run_evidence(paths: VibePaths) -> tuple[dict, dict, dict]:
    hypothesis = create_hypothesis(paths, "Owned candidate improves primary metric", target_metrics=["primary"])
    experiment = create_experiment(paths, hypothesis["hypothesis_id"], "compare owned candidate with baseline", baseline_target="baseline-a")
    metrics_file = paths.runs / "run_001" / "metrics.json"
    ensure_dir(metrics_file.parent)
    write_json(metrics_file, {"primary": 0.7, "baseline_primary": 0.6})
    evidence = add_evidence(
        paths,
        experiment["experiment_id"],
        run_id="run_001",
        trusted=True,
        schema_valid=True,
        metrics_file=str(metrics_file.relative_to(paths.root)),
        summary="owned candidate improved primary over baseline",
        metric_deltas={"primary": 0.1},
    )
    all_evidence = load_evidence(paths)
    all_evidence[evidence["evidence_id"]]["baseline_comparison"] = {"baseline": "baseline-a", "primary_delta": 0.1}
    all_evidence[evidence["evidence_id"]]["artifact_refs"] = [".vibe/runs/run_001/artifact.json"]
    save_evidence(paths, all_evidence)
    return hypothesis, experiment, all_evidence[evidence["evidence_id"]]


def test_v0110_untraceable_claim_excluded_from_final_narrative(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    _, experiment, evidence = trusted_run_evidence(paths)
    narrative = build_narrative(
        paths,
        claims=[
            {
                "claim": "primary improved with trusted evidence",
                "experiment_id": experiment["experiment_id"],
                "evidence_id": evidence["evidence_id"],
                "run_id": "run_001",
                "metrics_file": evidence["metrics_file"],
            },
            {"claim": "future larger model may improve accuracy"},
        ],
    )
    assert [row["claim"] for row in narrative["traceable_claims"]] == ["primary improved with trusted evidence"]
    assert [row["claim"] for row in narrative["speculation_or_future_work"]] == ["future larger model may improve accuracy"]
    md = (tmp_path / ".vibe" / "research" / "presentation" / "narrative.md").read_text()
    assert "primary improved with trusted evidence" in md
    assert "future larger model may improve accuracy" in md


def test_v0110_reproducibility_package_and_tables_are_traceable(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    _, _, evidence = trusted_run_evidence(paths)
    package = build_reproducibility_package(paths)
    row = package["evidence_rows"][0]
    assert row["evidence_id"] == evidence["evidence_id"]
    assert row["experiment_id"] == evidence["experiment_id"]
    assert row["run_id"] == "run_001"
    assert row["metrics_file"].endswith("metrics.json")
    assert row["adapter_revision"]
    assert row["policy_revision"]
    assert row["code_commit"]
    tables = export_presentation_tables(paths)
    baseline_rows = tables["tables"]["baseline_comparisons"]
    assert baseline_rows[0]["evidence_id"] == evidence["evidence_id"]
    assert baseline_rows[0]["baseline_comparison"]["baseline"] == "baseline-a"


def test_v0110_framework_spec_aligns_with_internal_capability(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    hypothesis, _, evidence = trusted_run_evidence(paths)
    asset = add_external_asset(paths, source="https://example.test/baseline", title="Baseline", purpose="baseline", license_or_restrictions="MIT", dependency_mode="regression_only")
    proposal = create_framework_proposal(
        paths,
        title="Owned Alpha",
        hypothesis_id=hypothesis["hypothesis_id"],
        asset_id=asset["asset_id"],
        design_summary="owned module replacing baseline core",
        module_design="src/owned_alpha",
        data_flow="features -> model -> metrics",
        interfaces=["run(config)->metrics"],
        training_entrypoint="python -m owned_alpha.train",
        evaluation_entrypoint="python -m owned_alpha.evaluate",
        metrics_schema_ref="primary",
        external_baseline_asset_id=asset["asset_id"],
        rollback_strategy="use external baseline",
        minimal_scope="evaluation only",
        downstream_src_target="src/owned_alpha",
        remaining_upside="faster iteration",
        trusted_evidence_ids=[evidence["evidence_id"]],
        status="approved",
    )
    write_json(
        paths.vibe / "adapter" / "internal_capabilities" / "owned-alpha.json",
        {
            "capability_id": "owned-alpha-eval",
            "proposal_id": proposal["proposal_id"],
            "status": "draft",
            "entrypoint": "python -m owned_alpha.evaluate",
            "contracts": ["metrics_export", "baseline_comparison"],
        },
    )
    spec = build_framework_spec(paths)
    assert spec["modules"][0]["module_id"] == proposal["proposal_id"]
    assert "features -> model -> metrics" in spec["data_flow"]
    assert "python -m owned_alpha.evaluate" in spec["evaluation_entrypoints"]
    assert spec["alignment"][0]["has_internal_capability"] is True
    assert spec["optional_external_regression"][0]["asset_id"] == asset["asset_id"]


def test_v0110_negative_results_and_transition_timeline_preserved(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    hypothesis, experiment, evidence = trusted_run_evidence(paths)
    update_hypothesis(paths, hypothesis["hypothesis_id"], {"status": "stopped", "stop_reason": "trusted negative follow-up"})
    negative = add_evidence(
        paths,
        experiment["experiment_id"],
        run_id="run_002",
        trusted=True,
        schema_valid=True,
        metrics_file=".vibe/runs/run_002/metrics.json",
        summary="protected metric regressed",
        metric_deltas={"primary": -0.2},
        protected_metric_regressions=[{"metric": "safety", "delta": -0.1}],
        failure_kind="scientific",
    )
    finding = add_scout_finding(paths, title="Negative outside result", task_match=0.9, dataset_match=0.9, metric_match=0.9, credibility=0.9, counterevidence=["regression"])
    triage_scout_finding(paths, finding["finding_id"])
    create_scout_claim(paths, claim="external result warns about regression", support_finding_ids=[finding["finding_id"]], suggested_experiment="compare owned")
    asset = add_external_asset(paths, source="https://example.test/external", title="External baseline", purpose="baseline", license_or_restrictions="MIT", dependency_mode="regression_only")
    external_deemphasis_plan(paths, proposed_external_ratio=0.2, policy_allowed=True, rationale="owned candidate has trusted comparison")
    narrative = build_narrative(paths)
    assert {row.get("kind") for row in narrative["negative_results"]} >= {"hypothesis", "evidence", "scout"}
    assert any(row.get("evidence_id") == negative["evidence_id"] for row in narrative["negative_results"])
    tables = export_presentation_tables(paths)
    timeline = tables["tables"]["external_to_owned_transition"]
    assert any(row.get("event_id") == asset["asset_id"] for row in timeline)
    assert any(row.get("event_type") == "external_deemphasis" for row in timeline)
    scout_trace = tables["tables"]["scout_to_experiment_trace"]
    assert scout_trace[0]["experiment_ids"] == [experiment["experiment_id"]]
    assert evidence["evidence_id"]


def test_v0110_present_package_cli_writes_manifest(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    trusted_run_evidence(paths)
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(json.dumps([{"claim": "traceable", "evidence_id": "ev_001"}]))
    result = invoke("present", "package", "--target", str(tmp_path), "--claims-file", str(claims_file))
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["counts"]["traceable_claims"] == 1
    assert read_json(paths.research / "presentation" / "manifest.json", {})["narrative"] == "narrative.json"
    package = build_presentation_package(paths)
    assert package["counts"]["reproducibility_rows"] == 1
