from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.internalization import (
    add_external_asset,
    build_lineage_memory,
    create_framework_proposal,
    internalization_readiness,
)
from vibe_research.io import append_jsonl, read_json
from vibe_research.paths import VibePaths
from vibe_research.research_manager import add_evidence, create_experiment, create_hypothesis


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "generic owned framework", "--background", "toy downstream repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def trusted_evidence(paths: VibePaths) -> tuple[str, str]:
    hypothesis = create_hypothesis(paths, "Improve generic evidence flow", rationale="toy hypothesis")
    experiment = create_experiment(paths, hypothesis["hypothesis_id"], "toy experiment", stage="smoke")
    evidence = add_evidence(paths, experiment["experiment_id"], trusted=True, schema_valid=True, summary="trusted toy evidence")
    return hypothesis["hypothesis_id"], evidence["evidence_id"]


def test_v090_external_asset_registry_and_relation_cli(tmp_path: Path):
    initialized_paths(tmp_path)
    result = invoke(
        "lineage",
        "add-external-asset",
        "--target",
        str(tmp_path),
        "--source",
        "https://example.invalid/repo.git",
        "--title",
        "Toy external baseline",
        "--purpose",
        "baseline",
        "--license",
        "permissive test license",
        "--dependency-mode",
        "reference",
    )
    assert result.exit_code == 0
    asset = json.loads(result.output)
    assert asset["asset_id"] == "asset_001"
    assert asset["purpose"] == "baseline"

    link = invoke(
        "lineage",
        "link",
        "--target",
        str(tmp_path),
        "--source-id",
        asset["asset_id"],
        "--target-id",
        "hyp_001",
        "--relation-type",
        "supports",
    )
    assert link.exit_code == 0
    relation = json.loads(link.output)
    assert relation["source_id"] == "asset_001"
    assert relation["target_id"] == "hyp_001"


def test_v090_readiness_blocks_without_trusted_evidence_or_baseline_source(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    hypothesis_id, _evidence_id = trusted_evidence(paths)
    append_jsonl(
        paths.research / "lineage" / "external_assets.jsonl",
        {
            "asset_id": "asset_999",
            "source": "",
            "title": "Broken external asset",
            "purpose": "baseline",
            "license_or_restrictions": "",
            "dependency_mode": "reference",
            "current_internalization_level": "external_only",
        },
    )
    proposal = create_framework_proposal(
        paths,
        title="Broken proposal",
        hypothesis_id=hypothesis_id,
        asset_id="asset_999",
        design_summary="toy design",
        module_design="toy module",
        data_flow="toy data flow",
        metrics_schema_ref="primary",
        external_baseline_asset_id="asset_999",
        rollback_strategy="revert to external baseline",
        minimal_scope="one module",
        downstream_src_target="src/toy_framework",
        remaining_upside="could reduce dependency",
        trusted_evidence_ids=[],
    )
    audit = internalization_readiness(paths, proposal["proposal_id"])
    assert audit["can_transition"] is False
    assert "missing_trusted_or_qualifying_scout_evidence" in audit["blockers"]
    assert "external_baseline_missing_source" in audit["blockers"]
    assert "asset_999:missing_source" in audit["blockers"]


def test_v090_readiness_passes_with_trusted_evidence_and_keeps_baseline(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    hypothesis_id, evidence_id = trusted_evidence(paths)
    asset = add_external_asset(
        paths,
        source="https://example.invalid/repo.git",
        title="Toy external baseline",
        purpose="baseline",
        license_or_restrictions="permissive test license",
        dependency_mode="regression_baseline",
        replacement_plan="shadow internal candidate must compare against this baseline",
    )
    proposal = create_framework_proposal(
        paths,
        title="Toy owned shadow module",
        hypothesis_id=hypothesis_id,
        asset_id=asset["asset_id"],
        design_summary="internal shadow equivalent with explicit comparison",
        module_design="src/toy_framework/module.py",
        data_flow="same input, comparable output",
        metrics_schema_ref="primary",
        external_baseline_asset_id=asset["asset_id"],
        rollback_strategy="disable internal shadow and keep external baseline",
        minimal_scope="single importable module",
        downstream_src_target="src/toy_framework",
        remaining_upside="remove brittle wrapper",
        trusted_evidence_ids=[evidence_id],
        status="approved",
    )
    result = invoke("internalization", "readiness", proposal["proposal_id"], "--target", str(tmp_path))
    assert result.exit_code == 0
    audit = json.loads(result.output)
    assert audit["can_transition"] is True
    assert audit["blockers"] == []
    assert audit["proposal"]["external_baseline_asset_id"] == asset["asset_id"]


def test_v090_internalization_decision_and_lineage_memory(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    asset = add_external_asset(
        paths,
        source="https://example.invalid/repo.git",
        title="Toy dependency",
        purpose="temporary_wrapper",
        license_or_restrictions="permissive test license",
        dependency_mode="active_wrapper",
        replacement_plan="replace with reviewed internal module",
    )
    decision = invoke(
        "internalization",
        "decision",
        "--target",
        str(tmp_path),
        "--internalize-what",
        "toy wrapper idea",
        "--why-now",
        "trusted evidence and remaining upside",
        "--expected-benefit",
        "clearer owned interface",
        "--downstream-src-target",
        "src/toy_framework",
        "--baseline-comparison",
        asset["asset_id"],
        "--rollback-plan",
        "return to external wrapper",
        "--asset-id",
        asset["asset_id"],
        "--risk",
        "parity failure",
    )
    assert decision.exit_code == 0
    data = json.loads(decision.output)
    assert data["risks"] == ["parity failure"]

    memory = build_lineage_memory(paths)
    assert memory["external_dependencies"][0]["asset_id"] == asset["asset_id"]
    memory_path = tmp_path / ".vibe" / "research" / "lineage" / "memory.md"
    assert "Toy dependency" in memory_path.read_text()
    assert read_json(tmp_path / ".vibe" / "research" / "lineage" / "memory.json", {})["decisions"][0]["asset_id"] == asset["asset_id"]
