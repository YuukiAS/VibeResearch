from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.compiler import compile_reviewed_plan
from vibe_research.io import read_json, read_jsonl
from vibe_research.knowledge_lifecycle import advance_knowledge_ttl, load_latest_knowledge, orphan_audit, record_knowledge_event
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_from_mechanism_card
from vibe_research.reviewer import review_draft_plan, write_review_outputs
from vibe_research.scout import create_mechanism_card


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def init_repo(tmp_path: Path) -> VibePaths:
    result = invoke("init", "--target", str(tmp_path), "--goal", "orphan knowledge", "--background", "toy repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(tmp_path)


def card_kwargs(**overrides):
    data = {
        "source_type": "paper",
        "source": "https://example.invalid/paper",
        "claim": "Shape-aware components reduce remote false positives.",
        "mechanism_extraction": "component-veto-with-shape-prior",
        "why_it_matters": "It targets the current false-positive failure anchor.",
        "failure_anchor": "remote false positives persist after baseline filtering",
        "possible_mve": "run one-case component veto MVE and save a metric artifact",
        "required_assets": ["component mask"],
        "risks": ["may over-remove true positives"],
        "stop_reason": "no component-level precision gain",
    }
    data.update(overrides)
    return data


def test_repo_and_paper_expire_after_two_unconsumed_cycles(tmp_path: Path):
    paths = init_repo(tmp_path)
    record_knowledge_event(paths, source_type="repo", source="https://example.invalid/repo.git")
    record_knowledge_event(paths, source_type="paper", source="https://example.invalid/paper")

    first = advance_knowledge_ttl(paths)
    second = advance_knowledge_ttl(paths)

    assert first["expired"] == []
    assert len(second["expired"]) == 2
    assert {row["status"] for row in load_latest_knowledge(paths).values()} == {"EXPIRED_ORPHAN"}
    assert read_jsonl(paths.kernel / "RESEARCH_REGISTRY.jsonl")[-1]["event_type"] == "expired_orphan"


def test_archived_reference_does_not_count_as_active_queue(tmp_path: Path):
    paths = init_repo(tmp_path)

    create_mechanism_card(paths, **card_kwargs(possible_mve=""))
    audit = orphan_audit(paths)

    assert audit["archived_references"] == 1
    assert audit["active_queue"] == []


def test_mechanism_card_to_compile_becomes_active_mechanism(tmp_path: Path):
    paths = init_repo(tmp_path)
    card = create_mechanism_card(paths, **card_kwargs())
    draft = build_draft_from_mechanism_card(paths, card)
    outputs = write_review_outputs(paths, review_draft_plan(paths, draft))
    reviewed = read_json(outputs["reviewed_manifest"], {})

    compile_reviewed_plan(paths, reviewed)
    latest = load_latest_knowledge(paths)

    assert list(latest.values())[0]["status"] == "ACTIVE_MECHANISM"


def test_orphan_audit_reports_counts(tmp_path: Path):
    paths = init_repo(tmp_path)
    record_knowledge_event(paths, source_type="user_idea", source="try method later")
    create_mechanism_card(paths, **card_kwargs(possible_mve=""))
    advance_knowledge_ttl(paths, cycles=2)

    audit = orphan_audit(paths)

    assert audit["expired_orphans"] == 1
    assert audit["archived_references"] == 1
    assert "Expired orphans: `1`" in (paths.research / "knowledge" / "orphan_audit.md").read_text()


def test_expired_orphan_cli_writes_registry(tmp_path: Path):
    init_repo(tmp_path)
    ingest = invoke("knowledge", "ingest", "--target", str(tmp_path), "--source-type", "deep_note", "--source", "note.md")
    clear = invoke("knowledge", "advance-ttl", "--target", str(tmp_path), "--cycles", "2")

    assert ingest.exit_code == 0
    assert clear.exit_code == 0
    assert json.loads(clear.output)["expired"][0]["status"] == "EXPIRED_ORPHAN"
    assert read_jsonl(tmp_path / ".vibe" / "kernel" / "RESEARCH_REGISTRY.jsonl")[-1]["event_type"] == "expired_orphan"
