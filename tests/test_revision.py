from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.io import read_json
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_plan, write_draft_plan
from vibe_research.reviewer import review_draft_plan, write_review_outputs
from vibe_research.revision import build_revision_packet, resubmit_draft


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def base_kwargs() -> dict[str, str]:
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


def init_paths(tmp_path: Path) -> VibePaths:
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    (paths.kernel / "FAILURE_SIGNATURES.md").write_text("# Failure Signatures\n\nremote false positives persist after baseline filtering\n")
    return paths


def test_revise_creates_structured_revision_packet(tmp_path: Path):
    paths = init_paths(tmp_path)
    kwargs = base_kwargs()
    kwargs["expected_belief_update"] = "can run"
    draft = build_draft_plan(paths, **kwargs)
    review = review_draft_plan(paths, draft)

    packet = build_revision_packet(review)

    assert review["verdict"] == "REVISE"
    assert packet["failed_criteria"]
    assert "expected_belief_update" in packet["allowed_fields"]
    assert packet["evidence_gaps"] == ["belief update"]
    assert packet["resubmission_deadline"]


def test_planner_resubmits_only_requested_fields(tmp_path: Path):
    paths = init_paths(tmp_path)
    kwargs = base_kwargs()
    kwargs["expected_belief_update"] = "can run"
    draft = build_draft_plan(paths, **kwargs)
    packet = build_revision_packet(review_draft_plan(paths, draft))

    revised = resubmit_draft(
        draft,
        packet,
        {"expected_belief_update": "decide whether the component veto has mechanism evidence"},
        addressed=["weak belief update fixed"],
    )

    assert revised["plan"]["expected_belief_update"].startswith("decide whether")
    assert revised["revision_history"][0]["updated_fields"] == ["expected_belief_update"]
    assert revised["plan"]["mechanism"] == draft["plan"]["mechanism"]

    with pytest.raises(ValueError):
        resubmit_draft(draft, packet, {"mechanism": "different route"})


def test_unresolved_blocking_issue_is_rejected_again(tmp_path: Path):
    paths = init_paths(tmp_path)
    kwargs = base_kwargs()
    kwargs["mechanism"] = "generic 3D U-Net rerun"
    draft = build_draft_plan(paths, **kwargs)

    review = review_draft_plan(paths, draft)

    assert review["verdict"] == "REJECT"
    assert any(item["code"] == "generic_low_value_route" for item in review["criteria"])


def test_revision_loop_limit_asks_human(tmp_path: Path):
    paths = init_paths(tmp_path)
    kwargs = base_kwargs()
    kwargs["expected_belief_update"] = "can run"
    draft = build_draft_plan(paths, **kwargs)
    packet = build_revision_packet(review_draft_plan(paths, draft))
    revised_once = resubmit_draft(draft, packet, {"expected_belief_update": "can run"}, not_addressed=["still weak"])
    revised_twice = resubmit_draft(revised_once, packet, {"expected_belief_update": "can run"}, not_addressed=["still weak"])

    review = review_draft_plan(paths, revised_twice)

    assert review["verdict"] == "ASK_HUMAN"
    assert any(item["code"] == "revision_loop_limit" for item in review["criteria"])


def test_accepted_reviewed_manifest_carries_revision_history(tmp_path: Path):
    paths = init_paths(tmp_path)
    kwargs = base_kwargs()
    kwargs["expected_belief_update"] = "can run"
    draft = build_draft_plan(paths, **kwargs)
    write_draft_plan(paths, draft)
    packet = build_revision_packet(review_draft_plan(paths, draft))
    (paths.kernel / "revision_packet.json").write_text(__import__("json").dumps(packet))

    result = invoke(
        "planner",
        "resubmit",
        "--target",
        str(tmp_path),
        "--revision-packet",
        str(paths.kernel / "revision_packet.json"),
        "--set",
        "expected_belief_update=decide whether component veto has mechanism evidence",
        "--addressed",
        "weak belief update fixed",
    )
    assert result.exit_code == 0

    review = review_draft_plan(paths, read_json(paths.kernel / "draft_plan_manifest.json", {}))
    outputs = write_review_outputs(paths, review)
    reviewed = read_json(outputs["reviewed_manifest"], {})

    assert review["verdict"] == "ACCEPT"
    assert reviewed["revision_history"]
    assert "resubmitted_draft" in (paths.kernel / "PLAN_REVISION_REGISTRY.jsonl").read_text()
