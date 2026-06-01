from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.convergence import close_convergence_budget, dependency_audit, freeze_check, record_override, risk_gate, set_convergence_stage, write_known_risk_review
from vibe_research.internalization import add_external_asset
from vibe_research.io import ensure_dir, read_json, write_json
from vibe_research.paths import VibePaths
from vibe_research.presentation import build_reproducibility_package
from vibe_research.research_manager import add_evidence, create_experiment, create_hypothesis


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "final convergence", "--background", "generic downstream repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def trusted_evidence(paths: VibePaths, *, protected_regression: bool = False) -> dict:
    hypothesis = create_hypothesis(paths, "Owned candidate can freeze", protected_metrics={"safety": {"direction": "max"}})
    experiment = create_experiment(paths, hypothesis["hypothesis_id"], "freeze-ready trusted evaluation")
    metrics_file = paths.runs / "run_001" / "metrics.json"
    ensure_dir(metrics_file.parent)
    write_json(metrics_file, {"primary": 0.8, "safety": 0.9})
    return add_evidence(
        paths,
        experiment["experiment_id"],
        run_id="run_001",
        trusted=True,
        schema_valid=True,
        metrics_file=str(metrics_file.relative_to(paths.root)),
        summary="trusted freeze evidence",
        metric_deltas={"primary": 0.2},
        protected_metric_regressions=[{"metric": "safety", "delta": -0.1}] if protected_regression else [],
        failure_kind="none",
    )


def make_freeze_ready(paths: VibePaths) -> None:
    trusted_evidence(paths)
    build_reproducibility_package(paths)
    close_convergence_budget(paths, rationale="budget ledger reviewed")
    write_known_risk_review(paths, "Known risks reviewed; no unresolved protected-metric risk.")


def test_v0111_freeze_blocked_without_evidence_or_reproducibility(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    result = freeze_check(paths, user_approved=True, known_risk_review="reviewed", budget_closed=True)
    assert result["accepted"] is False
    assert "missing_trusted_evidence" in result["blockers"]
    assert "missing_reproducibility_package" in result["blockers"]


def test_v0111_freeze_requires_all_gates_and_user_approval(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    make_freeze_ready(paths)
    blocked = freeze_check(paths, user_approved=False)
    assert blocked["accepted"] is False
    assert "missing_user_approval" in blocked["blockers"]
    accepted = freeze_check(paths, user_approved=True)
    assert accepted["accepted"] is True
    state = read_json(paths.research / "convergence" / "state.json", {})
    assert state["stage"] == "final_owned_freeze"
    assert state["frozen"] is True


def test_v0111_protected_metric_regression_blocks_freeze(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    trusted_evidence(paths, protected_regression=True)
    build_reproducibility_package(paths)
    close_convergence_budget(paths, rationale="closed")
    write_known_risk_review(paths, "risk reviewed")
    result = freeze_check(paths, user_approved=True)
    assert result["accepted"] is False
    assert "protected_metric_instability" in result["blockers"]


def test_v0111_late_stage_risk_gate_blocks_external_direction(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    set_convergence_stage(paths, "external_regression_only", rationale="owned candidate is focus")
    result = risk_gate(paths, change_type="new_external_method", external_method_size="large")
    assert result["decision"] == "block"
    assert "large_external_method_addition" in result["blockers"]
    assert "stage_allows_external_regression_only" in result["blockers"]


def test_v0111_user_override_unblocks_blocked_action(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    set_convergence_stage(paths, "owned_candidate_focus", rationale="late owned focus")
    override = record_override(paths, target="late core repair", reason="user accepted reproducibility reset", approved_by_user=True, scope=["core_mechanism_change"])
    result = risk_gate(paths, change_type="core_patch", core_mechanism_change=True, override_id=override["override_id"])
    assert result["decision"] == "allow"
    assert result["override_id"] == override["override_id"]
    assert result["blockers"] == []


def test_v0111_dependency_audit_classifies_final_dependencies(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    necessary = add_external_asset(paths, source="https://example.test/required", title="Required lib", purpose="dependency", license_or_restrictions="MIT", dependency_mode="required")
    regression = add_external_asset(paths, source="https://example.test/baseline", title="Baseline", purpose="baseline", license_or_restrictions="MIT", dependency_mode="regression_only")
    write_json(
        paths.vibe / "adapter" / "internal_capabilities" / "owned-core.json",
        {"capability_id": "owned-core", "status": "draft", "entrypoint": "python -m owned.evaluate", "contracts": ["metrics_export"]},
    )
    audit = dependency_audit(paths)
    by_id = {row["dependency_id"]: row for row in audit["dependencies"]}
    assert by_id[necessary["asset_id"]]["classification"] == "necessary_dependency"
    assert by_id[regression["asset_id"]]["classification"] == "regression_dependency"
    assert audit["main_path_sufficiently_owned"] is False
    assert audit["blocking_external_dependency_ids"] == [necessary["asset_id"]]


def test_v0111_converge_cli_roundtrip(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    make_freeze_ready(paths)
    check = invoke("converge", "freeze-check", "--target", str(tmp_path), "--user-approved")
    assert check.exit_code == 0
    assert json.loads(check.output)["accepted"] is True
    gate = invoke("converge", "risk-gate", "new_external_method", "--target", str(tmp_path), "--external-method-size", "large")
    assert gate.exit_code == 1
    override = invoke("converge", "override", "--target", str(tmp_path), "--target-name", "late external baseline", "--reason", "user requested comparison", "--approved-by-user", "--scope", "large_external_method_addition")
    assert override.exit_code == 0
    override_id = json.loads(override.output)["override_id"]
    gate_allowed = invoke("converge", "risk-gate", "new_external_method", "--target", str(tmp_path), "--external-method-size", "large", "--override-id", override_id)
    assert gate_allowed.exit_code == 0
    assert json.loads(gate_allowed.output)["decision"] == "allow"
