from __future__ import annotations

from typer.testing import CliRunner

from vibe_research.anti_stall import run_anti_stall_benchmark, validate_anti_stall_report
from vibe_research.cli import app
from vibe_research.io import read_json, read_jsonl
from vibe_research.paths import VibePaths


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def init_repo(tmp_path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    return VibePaths(tmp_path)


def test_anti_stall_benchmark_passes_all_categories(tmp_path):
    paths = init_repo(tmp_path)

    report = run_anti_stall_benchmark(paths)

    assert validate_anti_stall_report(report) == []
    assert report["score"]["passed"] == report["score"]["total"]
    assert all(report["score"]["categories"].values())


def test_anti_stall_covers_required_traps(tmp_path):
    paths = init_repo(tmp_path)

    report = run_anti_stall_benchmark(paths)
    traps = report["traps"]

    assert traps["generic_unet_rejected"]["passed"] is True
    assert traps["negative_memory_checked"]["passed"] is True
    assert traps["clone_repo_requires_mve"]["passed"] is True
    assert traps["one_case_promotes_subset_debt"]["passed"] is True
    assert traps["smoke_is_feasibility_only"]["passed"] is True
    assert traps["watch_debt_cleared"]["passed"] is True
    assert traps["orphan_knowledge_cleared"]["passed"] is True
    assert traps["registry_duplicate_blocked"]["blocked"] is True
    assert traps["low_quota_checkpoint_resume"]["resume_exists"] is True


def test_anti_stall_writes_registry_and_resume(tmp_path):
    paths = init_repo(tmp_path)

    run_anti_stall_benchmark(paths)

    registry_events = [row["event_type"] for row in read_jsonl(paths.kernel / "RESEARCH_REGISTRY.jsonl")]
    assert "expired_orphan" in registry_events
    assert "decision_debt_clearance" in registry_events
    assert (tmp_path / "RESUME.md").exists()


def test_anti_stall_cli_roundtrip(tmp_path):
    init_repo(tmp_path)

    run = invoke("anti-stall", "run", "--target", str(tmp_path))
    validate = invoke("anti-stall", "validate", "--target", str(tmp_path))

    assert run.exit_code == 0
    assert validate.exit_code == 0
    report = read_json(tmp_path / ".vibe" / "kernel" / "ANTI_STALL_BENCHMARK.json", {})
    assert report["score"]["passed"] == report["score"]["total"]
