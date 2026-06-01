from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.io import read_json
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_plan, write_draft_plan
from vibe_research.reviewer import review_draft_plan, write_review_outputs


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def reviewable_kwargs() -> dict[str, str]:
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


def init_with_failure_signature(tmp_path: Path) -> VibePaths:
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    (paths.kernel / "FAILURE_SIGNATURES.md").write_text("# Failure Signatures\n\nremote false positives persist after baseline filtering\n")
    return paths


def test_reviewer_rejects_generic_unet_plan(tmp_path: Path):
    paths = init_with_failure_signature(tmp_path)
    kwargs = reviewable_kwargs()
    kwargs["mechanism"] = "generic 3D U-Net rerun"
    kwargs["hypothesis"] = "another U-Net may improve the result"
    draft = build_draft_plan(paths, **kwargs)

    review = review_draft_plan(paths, draft)

    assert review["verdict"] == "REJECT"
    assert any(item["code"] == "generic_low_value_route" for item in review["criteria"])


def test_reviewer_rejects_metadata_only_smoke(tmp_path: Path):
    paths = init_with_failure_signature(tmp_path)
    kwargs = reviewable_kwargs()
    kwargs["minimum_experiment"] = "metadata import smoke only"
    kwargs["expected_artifact"] = "smoke"
    draft = build_draft_plan(paths, **kwargs)

    review = review_draft_plan(paths, draft)

    assert review["verdict"] == "REJECT"
    assert any(item["code"] == "metadata_or_smoke_only" for item in review["criteria"])


def test_reviewer_accepts_new_mechanism_with_mve(tmp_path: Path):
    paths = init_with_failure_signature(tmp_path)
    draft = build_draft_plan(paths, **reviewable_kwargs())
    write_draft_plan(paths, draft)

    result = invoke("reviewer", "review", "--target", str(tmp_path))

    assert result.exit_code == 0
    reviewed = read_json(paths.kernel / "reviewed_plan_manifest.json", {})
    assert reviewed["review"]["verdict"] == "ACCEPT"
    assert reviewed["draft_plan"]["plan"]["expected_belief_update"]
    assert (paths.kernel / "plan_review_report.md").exists()


def test_reviewer_asks_human_for_safety_risk(tmp_path: Path):
    paths = init_with_failure_signature(tmp_path)
    kwargs = reviewable_kwargs()
    kwargs["risk"] = "may require upload to hosted validation before review"
    draft = build_draft_plan(paths, **kwargs)

    review = review_draft_plan(paths, draft)
    outputs = write_review_outputs(paths, review)

    assert review["verdict"] == "ASK_HUMAN"
    assert outputs["reviewed_manifest"] is None
    assert not (paths.kernel / "reviewed_plan_manifest.json").exists()


def test_review_report_is_traceable(tmp_path: Path):
    paths = init_with_failure_signature(tmp_path)
    draft = build_draft_plan(paths, **reviewable_kwargs())
    review = review_draft_plan(paths, draft)
    outputs = write_review_outputs(paths, review)

    report = outputs["report"].read_text()
    assert "Verdict: ACCEPT" in report
    assert "Evidence records checked" in report
    assert "Negative memory checked: true" in report
    assert "Failure signatures checked: true" in report
    registry = (paths.kernel / "PLAN_REVIEW_REGISTRY.jsonl").read_text()
    assert "ACCEPT" in registry
