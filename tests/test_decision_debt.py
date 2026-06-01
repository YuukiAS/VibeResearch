from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.decision_debt import (
    clear_expired_decision_debts,
    debt_record_from_reflection,
    load_open_decision_debts,
    validate_debt_record,
)
from vibe_research.io import read_jsonl
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_plan
from vibe_research.reflector import validate_reflection, write_reflection_outputs


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def init_repo(tmp_path: Path) -> VibePaths:
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    return VibePaths(tmp_path)


def reflection(**overrides):
    data = {
        "schema_version": 1,
        "created_at": "2026-06-01T00:00:00Z",
        "session_role": "reflector",
        "verdict": "REFINE",
        "source_result": ".vibe/executor/result_manifest.json",
        "accepted_plan_id": "component-veto-with-shape-prior",
        "review_approval_id": "review-1",
        "evidence": {"type": "feasibility", "summary": "smoke success only"},
        "metric": {"trusted": False, "summary": "smoke metric"},
        "guardrail": {"status": "ok", "summary": "no guardrail regression"},
        "belief_update": "Feasibility only; evidence debt remains.",
        "next_action": {
            "type": "refinement_debt",
            "missing_evidence": "trusted mechanism evidence",
            "repayment_mve": "run subset MVE for component veto",
            "ttl_rounds": 2,
            "promotion_condition": "subset MVE is trusted and improves precision",
            "pivot_condition": "subset MVE changes the mechanism",
            "stop_condition": "subset MVE remains negative or missing",
        },
        "issues": [],
        "executor_cannot_declare_success": True,
    }
    data.update(overrides)
    return data


def plan_kwargs(**overrides: str) -> dict[str, str]:
    data = {
        "mode": "invent",
        "failure_anchor": "remote false positives persist after baseline filtering",
        "hypothesis": "a component veto can remove remote false positives",
        "mechanism": "component-veto-with-shape-prior",
        "minimum_experiment": "one-case component veto with saved mask artifact",
        "expected_artifact": ".vibe/runs/r001/component_veto_metrics.json",
        "expected_belief_update": "decide whether component veto has mechanism evidence",
        "compute_cost": "local cpu under 5 minutes",
        "risk": "may over-remove true positives",
        "fallback": "record negative evidence and try route-level filter",
        "stop_condition": "no component-level precision gain",
        "confidence": "speculative_mechanism",
    }
    data.update(overrides)
    return data


def test_watch_without_repayment_mve_is_rejected():
    record = debt_record_from_reflection(
        reflection(verdict="WATCH", next_action={"type": "watch_debt", "missing_evidence": "subset robustness", "ttl_rounds": 2})
    )

    assert "repayment_mve is required" in validate_debt_record(record)


def test_reflector_refine_writes_open_debt(tmp_path: Path):
    paths = init_repo(tmp_path)

    write_reflection_outputs(paths, reflection())

    debts = load_open_decision_debts(paths)
    assert debts
    assert debts[0]["repayment_mve"] == "run subset MVE for component veto"
    assert "repayment_mve" in (paths.kernel / "OPEN_DEBTS.md").read_text()
    assert validate_reflection(reflection()) == []


def test_two_uncleared_rounds_auto_stop_and_write_registry(tmp_path: Path):
    paths = init_repo(tmp_path)
    write_reflection_outputs(paths, reflection())

    first = clear_expired_decision_debts(paths)
    second = clear_expired_decision_debts(paths)

    assert first["cleared"] == []
    assert second["cleared"][0]["clearance_decision"] == "STOP"
    assert load_open_decision_debts(paths) == []
    assert "STOP debt" in (paths.kernel / "NEGATIVE_MEMORY.md").read_text()
    assert read_jsonl(paths.kernel / "RESEARCH_REGISTRY.jsonl")[-1]["event_type"] == "decision_debt_clearance"


def test_expired_pivot_debt_writes_plan_seed_for_reviewer(tmp_path: Path):
    paths = init_repo(tmp_path)
    pivot = reflection(next_action={**reflection()["next_action"], "expiry_decision": "PIVOT"})
    write_reflection_outputs(paths, pivot)

    result = clear_expired_decision_debts(paths, rounds=2)

    assert result["cleared"][0]["clearance_decision"] == "PIVOT"
    seed = read_jsonl(paths.kernel / "PLAN_SEEDS.jsonl")[-1]
    assert seed["reviewer_required"] is True


def test_planner_reads_open_debt_and_prioritizes_repayment(tmp_path: Path):
    paths = init_repo(tmp_path)
    write_reflection_outputs(paths, reflection())

    ignored = build_draft_plan(paths, **plan_kwargs(mechanism="unrelated route filter"))
    addressed = build_draft_plan(paths, **plan_kwargs(minimum_experiment="run subset MVE for component veto"))

    assert any(item["code"] == "open_decision_debt_priority" for item in ignored["diagnostics"])
    assert ignored["review_route"] == "requires_revision"
    assert any(item["code"] == "open_decision_debt_addressed" for item in addressed["diagnostics"])


def test_debt_cli_clear_advances_ttl(tmp_path: Path):
    paths = init_repo(tmp_path)
    write_reflection_outputs(paths, reflection())

    listed = invoke("debt", "list", "--target", str(tmp_path))
    cleared = invoke("debt", "clear", "--target", str(tmp_path), "--rounds", "2")

    assert listed.exit_code == 0
    assert cleared.exit_code == 0
    assert not load_open_decision_debts(paths)
