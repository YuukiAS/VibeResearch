from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.io import read_json
from vibe_research.paths import VibePaths
from vibe_research.session_budget_guard import (
    guard_session_action,
    parse_codex_status,
    record_zero_cost_wait,
    refresh_budget_from_status,
    write_low_budget_checkpoint,
)


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def test_session_budget_state_created_on_init(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0

    state = read_json(tmp_path / ".vibe" / "kernel" / "SESSION_BUDGET_STATE.json", {})

    assert state["schema_version"] == 1
    assert state["quota_source"] == "unknown/manual"
    assert (tmp_path / ".vibe" / "executor" / "wait_until_budget_reset.sh").exists()


def test_parse_and_refresh_codex_status_text(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)

    parsed = parse_codex_status("5h limit: 17% left\nweekly limit: 82% left")
    state = refresh_budget_from_status(
        paths,
        status_text="5h limit: 17% left\nweekly limit: 82% left",
        session_name="s-review",
        role="reviewer",
        resume_command="vibe reviewer review",
    )

    assert parsed["five_hour_quota_percent"] == 17
    assert state["weekly_quota_percent"] == 82
    assert state["session_name"] == "s-review"
    assert state["next_resume_command"] == "vibe reviewer review"


def test_budget_guard_blocks_new_planning_below_20_percent(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    refresh_budget_from_status(paths, status_text="5h limit: 15% left\nweekly limit: 90% left", role="planner")

    result = guard_session_action(paths, role="planner", phase="PLAN")

    assert result["ok"] is False
    assert any("blocked below 20%" in reason for reason in result["reasons"])


def test_low_budget_checkpoint_writes_resume(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    state = refresh_budget_from_status(
        paths,
        status_text="5h limit: 8% left\nweekly limit: 70% left",
        session_name="s-exec",
        role="executor",
        resume_command="vibe executor validate-result",
    )

    checkpoint = write_low_budget_checkpoint(paths, state, phase="EXECUTE", reasons=["quota below 10"])

    assert Path(checkpoint["checkpoint_path"]).exists()
    resume = (tmp_path / "RESUME.md").read_text()
    assert "vibe executor validate-result" in resume
    assert read_json(tmp_path / ".vibe" / "kernel" / "SESSION_BUDGET_STATE.json", {})["checkpoint_path"].endswith("s-exec-execute-checkpoint.json")


def test_guard_checkpoint_on_block_generates_resume(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)
    refresh_budget_from_status(paths, status_text="5h limit: 5% left\nweekly limit: 60% left", session_name="s-plan", role="planner")

    result = invoke("session-budget", "guard", "--target", str(tmp_path), "--phase", "PLAN", "--role", "planner", "--checkpoint-on-block")

    assert result.exit_code == 1
    assert "Session budget guard: blocked" in result.output
    assert (tmp_path / "RESUME.md").exists()


def test_zero_cost_wait_distinguishes_slurm_and_quota_waits(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    paths = VibePaths(tmp_path)

    slurm = record_zero_cost_wait(paths, wait_type="slurm-job", job_id="12345", resume_command="vibe scheduler-monitor")
    quota = record_zero_cost_wait(paths, wait_type="quota-wait", estimated_reset_at="2026-06-01T12:00:00Z", resume_command="vibe session-budget guard --phase PLAN")

    assert slurm["zero_cost"] is True
    assert "squeue -j 12345" in slurm["poll_command"]
    assert quota["wait_type"] == "quota-wait"
    assert quota["poll_command"].endswith("wait_until_budget_reset.sh")


def test_session_budget_cli_refresh_and_wait_mode(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0

    refresh = invoke(
        "session-budget",
        "refresh",
        "--target",
        str(tmp_path),
        "--status-text",
        "5h limit: 44% left\nweekly limit: 91% left",
        "--session-name",
        "s-reflect",
        "--role",
        "reflector",
    )
    wait = invoke("session-budget", "wait-mode", "--target", str(tmp_path), "--wait-type", "quota-wait", "--estimated-reset-at", "2026-06-01T12:00:00Z")

    assert refresh.exit_code == 0
    assert wait.exit_code == 0
    state = read_json(tmp_path / ".vibe" / "kernel" / "SESSION_BUDGET_STATE.json", {})
    assert state["five_hour_quota_percent"] == 44
