from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.io import read_json
from vibe_research.paths import VibePaths
from vibe_research.planner import build_draft_plan, validate_draft_plan, write_draft_plan


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def valid_plan_kwargs() -> dict[str, str]:
    return {
        "mode": "invent",
        "failure_anchor": "remote false positives persist after baseline filtering",
        "hypothesis": "a component veto can remove remote false positives",
        "mechanism": "component-veto-with-shape-prior",
        "minimum_experiment": "one-case component veto with saved mask artifact",
        "expected_artifact": ".vibe/runs/r001/component_veto_metrics.json",
        "expected_belief_update": "decide whether component veto has mechanism evidence",
        "compute_cost": "local cpu under 5 minutes",
        "risk": "may over-remove true positives",
        "fallback": "record negative evidence and try route-level filter",
        "stop_condition": "no component-level precision gain",
        "confidence": "speculative_mechanism",
    }


def test_planner_rejects_missing_failure_anchor(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    kwargs = valid_plan_kwargs()
    kwargs["failure_anchor"] = ""

    plan = build_draft_plan(VibePaths(tmp_path), **kwargs)
    ok, diagnostics = validate_draft_plan(plan)

    assert ok is False
    assert any(item["code"] == "missing_failure_anchor" for item in diagnostics)


def test_planner_rejects_missing_expected_belief_update(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    kwargs = valid_plan_kwargs()
    kwargs["expected_belief_update"] = ""

    plan = build_draft_plan(VibePaths(tmp_path), **kwargs)
    ok, diagnostics = validate_draft_plan(plan)

    assert ok is False
    assert any(item["code"] == "missing_expected_belief_update" for item in diagnostics)


def test_planner_downgrades_smoke_only_plan(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    kwargs = valid_plan_kwargs()
    kwargs["minimum_experiment"] = "import smoke check only"
    kwargs["expected_artifact"] = "smoke"

    plan = build_draft_plan(VibePaths(tmp_path), **kwargs)
    ok, diagnostics = validate_draft_plan(plan)

    assert ok is True
    assert plan["review_route"] == "requires_revision"
    assert any(item["code"] == "smoke_only" for item in diagnostics)


def test_planner_marks_negative_memory_overlap(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    (tmp_path / ".vibe" / "kernel" / "NEGATIVE_MEMORY.md").write_text("component-veto-with-shape-prior failed on fold0\n")

    plan = build_draft_plan(VibePaths(tmp_path), **valid_plan_kwargs())

    assert plan["review_route"] == "requires_revision"
    assert any(item["code"] == "negative_memory_overlap" for item in plan["diagnostics"])


def test_planner_writes_reviewable_draft_manifest(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    plan = build_draft_plan(VibePaths(tmp_path), **valid_plan_kwargs())
    ok, diagnostics = validate_draft_plan(plan)
    path = write_draft_plan(VibePaths(tmp_path), plan)

    assert ok is True
    assert not any(item["level"] == "error" for item in diagnostics)
    assert path.name == "draft_plan_manifest.json"
    saved = read_json(path, {})
    assert saved["session_role"] == "planner"
    assert saved["plan"]["expected_belief_update"]
    assert saved["review_route"] == "reviewer"


def test_planner_cli_writes_draft_without_approval(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    kwargs = valid_plan_kwargs()
    result = invoke(
        "planner",
        "draft",
        "--target",
        str(tmp_path),
        "--mode",
        kwargs["mode"],
        "--failure-anchor",
        kwargs["failure_anchor"],
        "--hypothesis",
        kwargs["hypothesis"],
        "--mechanism",
        kwargs["mechanism"],
        "--minimum-experiment",
        kwargs["minimum_experiment"],
        "--expected-artifact",
        kwargs["expected_artifact"],
        "--expected-belief-update",
        kwargs["expected_belief_update"],
        "--compute-cost",
        kwargs["compute_cost"],
        "--risk",
        kwargs["risk"],
        "--fallback",
        kwargs["fallback"],
        "--stop-condition",
        kwargs["stop_condition"],
        "--confidence",
        kwargs["confidence"],
    )

    assert result.exit_code == 0
    draft = read_json(tmp_path / ".vibe" / "kernel" / "draft_plan_manifest.json", {})
    assert draft["session_role"] == "planner"
    assert not (tmp_path / ".vibe" / "kernel" / "reviewed_plan_manifest.json").exists()
    assert not (tmp_path / ".vibe" / "kernel" / "execution_manifest.json").exists()
