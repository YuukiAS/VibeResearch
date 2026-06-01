from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.daemon import daemon_autonomy_audit, daemon_status
from vibe_research.io import write_json, write_yaml
from vibe_research.paths import VibePaths
from vibe_research.project import create_cycle, sync_resource_plan_from_portfolio


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
