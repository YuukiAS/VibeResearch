from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.daemon import daemon_autonomy_audit, daemon_status
from vibe_research.io import write_json
from vibe_research.paths import VibePaths


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
