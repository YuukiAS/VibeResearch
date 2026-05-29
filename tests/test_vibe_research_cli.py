from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.io import read_json


runner = CliRunner()


def invoke(*args: str, cwd: Path | None = None):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def test_init_creates_required_surface(tmp_path: Path):
    result = invoke("init", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert (tmp_path / ".vibe" / "config.yaml").exists()
    assert (tmp_path / ".vibe" / "dashboard" / "timeline.html").exists()
    assert (tmp_path / ".vibe" / "dashboard" / "timeline.svg").exists()
    assert (tmp_path / "RUN.md").exists()
    assert (tmp_path / "VIBE_STATUS.md").exists()
    assert (tmp_path / "VIBE_TODO.md").exists()
    assert (tmp_path / "VIBE_TIMELINE.md").exists()
    assert (tmp_path / "VIBE_LEADERBOARD.md").exists()


def test_cycle_run_queue_and_reflection_flow(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("idea", "try topology cleanup", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "2").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    run_id = sorted(state["runs"])[0]
    assert invoke("review", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("branch", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("dryrun", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("queue", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("submit-queue", "--target", str(tmp_path), "--dry").exit_code == 0
    assert invoke("monitor", "--target", str(tmp_path)).exit_code == 0
    assert invoke("collect", run_id, "--target", str(tmp_path), "--metric", "0.7", "--trusted").exit_code == 0
    assert invoke("reflect", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("revise-plan", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("reflect-cycle", "c001", "--target", str(tmp_path)).exit_code == 0
    assert invoke("revise-cycle", "c001", "--target", str(tmp_path), "--mode", "balanced").exit_code == 0
    assert (tmp_path / ".vibe" / "runs" / run_id / "revised_plan.md").read_text()
    assert "0.7" in (tmp_path / "VIBE_LEADERBOARD.md").read_text()
    assert "cycle_revised_plan_written" in (tmp_path / "VIBE_TIMELINE.md").read_text()


def test_literature_and_deep_research_interfaces(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--target", str(tmp_path)).exit_code == 0
    assert invoke("lit-refresh-cycle", "c001", "--target", str(tmp_path), "--query", "segmentation topology").exit_code == 0
    assert invoke("deep-request-cycle", "c001", "route selection", "--target", str(tmp_path)).exit_code == 0
    request = next((tmp_path / ".vibe" / "research" / "deep_requests").glob("dr*.md"))
    result_path = tmp_path / ".vibe" / "research" / "raw" / "deep_reports" / f"{request.stem}_result.md"
    result_path.write_text("# Report\n\nUse route A.")
    assert invoke("ingest-deep-research", request.stem, "--target", str(tmp_path)).exit_code == 0
    assert (tmp_path / ".vibe" / "research" / "wiki" / "synthesis" / f"{request.stem}.md").exists()

