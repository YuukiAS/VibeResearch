from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.compiler import compile_reviewed_plan
from vibe_research.io import read_json
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_from_mechanism_card
from vibe_research.reviewer import review_draft_plan, write_review_outputs
from vibe_research.scout import create_mechanism_card, validate_mechanism_card


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def init_repo(tmp_path: Path) -> VibePaths:
    result = invoke("init", "--target", str(tmp_path), "--goal", "knowledge pipeline", "--background", "toy repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(tmp_path)


def card_kwargs(**overrides):
    data = {
        "source_type": "paper",
        "source": "https://example.invalid/paper",
        "claim": "Shape-aware connected components can reduce remote false positives.",
        "mechanism_extraction": "component-veto-with-shape-prior",
        "why_it_matters": "It targets the current false-positive failure anchor.",
        "failure_anchor": "remote false positives persist after baseline filtering",
        "possible_mve": "run one-case component veto MVE and save a metric artifact",
        "required_assets": ["component mask", "baseline prediction"],
        "risks": ["may over-remove true positives"],
        "stop_reason": "no component-level precision gain",
    }
    data.update(overrides)
    return data


def accepted_reviewed_from_card(paths: VibePaths, card: dict) -> dict:
    draft = build_draft_from_mechanism_card(paths, card)
    review = review_draft_plan(paths, draft)
    outputs = write_review_outputs(paths, review)
    return read_json(outputs["reviewed_manifest"], {})


def test_scout_mechanism_card_does_not_write_execution_manifest(tmp_path: Path):
    paths = init_repo(tmp_path)

    card = create_mechanism_card(paths, **card_kwargs(source_type="repo", source="https://example.invalid/repo.git"))

    assert card["card_path"].endswith("mechanism_card.md")
    assert (tmp_path / card["card_path"]).exists()
    assert not (paths.kernel / "execution_manifest.json").exists()


def test_repo_source_cli_only_generates_mechanism_card(tmp_path: Path):
    paths = init_repo(tmp_path)
    result = invoke(
        "scout",
        "mechanism-card",
        "--target",
        str(tmp_path),
        "--source-type",
        "repo",
        "--source",
        "https://example.invalid/repo.git",
        "--claim",
        card_kwargs()["claim"],
        "--mechanism-extraction",
        card_kwargs()["mechanism_extraction"],
        "--why-it-matters",
        card_kwargs()["why_it_matters"],
        "--failure-anchor",
        card_kwargs()["failure_anchor"],
        "--possible-mve",
        card_kwargs()["possible_mve"],
        "--required-asset",
        "component mask",
        "--risk",
        "may over-remove true positives",
        "--stop-reason",
        card_kwargs()["stop_reason"],
    )

    assert result.exit_code == 0
    card = json.loads(result.output)
    assert card["source_type"] == "repo"
    assert (tmp_path / card["card_path"]).name == "mechanism_card.md"
    assert not (paths.kernel / "execution_manifest.json").exists()


def test_mechanism_card_without_mve_is_archived(tmp_path: Path):
    paths = init_repo(tmp_path)

    card = create_mechanism_card(paths, **card_kwargs(possible_mve=""))

    assert card["status"] == "ARCHIVED_NO_MVE"
    assert "possible_mve is required before planning" in validate_mechanism_card(card)
    with pytest.raises(ValueError, match="possible_mve"):
        build_draft_from_mechanism_card(paths, card)


def test_valid_mechanism_card_enters_planner(tmp_path: Path):
    paths = init_repo(tmp_path)
    card = create_mechanism_card(paths, **card_kwargs())

    draft = build_draft_from_mechanism_card(paths, card)

    assert draft["source"] == f"mechanism_card:{card['card_id']}"
    assert draft["plan"]["minimum_experiment"] == card["possible_mve"]
    assert draft["plan"]["expected_belief_update"]
    assert draft["plan"]["fallback"]


def test_compiler_preserves_mechanism_card_and_rejects_clone_only(tmp_path: Path):
    paths = init_repo(tmp_path)
    card = create_mechanism_card(paths, **card_kwargs())
    reviewed = accepted_reviewed_from_card(paths, card)

    manifest = compile_reviewed_plan(paths, reviewed)

    assert card["card_path"] in manifest["input_assets"]
    assert manifest["mechanism_card"]["card_id"] == card["card_id"]

    reviewed["draft_plan"]["plan"]["minimum_experiment"] = "git clone https://example.invalid/repo.git"
    with pytest.raises(ValueError, match="clone/install"):
        compile_reviewed_plan(paths, reviewed)
