from __future__ import annotations

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.io import read_json, read_jsonl
from vibe_research.os_beta import run_closed_loop_harness, validate_closed_loop
from vibe_research.paths import VibePaths


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def init_repo(tmp_path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    return VibePaths(tmp_path)


def test_os_beta_runs_complete_multi_session_closed_loop(tmp_path):
    paths = init_repo(tmp_path)

    report = run_closed_loop_harness(paths)

    assert report["chain_complete"] is True
    assert report["review_before_execute"] is True
    assert report["manifest_driven_execution"] is True
    assert report["reflect_before_next_plan"] is True
    assert report["role_isolation"]["ok"] is True
    assert (paths.kernel / "draft_plan_manifest.json").exists()
    assert (paths.kernel / "plan_review_report.md").exists()
    assert (paths.kernel / "reviewed_plan_manifest.json").exists()
    assert (paths.kernel / "execution_manifest.json").exists()
    assert (paths.executor / "result_report.md").exists()
    assert (paths.kernel / "reflect_report.md").exists()
    assert (paths.kernel / "belief_ratchet_record.json").exists()
    assert read_jsonl(paths.kernel / "RESEARCH_REGISTRY.jsonl")


def test_os_beta_validate_requires_closed_loop_artifacts(tmp_path):
    paths = init_repo(tmp_path)

    missing = validate_closed_loop(paths)
    run_closed_loop_harness(paths)
    ok = validate_closed_loop(paths)

    assert missing["ok"] is False
    assert ok["ok"] is True


def test_os_beta_registry_blocking_debt_and_low_quota_probe(tmp_path):
    paths = init_repo(tmp_path)

    report = run_closed_loop_harness(paths)

    assert report["registry_blocking"]["blocked"] is True
    assert report["debt_clearing"]["cleared_count"] >= 1
    assert report["low_quota_checkpoint"]["blocked"] is True
    assert report["low_quota_checkpoint"]["checkpoint_path"]
    assert (tmp_path / "RESUME.md").exists()


def test_os_beta_cli_roundtrip(tmp_path):
    init_repo(tmp_path)

    run = invoke("os-beta", "run", "--target", str(tmp_path))
    validate = invoke("os-beta", "validate", "--target", str(tmp_path))

    assert run.exit_code == 0
    assert validate.exit_code == 0
    report = read_json(tmp_path / ".vibe" / "kernel" / "OS_BETA_HARNESS.json", {})
    assert report["chain_complete"] is True
