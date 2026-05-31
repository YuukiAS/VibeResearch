from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.backends import SlurmBackend
from vibe_research.cli import app
from vibe_research.io import read_json, read_jsonl, write_json
from vibe_research.paths import VibePaths


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "generic slurm monitor", "--background", "toy repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def test_v0103_squeue_timeout_falls_back_to_sacct_completed(tmp_path: Path, monkeypatch):
    paths = initialized_paths(tmp_path)

    def fake_run(command, **kwargs):
        if command[0] == "squeue":
            raise subprocess.TimeoutExpired(command, 10)
        if command[0] == "sacct":
            return subprocess.CompletedProcess(command, 0, stdout="COMPLETED|0:0\n", stderr="")
        if command[0] == "scontrol":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="unavailable")
        raise AssertionError(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    poll = SlurmBackend(paths, {}).poll({"job_id": "123", "launch_workdir": str(tmp_path)})
    assert poll.finished is True
    assert poll.status == "finished"
    assert poll.details["command"] == "squeue"
    assert "COMPLETED" in poll.details["sacct_stdout"]


def test_v0103_squeue_socket_error_falls_back_to_sacct_running(tmp_path: Path, monkeypatch):
    paths = initialized_paths(tmp_path)

    def fake_run(command, **kwargs):
        if command[0] == "squeue":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="error creating slurm stream socket")
        if command[0] == "sacct":
            return subprocess.CompletedProcess(command, 0, stdout="RUNNING|0:0\n", stderr="")
        if command[0] == "scontrol":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="unavailable")
        raise AssertionError(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    poll = SlurmBackend(paths, {}).poll({"job_id": "123", "launch_workdir": str(tmp_path)})
    assert poll.finished is False
    assert poll.status == "running"
    assert poll.details["reason"] == "slurm_query_unavailable"


def test_v0103_monitor_archives_stale_active_job_when_metrics_collected(tmp_path: Path, monkeypatch):
    paths = initialized_paths(tmp_path)
    run_id = "r001"
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {run_id: {"run_id": run_id, "cycle_id": "c001", "status": "submitted"}}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "metrics.json", {"schema_valid": True, "metrics": {"primary": 1.0}})
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [{"run_id": run_id, "cycle_id": "c001", "backend": "slurm", "job_id": "123", "launch_workdir": str(tmp_path), "poll_details": {"wait_verdict": {"verdict": "fallback_not_better_keep_preferred"}}}]})

    def fake_run(command, **kwargs):
        if command[0] == "squeue":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="error creating slurm stream socket")
        if command[0] == "sacct":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="accounting unavailable")
        if command[0] == "scontrol":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="unavailable")
        raise AssertionError(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = invoke("monitor", "--target", str(tmp_path))
    assert result.exit_code == 0
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert active["active"] == []
    completed = read_jsonl(tmp_path / ".vibe" / "scheduler" / "completed_jobs.jsonl")
    assert completed[-1]["status"] == "collected"
    assert completed[-1]["poll_details"]["reason"] == "stale_active_terminal_artifact"
