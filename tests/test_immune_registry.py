from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.immune_registry import immune_check, load_budget_recovery, record_registry_event, route_fingerprint
from vibe_research.io import read_jsonl, write_json
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_plan
from vibe_research.reviewer import review_draft_plan


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def plan_kwargs(**overrides: str) -> dict[str, str]:
    data = {
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
    data.update(overrides)
    return data


def init_repo(tmp_path: Path) -> VibePaths:
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    (paths.kernel / "FAILURE_SIGNATURES.md").write_text("# Failure Signatures\n\nremote false positives persist after baseline filtering\n")
    return paths


def failed_payload() -> dict:
    return {
        "failure_anchor": "remote false positives persist after baseline filtering",
        "mechanism": "component-veto-with-shape-prior",
        "minimum_experiment": "one-case component veto MVE with saved mask artifact",
        "expected_artifact": ".vibe/runs/r001/component_veto_metrics.json",
        "reflect_decision": "STOP",
        "evidence_type": "negative",
    }


def test_route_fingerprint_is_stable():
    first = route_fingerprint(failed_payload())
    second = route_fingerprint(failed_payload())

    assert first["fingerprint"] == second["fingerprint"]
    assert first["artifact_type"] == "metric"


def test_old_experiment_rename_is_blocked_for_planner_and_reviewer(tmp_path: Path):
    paths = init_repo(tmp_path)
    record_registry_event(paths, event_type="reflect", payload=failed_payload())

    draft = build_draft_plan(paths, **plan_kwargs(expected_artifact=".vibe/runs/r999/component_veto_metrics.json"))
    review = review_draft_plan(paths, draft)

    assert any(item["code"] == "registry_repeat_route" for item in draft["diagnostics"])
    assert review["verdict"] == "REJECT"
    assert any(item["code"] == "immune_repeat_route" for item in review["criteria"])


def test_new_verifier_proxy_can_reenter(tmp_path: Path):
    paths = init_repo(tmp_path)
    record_registry_event(paths, event_type="reflect", payload=failed_payload())
    draft = build_draft_plan(paths, **plan_kwargs(mechanism="new verifier proxy for component-veto-with-shape-prior"))

    result = immune_check(paths, draft)

    assert result["blocked"] is False
    assert result["novelty"] is True


def test_failure_antigen_affects_later_plan(tmp_path: Path):
    paths = init_repo(tmp_path)
    record_registry_event(paths, event_type="reflect", payload={**failed_payload(), "reflect_decision": "PIVOT"})
    antigens = read_jsonl(paths.kernel / "FAILURE_ANTIGENS.jsonl")
    draft = build_draft_plan(paths, **plan_kwargs())

    assert antigens
    assert immune_check(paths, draft)["antigen_matches"]


def test_budget_checkpoint_is_recoverable(tmp_path: Path):
    paths = init_repo(tmp_path)
    record_registry_event(
        paths,
        event_type="budget_checkpoint",
        payload={"checkpoint_path": ".vibe/kernel/budget_checkpoints/s1.json", "resume_command": "vibe next"},
    )

    recovery = load_budget_recovery(paths)

    assert recovery["records"][0]["checkpoint_path"] == ".vibe/kernel/budget_checkpoints/s1.json"
    assert recovery["records"][0]["resume_command"] == "vibe next"


def test_registry_cli_records_and_checks(tmp_path: Path):
    paths = init_repo(tmp_path)
    payload = tmp_path / "payload.json"
    write_json(payload, failed_payload())

    record = invoke("registry", "record", "--target", str(tmp_path), "--event-type", "reflect", str(payload))
    check = invoke("registry", "check", "--target", str(tmp_path), str(payload))

    assert record.exit_code == 0
    assert check.exit_code == 1
    assert (paths.kernel / "RESEARCH_REGISTRY.jsonl").exists()
