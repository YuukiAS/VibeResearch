from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.codex_adapter import codex_exec_command, codex_exec_help, codex_sandbox_for, run_codex
from vibe_research.io import write_json
from vibe_research.paths import VibePaths


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def initialized_paths(root: Path) -> VibePaths:
    result = invoke("init", "--target", str(root), "--goal", "generic codex runtime", "--background", "toy repo", "--no-root-portal")
    assert result.exit_code == 0
    return VibePaths(root)


def test_v0102_codex_command_omits_unsupported_approval_flag(tmp_path: Path, monkeypatch):
    codex_exec_help.cache_clear()

    def fake_run(command, **kwargs):
        assert command == ["codex", "exec", "--help"]
        return subprocess.CompletedProcess(command, 0, stdout="Usage\n  -C\n  --sandbox\n  --output-last-message\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    command = codex_exec_command(VibePaths(tmp_path), "revised_plan", {"codex": {"approval_policy": "never"}}, tmp_path / "last.md")
    assert "--ask-for-approval" not in command
    assert "--approval-policy" not in command
    assert "--sandbox" in command
    assert "workspace-write" in command


def test_v0102_read_role_default_sandbox_is_writable(tmp_path: Path):
    assert codex_sandbox_for("revised_plan", {}) == "workspace-write"


def test_v0102_failed_codex_empty_output_replaces_stale_artifact_with_current_fallback(tmp_path: Path, monkeypatch):
    paths = initialized_paths(tmp_path)
    run_id = "r001"
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "revised_plan.md").write_text("# stale\n\n## Decision\nblocked_missing_decision\n")
    write_json(run_dir / "metrics.json", {"schema_valid": True, "metrics": {"primary": 1.0}})
    codex_exec_help.cache_clear()

    def fake_run(command, **kwargs):
        if command == ["codex", "exec", "--help"]:
            return subprocess.CompletedProcess(command, 0, stdout="Usage\n  -C\n  --sandbox\n  --output-last-message\n", stderr="")
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="unsupported runtime")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_codex(paths, "revised_plan", run_id, offline=False)
    assert result.exit_code == 2
    assert "collect_more_metrics" in (run_dir / "revised_plan.md").read_text()
    assert "blocked_missing_decision" not in (run_dir / "revised_plan.md").read_text()
