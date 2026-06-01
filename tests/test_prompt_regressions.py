from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from typer.testing import CliRunner

from vibe_research.artifacts import validate_artifact
from vibe_research.automation import auto_cycle
from vibe_research.cli import app
from vibe_research.daemon import daemon_autonomy_audit, daemon_status
from vibe_research.decisions import ensure_decision_after_revise, load_decision, make_decision, write_decision
from vibe_research.git_ops import create_branch
from vibe_research.io import append_jsonl, write_json, write_yaml
from vibe_research.locks import active_advance_lock, advancing_lock
from vibe_research.loop_guard import apply_loop_guard
from vibe_research.paths import VibePaths
from vibe_research.project import create_cycle, sync_resource_plan_from_portfolio
from vibe_research.promotion import compile_decision, validate_resource_plan
from vibe_research.scheduler import dependencies_blocked


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "prompt regression", "--background", "generic downstream repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def test_v0121_daemon_audit_flags_monitor_only_with_actionable_next(tmp_path: Path, monkeypatch):
    paths = initialized_paths(tmp_path)
    write_json(paths.state / "daemon.json", {"mode": "monitor", "interval": 300, "auto_next": False, "dry_submit": False, "max_steps": 30})
    write_json(paths.state / "state.json", {"next_action": "vibe plan-cycle", "runs": {}})
    monkeypatch.setattr("vibe_research.daemon.shutil.which", lambda name: None)
    status = daemon_status(paths)
    assert status["next_action"] == "vibe plan-cycle"
    assert status["actionable_next_action"] is True
    assert "daemon_monitor_only_while_next_action_is_actionable" in status["autonomous_progress_blockers"]
    assert "daemon_auto_next_false_while_next_action_is_actionable" in status["autonomous_progress_blockers"]
    audit = daemon_autonomy_audit(paths)
    assert audit["ok"] is False
    assert "auto-cycle --auto-next --real-submit" in audit["restart_recommendation"]
    cli = invoke("daemon", "audit-autonomy", "--target", str(tmp_path))
    assert cli.exit_code == 1
    payload = json.loads(cli.output)
    assert "daemon_monitor_only_while_next_action_is_actionable" in payload["blockers"]


def activate_three_executable_capabilities(paths: VibePaths) -> None:
    capabilities = []
    for index in range(1, 4):
        cap_id = f"route-{index}"
        capabilities.append(
            {
                "id": cap_id,
                "version": "test",
                "status": "active",
                "task_type": "metrics_export",
                "supported_decisions": ["collect_more_metrics"],
                "description": f"Concrete route {index}",
                "dryrun": {"command": f"bash -lc 'echo dry-{index}'"},
                "entrypoint": {"type": "local", "command": f"bash -lc 'mkdir -p .vibe/results; printf \"{{\\\"primary\\\": {index}}}\" > .vibe/results/{cap_id}.json'"},
                "outputs": {"expected_output_path": f".vibe/results/{cap_id}.json", "metrics_file_path": f".vibe/results/{cap_id}.json"},
                "metrics_schema": {"required": ["primary"], "types": {"primary": "number"}, "primary_metric": "primary"},
                "artifact_rules": {"expected_outputs": [f".vibe/results/{cap_id}.json"]},
                "resources": {"default": {"gpu": 0, "cpus": 1, "mem_gb": 1, "time": "00:05:00"}, "automatic_submission_allowed": True, "allowed_backends": ["local"]},
                "trust_checks": ["metrics_schema"],
                "contract_tests": ["smoke"],
                "activation": {"contract_status": "passed"},
            }
        )
        write_json(paths.vibe / "contract_tests" / f"{cap_id}.json", {"capability_id": cap_id, "status": "passed"})
    write_yaml(
        paths.vibe / "adapter.yaml",
        {
            "adapter_revision": "test-rev",
            "maturity_level": "evaluation_ready",
            "capabilities": capabilities,
        },
    )


