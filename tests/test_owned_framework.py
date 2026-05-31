from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.internalization import add_external_asset, create_framework_proposal
from vibe_research.owned import owned_contract, owned_design_audit, owned_shadow_plan, scaffold_owned_framework
from vibe_research.paths import VibePaths
from vibe_research.research_manager import add_evidence, create_experiment, create_hypothesis


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "generic owned alpha", "--background", "toy downstream repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def approved_proposal(paths: VibePaths, *, status: str = "approved") -> dict:
    hypothesis = create_hypothesis(paths, "Owned framework alpha")
    experiment = create_experiment(paths, hypothesis["hypothesis_id"], "trusted experiment")
    evidence = add_evidence(paths, experiment["experiment_id"], trusted=True, schema_valid=True, summary="trusted")
    asset = add_external_asset(
        paths,
        source="https://example.invalid/repo.git",
        title="Toy external baseline",
        purpose="baseline",
        license_or_restrictions="permissive test license",
        dependency_mode="regression_baseline",
    )
    return create_framework_proposal(
        paths,
        title="Toy owned alpha",
        hypothesis_id=hypothesis["hypothesis_id"],
        asset_id=asset["asset_id"],
        design_summary="minimal owned alpha",
        module_design="src/toy_owned/module.py",
        data_flow="same input and comparable metrics",
        metrics_schema_ref="primary",
        external_baseline_asset_id=asset["asset_id"],
        rollback_strategy="return to external baseline",
        minimal_scope="single importable framework",
        downstream_src_target="src/toy_owned",
        remaining_upside="reduce external dependency",
        trusted_evidence_ids=[evidence["evidence_id"]],
        status=status,
    )


def test_v0100_scaffold_generates_owned_alpha_and_contract(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    proposal = approved_proposal(paths)
    result = scaffold_owned_framework(paths, proposal["proposal_id"], framework_name="toy_owned")
    assert result["status"] == "created"
    assert (tmp_path / "src" / "toy_owned" / "evaluate.py").exists()
    assert (tmp_path / ".vibe" / "adapter" / "internal_capabilities" / "toy_owned-owned-eval-smoke.json").exists()
    contract = owned_contract(paths, "toy_owned")
    assert contract["passed"] is True
    assert contract["checks"]["baseline_comparison_hook"] is True


def test_v0100_scaffold_does_not_overwrite_user_code(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    proposal = approved_proposal(paths)
    existing = tmp_path / "src" / "toy_owned" / "__init__.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("# user code\n")
    result = scaffold_owned_framework(paths, proposal["proposal_id"], framework_name="toy_owned")
    assert result["status"] == "blocked"
    assert "would_overwrite:src/toy_owned/__init__.py" in result["blockers"]
    assert existing.read_text() == "# user code\n"


def test_v0100_agents_constraint_blocks_forbidden_target(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    (tmp_path / "AGENTS.md").write_text("Do not edit src/blocked_framework\n")
    proposal = approved_proposal(paths)
    result = scaffold_owned_framework(paths, proposal["proposal_id"], framework_name="blocked_framework")
    assert result["status"] == "blocked"
    assert any(item.startswith("agents_denies:src/blocked_framework") for item in result["blockers"])


def test_v0100_proposal_missing_or_unapproved_blocks_scaffold(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    proposal = approved_proposal(paths, status="proposed")
    result = scaffold_owned_framework(paths, proposal["proposal_id"], framework_name="toy_owned")
    assert result["status"] == "blocked"
    assert "framework_proposal_not_approved" in result["blockers"]


def test_v0100_shadow_plan_keeps_external_baseline(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    proposal = approved_proposal(paths)
    plan = owned_shadow_plan(paths, proposal["proposal_id"])
    assert plan["mode"] == "shadow"
    assert plan["must_not_replace_primary_path"] is True
    assert plan["external_baseline_asset_id"] == proposal["external_baseline_asset_id"]


def test_v0100_design_audit_flags_external_core_call(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    proposal = approved_proposal(paths)
    scaffold_owned_framework(paths, proposal["proposal_id"], framework_name="toy_owned")
    with (tmp_path / "src" / "toy_owned" / "evaluate.py").open("a") as handle:
        handle.write("\n# external_core_call should keep this wrapped_external\n")
    audit = owned_design_audit(paths, "toy_owned", proposal_id=proposal["proposal_id"])
    assert audit["owned_core_allowed"] is False
    assert audit["classification"] == "wrapped_external"


def test_v0100_owned_cli_roundtrip(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    proposal = approved_proposal(paths)
    result = invoke("owned", "scaffold", proposal["proposal_id"], "--target", str(tmp_path), "--framework-name", "toy_owned")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "created"
    contract = invoke("owned", "contract", "toy_owned", "--target", str(tmp_path))
    assert contract.exit_code == 0
