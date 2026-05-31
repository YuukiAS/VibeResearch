from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.internalization import add_external_asset, create_framework_proposal, internalization_readiness
from vibe_research.paths import VibePaths
from vibe_research.research_manager import create_hypothesis
from vibe_research.scout import add_scout_finding, create_scout_claim, scout_audit, scout_query_context, triage_scout_finding


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "generic scout", "--background", "toy downstream repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def test_v091_generic_paper_is_background_not_actionable(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    finding = add_scout_finding(
        paths,
        title="Broad overview paper",
        task_match=0.45,
        dataset_match=0.15,
        metric_match=0.2,
        method_match=0.25,
        failure_mode_match=0.1,
        actionability=0.2,
        novelty=0.4,
        credibility=0.7,
        summary="Useful context but no concrete experiment.",
    )
    triage = triage_scout_finding(paths, finding["finding_id"])
    assert triage["category"] == "background"
    assert triage["allowed_for_experiment"] is False


def test_v091_specific_reproducible_finding_is_implementation_reference(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    finding = add_scout_finding(
        paths,
        title="Specific failure-mode method with code",
        task_match=0.9,
        dataset_match=0.75,
        metric_match=0.8,
        method_match=0.9,
        failure_mode_match=0.85,
        actionability=0.8,
        novelty=0.6,
        credibility=0.9,
        has_code=True,
        reproducible_experiment=True,
        relationship_to_hypothesis="implementation reference",
    )
    triage = triage_scout_finding(paths, finding["finding_id"])
    assert triage["category"] == "implementation_reference"
    assert triage["allowed_for_experiment"] is True


def test_v091_strong_no_code_method_evidence_is_candidate_method(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    finding = add_scout_finding(
        paths,
        title="Strong method evidence without code",
        task_match=0.82,
        dataset_match=0.72,
        metric_match=0.78,
        method_match=0.82,
        failure_mode_match=0.74,
        actionability=0.55,
        novelty=0.8,
        credibility=0.9,
        has_code=False,
        reproducible_experiment=False,
    )
    triage = triage_scout_finding(paths, finding["finding_id"])
    assert triage["category"] == "candidate_method"
    assert triage["allowed_for_experiment"] is False


def test_v091_claim_map_negative_evidence_and_audit_memo(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    finding = add_scout_finding(
        paths,
        title="Method harms protected metric",
        task_match=0.8,
        dataset_match=0.7,
        metric_match=0.8,
        method_match=0.8,
        failure_mode_match=0.85,
        actionability=0.65,
        novelty=0.5,
        credibility=0.85,
        relationship_to_hypothesis="negative evidence",
        counterevidence=["similar task reported protected metric regression"],
    )
    triage = triage_scout_finding(paths, finding["finding_id"])
    claim = create_scout_claim(
        paths,
        claim="The method may improve the primary metric while harming a protected metric.",
        support_finding_ids=[],
        oppose_finding_ids=[finding["finding_id"]],
        applicability="similar failure mode",
        transfer_limits="requires protected metric guard",
        suggested_experiment="only test with explicit rollback",
        confidence=0.8,
    )
    audit = scout_audit(paths)
    assert triage["category"] == "negative_evidence"
    assert claim["claim_id"] == "claim_001"
    assert audit["negative_evidence_count"] == 1
    assert "Negative evidence records: `1`" in (tmp_path / ".vibe" / "research" / "scout" / "memo.md").read_text()


def test_v091_query_context_uses_hypothesis_memory(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    hypothesis = create_hypothesis(paths, "Reduce repeated false positives", target_metrics=["primary"])
    result = scout_query_context(paths)
    assert result["hypotheses"][0]["hypothesis_id"] == hypothesis["hypothesis_id"]
    assert "Reduce repeated false positives" in result["hypotheses"][0]["query_seed"]


def test_v091_scout_evidence_supports_shadow_internal_but_warns(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    hypothesis = create_hypothesis(paths, "Internalize a generic module")
    asset = add_external_asset(
        paths,
        source="https://example.invalid/repo.git",
        title="Toy baseline",
        purpose="baseline",
        license_or_restrictions="permissive test license",
        dependency_mode="reference",
    )
    finding = add_scout_finding(
        paths,
        title="Specific implementation reference",
        task_match=0.9,
        dataset_match=0.8,
        metric_match=0.8,
        method_match=0.9,
        failure_mode_match=0.9,
        actionability=0.8,
        novelty=0.7,
        credibility=0.9,
        has_code=True,
        reproducible_experiment=True,
    )
    triage_scout_finding(paths, finding["finding_id"])
    proposal = create_framework_proposal(
        paths,
        title="Scout-supported shadow module",
        hypothesis_id=hypothesis["hypothesis_id"],
        asset_id=asset["asset_id"],
        design_summary="shadow implementation from scout evidence",
        module_design="src/toy/module.py",
        data_flow="same input, comparable output",
        metrics_schema_ref="primary",
        external_baseline_asset_id=asset["asset_id"],
        rollback_strategy="keep external baseline",
        minimal_scope="one module",
        downstream_src_target="src/toy",
        remaining_upside="reduce external dependency",
        scout_evidence_ids=[finding["finding_id"]],
    )
    audit = internalization_readiness(paths, proposal["proposal_id"])
    assert audit["can_transition"] is True
    assert "scout_evidence_supports_shadow_internal_but_does_not_replace_project_experiment_evidence" in audit["warnings"]


def test_v091_scout_cli_roundtrip(tmp_path: Path):
    initialized_paths(tmp_path)
    result = invoke(
        "scout",
        "add-finding",
        "--target",
        str(tmp_path),
        "--title",
        "CLI actionable finding",
        "--task-match",
        "0.9",
        "--dataset-match",
        "0.8",
        "--metric-match",
        "0.8",
        "--method-match",
        "0.9",
        "--failure-mode-match",
        "0.8",
        "--actionability",
        "0.8",
        "--credibility",
        "0.9",
        "--has-code",
    )
    assert result.exit_code == 0
    finding = json.loads(result.output)
    triage = invoke("scout", "triage", finding["finding_id"], "--target", str(tmp_path))
    assert triage.exit_code == 0
    assert json.loads(triage.output)["category"] == "implementation_reference"