def test_v0122_post_target_plan_cycle_compiles_active_capability_routes(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    activate_three_executable_capabilities(paths)
    write_json(paths.research / "sustained_round_audit.json", {"complete": True, "completed_round_count": 3})
    write_json(paths.research / "auto_method_search.json", {"searches": {"recent": {"status": "searched", "results": [{"title": "external method"}]}}})
    cycle = create_cycle(paths)
    plan = sync_resource_plan_from_portfolio(paths, cycle)
    run_keys = set(plan["runs"])
    assert run_keys == {"route-1", "route-2", "route-3"}
    assert not {"baseline-check", "diagnostic-check", "first-hypothesis"}.intersection(run_keys)
    assert plan["decision_id"]
    assert plan["post_target_continuation"]["generic_placeholder_repaired"] is True
    capability_ids = {spec["adapter_metadata"]["capability_id"] for spec in plan["runs"].values()}
    assert capability_ids == {"route-1", "route-2", "route-3"}
    assert all(spec["dryrun"]["command"] and spec["entrypoint"]["command"] for spec in plan["runs"].values())


def test_v0123_auto_cycle_refuses_second_advancing_lock(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    with advancing_lock(paths, command="auto-cycle", current_action="vibe reflect r001"):
        lock = active_advance_lock(paths)
        assert lock["command"] == "auto-cycle"
        assert lock["current_action"] == "vibe reflect r001"
        with pytest.raises(RuntimeError, match="advance_lock_active"):
            auto_cycle(paths, offline=True, dry_submit=True, max_steps=1)


def test_v0123_negative_untrusted_metrics_do_not_promote(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    run_id = "r001"
    (paths.runs / run_id).mkdir(parents=True, exist_ok=True)
    write_json(
        paths.runs / run_id / "metrics.json",
        {
            "schema_status": "valid",
            "trust_status": "untrusted",
            "trusted": False,
            "primary": -0.3944,
            "metric_delta": {"primary": -0.3944},
        },
    )
    (paths.runs / run_id / "reflect.md").write_text("Verdict: do_not_promote\nRecommended decision: failed_stop_or_redesign\n")
    decision = ensure_decision_after_revise(paths, run_id, "## Decision\npromote_to_baseline_compare against trusted baseline")
    assert decision.decision_type == "stop_direction"
    assert decision.baseline_comparison_target == ""
    assert decision.provenance["source"] == "metrics_reflection_guard"

    run_id = "r002"
    (paths.runs / run_id).mkdir(parents=True, exist_ok=True)
    write_json(
        paths.runs / run_id / "metrics.json",
        {
            "schema_status": "valid",
            "trust_status": "untrusted",
            "trusted": False,
            "primary": -0.3944,
            "metric_delta": {"primary": -0.3944},
        },
    )
    write_decision(
        paths,
        make_decision(
            paths,
            run_id,
            "promote_to_baseline_compare",
            required_action="promote_to_baseline_compare",
            baseline_comparison_target="trusted_baseline",
            provenance={"source": "legacy_markdown_inference"},
        ),
    )
    repaired = ensure_decision_after_revise(paths, run_id, "baseline")
    loaded = load_decision(paths, run_id)
    assert repaired.decision_type == "stop_direction"
    assert loaded.decision_type == "stop_direction"


def test_v0124_explicit_no_job_portfolio_actions_preserved(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    activate_three_executable_capabilities(paths)
    cycle = create_cycle(paths)
    portfolio = paths.cycles / cycle / "portfolio_plan.md"
    portfolio.write_text(
        """# Portfolio plan

## Resource policy
- No long-running jobs.
- No Slurm submissions.
- no_gpu_no_slurm.

## Selected actions
- run `trust_repair_and_metric_audit`
- run `reference_evidence_review`
- run `mednext_route_decision`
- do not repeat old smoke routes without a new ablation or trust repair purpose.
"""
    )
    errors_before = validate_resource_plan(paths, cycle)
    assert any("explicit local/no-job actions" in error for error in errors_before)

    plan = sync_resource_plan_from_portfolio(paths, cycle)
    expected_order = ["trust_repair_and_metric_audit", "reference_evidence_review", "mednext_route_decision"]
    expected = set(expected_order)
    assert list(plan["runs"]) == expected_order
    assert not {"baseline-check", "diagnostic-check", "first-hypothesis"}.intersection(plan["runs"])
    assert plan["max_gpu_jobs"] == 0
    assert plan["mode"] == "portfolio_explicit_local"
    assert plan["portfolio_explicit_local"]["actions"] == expected_order
    for action, spec in plan["runs"].items():
        assert spec["resources"]["gpu"] == 0
        assert spec["resources"]["allowed_backends"] == ["local"]
        assert spec["entrypoint"]["type"] == "local"
        assert spec["run_kind"] == "artifact_only"
        assert spec["adapter_metadata"]["source"] == "portfolio_explicit_local_action"
        assert spec["adapter_metadata"]["action"] == action
        assert spec["adapter_metadata"]["no_job"] is True
    assert validate_resource_plan(paths, cycle) == []


def test_v0125_artifact_only_branch_records_logical_branch_with_dirty_git(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "dirty.txt").write_text("uncommitted\n")
    run_id = "r001_artifact_audit"
    (paths.runs / run_id).mkdir(parents=True, exist_ok=True)
    write_json(
        paths.state / "state.json",
        {
            "runs": {
                run_id: {
                    "run_id": run_id,
                    "cycle_id": "c001",
                    "status": "reviewed",
                    "branch": "vibe/r001-artifact-audit",
                    "run_kind": "artifact_only",
                    "adapter_metadata": {"no_job": True},
                }
            }
        },
    )
    branch = create_branch(paths, run_id)
    state = json.loads((paths.state / "state.json").read_text())
    run = state["runs"][run_id]
    assert branch == "vibe/r001-artifact-audit"
    assert run["status"] == "patched"
    assert run["branch_mode"] == "logical_no_git"
    assert state["next_action"] == f"vibe dryrun {run_id}"
    assert "branch_recorded=logical_no_git" in (paths.runs / run_id / "branch.txt").read_text()
    assert (paths.runs / run_id / "patch.diff").read_text() == ""
    status = invoke("status", "--target", str(tmp_path))
    assert status.exit_code == 0
    assert "logical/no-git" in status.output


def test_v0126_artifact_only_zero_metrics_do_not_trip_repeated_evidence(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    state = {
        "cycles": {"c001": {"status": "active"}},
        "runs": {
            "r001_audit": {"run_id": "r001_audit", "cycle_id": "c001", "status": "revised", "run_kind": "artifact_only", "adapter_metadata": {"no_job": True}},
            "r002_review": {"run_id": "r002_review", "cycle_id": "c001", "status": "revised", "run_kind": "artifact_only", "adapter_metadata": {"no_job": True}},
            "r003_decision": {
                "run_id": "r003_decision",
                "cycle_id": "c001",
                "status": "queued",
                "run_kind": "artifact_only",
                "adapter_metadata": {"no_job": True},
                "dependencies": {"run_after": ["r001_audit", "r002_review"]},
            },
        },
    }
    write_json(paths.state / "state.json", state)
    for run_id in ["r001_audit", "r002_review"]:
        append_jsonl(
            paths.leaderboard / "history.jsonl",
            {
                "run_id": run_id,
                "cycle_id": "c001",
                "primary_metric": 0.0,
                "trusted": False,
                "trust_status": "untrusted",
                "schema_status": "valid",
                "run_kind": "artifact_only",
                "adapter_metadata": {"no_job": True},
            },
        )
    assert not apply_loop_guard(paths, "r002_review")
    assert not apply_loop_guard(paths, "c001")
    assert not dependencies_blocked(state, state["runs"]["r003_decision"])


def test_v0126_artifact_only_revised_plan_does_not_promote_on_baseline_word(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    run_id = "r001_artifact_review"
    (paths.runs / run_id).mkdir(parents=True, exist_ok=True)
    write_json(
        paths.state / "state.json",
        {
            "runs": {
                run_id: {
                    "run_id": run_id,
                    "cycle_id": "c001",
                    "status": "collected",
                    "run_kind": "artifact_only",
                    "adapter_metadata": {"no_job": True},
                }
            }
        },
    )
    decision = ensure_decision_after_revise(paths, run_id, "## Decision\nCompare against baseline context before closing the artifact audit.")
    assert decision.decision_type == "collect_more_metrics"
    assert decision.baseline_comparison_target == ""
    assert decision.provenance["source"] == "artifact_only_promotion_guard"


def test_v0127_reflect_accepts_result_interpretation_aliases_only_for_reflect(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    run_id = "r001_alias_reflect"
    (paths.runs / run_id).mkdir(parents=True, exist_ok=True)
    (paths.runs / run_id / "reflect.md").write_text("# Reflect\n\n## Completed Result Interpretation\nusable local artifact\n")
    assert validate_artifact(paths, "reflect", run_id) == []

    (paths.runs / run_id / "reflect.md").write_text("# Reflect\n\n## Result Interpretation\nusable local artifact\n")
    assert validate_artifact(paths, "reflect", run_id) == []

    (paths.runs / run_id / "revised_plan.md").write_text(
        """# Revised Plan

## Completed Result Interpretation
ok

## Decision
collect_more_metrics

## Plan update
none

## Required changes
none

## Evidence needed
artifact output

## Literature refresh decision
no

## Deep research decision
no

## Idea pool update
none

## Portfolio implication
none

## Next experiment proposal
none

## Stop condition
none
"""
    )
    issues = validate_artifact(paths, "revised_plan", run_id)
    assert any("missing required section `## Result interpretation`" in issue.message for issue in issues)


def test_v0133_cycle_preserves_blocked_missing_artifact_adapter(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    cycle_id = "c019"
    (paths.cycles / cycle_id).mkdir(parents=True, exist_ok=True)
    text = """# Cycle Revised Plan

## Cycle-level interpretation
Cycle did not produce substantive research evidence.
Verdict: BLOCKED_MISSING_ARTIFACT_ADAPTER

## Direction decisions
blocked_missing_artifact_adapter
trust_metric_audit_repair
reference_evidence_review_repair
mednext_route_decision_repair
reference_only

## Portfolio mode update
patch_required_artifact_adapter_repair

## Next portfolio sketch
repair local artifact adapters only

## Resource update
No Slurm and no GPU work.

## Literature and deep research decision
Literature: no. Deep research: no.

## Idea pool update
none

## User decision needed
none

## Stop condition
stop placeholder artifact metrics
"""
    decision = ensure_decision_after_revise(paths, cycle_id, text)
    assert decision.decision_type == "blocked_missing_artifact_adapter"
    assert "trust_metric_audit_repair" in decision.blocking_questions
    assert "reference_evidence_review_repair" in decision.blocking_questions
    assert "mednext_route_decision_repair" in decision.blocking_questions
    ok, message = compile_decision(paths, cycle_id)
    assert ok is False
    assert "artifact adapter" in message.lower()
    assert load_decision(paths, cycle_id).decision_type == "blocked_missing_artifact_adapter"


def test_v0133_reference_only_is_not_collect_more_metrics(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    cycle_id = "c020"
    (paths.cycles / cycle_id).mkdir(parents=True, exist_ok=True)
    decision = ensure_decision_after_revise(
        paths,
        cycle_id,
        "## Direction decisions\nreference_only\nMedNeXt route stance remains reference_only; do not collect more metrics for this route.",
    )
    assert decision.decision_type == "stop_direction"
    assert decision.required_action != "collect_more_metrics"
