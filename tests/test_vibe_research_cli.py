from __future__ import annotations

from pathlib import Path
import os

from typer.testing import CliRunner

from vibe_research.artifacts import validate_artifact
from vibe_research.codex_adapter import run_codex
from vibe_research.cli import app
from vibe_research.config import detect_config
from vibe_research.io import read_json, read_yaml
from vibe_research.paths import VibePaths
from vibe_research.portal import GENERATED_NOTICE


runner = CliRunner()


def invoke(*args: str, cwd: Path | None = None):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def test_init_creates_required_surface(tmp_path: Path):
    result = invoke("init", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert (tmp_path / ".vibe" / "config.yaml").exists()
    assert (tmp_path / ".vibe" / "config.local.yaml").exists()
    assert (tmp_path / ".vibe" / "config.schema.json").exists()
    assert (tmp_path / ".vibe" / "portal").exists()
    assert (tmp_path / ".vibe" / "dashboard" / "timeline.html").exists()
    assert (tmp_path / ".vibe" / "dashboard" / "timeline.svg").exists()
    assert (tmp_path / "RUN.md").exists()
    assert (tmp_path / "VIBE_STATUS.md").exists()
    assert (tmp_path / "VIBE_TODO.md").exists()
    assert (tmp_path / "VIBE_TIMELINE.md").exists()
    assert (tmp_path / "VIBE_LEADERBOARD.md").exists()
    assert (tmp_path / "RUN.md").read_text().startswith(GENERATED_NOTICE)


def test_config_commands_and_schema_validation(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    result = invoke("config", "validate", "--target", str(tmp_path))
    assert result.exit_code == 0
    show = invoke("config", "show", "--target", str(tmp_path))
    assert show.exit_code == 0
    assert "0.4.0" in show.output
    schema = read_json(tmp_path / ".vibe" / "config.schema.json", {})
    assert schema["title"] == "ProjectConfig"


def test_config_detect_with_fake_slurm_and_gpu_commands(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    scripts = {
        "sinfo": "print('gpu_short gpu:a100:2')",
        "squeue": "print('123 gpu_short job user R 00:01 1 node')",
        "sacct": "print('123|COMPLETED|00:01:00')",
        "sbatch": "print('slurm 23.11')",
        "scancel": "print('slurm 23.11')",
        "nvidia-smi": "print('NVIDIA A100-SXM4-40GB')",
    }
    for name, body in scripts.items():
        path = fake_bin / name
        path.write_text(f"#!/usr/bin/env python3\n{body}\n")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH','')}")
    detected = detect_config(VibePaths(tmp_path), write=True)
    assert detected["commands"]["sinfo"]["available"]
    assert detected["gpu"]["count"] == 1
    assert (tmp_path / ".vibe" / "config.detected.yaml").exists()
    written = read_yaml(tmp_path / ".vibe" / "config.detected.yaml", {})
    assert written["suggested_config"]["execution"]["backend"] == "slurm"


def test_default_portal_creation_and_rebuild(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    (tmp_path / "VIBE_STATUS.md").unlink()
    assert invoke("portal", "build", "--target", str(tmp_path)).exit_code == 0
    assert (tmp_path / "VIBE_STATUS.md").exists()
    assert (tmp_path / "VIBE_STATUS.md").read_text().startswith(GENERATED_NOTICE)


def test_init_minimal_no_root_portal_creates_only_vibe_root(tmp_path: Path):
    result = invoke("init", "--minimal", "--no-root-portal", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == [".vibe"]
    assert (tmp_path / ".vibe" / "portal" / "RUN.md").exists()
    assert not (tmp_path / "RUN.md").exists()


def test_agents_snippet_generation_and_explicit_install(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert (tmp_path / ".vibe" / "AGENTS.md").exists()
    assert (tmp_path / ".vibe" / "AGENTS_SNIPPET.md").exists()
    assert not (tmp_path / "AGENTS.md").exists()
    second = tmp_path / "with_agents"
    assert invoke("init", "--target", str(second), "--install-agents-snippet").exit_code == 0
    assert "VIBERESEARCH_AGENTS_SNIPPET_START" in (second / "AGENTS.md").read_text()


def test_audit_current_writes_alignment_report(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    result = invoke("audit", "current", "--target", str(tmp_path))
    assert result.exit_code == 0
    report = tmp_path / ".vibe" / "reports" / "dev" / "current_alignment_audit.md"
    assert report.exists()
    text = report.read_text()
    assert "root portal" in text
    assert "AGENTS snippet" in text


def test_cycle_run_queue_and_reflection_flow(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("idea", "try topology cleanup", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "2").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    run_id = sorted(state["runs"])[0]
    assert invoke("review", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("branch", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("patch", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("dryrun", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("queue", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("submit-queue", "--target", str(tmp_path), "--dry").exit_code == 0
    assert invoke("monitor", "--target", str(tmp_path)).exit_code == 0
    assert invoke("collect", run_id, "--target", str(tmp_path), "--metric", "0.7", "--trusted").exit_code == 0
    assert invoke("reflect", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("revise-plan", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("reflect-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("revise-cycle", "c001", "--offline", "--target", str(tmp_path), "--mode", "balanced").exit_code == 0
    assert invoke("validate-hard-rules", "--target", str(tmp_path)).exit_code == 0
    assert (tmp_path / ".vibe" / "runs" / run_id / "revised_plan.md").read_text()
    assert "0.7" in (tmp_path / "VIBE_LEADERBOARD.md").read_text()
    assert "cycle_revised_plan_written" in (tmp_path / "VIBE_TIMELINE.md").read_text()


def test_literature_and_deep_research_interfaces(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("lit-refresh-cycle", "c001", "--target", str(tmp_path), "--query", "segmentation topology").exit_code == 0
    assert invoke("deep-request-cycle", "c001", "route selection", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert "Next:" in invoke("next", "--target", str(tmp_path)).output
    request = next((tmp_path / ".vibe" / "research" / "deep_requests").glob("dr*.md"))
    result_path = tmp_path / ".vibe" / "research" / "raw" / "deep_reports" / f"{request.stem}_result.md"
    result_path.write_text("# Report\n\nUse route A.")
    assert invoke("ingest-deep-research", request.stem, "--target", str(tmp_path)).exit_code == 0
    assert (tmp_path / ".vibe" / "research" / "wiki" / "synthesis" / f"{request.stem}.md").exists()


def test_expanded_operator_commands(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("migrate", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    run_id = sorted(state["runs"])[0]
    assert invoke("validate-manifest", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("scheduler-status", "--target", str(tmp_path)).exit_code == 0
    assert invoke("paper-search", "topology", "--target", str(tmp_path), "--offline").exit_code == 0
    assert invoke("paper-add", "Example Paper", "--target", str(tmp_path), "--source-url", "https://arxiv.org/abs/0000.0000").exit_code == 0
    assert invoke("paper-list", "--target", str(tmp_path)).exit_code == 0
    assert invoke("wiki-ingest", "p_example-paper", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert (tmp_path / ".vibe" / "research" / "wiki" / "concepts" / "paper-methods.md").exists()
    assert invoke("wiki-lint", "--target", str(tmp_path)).exit_code == 0
    assert invoke("codex-plan", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("daemon", "status", "--target", str(tmp_path)).exit_code == 0


def test_slurm_dry_backend_records_launch(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    run_id = sorted(state["runs"])[0]
    assert invoke("review", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("patch", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("dryrun", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("queue", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("submit-queue", "--target", str(tmp_path), "--backend", "slurm", "--dry").exit_code == 0
    launch = read_json(tmp_path / ".vibe" / "runs" / run_id / "launch.json", {})
    assert launch["backend"] == "slurm"
    assert "partition_reason" in launch
    assert (tmp_path / ".vibe" / "runs" / run_id / "artifacts" / f"{run_id}.sbatch").exists()


def test_blocking_deep_research_blocks_next(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("deep-request-cycle", "c001", "route selection", "--blocking", "--offline", "--target", str(tmp_path)).exit_code == 0
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "blocked_waiting_deep_research" in result.output


def test_auto_cycle_reaches_first_submission(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    result = invoke("auto-cycle", "--offline", "--dry-submit", "--max-steps", "12", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "planned c001" in result.output
    assert "reviewed c001" in result.output
    assert "generated r001_baseline_check" in result.output
    assert "submitted r001_baseline_check" in result.output


def test_codex_runner_uses_fake_codex_and_writes_artifact(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "args=sys.argv\n"
        "out=pathlib.Path(args[args.index('--output-last-message')+1])\n"
        "out.write_text('# Portfolio Plan for c001\\n\\n## Stage\\nexploration\\n\\n## Current leaderboard summary\\nnone\\n\\n## User ideas and directives considered\\nnone\\n\\n## Candidate directions\\n- baseline\\n\\n## Selected runs\\n- r001\\n\\n## Dependency graph\\nnone\\n\\n## Resource budget\\ndefault\\n\\n## Portfolio success criteria\\nlearn\\n\\n## Stop or shrink criteria\\nstop failures\\n')\n"
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH','')}")
    result = run_codex(VibePaths(tmp_path), "portfolio_planner", "c001")
    assert result.ok
    assert "Portfolio Plan" in (tmp_path / ".vibe" / "cycles" / "c001" / "portfolio_plan.md").read_text()
    assert not validate_artifact(VibePaths(tmp_path), "portfolio_planner", "c001")


def test_todo_cli_commands_exist():
    result = invoke("--help")
    help_text = result.output
    for command in [
        "init",
        "audit",
        "config",
        "portal",
        "status",
        "idea",
        "directive",
        "plan-cycle",
        "review-cycle",
        "generate-runs",
        "review",
        "branch",
        "patch",
        "dryrun",
        "queue",
        "submit-queue",
        "monitor",
        "collect",
        "reflect",
        "revise-plan",
        "reflect-cycle",
        "revise-cycle",
        "lit-refresh",
        "lit-refresh-cycle",
        "deep-request",
        "deep-request-cycle",
        "ingest-deep-research",
        "wiki-ingest",
        "leaderboard",
        "timeline",
        "merge",
        "abandon",
        "next",
    ]:
        assert command in help_text
