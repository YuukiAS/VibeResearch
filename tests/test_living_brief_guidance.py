from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.human_guidance import add_human_guidance
from vibe_research.io import read_json, read_jsonl
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_plan
from vibe_research.reviewer import review_draft_plan


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def init_repo(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "improve segmentation", "--background", "toy benchmark", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def test_v0203_init_idea_writes_human_guidance_and_living_brief(tmp_path: Path):
    result = invoke(
        "init",
        "--target",
        str(tmp_path),
        "--goal",
        "improve segmentation",
        "--background",
        "toy benchmark",
        "--idea",
        "CenterC false positives may need a component-level verifier",
        "--no-root-portal",
    )

    assert result.exit_code == 0
    guidance = read_jsonl(tmp_path / ".vibe" / "research" / "human_guidance.jsonl")
    assert guidance[-1]["status"] == "ACTIVE"
    assert guidance[-1]["priority"] == "high"
    assert "component-level verifier" in (tmp_path / ".vibe" / "research" / "HUMAN_IDEA_INBOX.md").read_text()
    assert (tmp_path / ".vibe" / "research" / "CURRENT_RESEARCH_BRIEF.zh.md").exists()
    assert (tmp_path / ".vibe" / "research" / "CURRENT_RESEARCH_BRIEF.en.md").exists()
    brief = read_json(tmp_path / ".vibe" / "research" / "research_brief.json", {})
    assert brief["brief_language"] == "zh"
    assert brief["sections"]["project_goal"] == "improve segmentation"


def test_v0203_planner_and_reviewer_gate_active_human_guidance(tmp_path: Path):
    paths = init_repo(tmp_path)
    add_human_guidance(
        paths,
        "Prioritize a component verifier for CenterC false positives.",
        linked_failure_signature="CenterC false positives",
        suggested_mechanism="component verifier",
    )

    draft = build_draft_plan(
        paths,
        mode="recombine",
        failure_anchor="generic calibration drift",
        hypothesis="a generic calibration postprocess may help",
        mechanism="histogram calibration",
        minimum_experiment="run one-case calibration MVE",
        expected_artifact=".vibe/runs/generic/metrics.json",
        expected_belief_update="decide whether calibration helps",
        compute_cost="local cpu",
        risk="may not target the user guidance",
        fallback="archive",
        stop_condition="no metric evidence",
        confidence="speculative_mechanism",
    )

    assert any(item["code"] == "human_guidance_unaddressed" for item in draft["diagnostics"])
    review = review_draft_plan(paths, draft)
    assert review["verdict"] == "REVISE"
    assert any(item["code"] == "human_guidance_not_addressed" for item in review["criteria"])

    addressed = build_draft_plan(
        paths,
        mode="recombine",
        failure_anchor="CenterC false positives",
        hypothesis="a component verifier can reduce CenterC false positives",
        mechanism="component verifier",
        minimum_experiment="run one-case component verifier MVE",
        expected_artifact=".vibe/runs/component_verifier/metrics.json",
        expected_belief_update="decide whether component verifier reduces CenterC false positives",
        compute_cost="local cpu",
        risk="may reduce recall",
        fallback="archive verifier route",
        stop_condition="no precision gain",
        confidence="speculative_mechanism",
    )
    assert any(item["status"] == "absorbed" for item in addressed["human_guidance_considered"])
    addressed_review = review_draft_plan(paths, addressed)
    assert not any(item["code"] == "human_guidance_not_addressed" for item in addressed_review["criteria"])


def test_v0203_guidance_and_brief_cli(tmp_path: Path):
    paths = init_repo(tmp_path)

    added = invoke(
        "guidance",
        "add",
        "T2 alignment is probably the core uncertainty.",
        "--target",
        str(tmp_path),
        "--language",
        "en",
        "--priority",
        "high",
    )
    assert added.exit_code == 0
    payload = json.loads(added.output)
    assert payload["language"] == "en"

    reviewed = invoke("guidance", "review", payload["guidance_id"], "--target", str(tmp_path), "--status", "NEEDS_MORE_EVIDENCE", "--notes", "needs metric evidence")
    assert reviewed.exit_code == 0
    listed = invoke("guidance", "list", "--target", str(tmp_path), "--status", "NEEDS_MORE_EVIDENCE")
    assert payload["guidance_id"] in listed.output

    brief = invoke("brief", "update", "--target", str(paths.root), "--language", "en")
    assert brief.exit_code == 0
    brief_payload = json.loads(brief.output)
    assert brief_payload["preferred_language"] == "en"
    assert (tmp_path / ".vibe" / "research" / "CURRENT_RESEARCH_BRIEF.en.md").exists()
