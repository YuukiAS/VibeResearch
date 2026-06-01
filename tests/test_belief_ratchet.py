from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.belief_ratchet import apply_belief_ratchet, build_ratchet_record, validate_ratchet_record
from vibe_research.cli import app
from vibe_research.io import read_json, write_json
from vibe_research.paths import VibePaths


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def init_repo(tmp_path: Path) -> VibePaths:
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    write_json(paths.kernel / "execution_manifest.json", {"accepted_plan_id": "plan-1", "review_approval_id": "review-1"})
    return paths


def reflection(**overrides):
    data = {
        "schema_version": 1,
        "session_role": "reflector",
        "verdict": "REFINE",
        "accepted_plan_id": "plan-1",
        "review_approval_id": "review-1",
        "source_result": ".vibe/executor/result_manifest.json",
        "evidence": {"type": "feasibility", "summary": "smoke ran"},
        "metric": {"trusted": False, "path": ".vibe/runs/r001/smoke_status.json", "evidence_type": "feasibility", "summary": "smoke"},
        "guardrail": {"status": "unknown", "summary": "not measured"},
        "belief_update": "Feasibility improved but metric belief did not move.",
        "next_action": {"type": "refinement_debt", "reason": "collect metric evidence"},
    }
    data.update(overrides)
    return data


def test_feasibility_is_not_metric_progress(tmp_path: Path):
    paths = init_repo(tmp_path)
    record = build_ratchet_record(paths, reflection())

    assert record["evidence_type"] == "feasibility"
    assert record["belief_delta"]["metric_progress"] is False
    assert validate_ratchet_record(record) == []


def test_mechanism_signal_is_preserved_without_metric_gain(tmp_path: Path):
    paths = init_repo(tmp_path)
    record = build_ratchet_record(
        paths,
        reflection(
            verdict="REFINE",
            evidence={"type": "mechanism", "summary": "verifier detects remote false positives"},
            metric={"trusted": True, "path": ".vibe/runs/r001/mechanism_metrics.json", "primary": 0.0, "mechanism_signal": True},
            belief_update="Verifier mechanism is useful even without final metric gain.",
        ),
    )
    write_json(paths.kernel / "reflect_manifest.json", reflection(evidence={"type": "mechanism"}, metric=record["metric_vector"], belief_update=record["belief_update"]))
    applied = apply_belief_ratchet(paths)

    assert record["evidence_type"] == "mechanism"
    assert record["belief_delta"]["mechanism"] == "preserve"
    assert "mechanism" in (tmp_path / ".vibe" / "kernel" / "MECHANISM_MEMORY.md").read_text()
    assert applied["evidence_type"] == "mechanism"


def test_one_case_does_not_create_robustness_belief(tmp_path: Path):
    paths = init_repo(tmp_path)
    record = build_ratchet_record(
        paths,
        reflection(
            verdict="PROCEED",
            evidence={"type": "mve_success", "summary": "one-case positive"},
            metric={"trusted": True, "path": ".vibe/runs/r001/one_case_metric.json", "primary": 0.8, "folds": 1},
            next_action={"type": "promotion_debt", "next_debt": "subset"},
        ),
    )

    assert record["evidence_type"] in {"mechanism", "metric"}
    assert record["belief_delta"]["robustness"] is False


def test_negative_evidence_updates_immune_memory(tmp_path: Path):
    paths = init_repo(tmp_path)
    write_json(
        paths.kernel / "reflect_manifest.json",
        reflection(
            verdict="PIVOT",
            evidence={"type": "guardrail_regression", "summary": "guardrail regressed"},
            metric={"trusted": True, "path": ".vibe/runs/r001/metrics.json", "guardrail_regression": True},
            belief_update="Route should not repeat.",
            next_action={"type": "negative_memory", "reason": "guardrail regression"},
        ),
    )

    record = apply_belief_ratchet(paths)

    assert record["evidence_type"] == "negative"
    assert "avoid_repeat" in (tmp_path / ".vibe" / "kernel" / "NEGATIVE_MEMORY.md").read_text()


def test_ratchet_record_is_traceable_and_cli_validates(tmp_path: Path):
    paths = init_repo(tmp_path)
    write_json(paths.kernel / "reflect_manifest.json", reflection())

    result = invoke("ratchet", "apply", "--target", str(tmp_path))

    assert result.exit_code == 0
    record = read_json(paths.kernel / "belief_ratchet_record.json", {})
    assert record["accepted_plan_id"] == "plan-1"
    assert record["execution_manifest"].endswith("execution_manifest.json")
    assert record["artifact_pointer"] == ".vibe/runs/r001/smoke_status.json"
    validate = invoke("ratchet", "validate", str(paths.kernel / "belief_ratchet_record.json"))
    assert validate.exit_code == 0
