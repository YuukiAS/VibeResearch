from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.io import append_jsonl, read_json, write_json
from vibe_research.paths import VibePaths
from vibe_research.reliability import compare_checkpoints, reliability_checkpoint, reliability_doctor, reliability_report
from vibe_research.research_manager import research_paths


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "long run soak", "--background", "generic downstream repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def old_timestamp(hours: int = 48) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test_v0120_detects_stale_active_submitted_mismatch(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    write_json(
        paths.state / "state.json",
        {
            "updated_at": old_timestamp(),
            "runs": {
                "run_001": {"status": "submitted", "updated_at": old_timestamp()},
            },
        },
    )
    report = reliability_report(paths, stale_hours=24)
    active = report["checks"]["active_run_consistency"]
    assert active["status"] == "blocked"
    assert "run_001:stale_active_run" in active["issues"]
    assert report["status"] == "blocked"


def test_v0120_detects_stale_blockers_budget_and_memo_freshness(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    write_json(paths.state / "state.json", {"updated_at": old_timestamp(), "blocked_reason": "needs user decision", "runs": {}})
    append_jsonl(research_paths(paths)["budget"], {"created_at": old_timestamp(), "status": "reserved", "gpu_hours": 50})
    report = reliability_report(paths, stale_hours=24, memo_fresh_hours=1)
    assert "state:stale_blocked_reason" in report["checks"]["stale_blockers"]["issues"]
    assert "budget:total_gpu_hour_cap_exceeded" in report["checks"]["budget_drift"]["issues"]
    assert "memo:no_recent_memo" in report["checks"]["memo_freshness"]["warnings"]
    assert report["checks"]["budget_drift"]["summary"]["reserved_or_spent_gpu_hours"] == 50


def test_v0120_checkpoint_creation_and_comparison(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    first = reliability_checkpoint(paths, label="initial")
    write_json(paths.state / "state.json", {"updated_at": old_timestamp(), "runs": {"run_002": {"status": "running", "updated_at": old_timestamp()}}})
    second = reliability_checkpoint(paths, label="with-active-run")
    comparison = compare_checkpoints(paths)
    assert first["checkpoint_id"] == "soak_001"
    assert second["checkpoint_id"] == "soak_002"
    assert comparison["deltas"]["active_runs_added"] == ["run_002"]
    assert read_json(paths.research / "reliability" / "latest_checkpoint.json", {})["checkpoint_id"] == "soak_002"


def test_v0120_doctor_outputs_safe_recovery_commands_only(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    write_json(paths.state / "state.json", {"updated_at": old_timestamp(), "runs": {"run_003": {"status": "running", "updated_at": old_timestamp()}}})
    doctor = reliability_doctor(paths, stale_hours=24)
    assert doctor["status"] == "blocked"
    assert doctor["no_live_mutation"] is True
    joined = "\n".join(doctor["safe_recommendations"])
    assert "vibe monitor" in joined
    assert "vibe collect" in joined
    assert "scancel" not in joined
    assert "sbatch" not in joined
    assert "submit-queue" not in joined


def test_v0120_reliability_cli_roundtrip(tmp_path: Path):
    paths = initialized_paths(tmp_path)
    report = invoke("reliability", "report", "--target", str(tmp_path))
    assert report.exit_code == 0
    checkpoint = invoke("reliability", "checkpoint", "--target", str(tmp_path), "--label", "cli")
    assert checkpoint.exit_code == 0
    assert json.loads(checkpoint.output)["checkpoint_id"] == "soak_001"
    comparison = invoke("reliability", "compare", "--target", str(tmp_path))
    assert comparison.exit_code == 0
    assert json.loads(comparison.output)["status"] == "compared"
    doctor = invoke("reliability", "doctor", "--target", str(tmp_path))
    assert doctor.exit_code in {0, 1}
    assert read_json(paths.research / "reliability" / "doctor.json", {})["no_live_mutation"] is True
