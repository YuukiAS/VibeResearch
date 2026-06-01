from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
import os
import subprocess
import sys
from shlex import quote as shlex_quote

from typer.testing import CliRunner

from vibe_research.artifacts import validate_artifact
from vibe_research.adapter_schema import AdapterCapability, AdapterManifest, ArtifactRules, MetricsSchema, ResourcePolicy, load_adapter_manifest, write_adapter_manifest
from vibe_research.automation import auto_cycle, auto_next
from vibe_research.codex_adapter import prompt_packet, run_codex
from vibe_research.cli import app
from vibe_research.config import detect_config, load_config
from vibe_research.daemon import daemon_start, daemon_status
from vibe_research.decisions import make_decision, write_decision
from vibe_research.ideas import create_idea
from vibe_research.io import append_jsonl, read_json, read_jsonl, read_yaml, write_json, write_yaml
from vibe_research.loop_guard import apply_loop_guard
from vibe_research.models import ProjectConfig
from vibe_research.paths import VibePaths
from vibe_research.papers import auto_method_search
from vibe_research.portal import GENERATED_NOTICE
from vibe_research.promotion import compile_decision, ensure_executable_resource_plan, synthesize_cycle_decision
from vibe_research.research_manager import default_candidates
from vibe_research.resource_policy import normalize_run_resources
from vibe_research.scheduler import collect as collect_run
from vibe_research.scheduler import paused_direction
from vibe_research.scheduler import should_requeue_to_fallback
from vibe_research.backends import PollResult, SlurmBackend, fallback_completion_estimates, start_plus_run_hours
from vibe_research.slurm import choose_partition, render_sbatch


runner = CliRunner()


def invoke(*args: str, cwd: Path | None = None):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def answer_all_research_questions(root: Path) -> None:
    for question in read_jsonl(root / ".vibe" / "research" / "questions.jsonl"):
        if question.get("status", "open") == "open":
            result = invoke("research", "answer", str(question["question_id"]), "--answer", "confirmed for test", "--target", str(root))
            assert result.exit_code == 0


def enable_toy_adapter(root: Path) -> None:
    (root / ".vibe" / "config.local.yaml").write_text("adapter:\n  kind: toy\n")
    paths = VibePaths(root)
    manifest = AdapterManifest(
        project_id=root.name,
        project_name=root.name,
        open_questions=[],
        capabilities=[
            AdapterCapability(
                id="toy-metrics-export",
                version="test",
                status="active",
                task_type="metrics_export",
                supported_decisions=["collect_more_metrics"],
                description="Test-only active instrumentation capability for toy adapter readiness.",
                dryrun={"command": "python3 -c 'import json, pathlib; p=pathlib.Path(\".vibe/toy_contract.json\"); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({\"primary\": 1.0})+\"\\n\")'"},
                entrypoint={"type": "local", "command": "python3 -c 'import json, pathlib; p=pathlib.Path(\".vibe/toy_contract.json\"); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({\"primary\": 1.0})+\"\\n\")'"},
                outputs={"expected_output_path": ".vibe/toy_contract.json", "metrics_file_path": ".vibe/toy_contract.json"},
                metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="test"),
                artifact_rules=ArtifactRules(expected_outputs=[".vibe/toy_contract.json"], trusted_path_patterns=[".vibe/*.json"], version="test"),
                resources=ResourcePolicy(automatic_submission_allowed=False, user_confirmation_required=False),
                trust_checks=["schema_valid_metrics", "expected_output_exists"],
                contract_tests=["toy-metrics-export"],
                activation={"contract_status": "passed", "contract_test_result_id": "test", "command_template_hash": "test", "metrics_schema_hash": "test", "artifact_rule_hash": "test"},
            )
        ],
    )
    write_adapter_manifest(paths, manifest)
    write_json(root / ".vibe" / "contract_tests" / "toy-metrics-export.json", {"capability_id": "toy-metrics-export", "status": "passed", "created_at": "test"})


def enable_train_smoke_adapter(root: Path) -> None:
    (root / ".vibe" / "config.local.yaml").write_text("adapter:\n  kind: config\n")
    paths = VibePaths(root)
    manifest = AdapterManifest(
        project_id=root.name,
        project_name=root.name,
        open_questions=[],
        capabilities=[
            AdapterCapability(
                id="train-smoke",
                version="test",
                status="active",
                task_type="train_smoke",
                supported_decisions=["launch_gpu_gate"],
                description="Test-only Slurm-backed train smoke capability.",
                dryrun={"command": "python3 -c 'print(\"dry\")'"},
                entrypoint={"type": "slurm", "command": "python3 -c 'import json, pathlib; pathlib.Path(\".vibe/train_metrics.json\").write_text(json.dumps({\"primary\": 1.0, \"classification\": \"pass\"}))'"},
                outputs={"expected_output_path": ".vibe/train_metrics.json", "metrics_file_path": ".vibe/train_metrics.json"},
                metrics_schema=MetricsSchema(required=["primary", "classification"], types={"primary": "number", "classification": "string"}, primary_metric="primary", version="test"),
                artifact_rules=ArtifactRules(expected_outputs=[".vibe/train_metrics.json"], trusted_path_patterns=[".vibe/*.json"], version="test"),
                resources=ResourcePolicy(
                    automatic_submission_allowed=True,
                    user_confirmation_required=False,
                    allowed_backends=["slurm"],
                    default={"gpu": 1, "cpus": 1, "mem_gb": 1, "time": "00:10:00", "qos": "gpu_access"},
                ),
                trust_checks=["schema_valid_metrics", "expected_output_exists"],
                contract_tests=["train-smoke"],
                activation={"contract_status": "passed", "contract_test_result_id": "test", "command_template_hash": "test", "metrics_schema_hash": "test", "artifact_rule_hash": "test"},
            )
        ],
    )
    write_adapter_manifest(paths, manifest)
    write_json(root / ".vibe" / "contract_tests" / "train-smoke.json", {"capability_id": "train-smoke", "status": "passed", "created_at": "test"})


def compile_toy_cycle(root: Path, cycle_id: str = "c001") -> None:
    paths = VibePaths(root)
    decision = make_decision(
        paths,
        cycle_id,
        "launch_gpu_gate",
        rationale="test toy adapter compilation",
        selected_direction="d001_toy",
        required_action="run toy adapter task",
        confidence="high",
    )
    write_decision(paths, decision)
    ok, message = compile_decision(paths, cycle_id)
    assert ok, message


def write_run_decision(root: Path, run_id: str) -> None:
    paths = VibePaths(root)
    decision = make_decision(
        paths,
        run_id,
        "collect_more_metrics",
        rationale="test run decision",
        required_action="collect schema-valid metrics",
        confidence="medium",
    )
    write_decision(paths, decision)


def prepare_toy_run(root: Path) -> str:
    assert invoke("init", "--target", str(root)).exit_code == 0
    enable_toy_adapter(root)
    assert invoke("plan-cycle", "--offline", "--target", str(root)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(root)).exit_code == 0
    compile_toy_cycle(root)
    assert invoke("generate-runs", "c001", "--target", str(root), "--count", "1").exit_code == 0
    return sorted(read_json(root / ".vibe" / "state" / "state.json", {})["runs"])[0]


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


def test_init_brief_and_initial_ideas(tmp_path: Path):
    idea_file = tmp_path / "ideas.txt"
    idea_file.write_text("- idea from file\n")
    result = invoke(
        "init",
        "--target",
        str(tmp_path / "repo"),
        "--goal",
        "Improve validation",
        "--background",
        "Medical segmentation benchmark",
        "--idea",
        "try calibration",
        "--idea-file",
        str(idea_file),
    )
    assert result.exit_code == 0
    repo = tmp_path / "repo"
    assert "Improve validation" in (repo / ".vibe" / "project" / "brief.md").read_text()
    ideas = read_jsonl(repo / ".vibe" / "ideas" / "registry.jsonl")
    assert [row["source"] for row in ideas] == ["init", "init"]
    assert invoke("vendor-runtime", "--target", str(repo)).exit_code == 0
    assert (repo / ".vibe" / "runtime" / "README.md").exists()


def test_minimal_init_marks_missing_brief(tmp_path: Path):
    assert invoke("init", "--minimal", "--no-root-portal", "--target", str(tmp_path)).exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert state["project_brief_missing"] is True
    result = invoke("next", "--target", str(tmp_path))
    assert "project_brief_missing" in result.output


def test_init_always_creates_resource_onboarding(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    questions = read_yaml(tmp_path / ".vibe" / "resources" / "policy_questions.yaml", {})
    assert questions["status"] in {"needs_resource_answers", "configured_needs_confirmation"}
    question_ids = {row["id"] for row in questions["questions"]}
    assert {"q_resource_mode", "q_slurm_partitions", "q_slurm_gres", "q_experiment_runtime_caps", "q_delivery_runtime_caps", "q_gpu_submission_permission"} <= question_ids
    detected = read_yaml(tmp_path / ".vibe" / "resources" / "detected.yaml", {})
    assert "slurm" in detected
    assert "gpu" in detected
    assert (tmp_path / ".vibe" / "config.detected.yaml").exists()
    research_questions = {row["question_id"] for row in read_jsonl(tmp_path / ".vibe" / "research" / "questions.jsonl")}
    assert {
        "q_init_project_goal",
        "q_init_project_background",
        "q_init_initial_ideas",
        "q_init_resource_mode",
        "q_init_slurm_partitions",
        "q_init_slurm_gres",
        "q_init_queue_wait_limit",
        "q_init_experiment_runtime_cap",
        "q_init_delivery_runtime_cap",
        "q_init_gpu_submission_permission",
        "q_init_budget_caps",
        "q_init_autonomy_level",
        "q_init_primary_metric",
        "q_init_protected_metrics",
        "q_init_adapter_execution_surface",
    } <= research_questions
    by_id = {row["question_id"]: row for row in read_jsonl(tmp_path / ".vibe" / "research" / "questions.jsonl")}
    assert by_id["q_init_project_goal"]["requires_user_answer"] is True
    assert by_id["q_init_initial_ideas"]["answer_can_be"] == "none"
    assert by_id["q_init_slurm_gres"]["requires_user_answer"] is True
    answered = invoke("research", "answer", "q_init_budget_caps", "--answer", "daily 4 jobs, 8 gpu hours", "--target", str(tmp_path))
    assert answered.exit_code == 0
    assert any(row.get("question_id") == "q_init_budget_caps" and row.get("status") == "answered" for row in read_jsonl(tmp_path / ".vibe" / "research" / "questions.jsonl"))


def test_config_commands_and_schema_validation(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    result = invoke("config", "validate", "--target", str(tmp_path))
    assert result.exit_code == 0
    show = invoke("config", "show", "--target", str(tmp_path))
    assert show.exit_code == 0
    assert "0.12.1" in show.output
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
    assert detected["slurm"]["partitions"] == [{"name": "gpu_short", "gres_raw": "gpu:a100:2", "gres": "gpu:a100:{gpu}"}]
    assert detected["suggested_config"]["execution"]["slurm"]["gres_by_partition"] == {"gpu_short": "gpu:a100:{gpu}"}
    assert detected["gpu"]["count"] == 1
    assert (tmp_path / ".vibe" / "config.detected.yaml").exists()
    written = read_yaml(tmp_path / ".vibe" / "config.detected.yaml", {})
    assert written["suggested_config"]["execution"]["backend"] == "slurm"


def test_v0835_yaml_config_overrides_stale_json_mirror(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    config_yaml = read_yaml(tmp_path / ".vibe" / "config.yaml", {})
    config_json = read_json(tmp_path / ".vibe" / "config.json", {})
    config_yaml.setdefault("execution", {}).setdefault("slurm", {})["default_partition"] = "htzhulab"
    config_yaml["execution"]["slurm"]["preferred_partitions"] = ["htzhulab"]
    config_yaml["execution"]["slurm"]["fallback_partitions"] = ["a100-gpu", "volta-gpu"]
    config_json.setdefault("execution", {}).setdefault("slurm", {})["default_partition"] = "gpu_short"
    config_json["execution"]["slurm"]["preferred_partitions"] = ["gpu_short"]
    config_json["execution"]["slurm"]["fallback_partitions"] = ["gpu"]
    write_yaml(tmp_path / ".vibe" / "config.yaml", config_yaml)
    write_json(tmp_path / ".vibe" / "config.json", config_json)

    loaded = load_config(VibePaths(tmp_path), include_local=False)
    assert loaded["execution"]["slurm"]["default_partition"] == "htzhulab"
    assert loaded["execution"]["slurm"]["preferred_partitions"] == ["htzhulab"]
    assert loaded["execution"]["slurm"]["fallback_partitions"] == ["a100-gpu", "volta-gpu"]


def test_default_portal_creation_and_rebuild(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    (tmp_path / "VIBE_STATUS.md").unlink()
    assert invoke("portal", "build", "--target", str(tmp_path)).exit_code == 0
    assert (tmp_path / "VIBE_STATUS.md").exists()
    assert (tmp_path / "VIBE_STATUS.md").read_text().startswith(GENERATED_NOTICE)


def test_v0838_portal_rebuild_tolerates_disappearing_root_mirror(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    original_unlink = Path.unlink
    calls = []

    def racing_unlink(self, missing_ok=False):
        if self == tmp_path / "RUN.md":
            calls.append(missing_ok)
            original_unlink(self, missing_ok=True)
            return original_unlink(self, missing_ok=missing_ok)
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", racing_unlink)
    result = invoke("portal", "build", "--target", str(tmp_path), "--force")
    assert result.exit_code == 0
    assert True in calls
    assert (tmp_path / "RUN.md").exists()


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


def test_v080_research_init_registry_policy_memory_memo_and_exports(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve robust validation", "--background", "Synthetic benchmark").exit_code == 0
    assert (tmp_path / ".vibe" / "research" / "events.jsonl").exists()
    assert (tmp_path / ".vibe" / "policies" / "budget.yaml").exists()
    assert invoke("policy", "lint", "--target", str(tmp_path)).exit_code == 0
    created = invoke("hypothesis", "create", "try calibrated evaluator", "--stage", "analysis", "--target", str(tmp_path))
    assert created.exit_code == 0
    hypotheses = read_json(tmp_path / ".vibe" / "research" / "hypotheses.json", {})
    hyp_id = next(iter(hypotheses))
    assert invoke("experiment", "create", hyp_id, "--design", "calibration smoke", "--stage", "analysis", "--target", str(tmp_path)).exit_code == 0
    stage_policy = read_yaml(tmp_path / ".vibe" / "policies" / "stage_gates.yaml", {})
    stage_policy["protected_metrics"] = {"guardrail": {"max_regression": 0.0}}
    write_yaml(tmp_path / ".vibe" / "policies" / "stage_gates.yaml", stage_policy)
    experiments = read_json(tmp_path / ".vibe" / "research" / "experiments.json", {})
    exp_id = next(iter(experiments))
    assert invoke("experiment", "analyze", exp_id, "--trusted", "--schema-valid", "--summary", "trusted positive evidence", "--primary-delta", "0.2", "--target", str(tmp_path)).exit_code == 0
    assert invoke("hypothesis", "promote", hyp_id, "--reason", "trusted improvement", "--target", str(tmp_path)).exit_code == 0
    assert invoke("memory", "build", "--target", str(tmp_path)).exit_code == 0
    assert invoke("memo", "daily", "--target", str(tmp_path), "--language", "zh-CN").exit_code == 0
    memo_text = next((tmp_path / ".vibe" / "memos").glob("*.md")).read_text()
    assert "每日研究日志" in memo_text
    assert invoke("dashboard", "export-research", "--target", str(tmp_path)).exit_code == 0
    graph = read_json(tmp_path / ".vibe" / "dashboard" / "hypothesis_graph.json", {})
    assert any(edge["type"] == "hypothesis_to_experiment" for edge in graph["edges"])


def test_v0109_research_init_syncs_repaired_project_brief_to_config_and_questions(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--no-root-portal").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    questions_path = tmp_path / ".vibe" / "research" / "questions.jsonl"
    questions_path.write_text("")
    append_jsonl(questions_path, {"question_id": "missing_project_goal", "status": "open"})
    append_jsonl(questions_path, {"question_id": "missing_project_background", "status": "open"})
    (tmp_path / ".vibe" / "project" / "brief.md").write_text(
        "# Project Brief\n\n"
        "## Goal\n"
        "Run a generic evidence-gated research pipeline.\n\n"
        "## Background\n"
        "The project has concrete baseline, metrics, and compute constraints.\n"
    )
    stale = read_yaml(tmp_path / ".vibe" / "config.yaml", {})
    stale.setdefault("project", {})["goal"] = "Define the research objective for stale."
    stale["project"]["background"] = "Project background has not been supplied yet; update .vibe/project/brief.md before serious planning."
    write_yaml(tmp_path / ".vibe" / "config.yaml", stale)
    write_json(tmp_path / ".vibe" / "config.json", stale)

    result = invoke("research", "init", "--target", str(tmp_path))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert not [row for row in data["open_questions"] if row.get("question_id") in {"missing_project_goal", "missing_project_background"}]
    config = read_yaml(tmp_path / ".vibe" / "config.yaml", {})
    assert config["project"]["goal"] == "Run a generic evidence-gated research pipeline."
    assert "concrete baseline" in config["project"]["background"]
    by_id = {row["question_id"]: row for row in read_jsonl(questions_path)}
    assert by_id["missing_project_goal"]["status"] == "resolved"
    assert by_id["missing_project_background"]["status"] == "resolved"


def test_v01010_dryrun_refuses_active_submitted_run_without_state_rollback(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    run_id = "r001_active"
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    run = {
        "run_id": run_id,
        "cycle_id": "c001",
        "status": "submitted",
        "entrypoint": {"type": "slurm", "command": "python train.py"},
        "dryrun": {"command": "python -c 'print(1)'"},
        "resources": {"gpu": 1, "cpus": 1, "mem_gb": 1, "time": "00:10:00"},
    }
    state.setdefault("runs", {})[run_id] = run
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True)
    write_json(run_dir / "manifest.json", run)
    write_yaml(run_dir / "manifest.yaml", run)
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [{"run_id": run_id, "backend": "slurm", "job_id": "123", "status": "submitted"}]})

    result = invoke("dryrun", run_id, "--target", str(tmp_path))
    assert result.exit_code != 0
    assert "already active/submitted" in result.output
    updated = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert updated["runs"][run_id]["status"] == "submitted"


def test_v01011_next_collects_finished_current_cycle_before_idea_refresh(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    create_idea(VibePaths(tmp_path), "needs literature")
    ideas = read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")
    ideas[0]["status"] = "needs_literature_refresh"
    (tmp_path / ".vibe" / "ideas" / "registry.jsonl").write_text("")
    for row in ideas:
        append_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl", row)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state.update(
        {
            "current_cycle_id": "c001",
            "cycles": {"c001": {"status": "reviewed"}},
            "runs": {"r001_done": {"run_id": "r001_done", "cycle_id": "c001", "status": "finished"}},
            "next_action": "vibe reflect-cycle c001",
        }
    )
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)

    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "vibe collect r001_done" in result.output
    assert "lit-refresh-idea" not in result.output
    assert "reflect-cycle" not in result.output


def test_v01016_current_cycle_output_lifecycle_preempts_cycle_closeout(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    for status, expected in [
        ("finished", "vibe collect r001"),
        ("collected", "vibe reflect r001"),
        ("reflected", "vibe revise-plan r001"),
    ]:
        cycle_dir = tmp_path / ".vibe" / "cycles" / "c001"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        for artifact in ["cycle_reflect.md", "cycle_revised_plan.md"]:
            path = cycle_dir / artifact
            if path.exists():
                path.unlink()
        state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
        state.update(
            {
                "current_cycle_id": "c001",
                "cycles": {"c001": {"status": "reviewed"}},
                "runs": {"r001": {"run_id": "r001", "cycle_id": "c001", "status": status}},
                "next_action": "vibe reflect-cycle c001",
            }
        )
        write_json(tmp_path / ".vibe" / "state" / "state.json", state)
        result = invoke("next", "--target", str(tmp_path))
        assert result.exit_code == 0
        assert expected in result.output
        assert "reflect-cycle" not in result.output


def test_v01017_real_progress_counts_nested_baseline_metrics(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    run_id = "r001_real"
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state.setdefault("runs", {})[run_id] = {
        "run_id": run_id,
        "cycle_id": "c001",
        "status": "collected",
        "run_kind": "real_experiment",
        "backend": "slurm",
        "adapter_metadata": {"task_type": "train_smoke", "capability_id": "train-smoke"},
    }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True)
    write_json(run_dir / "launch.json", {"backend": "slurm", "job_id": "123"})
    write_json(
        run_dir / "metrics.json",
        {
            "schema_status": "valid",
            "missing_metrics": False,
            "metrics": {
                "primary": 0.9,
                "baseline_metrics": {"primary": 0.8},
                "metric_delta": {"primary": 0.1},
            },
        },
    )

    result = invoke("experiment", "real-progress", "--target", str(tmp_path))
    assert result.exit_code == 0
    progress = json.loads(result.output)
    row = next(item for item in progress["all_runs"] if item["run_id"] == run_id)
    assert row["counts_toward_real_experiment_cycle"] is True
    assert row["has_baseline_comparison"] is True
    assert row["classification"] == "counted"
    assert progress["non_counting_real_experiment_runs"] == []


def test_v01018_offline_revise_preserves_completed_trusted_candidate_run(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    run_id = "r001_real"
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state.setdefault("runs", {})[run_id] = {
        "run_id": run_id,
        "cycle_id": "c001",
        "status": "collected",
        "run_kind": "real_experiment",
        "backend": "slurm",
    }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "reflect.md").write_text("# Reflect\n\nschema-valid metrics collected\n")
    write_json(
        run_dir / "metrics.json",
        {
            "schema_status": "valid",
            "missing_metrics": False,
            "trusted_candidate": True,
            "trusted": False,
            "metrics": {"primary": 1.0},
        },
    )

    result = invoke("revise-plan", run_id, "--offline", "--target", str(tmp_path))
    assert result.exit_code == 0
    updated = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert updated["runs"][run_id]["status"] == "revised"
    decision = read_json(run_dir / "decision.json", {})
    assert decision["decision_type"] == "collect_more_metrics"
    assert decision["decision_type"] != "blocked_missing_decision"


def test_v01019_current_cycle_run_step_preempts_stale_real_repair(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    write_json(
        tmp_path / ".vibe" / "research" / "real_experiment_progress.json",
        {
            "non_counting_real_experiment_runs": [
                {
                    "run_id": "r001_old",
                    "status": "failed",
                    "requires_repair": True,
                }
            ]
        },
    )
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state.update(
        {
            "current_cycle_id": "c002",
            "cycles": {
                "c001": {"status": "reviewed"},
                "c002": {"status": "reviewed"},
            },
            "runs": {
                "r001_old": {"run_id": "r001_old", "cycle_id": "c001", "status": "failed", "run_kind": "real_experiment"},
                "r002_new": {"run_id": "r002_new", "cycle_id": "c002", "status": "generated"},
            },
        }
    )
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)

    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "vibe review r002_new" in result.output
    assert "vibe experiment real-progress" not in result.output


def test_v01011_compatible_preferred_partition_remains_ahead_of_available_fallback(monkeypatch):
    monkeypatch.setattr("vibe_research.slurm.probe_available_partitions", lambda: ({"a100-gpu"}, "sinfo"))
    manifest = {
        "resources": {
            "gpu": 1,
            "preferred_partitions": ["lab-gpu"],
            "fallback_partitions": ["a100-gpu"],
            "min_cuda_compute_capability": 7.5,
        }
    }
    config = {
        "execution": {
            "slurm": {
                "partitions": [
                    {"name": "lab-gpu", "gpu_family": "a100", "cuda_compute_capability": 8.0},
                    {"name": "a100-gpu", "gpu_family": "a100", "cuda_compute_capability": 8.0},
                ]
            }
        }
    }
    partition, reason = choose_partition(manifest, config)
    assert partition == "lab-gpu"
    assert reason.startswith("preferred_partition_selected: fallback_requires_wait_policy_evidence")


def test_v01013_scheduler_status_ignores_noncounting_finished_collect_noise(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {
        "r001_noncounting": {
            "run_id": "r001_noncounting",
            "status": "finished",
            "non_counting_classification": "superseded",
        },
        "r002_collect": {"run_id": "r002_collect", "status": "finished"},
    }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)

    status = daemon_status(VibePaths(tmp_path))
    assert status["next_collection_runs"] == ["r002_collect"]


def test_v01014_fallback_requeue_no_better_partition_has_no_executable_command(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {
            "active": [
                {
                    "run_id": "r001",
                    "job_id": "111",
                    "backend": "slurm",
                    "partition": "preferred",
                    "poll_details": {
                        "wait_verdict": {
                            "verdict": "fallback_not_better_keep_preferred",
                            "preferred_partition": "preferred",
                            "fallback_checked": [{"partition": "fallback", "estimated_start_plus_run_hours": 99}],
                        }
                    },
                }
            ]
        },
    )
    result = invoke("scheduler-requeue-fallback", "--target", str(tmp_path), "--allow-outside-policy")
    assert result.exit_code == 0
    data = json.loads(result.output)
    candidate = data["candidates"][0]
    assert candidate["eligible"] is False
    assert candidate["recommended_partition"] == ""
    assert candidate["executable_command"] == ""


def test_v080_portfolio_blocks_budget_and_duplicate_but_allows_changed_repeat(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy").exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("research", "init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy", "--autonomy-level", "bounded_continuous", "--force").exit_code == 0
    assert invoke("hypothesis", "create", "test repeated design", "--stage", "smoke", "--target", str(tmp_path)).exit_code == 0
    hyp_id = next(iter(read_json(tmp_path / ".vibe" / "research" / "hypotheses.json", {})))
    assert invoke("experiment", "create", hyp_id, "--design", "same gate", "--stage", "smoke", "--capability", "toy-metrics-export", "--target", str(tmp_path)).exit_code == 0
    candidates = [
        {
            "hypothesis_id": hyp_id,
            "design_summary": "same gate",
            "stage": "smoke",
            "capability_id": "toy-metrics-export",
            "decision_type": "collect_more_metrics",
            "resource_units": {"gpu_hours": 0.0},
        },
        {
            "hypothesis_id": hyp_id,
            "design_summary": "same gate",
            "stage": "smoke",
            "capability_id": "toy-metrics-export",
            "decision_type": "collect_more_metrics",
            "changed_variable": "threshold",
            "failure_analysis": {"what_failed": "calibration"},
            "resource_units": {"gpu_hours": 0.0},
        },
        {
            "hypothesis_id": hyp_id,
            "design_summary": "expensive gate",
            "stage": "smoke",
            "capability_id": "toy-metrics-export",
            "decision_type": "collect_more_metrics",
            "resource_units": {"gpu_hours": 99.0},
            "confirmed": True,
        },
    ]
    candidate_file = tmp_path / "candidates.json"
    write_json(candidate_file, candidates)
    assert invoke("portfolio", "plan", "--candidate-file", str(candidate_file), "--target", str(tmp_path)).exit_code == 0
    plan = read_json(tmp_path / ".vibe" / "research" / "portfolio_plan.json", {})
    blocked = [reason for row in plan["blocked"] for reason in row["blocked_reasons"]]
    assert "blocked_repeating_experiment" in blocked
    assert "blocked_daily_gpu_hour_cap" in blocked
    assert len(plan["selected"]) == 1
    assert invoke("portfolio", "schedule", "--target", str(tmp_path)).exit_code == 0
    assert read_jsonl(tmp_path / ".vibe" / "research" / "budget_ledger.jsonl")


def test_v0839_default_portfolio_candidates_cover_multiple_routes(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy").exit_code == 0
    enable_toy_adapter(tmp_path)
    manifest = load_adapter_manifest(VibePaths(tmp_path))
    alt = manifest.capabilities[0].model_copy(deep=True)
    alt.id = "toy-alt-metrics-export"
    alt.supported_decisions = ["collect_more_metrics"]
    alt.activation = {**alt.activation, "contract_test_result_id": "test-alt"}
    manifest.capabilities.append(alt)
    write_adapter_manifest(VibePaths(tmp_path), manifest)
    assert invoke("hypothesis", "create", "first route", "--stage", "smoke", "--target", str(tmp_path)).exit_code == 0
    assert invoke("hypothesis", "create", "second route", "--stage", "smoke", "--target", str(tmp_path)).exit_code == 0
    candidates = default_candidates(VibePaths(tmp_path))
    assert len(candidates) >= 3
    assert len({row["capability_id"] for row in candidates}) == 2
    assert len({row["hypothesis_id"] for row in candidates}) >= 2


def test_v0839_sustained_round_audit_requires_multiroute_reflected_rounds(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy").exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("hypothesis", "create", "first route", "--stage", "smoke", "--target", str(tmp_path)).exit_code == 0
    assert invoke("hypothesis", "create", "second route", "--stage", "smoke", "--target", str(tmp_path)).exit_code == 0
    assert invoke("hypothesis", "create", "third route", "--stage", "smoke", "--target", str(tmp_path)).exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["cycles"] = {f"c00{idx}": {"status": "revised"} for idx in range(1, 4)}
    state["runs"] = {}
    for cycle_idx in range(1, 4):
        cycle = f"c00{cycle_idx}"
        cycle_dir = tmp_path / ".vibe" / "cycles" / cycle
        cycle_dir.mkdir(parents=True, exist_ok=True)
        (cycle_dir / "cycle_reflect.md").write_text("# Cycle Reflect\n\n## Run comparison\n- compared\n\n## Route classification\n- classified\n")
        (cycle_dir / "cycle_revised_plan.md").write_text("# Revised\n\n## Next-cycle diversity requirement\nmultiple routes\n")
        for route_idx in range(1, 4):
            run_id = f"r{cycle_idx}{route_idx:02d}_route"
            state["runs"][run_id] = {
                "cycle_id": cycle,
                "status": "revised",
                "direction_id": f"route_{route_idx}",
                "run_kind": "real_experiment",
                "backend": "local",
                "adapter_metadata": {"task_type": "metrics_export", "capability_id": "toy-metrics-export"},
            }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    (tmp_path / ".vibe" / "research" / "sources.jsonl").write_text(json.dumps({"source": "test", "query": "method", "results": [{"title": "paper"}]}) + "\n")
    result = invoke("research", "sustained-audit", "--target", str(tmp_path))
    assert result.exit_code == 0
    audit = read_json(tmp_path / ".vibe" / "research" / "sustained_round_audit.json", {})
    assert audit["complete"] is True
    assert audit["completed_round_count"] == 3


def test_v0839_sustained_round_audit_flags_fragmented_active_jobs(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy").exit_code == 0
    enable_toy_adapter(tmp_path)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["cycles"] = {"c001": {}, "c002": {}, "c003": {}}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [{"cycle_id": "c001"}, {"cycle_id": "c002"}, {"cycle_id": "c003"}]})
    result = invoke("research", "sustained-audit", "--target", str(tmp_path))
    assert result.exit_code == 0
    audit = read_json(tmp_path / ".vibe" / "research" / "sustained_round_audit.json", {})
    assert "active_jobs_fragmented_across_cycles_not_one_round" in audit["issues"]
    assert audit["complete"] is False


def test_v080_promotion_stop_require_trusted_evidence(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy").exit_code == 0
    assert invoke("hypothesis", "create", "untrusted idea", "--target", str(tmp_path)).exit_code == 0
    hyp_id = next(iter(read_json(tmp_path / ".vibe" / "research" / "hypotheses.json", {})))
    assert invoke("experiment", "create", hyp_id, "--design", "schema failure", "--target", str(tmp_path)).exit_code == 0
    exp_id = next(iter(read_json(tmp_path / ".vibe" / "research" / "experiments.json", {})))
    assert invoke("experiment", "analyze", exp_id, "--summary", "schema invalid", "--failure-kind", "schema", "--target", str(tmp_path)).exit_code == 0
    assert invoke("hypothesis", "promote", hyp_id, "--reason", "not enough", "--target", str(tmp_path)).exit_code == 1
    assert invoke("hypothesis", "stop", hyp_id, "--reason", "untrusted only", "--target", str(tmp_path)).exit_code == 1
    assert invoke("hypothesis", "stop", hyp_id, "--reason", "operator stop", "--user-decision", "--target", str(tmp_path)).exit_code == 0


def test_v081_bootstrap_dogfood_happy_path_and_readiness_exports(tmp_path: Path):
    result = invoke("bootstrap", "dogfood", "--target", str(tmp_path), "--profile", "0.8.1-happy-path")
    assert result.exit_code == 0
    assert ".vibe_dogfood/" in (tmp_path / ".gitignore").read_text()
    profile = tmp_path / ".vibe_dogfood" / "0.8.1-happy-path"
    readiness = read_json(profile / ".vibe" / "bootstrap" / "readiness.json", {})
    assert readiness["readiness_level"] == "real_experiment_ready"
    assert "evaluation_smoke" in readiness["active_capabilities"]
    assert (profile / ".vibe" / "script_readiness.json").exists()
    assert (profile / ".vibe" / "bootstrap" / "readiness_report.md").exists()
    memo = next((profile / ".vibe" / "memos").glob("*.md")).read_text()
    assert "初始化/接入工作" in memo
    export = read_json(profile / ".vibe" / "dashboard" / "readiness_export.json", {})
    assert "bootstrap_state" in export


def test_v081_bootstrap_blocks_conflicts_placeholders_and_resume_preserves_user_policy(tmp_path: Path):
    assert invoke("bootstrap", "dogfood", "--target", str(tmp_path), "--profile", "0.8.1-policy-conflict").exit_code == 0
    conflict = tmp_path / ".vibe_dogfood" / "0.8.1-policy-conflict"
    state = read_json(conflict / ".vibe" / "bootstrap" / "state.json", {})
    assert "questions" in state.get("blocked_phases", [])
    questions = read_jsonl(conflict / ".vibe" / "research" / "questions.jsonl")
    assert any(row.get("question_id") == "q_readme_agents_conflict" for row in questions)

    assert invoke("bootstrap", "dogfood", "--target", str(tmp_path), "--profile", "0.8.1-placeholder-script").exit_code == 0
    placeholder = tmp_path / ".vibe_dogfood" / "0.8.1-placeholder-script"
    report = read_json(placeholder / ".vibe" / "bootstrap" / "readiness.json", {})
    assert "evaluation_smoke" in report.get("contract_test_failures", [])

    assert invoke("bootstrap", "dogfood", "--target", str(tmp_path), "--profile", "0.8.1-resume-after-failure").exit_code == 0
    resume_repo = tmp_path / ".vibe_dogfood" / "0.8.1-resume-after-failure"
    budget = read_yaml(resume_repo / ".vibe" / "policies" / "budget.yaml", {})
    budget["daily_job_cap"] = 9
    write_yaml(resume_repo / ".vibe" / "policies" / "budget.yaml", budget)
    assert invoke("bootstrap", "resume", "--target", str(resume_repo)).exit_code == 0
    assert read_yaml(resume_repo / ".vibe" / "policies" / "budget.yaml", {})["daily_job_cap"] == 9
    assert read_json(resume_repo / ".vibe" / "bootstrap" / "state.json", {}).get("merge_warnings")


def test_v081_policy_gate_archive_import_and_external_dogfood(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b").exit_code == 0
    (tmp_path / ".vibe" / "policies" / "budget.yaml").unlink()
    run_id = prepare_toy_run(tmp_path / "toy")
    toy = tmp_path / "toy"
    (toy / ".vibe" / "policies" / "budget.yaml").unlink()
    state = read_json(toy / ".vibe" / "state" / "state.json", {})
    state["runs"][run_id]["status"] = "dryrun_passed"
    write_json(toy / ".vibe" / "state" / "state.json", state)
    queue_result = invoke("queue", run_id, "--target", str(toy))
    assert queue_result.exit_code == 1
    assert "Policy completeness blocked queue" in queue_result.output

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "VIBE_TIMELINE.md").write_text("collect_more_metrics primary=0.0 continued exploration\n")
    assert invoke("bootstrap", "archive", "--target", str(toy), "--source", str(legacy), "--note", "test").exit_code == 0
    archive_manifest = next((toy / ".vibe" / "archives").glob("*/manifest.json"))
    manifest = read_json(archive_manifest, {})
    assert manifest["trust_status"] == "historical_context_only"
    assert manifest["failure_summary"]["regression_cases"]
    assert invoke("bootstrap", "import-legacy", str(archive_manifest), "--target", str(toy)).exit_code == 0
    assert read_json(toy / ".vibe" / "research" / "legacy_import.json", {})["status"] == "imported_unverified"

    mock_external = tmp_path / "external"
    mock_external.mkdir()
    (mock_external / "README.md").write_text("External repo\n")
    out = tmp_path / "dogfood.json"
    assert invoke("bootstrap", "dogfood", "--target", str(toy), "--external-repo", str(mock_external), "--dry-run", "--output-report", str(out)).exit_code == 0
    dogfood = read_json(out, {})
    assert dogfood["dry_run"] is True
    assert dogfood["issue_classes"]


def test_v0839_external_clone_repo_records_provenance(tmp_path: Path):
    target = tmp_path / "target"
    assert invoke("init", "--target", str(target), "--goal", "Improve validation", "--background", "Toy", "--no-root-portal").exit_code == 0
    source = tmp_path / "source_repo"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    (source / "README.md").write_text("external method\n")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "init"], cwd=source, check=True, capture_output=True)
    result = invoke("external", "clone-repo", str(source), "--target", str(target), "--name", "method-source")
    assert result.exit_code == 0
    assert (target / ".vibe" / "research" / "external_repos" / "method-source" / "README.md").exists()
    rows = read_jsonl(target / ".vibe" / "research" / "external_repos.jsonl")
    assert rows[-1]["status"] == "cloned"
    assert rows[-1]["url"] == str(source)


def test_v082_discovery_prunes_heavy_dirs_and_reports_limits(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "eval.py").write_text("print('eval')\n")
    (repo / "scripts" / "extra_a.py").write_text("print('a')\n")
    (repo / "scripts" / "extra_b.py").write_text("print('b')\n")
    for name in ["data", "results", "models", "external_supervisors", ".vibe_legacy_20260530"]:
        folder = repo / name
        folder.mkdir(parents=True)
        (folder / "hidden_eval.py").write_text("print('heavy')\n")
        (folder / "hidden_metrics.json").write_text('{"primary": 0.0}\n')
    assert invoke("init", "--target", str(repo), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0

    config = read_yaml(repo / ".vibe" / "config.yaml", {})
    config["discovery"] = {"max_files": 2, "max_dirs": 200, "skip_dirs": ["custom_ignored"]}
    write_yaml(repo / ".vibe" / "config.yaml", config)
    assert invoke("adapter", "discover", "--target", str(repo)).exit_code == 0
    report = read_json(repo / ".vibe" / "discovery_report.json", {})

    scripts = report["candidates"]["scripts"]
    all_candidate_paths = "\n".join(path for values in report["candidates"].values() for path in values)
    assert "scripts/eval.py" in scripts
    for ignored in ["data/", "results/", "models/", "external_supervisors/", ".vibe_legacy_20260530/"]:
        assert ignored not in all_candidate_paths
    assert report["discovery_warnings"]

    out = repo / "dogfood.json"
    assert invoke("bootstrap", "dogfood", "--target", str(repo), "--external-repo", str(repo), "--dry-run", "--output-report", str(out)).exit_code == 0
    context = read_json(out, {})["readiness"]["context"]
    assert "scripts/eval.py" in context["candidate_scripts"]
    assert all("data/" not in path and "results/" not in path for path in context["candidate_scripts"])


def test_v0832_blank_yaml_adapter_fields_do_not_crash_status(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    (tmp_path / ".vibe" / "adapter.yaml").write_text(
        "adapter_version: test\n"
        "project_id: blank\n"
        "project_name: blank\n"
        "capabilities:\n"
        "  - id: blank-cap\n"
        "    status: draft\n"
        "    task_type: metrics_export\n"
        "    entrypoint:\n"
        "    inputs:\n"
        "    outputs:\n"
        "    activation:\n"
        "    trust_checks:\n"
        "open_questions: []\n"
    )
    manifest = load_adapter_manifest(VibePaths(tmp_path))
    cap = manifest.capabilities[0]
    assert cap.entrypoint == {}
    assert cap.inputs == {}
    assert cap.outputs == {}
    assert cap.activation == {}
    assert cap.trust_checks == []
    assert invoke("status", "--target", str(tmp_path)).exit_code == 0
    assert invoke("adapter", "doctor", "--target", str(tmp_path)).exit_code == 0


def test_v082_resume_clears_stale_question_block_after_answers(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    assert invoke("bootstrap", "init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--force").exit_code == 0
    assert invoke("bootstrap", "run", "--target", str(tmp_path)).exit_code == 0

    blocked_state = read_json(tmp_path / ".vibe" / "bootstrap" / "state.json", {})
    assert "questions" in blocked_state.get("blocked_phases", [])

    manifest = load_adapter_manifest(VibePaths(tmp_path))
    for question in manifest.open_questions:
        result = invoke("adapter", "ask", "--target", str(tmp_path), "--id", question.id, "--answer", "confirmed for test", "--confirm")
        assert result.exit_code == 0
    answer_all_research_questions(tmp_path)
    assert invoke("bootstrap", "resume", "--target", str(tmp_path)).exit_code == 0

    resumed = read_json(tmp_path / ".vibe" / "bootstrap" / "state.json", {})
    assert "questions" in resumed.get("completed_phases", [])
    assert "questions" not in resumed.get("blocked_phases", [])
    status = invoke("bootstrap", "status", "--target", str(tmp_path))
    assert status.exit_code == 0
    status_data = json.loads(status.output)
    assert status_data["readiness"]["required_questions"] == []


def test_v082_low_risk_instrumentation_activates_without_schema_edits(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    manifest = load_adapter_manifest(VibePaths(tmp_path))
    for question in manifest.open_questions:
        result = invoke("adapter", "ask", "--target", str(tmp_path), "--id", question.id, "--answer", "confirmed for test", "--confirm")
        assert result.exit_code == 0

    for capability_id in ["environment_probe", "data_probe", "baseline_inventory"]:
        assert invoke("adapter", "contract-test", capability_id, "--target", str(tmp_path)).exit_code == 0
        assert invoke("adapter", "activate", capability_id, "--target", str(tmp_path), "--confirm", "low-risk bootstrap contract").exit_code == 0

    manifest = load_adapter_manifest(VibePaths(tmp_path))
    by_id = {cap.id: cap for cap in manifest.capabilities}
    assert {cap_id for cap_id, cap in by_id.items() if cap.status == "active"} >= {"environment_probe", "data_probe", "baseline_inventory"}
    assert by_id["evaluation_smoke"].status == "blocked_missing_metrics_schema"
    assert by_id["metrics_export"].status == "blocked_missing_metrics_schema"
    assert by_id["train_smoke"].status == "blocked_missing_script"
    assert by_id["train_gate"].status == "blocked_missing_script"
    assert by_id["long_run_submit"].status == "blocked_missing_user_answer"


def test_v083_instrumentation_readiness_does_not_unlock_real_experiments(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    manifest = load_adapter_manifest(VibePaths(tmp_path))
    for question in manifest.open_questions:
        assert invoke("adapter", "ask", "--target", str(tmp_path), "--id", question.id, "--answer", "confirmed for test", "--confirm").exit_code == 0
    for capability_id in ["environment_probe", "data_probe", "baseline_inventory"]:
        assert invoke("adapter", "contract-test", capability_id, "--target", str(tmp_path)).exit_code == 0
        assert invoke("adapter", "activate", capability_id, "--target", str(tmp_path), "--confirm", "instrumentation only").exit_code == 0

    doctor = invoke("adapter", "doctor", "--target", str(tmp_path))
    assert doctor.exit_code == 0
    readiness = read_json(tmp_path / ".vibe" / "adapter_readiness.json", {})
    assert readiness["ready_for_instrumentation"] is True
    assert readiness["ready_for_real_experiments"] is False
    assert readiness["ready_for_experiments"] is False
    assert (tmp_path / ".vibe" / "adapter_real_experiment_gaps.md").exists()

    planned = invoke("plan-cycle", "--offline", "--target", str(tmp_path))
    assert planned.exit_code == 1
    assert "real-experiment adapter readiness is incomplete" in planned.output


def test_v0840_adapter_required_paths_are_downstream_dependency_readiness(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    paths = VibePaths(tmp_path)
    manifest = load_adapter_manifest(paths)
    manifest.capabilities[0].inputs = {"required_paths": ["data/manifest.json"]}
    write_adapter_manifest(paths, manifest)

    result = invoke("adapter", "doctor", "--target", str(tmp_path))
    assert result.exit_code == 0
    readiness = read_json(tmp_path / ".vibe" / "adapter_readiness.json", {})
    assert readiness["ready_for_real_experiments"] is False
    assert readiness["dependency_issues"][0]["scope"] == "downstream_adapter_dependency"
    assert "downstream adapter dependency" in (tmp_path / ".vibe" / "adapter_doctor.md").read_text()

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manifest.json").write_text("{}\n")
    result = invoke("adapter", "doctor", "--target", str(tmp_path))
    assert result.exit_code == 0
    readiness = read_json(tmp_path / ".vibe" / "adapter_readiness.json", {})
    assert readiness["dependency_issues"] == []
    assert readiness["ready_for_real_experiments"] is True


def test_v0840_contract_test_fails_missing_downstream_dependencies(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    paths = VibePaths(tmp_path)
    manifest = load_adapter_manifest(paths)
    cap = manifest.capabilities[0]
    cap.status = "draft"
    cap.inputs = {"required_files": ["data/splits_final.json"]}
    write_adapter_manifest(paths, manifest)

    result = invoke("adapter", "contract-test", "train-smoke", "--target", str(tmp_path))
    assert result.exit_code == 1
    contract = read_json(tmp_path / ".vibe" / "contract_tests" / "train-smoke.json", {})
    assert contract["status"] == "failed"
    assert any("downstream adapter dependency missing" in error for error in contract["errors"])


def test_v083_real_experiment_progress_counts_only_backend_submitted_interpretable_runs(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke(
        "decision",
        "write",
        "c001",
        "--type",
        "collect_more_metrics",
        "--action",
        "collect schema-valid metrics",
        "--direction",
        "toy-metrics-export",
        "--baseline",
        "trusted_baseline_proxy",
        "--target",
        str(tmp_path),
    ).exit_code == 0
    assert invoke("compile-decision", "c001", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    run_id = sorted(read_json(tmp_path / ".vibe" / "state" / "state.json", {})["runs"])[0]
    assert invoke("review", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("branch", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("patch", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("dryrun", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("queue", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("submit-queue", "--target", str(tmp_path), "--dry").exit_code == 0
    write_json(tmp_path / ".vibe" / "toy_metrics.json", {"primary": 0.7})
    assert invoke("collect", run_id, "--target", str(tmp_path), "--metric", "0.7").exit_code == 0

    progress_cmd = invoke("experiment", "real-progress", "--target", str(tmp_path))
    assert progress_cmd.exit_code == 0
    progress = json.loads(progress_cmd.output)
    assert progress["observed_count"] == 1
    assert progress["countable_runs"][0]["run_id"] == run_id
    assert progress["countable_runs"][0]["run_kind"] == "real_experiment"
    assert read_json(tmp_path / ".vibe" / "research" / "real_experiment_progress.json", {})["observed_count"] == 1


def test_v084_generate_runs_auto_compiles_and_recovers_resource_plan_block(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("decision", "write-block", "c001", "--reason", "old placeholder plan", "--decision-type", "blocked_missing_resource_plan", "--target", str(tmp_path)).exit_code == 0

    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert state["status"] == "blocked_missing_resource_plan"
    next_action = invoke("next", "--target", str(tmp_path))
    assert next_action.exit_code == 0
    assert "vibe generate-runs c001" in next_action.output

    generated = invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1")
    assert generated.exit_code == 0
    decision = read_json(tmp_path / ".vibe" / "cycles" / "c001" / "cycle_decision.json", {})
    plan = read_yaml(tmp_path / ".vibe" / "cycles" / "c001" / "resource_plan.yaml", {})
    assert decision["decision_type"] == "collect_more_metrics"
    assert plan["decision_id"] == decision["decision_id"]
    assert read_json(tmp_path / ".vibe" / "state" / "state.json", {})["runs"]


def test_v085_next_action_prioritizes_current_cycle_runs(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"]["r001_toy_audit"]["status"] = "collected"
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)

    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c002", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c002", "--target", str(tmp_path), "--count", "1").exit_code == 0

    next_action = invoke("next", "--target", str(tmp_path))
    assert next_action.exit_code == 0
    assert "vibe review r002_toy_audit" in next_action.output
    assert "r001_toy_audit" not in next_action.output


def test_cycle_run_queue_and_reflection_flow(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("idea", "try topology cleanup", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    compile_toy_cycle(tmp_path)
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
    assert invoke("collect", run_id, "--target", str(tmp_path), "--metric", "0.7").exit_code == 0
    assert invoke("reflect", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    write_run_decision(tmp_path, run_id)
    assert invoke("revise-plan", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("reflect-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    cycle_reflect = (tmp_path / ".vibe" / "cycles" / "c001" / "cycle_reflect.md").read_text()
    assert "## Route classification" in cycle_reflect
    assert "## External evidence consulted" in cycle_reflect
    assert "## Next-round requirements" in cycle_reflect
    compile_toy_cycle(tmp_path)
    assert invoke("revise-cycle", "c001", "--offline", "--target", str(tmp_path), "--mode", "balanced").exit_code == 0
    cycle_revised = (tmp_path / ".vibe" / "cycles" / "c001" / "cycle_revised_plan.md").read_text()
    assert "## Next-cycle diversity requirement" in cycle_revised
    assert invoke("validate-hard-rules", "--target", str(tmp_path)).exit_code == 0
    assert (tmp_path / ".vibe" / "runs" / run_id / "revised_plan.md").read_text()
    assert "0.7" in (tmp_path / "VIBE_LEADERBOARD.md").read_text()
    assert "cycle_revised_plan_written" in (tmp_path / "VIBE_TIMELINE.md").read_text()


def test_v070_decision_and_compiler_contracts(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 1
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    (tmp_path / ".vibe" / "config.local.yaml").write_text("adapter:\n  kind: config\n")
    assert invoke("decision", "write", "c001", "--type", "launch_gpu_gate", "--action", "run configured adapter task", "--target", str(tmp_path)).exit_code == 0
    assert invoke("validate-decision", "c001", "--target", str(tmp_path)).exit_code == 0
    result = invoke("compile-decision", "c001", "--target", str(tmp_path))
    assert result.exit_code == 1
    decision = read_json(tmp_path / ".vibe" / "cycles" / "c001" / "cycle_decision.json", {})
    assert decision["decision_type"] == "blocked_missing_capability"


def test_v070_valid_toy_decision_compiles_executable_resource_plan(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    compile_toy_cycle(tmp_path)
    assert invoke("validate-resource-plan", "c001", "--target", str(tmp_path)).exit_code == 0
    plan = read_yaml(tmp_path / ".vibe" / "cycles" / "c001" / "resource_plan.yaml", {})
    spec = plan["runs"]["toy-audit"]
    assert spec["dryrun"]["command"]
    assert spec["entrypoint"]["command"]
    assert spec["evaluation"]["metrics_schema"] == {"primary": "number"}


def test_v071_init_bootstraps_adapter_and_blocks_until_ready(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    for rel in [
        ".vibe/adapter.yaml",
        ".vibe/adapter_questions.yaml",
        ".vibe/research_brief.md",
        ".vibe/discovery_report.md",
        ".vibe/discovery_report.json",
        ".vibe/script_bootstrap_plan.md",
        ".vibe/adapter_gitignore_suggestion.md",
        ".vibe/contract_tests",
        ".vibe/run_contracts",
        ".vibe/adapter_history.jsonl",
        ".vibe/scripts/environment_probe.py",
        ".vibe/scripts/metrics_export.py",
        ".vibe/adapter_doctor.md",
    ]:
        assert (tmp_path / rel).exists()
    result = invoke("plan-cycle", "--offline", "--target", str(tmp_path))
    assert result.exit_code == 1
    readiness = read_json(tmp_path / ".vibe" / "dashboard" / "status.json", {})["adapter_readiness"]
    assert readiness["ready_for_experiments"] is False
    assert "metrics_export" in readiness["blocked_capabilities"]
    assert "Adapter Readiness" in (tmp_path / "VIBE_STATUS.md").read_text()


def test_v071_contract_test_and_activation_unlock_config_planner(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    manifest = load_adapter_manifest(VibePaths(tmp_path))
    for cap in manifest.capabilities:
        if cap.id == "metrics_export":
            cap.status = "draft"
            cap.supported_decisions = ["collect_more_metrics"]
            cap.metrics_schema = MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="test-v1")
            cap.artifact_rules.expected_outputs = [".vibe/bootstrap_metrics/metrics_export.json"]
            cap.artifact_rules.trusted_path_patterns = [".vibe/bootstrap_metrics/*.json"]
    write_adapter_manifest(VibePaths(tmp_path), manifest)
    for question in manifest.open_questions:
        assert invoke("adapter", "ask", "--target", str(tmp_path), "--id", question.id, "--answer", "confirmed for test", "--confirm").exit_code == 0
    assert invoke("adapter", "contract-test", "metrics_export", "--target", str(tmp_path)).exit_code == 0
    assert invoke("adapter", "activate", "metrics_export", "--target", str(tmp_path), "--confirm", "test activation").exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("decision", "write", "c001", "--type", "collect_more_metrics", "--action", "collect metrics", "--target", str(tmp_path)).exit_code == 0
    assert invoke("compile-decision", "c001", "--target", str(tmp_path)).exit_code == 0
    plan = read_yaml(tmp_path / ".vibe" / "cycles" / "c001" / "resource_plan.yaml", {})
    metadata = plan["runs"]["metrics_export"]["adapter_metadata"]
    assert metadata["capability_id"] == "metrics_export"
    assert metadata["adapter_revision"]
    assert metadata["metrics_schema_version"] == "test-v1"


def test_v0838_contract_test_prefers_dryrun_expected_output(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    manifest = load_adapter_manifest(VibePaths(tmp_path))
    command = (
        "python3 -c 'import json, pathlib; "
        "p=pathlib.Path(\".vibe/contract_metrics/train.json\"); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_text(json.dumps({\"primary\": 1.0})+\"\\n\")'"
    )
    manifest.capabilities = [
        AdapterCapability(
            id="train-contract",
            version="test",
            status="draft",
            task_type="train_smoke",
            supported_decisions=["launch_gpu_gate"],
            dryrun={"command": command, "expected_output_path": ".vibe/contract_metrics/train.json"},
            entrypoint={"type": "slurm", "command": "python train.py"},
            outputs={"expected_output_path": ".vibe/real_metrics/train.json", "metrics_file_path": ".vibe/real_metrics/train.json"},
            metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="test"),
            artifact_rules=ArtifactRules(expected_outputs=[".vibe/real_metrics/train.json"], trusted_path_patterns=[".vibe/real_metrics/*.json"], version="test"),
            resources=ResourcePolicy(automatic_submission_allowed=False, user_confirmation_required=True),
            contract_tests=["train-contract"],
        )
    ]
    write_adapter_manifest(VibePaths(tmp_path), manifest)
    result = invoke("adapter", "contract-test", "train-contract", "--target", str(tmp_path))
    assert result.exit_code == 0
    contract = read_json(tmp_path / ".vibe" / "contract_tests" / "train-contract.json", {})
    assert contract["status"] == "passed"
    assert contract["validated_output_path"] == ".vibe/contract_metrics/train.json"
    assert (tmp_path / ".vibe" / "contract_metrics" / "train.json").exists()
    assert not (tmp_path / ".vibe" / "real_metrics" / "train.json").exists()


def test_v071_direct_yaml_active_cannot_bypass_contract_test(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    manifest = load_adapter_manifest(VibePaths(tmp_path))
    for cap in manifest.capabilities:
        if cap.id == "metrics_export":
            cap.status = "active"
            cap.supported_decisions = ["collect_more_metrics"]
            cap.metrics_schema = MetricsSchema(required=["primary"], types={"primary": "number"})
            cap.artifact_rules.expected_outputs = [".vibe/bootstrap_metrics/metrics_export.json"]
            cap.trust_checks = ["schema_valid_metrics"]
            cap.contract_tests = ["metrics_export"]
    write_adapter_manifest(VibePaths(tmp_path), manifest)
    result = invoke("adapter", "doctor", "--target", str(tmp_path))
    assert result.exit_code == 0
    readiness = read_json(tmp_path / ".vibe" / "adapter_readiness.json", {})
    assert readiness["ready_for_experiments"] is False
    assert "metrics_export" in readiness["contract_failures"]


def test_v070_config_adapter_missing_entrypoint_blocks(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    (tmp_path / ".vibe" / "config.local.yaml").write_text("adapter:\n  kind: config\n")
    (tmp_path / ".vibe" / "adapter.yaml").write_text(
        "task:\n"
        "  key: broken\n"
        "  dryrun_command: python -c 'print(\"ok\")'\n"
        "  metrics_file_path: outputs/metrics.json\n"
        "  expected_output_path: outputs/metrics.json\n"
        "  metrics_schema:\n"
        "    primary: number\n"
        "  resources:\n"
        "    gpu: 0\n"
        "    cpus: 1\n"
        "    mem_gb: 1\n"
        "    time: '00:05:00'\n"
    )
    assert invoke("decision", "write", "c001", "--type", "launch_gpu_gate", "--action", "run config task", "--target", str(tmp_path)).exit_code == 0
    assert invoke("compile-decision", "c001", "--target", str(tmp_path)).exit_code == 1
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert state["status"] == "blocked_missing_resource_plan"
    assert "entrypoint.command" in state["blocked_reason"]


def test_v070_existing_real_resource_plan_remains_usable(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    write_yaml(
        tmp_path / ".vibe" / "cycles" / "c001" / "resource_plan.yaml",
        {
            "cycle_id": "c001",
            "mode": "legacy-real",
            "runs": {
                "legacy-real": {
                    "priority": 1,
                    "direction_id": "d001_legacy",
                    "hypothesis": "Run a legacy real command plan.",
                    "expected_learning": "legacy plan can still execute",
                    "cost": "low",
                    "dryrun": {"command": "python -c 'print(\"legacy dryrun ok\")'", "max_minutes": 5},
                    "entrypoint": {"type": "local", "command": "python -c 'print(\"legacy run ok\")'"},
                    "resources": {"gpu": 0, "cpus": 1, "mem_gb": 1, "time": "00:05:00"},
                    "outputs": {"expected_output_path": ".vibe/legacy_metrics.json"},
                    "evaluation": {"metrics_file_path": ".vibe/legacy_metrics.json", "metrics_schema": {"primary": "number"}},
                    "depends_on": [],
                    "cancel_if_failed": [],
                }
            },
        },
    )
    assert invoke("validate-resource-plan", "c001", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    run_id = sorted(state["runs"])[0]
    assert run_id == "r001_legacy_real"


def test_v070_metrics_schema_and_trust_gating(tmp_path: Path):
    run_id = prepare_toy_run(tmp_path)
    paths = VibePaths(tmp_path)
    collect_run(paths, run_id)
    metrics = read_json(tmp_path / ".vibe" / "runs" / run_id / "metrics.json", {})
    assert metrics["trust_status"] == "untrusted_missing_metrics"
    assert metrics["schema_status"] == "missing"
    assert read_json(tmp_path / ".vibe" / "leaderboard" / "best.json", {}) == {}

    bad_metrics = tmp_path / "bad_metrics.json"
    bad_metrics.write_text('{"other": 1.0}\n')
    collect_run(paths, run_id, metrics_file=str(bad_metrics))
    metrics = read_json(tmp_path / ".vibe" / "runs" / run_id / "metrics.json", {})
    assert metrics["trust_status"] == "untrusted_schema_failed"
    assert any("primary" in item for item in metrics["schema_errors"])
    assert read_json(tmp_path / ".vibe" / "leaderboard" / "best.json", {}) == {}


def test_v070_missing_expected_output_and_placeholder_stay_untrusted(tmp_path: Path):
    run_id = prepare_toy_run(tmp_path)
    paths = VibePaths(tmp_path)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    run = state["runs"][run_id]
    run["dryrun"]["command"] = "python -c 'print(\"vibe dryrun placeholder\")'"
    state["runs"][run_id] = run
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    write_json(tmp_path / ".vibe" / "runs" / run_id / "manifest.json", run)
    write_json(tmp_path / ".vibe" / "runs" / run_id / "manifest.yaml", run)
    collect_run(paths, run_id, metric=0.9)
    metrics = read_json(tmp_path / ".vibe" / "runs" / run_id / "metrics.json", {})
    assert metrics["trust_status"] in {"untrusted_missing_output", "untrusted_placeholder_command"}
    assert metrics["trusted"] is False
    assert read_json(tmp_path / ".vibe" / "leaderboard" / "best.json", {}) == {}


def test_v070_offline_revise_writes_block_decision(tmp_path: Path):
    run_id = prepare_toy_run(tmp_path)
    assert invoke("reflect", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("revise-plan", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    decision = read_json(tmp_path / ".vibe" / "runs" / run_id / "decision.json", {})
    assert decision["decision_type"] == "blocked_missing_decision"
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert state["runs"][run_id]["status"] == "blocked"


def test_v070_anti_loop_detects_repeated_decisions_and_zero_metrics(tmp_path: Path):
    run_id = prepare_toy_run(tmp_path)
    paths = VibePaths(tmp_path)
    write_run_decision(tmp_path, run_id)
    write_run_decision(tmp_path, run_id)
    assert apply_loop_guard(paths, run_id)
    decision = read_json(tmp_path / ".vibe" / "runs" / run_id / "decision.json", {})
    assert decision["decision_type"] == "blocked_repeating_evidence"

    second = tmp_path / "zero-metrics"
    run_id = prepare_toy_run(second)
    paths = VibePaths(second)
    collect_run(paths, run_id)
    collect_run(paths, run_id)
    assert apply_loop_guard(paths, run_id)
    decision = read_json(second / ".vibe" / "runs" / run_id / "decision.json", {})
    assert decision["decision_type"] == "blocked_repeating_evidence"


def test_v0104_loop_guard_scopes_repeated_decisions_to_same_run(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    paths = VibePaths(tmp_path)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {"r001": {"run_id": "r001", "status": "revised"}, "r002": {"run_id": "r002", "status": "revised"}}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    for run_id in ["r001", "r002"]:
        (tmp_path / ".vibe" / "runs" / run_id).mkdir(parents=True, exist_ok=True)
        write_run_decision(tmp_path, run_id)
    assert not apply_loop_guard(paths, "r002")


def test_v0104_loop_guard_allows_repeated_collect_for_valid_metrics(tmp_path: Path):
    run_id = prepare_toy_run(tmp_path)
    paths = VibePaths(tmp_path)
    write_json(tmp_path / ".vibe" / "runs" / run_id / "metrics.json", {"schema_valid": True, "metrics": {"primary": 1.0}})
    write_run_decision(tmp_path, run_id)
    write_run_decision(tmp_path, run_id)
    assert not apply_loop_guard(paths, run_id)


def test_literature_and_deep_research_interfaces(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("lit-refresh-cycle", "c001", "--target", str(tmp_path), "--query", "segmentation topology").exit_code == 0
    assert invoke("deep-request-cycle", "c001", "route selection", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert "Next:" in invoke("next", "--target", str(tmp_path)).output
    request = next((tmp_path / ".vibe" / "research" / "deep_requests").glob("dr*.md"))
    result_path = tmp_path / ".vibe" / "research" / "raw" / "deep_reports" / f"{request.stem}_result.md"
    result_path.write_text("# Report\n\nUse route A.")
    assert invoke("ingest-deep-research", request.stem, "--target", str(tmp_path), "--kind", "science").exit_code == 0
    assert (tmp_path / ".vibe" / "research" / "wiki" / "synthesis" / f"{request.stem}.md").exists()


def test_idea_pool_lifecycle_and_dashboard_intake(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("idea", "compare topology losses with deep research", "--target", str(tmp_path)).exit_code == 0
    ideas = read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")
    assert ideas[0]["idea_id"] == "idea_001"
    assert ideas[0]["linked_raw_id"] == "raw_001"
    assert invoke("ideas", "triage", "--target", str(tmp_path)).exit_code == 0
    ideas = read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")
    assert ideas[0]["status"] == "needs_deep_research"
    assert "Idea Intake" in (tmp_path / "VIBE_TODO.md").read_text()
    assert invoke("ideas", "promote", "idea_001", "--target", str(tmp_path)).exit_code == 0
    assert invoke("ideas", "reject", "idea_001", "--target", str(tmp_path), "--reason", "not now").exit_code == 0
    assert "idea_001" in (tmp_path / ".vibe" / "ideas" / "rejected.md").read_text()
    assert invoke("ideas", "archive", "idea_001", "--target", str(tmp_path), "--reason", "recorded").exit_code == 0
    assert "idea_001" in (tmp_path / ".vibe" / "ideas" / "archive.md").read_text()
    assert invoke("ideas", "clean", "--target", str(tmp_path)).exit_code == 0


def test_deep_request_from_idea_contextual_request(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("idea", "compare nnU-Net and SAM-style repo options", "--target", str(tmp_path)).exit_code == 0
    result = invoke("deep-request-from-idea", "idea_001", "--target", str(tmp_path))
    assert result.exit_code == 0
    registry = read_jsonl(tmp_path / ".vibe" / "research" / "deep_requests" / "registry.jsonl")
    request_id = registry[-1]["request_id"]
    request_text = (tmp_path / ".vibe" / "research" / "deep_requests" / f"{request_id}.md").read_text()
    assert "compare nnU-Net" in request_text
    assert "Paper DB" in request_text
    assert "Scheduler and resource constraints" in request_text
    ideas = read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")
    assert ideas[0]["linked_deep_request_id"] == request_id


def test_revised_plan_includes_idea_pool_update(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    compile_toy_cycle(tmp_path)
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    run_id = sorted(read_json(tmp_path / ".vibe" / "state" / "state.json", {})["runs"])[0]
    assert invoke("reflect", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    write_run_decision(tmp_path, run_id)
    assert invoke("revise-plan", run_id, "--offline", "--target", str(tmp_path)).exit_code == 0
    assert "## Idea pool update" in (tmp_path / ".vibe" / "runs" / run_id / "revised_plan.md").read_text()
    assert invoke("reflect-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    compile_toy_cycle(tmp_path)
    assert invoke("revise-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert "## Idea pool update" in (tmp_path / ".vibe" / "cycles" / "c001" / "cycle_revised_plan.md").read_text()


def test_markdown_deep_research_ingest_updates_idea_pool(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("deep-request", "benchmark comparison", "--target", str(tmp_path), "--offline").exit_code == 0
    request = next((tmp_path / ".vibe" / "research" / "deep_requests").glob("dr*.md"))
    result_path = tmp_path / ".vibe" / "research" / "raw" / "deep_reports" / f"{request.stem}_result.md"
    result_path.write_text("# Report\n\nRecommendation: try robust benchmark reranking.\nGitHub: https://github.com/example/repo\n")
    assert invoke("ingest-deep-research", request.stem, "--target", str(tmp_path), "--kind", "benchmark").exit_code == 0
    ideas = read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")
    assert any("robust benchmark" in row["raw_text"] for row in ideas)
    registry = read_jsonl(tmp_path / ".vibe" / "research" / "deep_requests" / "registry.jsonl")
    assert registry[-1]["kind"] == "benchmark"


def test_pdf_deep_research_ingest_with_mocked_extractor(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    assert invoke("deep-request", "repo comparison", "--target", str(tmp_path), "--offline").exit_code == 0
    request = next((tmp_path / ".vibe" / "research" / "deep_requests").glob("dr*.md"))
    pdf_path = tmp_path / ".vibe" / "research" / "raw" / "deep_reports" / f"{request.stem}_result.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 tiny placeholder")

    import vibe_research.research as research_module

    def fake_extract(paths, request_id, pdf_path):
        md = paths.research / "raw" / "deep_reports" / f"{request_id}_result.md"
        md.write_text("# Extracted\n\nRecommendation: try repo smoke test.\n")
        return md

    monkeypatch.setattr(research_module, "extract_deep_report_pdf", fake_extract)
    assert invoke("ingest-deep-research", request.stem, "--target", str(tmp_path), "--kind", "repo").exit_code == 0
    assert (tmp_path / ".vibe" / "research" / "raw" / "deep_reports" / f"{request.stem}_result.md").exists()


def test_static_dashboard_build_and_serve_smoke(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "dashboard", "--background", "synthetic").exit_code == 0
    assert invoke("idea", "dashboard idea", "--target", str(tmp_path)).exit_code == 0
    assert invoke("dashboard", "build", "--target", str(tmp_path)).exit_code == 0
    index = tmp_path / ".vibe" / "site" / "index.html"
    assert index.exists()
    text = index.read_text()
    assert "Idea Intake" in text
    assert "Codex quota" in text
    result = invoke("dashboard", "serve", "--target", str(tmp_path), "--once")
    assert result.exit_code == 0
    assert "127.0.0.1:8765" in result.output


def test_meeting_export_story_pack_and_finalize_reports(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "meeting", "--background", "synthetic").exit_code == 0
    assert invoke("idea", "meeting idea", "--target", str(tmp_path)).exit_code == 0
    assert invoke("export-meeting", "--target", str(tmp_path), "--date", "20260529").exit_code == 0
    out = tmp_path / ".vibe" / "reports" / "meeting" / "20260529"
    for name in [
        "story.md",
        "timeline.md",
        "leaderboard.md",
        "key_runs.md",
        "idea_pool.md",
        "deep_research_status.md",
        "paper_summary.md",
        "evidence_table.csv",
        "slides_outline.md",
    ]:
        assert (out / name).exists()
    assert (out / "figures").is_dir()
    assert invoke("finalize-reports", "--target", str(tmp_path)).exit_code == 0
    assert (tmp_path / ".vibe" / "reports" / "dev" / "alignment_after_changes.md").exists()
    assert (tmp_path / ".vibe" / "reports" / "dev" / "test_summary.md").exists()
    assert (tmp_path / ".vibe" / "portal" / "INSTALL.md").exists()
    assert (tmp_path / ".vibe" / "portal" / "USAGE.md").exists()


def test_dogfood_command_runs_mock_cycle(tmp_path: Path):
    result = invoke("dogfood", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert (tmp_path / ".vibe" / "site" / "index.html").exists()
    assert (tmp_path / ".vibe" / "reports" / "dev" / "alignment_after_changes.md").exists()


def test_expanded_operator_commands(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("migrate", "--target", str(tmp_path)).exit_code == 0
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    compile_toy_cycle(tmp_path)
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


def test_auto_method_search_creates_candidate_ideas(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "CARE myocardium", "--background", "cardiac MRI", "--no-root-portal").exit_code == 0

    def fake_search(paths, query, *, source="arxiv", limit=10, offline=False, add_candidates=False):
        assert "cardiac MRI myocardium" in query
        assert offline is False
        return [{"title": "Robust cardiac segmentation method", "source_url": "https://example.test/paper", "source": source}]

    monkeypatch.setattr("vibe_research.papers.paper_search", fake_search)
    result = auto_method_search(VibePaths(tmp_path))
    assert result["status"] == "searched"
    assert result["idea_ids"]
    ideas = read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")
    assert ideas[0]["source"] == "auto_method_search"
    assert ideas[0]["status"] == "needs_literature_refresh"
    assert "Robust cardiac segmentation method" in ideas[0]["raw_text"]

    again = auto_method_search(VibePaths(tmp_path))
    assert again["status"] == "already_done"
    assert len(read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")) == 1


def test_v0839_auto_method_search_runs_once_per_cycle_context(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "CARE myocardium", "--background", "cardiac MRI", "--no-root-portal").exit_code == 0
    calls = []

    def fake_search(paths, query, *, source="arxiv", limit=10, offline=False, add_candidates=False):
        calls.append((source, query))
        return [{"title": f"Method {len(calls)}", "source_url": "https://example.test/paper", "source": source}]

    monkeypatch.setattr("vibe_research.papers.paper_search", fake_search)
    first = auto_method_search(VibePaths(tmp_path))
    assert first["status"] == "searched"
    again = auto_method_search(VibePaths(tmp_path))
    assert again["status"] == "already_done"
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["current_cycle_id"] = "c999"
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    next_cycle = auto_method_search(VibePaths(tmp_path))
    assert next_cycle["status"] == "searched"
    marker = read_json(tmp_path / ".vibe" / "research" / "auto_method_search.json", {})
    assert set(marker["searches"]) == {"global", "c999"}


def test_v0839_offline_method_search_skip_does_not_block_later_online_search(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "CARE myocardium", "--background", "cardiac MRI", "--no-root-portal").exit_code == 0
    skipped = auto_method_search(VibePaths(tmp_path), offline=True, force=True)
    assert skipped["status"] == "skipped_offline"

    def fake_search(paths, query, *, source="arxiv", limit=10, offline=False, add_candidates=False):
        return [{"title": "Later Online Method", "source_url": "https://example.test/paper", "source": source}]

    monkeypatch.setattr("vibe_research.papers.paper_search", fake_search)
    online = auto_method_search(VibePaths(tmp_path), offline=False)
    assert online["status"] == "searched"
    ideas = read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")
    assert any("Later Online Method" in row["raw_text"] for row in ideas)


def test_auto_next_monitor_triggers_online_method_search(tmp_path: Path, monkeypatch):
    from vibe_research import automation

    calls = {"search": 0}
    monkeypatch.setattr(automation, "compute_next_action", lambda paths: ("vibe monitor", ""))
    monkeypatch.setattr(automation, "monitor", lambda paths: None)

    def fake_search(paths, *, offline=False, force=False):
        calls["search"] += 1
        assert offline is False
        return {"status": "searched"}

    monkeypatch.setattr(automation, "auto_method_search", fake_search)
    assert automation.auto_next(VibePaths(tmp_path), offline=False) == "monitored"
    assert calls["search"] == 1
    assert automation.auto_next(VibePaths(tmp_path), offline=True) == "monitored"
    assert calls["search"] == 1


def test_slurm_dry_backend_records_launch(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    compile_toy_cycle(tmp_path)
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


def test_synthesized_cycle_decision_uses_supported_train_decision(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("decision", "write-block", "c001", "--reason", "old mismatch", "--decision-type", "blocked_missing_capability", "--target", str(tmp_path)).exit_code == 0

    ok, message = ensure_executable_resource_plan(VibePaths(tmp_path), "c001")
    assert ok, message

    decision = read_json(tmp_path / ".vibe" / "cycles" / "c001" / "cycle_decision.json", {})
    assert decision["decision_type"] == "launch_gpu_gate"
    assert decision["selected_direction"] == "train-smoke"
    plan = read_yaml(tmp_path / ".vibe" / "cycles" / "c001" / "resource_plan.yaml", {})
    run = plan["runs"]["train-smoke"]
    assert run["entrypoint"]["type"] == "slurm"
    assert run["run_kind"] == "real_experiment"
    assert run["adapter_metadata"]["capability_id"] == "train-smoke"

    assert invoke("decision", "write-block", "c001", "--reason", "old mismatch", "--decision-type", "blocked_missing_capability", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    run_id = sorted(state["runs"])[0]
    assert state["runs"][run_id]["adapter_metadata"]["capability_id"] == "train-smoke"
    assert state["runs"][run_id]["entrypoint"]["type"] == "slurm"

    assert subprocess.run(["git", "init"], cwd=tmp_path, text=True, capture_output=True, check=False).returncode == 0
    assert subprocess.run(["git", "add", "."], cwd=tmp_path, text=True, capture_output=True, check=False).returncode == 0
    assert subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "init"], cwd=tmp_path, text=True, capture_output=True, check=False).returncode == 0
    (tmp_path / "dirty.txt").write_text("dirty\n")
    assert invoke("branch", run_id, "--target", str(tmp_path)).exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert state["runs"][run_id]["status"] == "patched"
    assert state["next_action"] == f"vibe dryrun {run_id}"
    assert "branch_skipped=adapter_backed_run" in (tmp_path / ".vibe" / "runs" / run_id / "branch.txt").read_text()
    assert (tmp_path / ".vibe" / "runs" / run_id / "patch.diff").read_text() == ""

    assert invoke("dryrun", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("queue", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("submit-queue", "--target", str(tmp_path), "--dry").exit_code == 0
    launch = read_json(tmp_path / ".vibe" / "runs" / run_id / "launch.json", {})
    assert launch["backend"] == "slurm"
    sbatch = (tmp_path / ".vibe" / "runs" / run_id / "artifacts" / f"{run_id}.sbatch").read_text()
    assert "#SBATCH --qos=gpu_access" in sbatch
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert state["runs"][run_id]["backend"] == "slurm"


def test_new_cycle_clears_stale_run_block_for_next_action(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["status"] = "blocked_missing_decision"
    state["blocked_reason"] = "old run block"
    state["next_action"] = "vibe decision show r001_old"
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)

    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert state["blocked_reason"] == ""
    assert state["next_action"] == "vibe review-cycle c001"
    next_result = invoke("next", "--target", str(tmp_path))
    assert next_result.exit_code == 0
    assert "Blocked:" not in next_result.output
    assert "vibe review-cycle c001" in next_result.output


def test_synthesized_cycle_decision_rotates_less_used_capability(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    paths = VibePaths(tmp_path)
    manifest = load_adapter_manifest(paths)
    second = manifest.capabilities[0].model_copy(deep=True)
    second.id = "train-smoke-b"
    second.description = "Second train smoke capability."
    second.outputs["expected_output_path"] = ".vibe/train_metrics_b.json"
    second.outputs["metrics_file_path"] = ".vibe/train_metrics_b.json"
    second.artifact_rules.expected_outputs = [".vibe/train_metrics_b.json"]
    second.contract_tests = ["train-smoke-b"]
    manifest.capabilities.append(second)
    write_adapter_manifest(paths, manifest)
    write_json(tmp_path / ".vibe" / "contract_tests" / "train-smoke-b.json", {"capability_id": "train-smoke-b", "status": "passed", "created_at": "test"})

    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    first = read_json(tmp_path / ".vibe" / "cycles" / "c001" / "cycle_decision.json", {})
    assert first["selected_direction"] == "train-smoke"

    second_decision = synthesize_cycle_decision(paths, "c002")
    assert second_decision.selected_direction == "train-smoke-b"


def test_v086_strict_preferred_partition_overrides_sinfo_fallback(monkeypatch):
    monkeypatch.setattr("vibe_research.slurm.probe_available_partitions", lambda: ({"a100-gpu"}, "sinfo"))
    manifest = {
        "resources": {
            "preferred_partitions": ["lab-gpu"],
            "fallback_partitions": ["a100-gpu"],
            "strict_preferred_partition": True,
        }
    }
    partition, reason = choose_partition(manifest, {"execution": {"slurm": {"default_partition": "general"}}})
    assert partition == "lab-gpu"
    assert reason == "strict_preferred_partition"


def test_v0106_preferred_partition_requires_wait_policy_before_fallback(monkeypatch):
    monkeypatch.setattr("vibe_research.slurm.probe_available_partitions", lambda: ({"a100-gpu"}, "sinfo"))
    manifest = {
        "resources": {
            "preferred_partitions": ["htzhulab"],
            "fallback_partitions": ["a100-gpu", "volta-gpu"],
        }
    }
    partition, reason = choose_partition(manifest, {"execution": {"slurm": {"default_partition": "general"}}})
    assert partition == "htzhulab"
    assert reason == "preferred_partition_selected: fallback_requires_wait_policy_evidence; sinfo"


def test_v0106_wait_policy_evidence_can_select_fallback(monkeypatch):
    monkeypatch.setattr("vibe_research.slurm.probe_available_partitions", lambda: ({"a100-gpu"}, "sinfo"))
    manifest = {
        "resources": {
            "preferred_partitions": ["htzhulab"],
            "fallback_partitions": ["a100-gpu", "volta-gpu"],
            "wait_verdict": {
                "verdict": "fallback_better_available",
                "recommended_partition": "a100-gpu",
                "preferred_estimated_start_plus_run_hours": 48,
                "recommended_estimated_start_plus_run_hours": 8,
            },
        }
    }
    partition, reason = choose_partition(manifest, {"execution": {"slurm": {"default_partition": "general"}}})
    assert partition == "a100-gpu"
    assert reason == "fallback_selected_after_wait_policy"


def test_v0830_init_records_partition_wait_and_runtime_policy(tmp_path: Path):
    result = invoke(
        "init",
        "--target",
        str(tmp_path),
        "--goal",
        "g",
        "--background",
        "b",
        "--no-root-portal",
        "--preferred-partition",
        "htzhulab",
        "--fallback-partition",
        "a100-gpu",
        "--fallback-partition",
        "volta-gpu",
        "--partition-gres",
        "a100-gpu=gpu:nvidia_a100-pcie-40gb:{gpu}",
        "--partition-gres",
        "volta-gpu=gpu:tesla_v100-sxm2-16gb:{gpu}",
        "--max-pending-start-plus-run-hours",
        "12",
        "--max-run-hours",
        "8",
        "--mature-max-run-hours",
        "24",
        "--delivery-max-run-hours",
        "72",
        "--max-epochs",
        "120",
        "--delivery-max-epochs",
        "5000",
    )
    assert result.exit_code == 0
    config = read_yaml(tmp_path / ".vibe" / "config.yaml", {})
    assert config["execution"]["slurm"]["preferred_partitions"] == ["htzhulab"]
    assert config["execution"]["slurm"]["fallback_partitions"] == ["a100-gpu", "volta-gpu"]
    assert config["execution"]["slurm"]["gres_by_partition"] == {
        "a100-gpu": "gpu:nvidia_a100-pcie-40gb:{gpu}",
        "volta-gpu": "gpu:tesla_v100-sxm2-16gb:{gpu}",
    }
    assert config["execution"]["slurm"]["max_pending_start_plus_run_hours"] == 12
    assert config["scheduler"]["max_run_hours_per_experiment"] == 8
    assert config["scheduler"]["mature_max_run_hours_per_experiment"] == 24
    assert config["scheduler"]["delivery_max_run_hours_per_experiment"] == 72
    assert config["scheduler"]["max_epochs_per_experiment"] == 120
    assert config["scheduler"]["delivery_max_epochs_per_experiment"] == 5000
    budget = read_yaml(tmp_path / ".vibe" / "scheduler" / "budget.yaml", {})
    assert budget["fallback_partitions"] == ["a100-gpu", "volta-gpu"]
    assert budget["delivery_max_run_hours_per_experiment"] == 72


def test_v0830_resource_policy_removes_default_strict_and_caps_runtime():
    resources = {
        "gpu": 1,
        "cpus": 4,
        "mem_gb": 16,
        "time": "100:00:00",
        "epochs": 10000,
        "preferred_partitions": ["htzhulab"],
        "fallback_partitions": ["a100-gpu", "volta-gpu"],
        "strict_preferred_partition": True,
    }
    config = {
        "execution": {"slurm": {"max_pending_start_plus_run_hours": 12}},
        "scheduler": {"max_run_hours_per_experiment": 8, "max_epochs_per_experiment": 120},
    }
    normalized = normalize_run_resources(resources, config)
    assert normalized["preferred_partitions"] == ["htzhulab"]
    assert normalized["fallback_partitions"] == ["a100-gpu", "volta-gpu"]
    assert "strict_preferred_partition" not in normalized
    assert normalized["time"] == "08:00:00"
    assert normalized["epochs"] == 120
    assert normalized["max_epochs"] == 120
    assert normalized["max_pending_start_plus_run_hours"] == 12


def test_v0833_delivery_stage_uses_delivery_runtime_cap():
    resources = {
        "gpu": 1,
        "time": "200:00:00",
        "epochs": 10000,
        "maturity": "delivery",
    }
    config = {
        "scheduler": {
            "max_run_hours_per_experiment": 8,
            "mature_max_run_hours_per_experiment": 24,
            "delivery_max_run_hours_per_experiment": 72,
            "max_epochs_per_experiment": 120,
            "mature_max_epochs_per_experiment": 1000,
            "delivery_max_epochs_per_experiment": 5000,
        }
    }
    normalized = normalize_run_resources(resources, config)
    assert normalized["time"] == "72:00:00"
    assert normalized["epochs"] == 5000
    assert normalized["runtime_limits"]["max_run_hours"] == 72


def test_v0836_real_progress_treats_superseded_failures_as_classified(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {
        "r001_failed": {
            "run_id": "r001_failed",
            "cycle_id": "c001",
            "status": "failed",
            "run_kind": "real_experiment",
            "backend": "slurm",
            "superseded_by": "r002_replacement",
            "adapter_metadata": {"task_type": "train_smoke", "capability_id": "train-smoke"},
        },
        "r002_replacement": {
            "run_id": "r002_replacement",
            "cycle_id": "c001",
            "status": "submitted",
            "run_kind": "real_experiment",
            "backend": "slurm",
            "adapter_metadata": {"task_type": "train_smoke", "capability_id": "train-smoke"},
        },
        "r003_failed": {
            "run_id": "r003_failed",
            "cycle_id": "c001",
            "status": "failed",
            "run_kind": "real_experiment",
            "backend": "slurm",
            "adapter_metadata": {"task_type": "train_smoke", "capability_id": "train-smoke"},
        },
    }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    result = invoke("experiment", "real-progress", "--target", str(tmp_path))
    assert result.exit_code == 0
    progress = json.loads(result.output)
    non_counting_ids = {row["run_id"] for row in progress["non_counting_real_experiment_runs"]}
    assert "r001_failed" not in non_counting_ids
    assert "r003_failed" in non_counting_ids
    failed = next(row for row in progress["all_runs"] if row["run_id"] == "r001_failed")
    assert failed["classification"] == "non_counting_superseded_by:r002_replacement"
    assert failed["requires_repair"] is False
    assert progress["next_action"] == "monitor active replacement real experiments; collect trusted metrics when they finish"


def test_v0841_choose_partition_skips_incompatible_gpu_runtime(monkeypatch):
    monkeypatch.setattr("vibe_research.slurm.probe_available_partitions", lambda: ({"volta-gpu", "a100-gpu"}, "sinfo"))
    manifest = {
        "resources": {
            "gpu": 1,
            "preferred_partitions": ["volta-gpu"],
            "fallback_partitions": ["a100-gpu"],
        }
    }
    config = {
        "execution": {
            "slurm": {
                "runtime_requirements": {"min_cuda_compute_capability": 7.5},
                "partitions": [
                    {"name": "volta-gpu", "gpu_family": "v100", "cuda_compute_capability": 7.0},
                    {"name": "a100-gpu", "gpu_family": "a100", "cuda_compute_capability": 8.0},
                ],
            }
        }
    }
    partition, reason = choose_partition(manifest, config)
    assert partition == "a100-gpu"
    assert reason.startswith("fallback_selected_preferred_incompatible: sinfo")
    assert "skipped_incompatible=volta-gpu=cuda_compute_capability_below_requirement" in reason


def test_v0841_fallback_wait_ignores_incompatible_partition_but_records_evidence():
    import vibe_research.backends as backends

    launch = {
        "partition": "htzhulab",
        "resource_request": {
            "gpu": 1,
            "time": "04:00:00",
            "fallback_partitions": ["volta-gpu", "a100-gpu"],
        },
    }
    config = {
        "execution": {
            "slurm": {
                "max_pending_start_plus_run_hours": 24,
                "runtime_requirements": {"min_cuda_compute_capability": 7.5},
                "fallback_partition_estimates": {"volta-gpu": 4, "a100-gpu": 10},
                "partitions": [
                    {"name": "volta-gpu", "gpu_family": "v100", "cuda_compute_capability": 7.0},
                    {"name": "a100-gpu", "gpu_family": "a100", "cuda_compute_capability": 8.0},
                ],
            }
        }
    }
    verdict = backends.evaluate_wait_policy(
        launch,
        config,
        {"max_start_plus_run_hours": 24, "estimated_start_plus_run_hours": 30},
        ["htzhulab", "volta-gpu", "a100-gpu"],
    )
    assert verdict["recommended_partition"] == "a100-gpu"
    by_partition = {row["partition"]: row for row in verdict["fallback_checked"]}
    assert by_partition["volta-gpu"]["compatible"] is False
    assert "cuda_compute_capability_below_requirement" in by_partition["volta-gpu"]["compatibility_reasons"]
    assert by_partition["a100-gpu"]["compatible"] is True


def test_v0841_next_blocks_on_unrepaired_real_experiment_failure(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {
        "r001_failed": {
            "run_id": "r001_failed",
            "cycle_id": "c001",
            "status": "failed",
            "run_kind": "real_experiment",
            "backend": "slurm",
            "adapter_metadata": {"task_type": "train_smoke", "capability_id": "train-smoke"},
        }
    }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "Blocked: real_experiment_repair_required" in result.output
    assert "vibe experiment real-progress" in result.output


def test_v0841_sustained_audit_blocks_on_unrepaired_real_experiment_failure(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {
        "r001_failed": {
            "run_id": "r001_failed",
            "cycle_id": "c001",
            "status": "failed",
            "run_kind": "real_experiment",
            "backend": "slurm",
            "adapter_metadata": {"task_type": "train_smoke", "capability_id": "train-smoke"},
        }
    }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    result = invoke("research", "sustained-audit", "--target", str(tmp_path))
    assert result.exit_code == 0
    audit = read_json(tmp_path / ".vibe" / "research" / "sustained_round_audit.json", {})
    assert "real_experiment_repair_required" in audit["issues"]
    assert audit["real_experiment_progress"]["repair_blockers"][0]["run_id"] == "r001_failed"
    assert audit["next_action"] == "repair or classify non-counting real experiment failures before planning another round"


def test_v0848_sustained_round_audit_counts_noncounting_terminal_but_not_all_abandoned(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(tmp_path / ".vibe" / "research" / "auto_method_search.json", {"searches": {"test": {"status": "searched"}}})
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["cycles"] = {"c001": {"status": "reviewed"}, "c002": {"status": "reviewed"}}
    state["runs"] = {}
    for cycle_id, status, classification in [
        ("c001", "blocked", "non_counting_execution_failure:failed"),
        ("c002", "abandoned", ""),
    ]:
        cycle_dir = tmp_path / ".vibe" / "cycles" / cycle_id
        cycle_dir.mkdir(parents=True, exist_ok=True)
        (cycle_dir / "cycle_reflect.md").write_text("## Run comparison\n\n## Route classification\n")
        (cycle_dir / "cycle_revised_plan.md").write_text("## Next-cycle diversity requirement\n")
        for idx, cap_id in enumerate(["cap-a", "cap-b", "cap-c"], start=1):
            run = {
                "run_id": f"{cycle_id}_r{idx}",
                "cycle_id": cycle_id,
                "status": status,
                "adapter_metadata": {"capability_id": cap_id, "task_type": "train_smoke"},
            }
            if classification:
                run["non_counting_classification"] = classification
            state["runs"][run["run_id"]] = run
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)

    result = invoke("research", "sustained-audit", "--target", str(tmp_path))
    assert result.exit_code == 0
    audit = read_json(tmp_path / ".vibe" / "research" / "sustained_round_audit.json", {})
    rows = {row["cycle_id"]: row for row in audit["cycles"]}
    assert rows["c001"]["round_complete"] is True
    assert rows["c001"]["attempted_route_count"] == 3
    assert rows["c002"]["round_complete"] is False
    assert rows["c002"]["all_runs_abandoned"] is True
    assert audit["completed_round_count"] == 1


def test_v0848_sustained_round_audit_surfaces_missing_capability_block(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(tmp_path / ".vibe" / "research" / "auto_method_search.json", {"searches": {"test": {"status": "searched"}}})
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["status"] = "blocked_missing_capability"
    state["blocked_reason"] = "active capabilities exactly repeat non-counting cycle"
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    result = invoke("research", "sustained-audit", "--target", str(tmp_path))
    assert result.exit_code == 0
    audit = read_json(tmp_path / ".vibe" / "research" / "sustained_round_audit.json", {})
    assert "blocked_missing_capability" in audit["issues"]
    assert audit["next_action"] == "run adapter doctor, activate a changed executable capability, or repair missing inputs before scheduling another sustained round"


def test_v0853_sustained_audit_flags_outside_wait_fallback(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(tmp_path / ".vibe" / "research" / "auto_method_search.json", {"searches": {"test": {"status": "searched"}}})
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {
            "active": [
                {
                    "run_id": "r001",
                    "cycle_id": "c001",
                    "backend": "slurm",
                    "status": "pending",
                    "poll_details": {"wait_verdict": {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "htzhulab"}},
                }
            ]
        },
    )
    result = invoke("research", "sustained-audit", "--target", str(tmp_path))
    assert result.exit_code == 0
    audit = read_json(tmp_path / ".vibe" / "research" / "sustained_round_audit.json", {})
    assert "fallback_better_but_outside_wait_policy" in audit["issues"]
    assert audit["next_action"] == "run vibe scheduler-requeue-fallback --allow-outside-policy to review fallback candidates before any explicit execute"


def test_v0858_next_links_outside_policy_fallback_review_command(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {
            "active": [
                {
                    "run_id": "r001",
                    "cycle_id": "c001",
                    "backend": "slurm",
                    "status": "pending",
                    "poll_details": {"wait_verdict": {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "htzhulab"}},
                }
            ]
        },
    )
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "vibe scheduler-requeue-fallback --allow-outside-policy" in result.output


def test_v0856_monitor_carries_forward_wait_verdict_after_transient_unknown(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    run_id = "r001_wait"
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {run_id: {"run_id": run_id, "cycle_id": "c001", "status": "submitted"}}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    prior = {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "htzhulab", "recommended_estimated_start_plus_run_hours": 20}
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {"active": [{"run_id": run_id, "cycle_id": "c001", "backend": "slurm", "job_id": "111", "poll_details": {"wait_verdict": prior}}]},
    )

    class FakeBackend:
        name = "slurm"

        def poll(self, launch):
            return PollResult("unknown", False, {"poll_timeout": True, "command": "squeue"})

        def cancel(self, launch):
            raise AssertionError("carried-forward wait evidence must not auto-cancel")

    monkeypatch.setattr("vibe_research.scheduler.get_backend", lambda paths, backend_name=None: FakeBackend())
    assert invoke("monitor", "--target", str(tmp_path)).exit_code == 0
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    details = active["active"][0]["poll_details"]
    assert details["wait_verdict"] == prior
    assert details["carried_forward_wait_verdict"] is True
    assert details["carried_forward_wait_source"] == "active_jobs_previous_poll_details"


def test_v0856_monitor_carries_forward_wait_verdict_from_monitor_jsonl(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    run_id = "r001_wait"
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {run_id: {"run_id": run_id, "cycle_id": "c001", "status": "submitted"}}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    prior = {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "htzhulab"}
    append_jsonl(run_dir / "monitor.jsonl", {"checked_at": "test", "wait_verdict": prior, "wait_policy": {"max_start_plus_run_hours": 12}})
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [{"run_id": run_id, "cycle_id": "c001", "backend": "slurm", "job_id": "111"}]})

    class FakeBackend:
        name = "slurm"

        def poll(self, launch):
            return PollResult("unknown", False, {"reason": "slurm_query_unavailable"})

    monkeypatch.setattr("vibe_research.scheduler.get_backend", lambda paths, backend_name=None: FakeBackend())
    assert invoke("monitor", "--target", str(tmp_path)).exit_code == 0
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    details = active["active"][0]["poll_details"]
    assert details["wait_verdict"] == prior
    assert details["wait_policy"]["max_start_plus_run_hours"] == 12
    assert details["carried_forward_wait_source"] == "run_monitor_jsonl"


def test_v0857_fallback_requeue_dry_run_blocks_outside_policy_without_allow(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {"active": [{"run_id": "r001", "job_id": "111", "backend": "slurm", "partition": "a100", "poll_details": {"wait_verdict": {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "lab"}}}]},
    )
    result = invoke("fallback-requeue", "--target", str(tmp_path))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["candidates"][0]["eligible"] is False
    assert data["candidates"][0]["blocked_reason"] == "outside_wait_policy_requires_allow_outside_policy"
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert active["active"][0]["job_id"] == "111"


def test_v0857_fallback_requeue_execute_with_outside_policy_records_provenance(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    run_id = "r001"
    run = {
        "run_id": run_id,
        "cycle_id": "c001",
        "direction_id": "d001",
        "branch": "",
        "hypothesis": "fallback requeue",
        "status": "submitted",
        "entrypoint": {"type": "slurm", "command": "python train.py"},
        "dryrun": {"command": "python -c 'print(1)'"},
        "resources": {"gpu": 1, "cpus": 1, "mem_gb": 1, "time": "00:10:00"},
    }
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {run_id: run}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "manifest.json", run)
    write_yaml(run_dir / "manifest.yaml", run)
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {"active": [{"run_id": run_id, "cycle_id": "c001", "job_id": "111", "backend": "slurm", "partition": "a100", "poll_details": {"wait_verdict": {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "lab"}}}]},
    )

    class FakeBackend:
        name = "slurm"

        def cancel(self, launch):
            return {"returncode": 0, "job_id": launch.get("job_id")}

        def submit(self, submitted_run_id, *, dry=False):
            manifest = read_json(tmp_path / ".vibe" / "runs" / submitted_run_id / "manifest.json", {})
            return {"run_id": submitted_run_id, "cycle_id": "c001", "backend": "slurm", "job_id": "222", "status": "submitted", "partition": manifest["resources"]["force_partition"], "resource_request": manifest["resources"]}

    monkeypatch.setattr("vibe_research.scheduler.get_backend", lambda paths, backend_name=None: FakeBackend())
    result = invoke("fallback-requeue", "--target", str(tmp_path), "--execute", "--allow-outside-policy", "--run-id", run_id)
    assert result.exit_code == 0
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert active["active"][0]["job_id"] == "222"
    assert active["active"][0]["partition"] == "lab"
    completed = read_jsonl(tmp_path / ".vibe" / "scheduler" / "completed_jobs.jsonl")
    assert completed[-1]["status"] == "cancelled_for_fallback"
    assert completed[-1]["operator_requeue"] is True


def test_v0859_fallback_requeue_execute_requires_explicit_scope(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {"active": [{"run_id": "r001", "job_id": "111", "backend": "slurm", "partition": "a100", "poll_details": {"wait_verdict": {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "lab"}}}]},
    )
    result = invoke("fallback-requeue", "--target", str(tmp_path), "--execute", "--allow-outside-policy")
    assert result.exit_code == 2
    assert "--execute requires --run-id <run> or --all" in result.output
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert active["active"][0]["job_id"] == "111"


def test_v0859_fallback_requeue_dry_run_writes_self_contained_approval_request(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {"active": [{"run_id": "r001", "job_id": "111", "backend": "slurm", "partition": "a100", "poll_details": {"wait_verdict": {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "lab"}}}]},
    )
    result = invoke("scheduler-requeue-fallback", "--target", str(tmp_path), "--allow-outside-policy")
    assert result.exit_code == 0
    data = json.loads(result.output)
    command = data["candidates"][0]["executable_command"]
    assert f"--target {shlex_quote(str(tmp_path))}" in command
    assert "--run-id r001" in command
    assert "--execute" in command
    assert "--allow-outside-policy" in command
    latest_json = read_json(tmp_path / ".vibe" / "scheduler" / "fallback_requeue_requests" / "latest.json", {})
    latest_md = (tmp_path / ".vibe" / "scheduler" / "fallback_requeue_requests" / "latest.md").read_text()
    assert latest_json["status"] == "dry_run_only_not_executed"
    assert latest_json["target"] == str(tmp_path.resolve())
    assert latest_json["rows"][0]["run_id"] == "r001"
    assert latest_json["rows"][0]["executable_command"] == command
    assert command in latest_md
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert active["active"][0]["job_id"] == "111"


def test_v0106_requeue_request_surfaces_move_back_to_preferred_command(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {
            "active": [
                {
                    "run_id": "r001",
                    "job_id": "111",
                    "backend": "slurm",
                    "status": "pending",
                    "partition": "a100-gpu",
                    "resource_request": {
                        "preferred_partitions": ["htzhulab"],
                        "fallback_partitions": ["a100-gpu", "volta-gpu"],
                    },
                }
            ]
        },
    )
    result = invoke("scheduler-requeue-fallback", "--target", str(tmp_path))
    assert result.exit_code == 0
    data = json.loads(result.output)
    command = data["candidates"][0]["preferred_requeue_command"]
    assert "--run-id r001" in command
    assert "--execute" in command
    assert "--to-preferred" in command
    latest_md = (tmp_path / ".vibe" / "scheduler" / "fallback_requeue_requests" / "latest.md").read_text()
    assert command in latest_md


def test_v0859_fallback_requeue_execute_run_id_only_requeues_selected_job(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    for run_id in ["r001", "r002"]:
        run = {
            "run_id": run_id,
            "cycle_id": "c001",
            "direction_id": f"d-{run_id}",
            "branch": "",
            "hypothesis": "fallback requeue",
            "status": "submitted",
            "entrypoint": {"type": "slurm", "command": "python train.py"},
            "dryrun": {"command": "python -c 'print(1)'"},
            "resources": {"gpu": 1, "cpus": 1, "mem_gb": 1, "time": "00:10:00"},
        }
        state.setdefault("runs", {})[run_id] = run
        run_dir = tmp_path / ".vibe" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_dir / "manifest.json", run)
        write_yaml(run_dir / "manifest.yaml", run)
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {
            "active": [
                {"run_id": "r001", "cycle_id": "c001", "job_id": "111", "backend": "slurm", "partition": "a100", "poll_details": {"wait_verdict": {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "lab"}}},
                {"run_id": "r002", "cycle_id": "c001", "job_id": "112", "backend": "slurm", "partition": "a100", "poll_details": {"wait_verdict": {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "lab"}}},
            ]
        },
    )

    class FakeBackend:
        name = "slurm"

        def cancel(self, launch):
            return {"returncode": 0, "job_id": launch.get("job_id")}

        def submit(self, submitted_run_id, *, dry=False):
            manifest = read_json(tmp_path / ".vibe" / "runs" / submitted_run_id / "manifest.json", {})
            return {"run_id": submitted_run_id, "cycle_id": "c001", "backend": "slurm", "job_id": "222", "status": "submitted", "partition": manifest["resources"]["force_partition"], "resource_request": manifest["resources"]}

    monkeypatch.setattr("vibe_research.scheduler.get_backend", lambda paths, backend_name=None: FakeBackend())
    result = invoke("scheduler-requeue-fallback", "--target", str(tmp_path), "--execute", "--allow-outside-policy", "--run-id", "r001")
    assert result.exit_code == 0
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert [row["run_id"] for row in active["active"]] == ["r001", "r002"]
    assert active["active"][0]["job_id"] == "222"
    assert active["active"][1]["job_id"] == "112"
    completed = read_jsonl(tmp_path / ".vibe" / "scheduler" / "completed_jobs.jsonl")
    assert len(completed) == 1
    assert completed[0]["run_id"] == "r001"


def test_v0859_sustained_audit_persists_executable_resource_issue_command(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {"active": [{"run_id": "r001", "cycle_id": "c001", "job_id": "111", "backend": "slurm", "partition": "a100", "poll_details": {"wait_verdict": {"verdict": "fallback_better_but_outside_wait_policy", "recommended_partition": "lab"}}}]},
    )
    result = invoke("research", "sustained-audit", "--target", str(tmp_path))
    assert result.exit_code == 0
    audit = read_json(tmp_path / ".vibe" / "research" / "sustained_round_audit.json", {})
    command = audit["active_resource_issues"][0]["executable_command"]
    assert f"--target {shlex_quote(str(tmp_path))}" in command
    assert "--run-id r001" in command
    assert "--execute" in command
    assert "--allow-outside-policy" in command
    markdown = (tmp_path / ".vibe" / "research" / "sustained_round_audit.md").read_text()
    assert command in markdown


def test_v0860_sustained_selftest_creates_isolated_passing_workspace(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    result = invoke("research", "sustained-selftest", "--target", str(tmp_path))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "passed"
    assert data["completed_round_count"] == 3
    assert data["candidate_count"] >= 3
    assert data["issues"] == []
    workspace = Path(data["workspace"])
    assert workspace.exists()
    assert tmp_path / ".vibe" / "selftests" / "sustained_round" in workspace.parents
    latest = read_json(tmp_path / ".vibe" / "selftests" / "sustained_round" / "latest.json", {})
    latest_md = (tmp_path / ".vibe" / "selftests" / "sustained_round" / "latest.md").read_text()
    assert latest["status"] == "passed"
    assert latest["workspace"] == data["workspace"]
    assert "Status: `passed`" in latest_md
    audit = read_json(workspace / ".vibe" / "research" / "sustained_round_audit.json", {})
    assert audit["complete"] is True
    assert audit["issues"] == []
    assert len(default_candidates(VibePaths(workspace))) >= 3


def test_v0844_next_clears_stale_noncounting_run_block_after_cycle_revision(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    cycle_dir = tmp_path / ".vibe" / "cycles" / "c001"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    (cycle_dir / "cycle_reflect.md").write_text("reflected\n")
    (cycle_dir / "cycle_revised_plan.md").write_text("revised\n")
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state.update(
        {
            "status": "blocked_missing_decision",
            "blocked_reason": "same decision repeated 2 times: blocked_missing_decision",
            "next_action": "vibe decision show r001_noncounting",
            "current_cycle_id": "c001",
            "cycles": {"c001": {"status": "reviewed"}},
            "runs": {
                "r001_noncounting": {
                    "run_id": "r001_noncounting",
                    "cycle_id": "c001",
                    "status": "blocked",
                    "non_counting_classification": "non_counting_execution_failure:failed",
                }
            },
        }
    )
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "Blocked:" not in result.output
    assert "vibe plan-cycle" in result.output


def test_v0844_next_clears_stale_cycle_block_after_abandoned_cycle_revision(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    cycle_dir = tmp_path / ".vibe" / "cycles" / "c009"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    (cycle_dir / "cycle_reflect.md").write_text("reflected\n")
    (cycle_dir / "cycle_revised_plan.md").write_text("revised\n")
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state.update(
        {
            "status": "blocked_missing_decision",
            "blocked_reason": "same decision repeated 2 times: blocked_missing_decision",
            "next_action": "vibe decision show c009",
            "current_cycle_id": "c009",
            "cycles": {"c009": {"status": "reviewed"}},
            "runs": {
                "r001_abandoned": {"run_id": "r001_abandoned", "cycle_id": "c009", "status": "abandoned"},
                "r002_abandoned": {"run_id": "r002_abandoned", "cycle_id": "c009", "status": "abandoned"},
            },
        }
    )
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "Blocked:" not in result.output
    assert "vibe plan-cycle" in result.output


def test_v0105_next_suppresses_stale_blocked_prefix_after_round_recovery(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    cycle_dir = tmp_path / ".vibe" / "cycles" / "c001"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    (cycle_dir / "cycle_reflect.md").write_text("## Run comparison\nok\n## Route classification\nok\n")
    (cycle_dir / "cycle_revised_plan.md").write_text("## Next-cycle diversity requirement\nok\n")
    write_json(tmp_path / ".vibe" / "research" / "sustained_round_audit.json", {"issues": [], "next_action": "plan the next multi-route portfolio"})
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state.update(
        {
            "status": "blocked_repeating_evidence",
            "blocked_reason": "same decision repeated 2 times: collect_more_metrics",
            "next_action": "vibe plan-cycle",
            "current_cycle_id": "c001",
            "cycles": {"c001": {"status": "reviewed"}},
            "runs": {
                "r001": {"run_id": "r001", "cycle_id": "c001", "status": "revised"},
                "r002": {"run_id": "r002", "cycle_id": "c001", "status": "revised"},
                "r003": {"run_id": "r003", "cycle_id": "c001", "status": "revised"},
            },
        }
    )
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "Blocked:" not in result.output
    assert "Next:" in result.output
    assert "vibe plan-cycle" in result.output
    updated = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert updated["blocked_reason"] == ""


def test_v0833_render_sbatch_uses_explicit_partition_specific_gres(tmp_path: Path):
    manifest = {
        "run_id": "r001",
        "resources": {"gpu": 1, "cpus": 1, "mem_gb": 4, "time": "01:00:00"},
        "entrypoint": {"command": "python train.py"},
    }
    config = {
        "execution": {
            "slurm": {
                "gres_by_partition": {
                    "a100-gpu": "gpu:nvidia_a100-pcie-40gb:{gpu}",
                    "volta-gpu": "gpu:tesla_v100-sxm2-16gb:{gpu}",
                }
            }
        }
    }
    a100 = render_sbatch(manifest, workdir=tmp_path, output=tmp_path / "out", error=tmp_path / "err", partition="a100-gpu", config=config)
    volta = render_sbatch(manifest, workdir=tmp_path, output=tmp_path / "out", error=tmp_path / "err", partition="volta-gpu", config=config)
    assert "#SBATCH --gres=gpu:nvidia_a100-pcie-40gb:1" in a100
    assert "#SBATCH --gres=gpu:tesla_v100-sxm2-16gb:1" in volta


def test_v0833_named_gpu_partitions_are_examples_not_builtin_defaults(tmp_path: Path):
    manifest = {
        "run_id": "r001",
        "resources": {"gpu": 1, "cpus": 1, "mem_gb": 4, "time": "01:00:00"},
        "entrypoint": {"command": "python train.py"},
    }
    script = render_sbatch(manifest, workdir=tmp_path, output=tmp_path / "out", error=tmp_path / "err", partition="a100-gpu", config={})
    assert "#SBATCH --gres=gpu:1" in script
    assert "nvidia_a100" not in script


def test_v0831_vibe_module_commands_use_current_python():
    from vibe_research.adapters import normalize_python_command

    command = "/old/external/env/bin/python -m vibe_research.some_entry --arg x"
    config = {"execution": {"python": {"executable": "/current/env/bin/python", "rewrite_vibe_module_commands": True}}}
    assert normalize_python_command(command, config).startswith("/current/env/bin/python -m vibe_research.some_entry")


def test_v0831_monitor_requeues_to_better_fallback_when_opted_in(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    config = read_yaml(tmp_path / ".vibe" / "config.yaml", {})
    config.setdefault("execution", {}).setdefault("slurm", {})["auto_requeue_to_better_fallback"] = True
    write_yaml(tmp_path / ".vibe" / "config.yaml", config)
    write_json(tmp_path / ".vibe" / "config.json", config)
    run_id = "r001_fallback"
    run = {
        "run_id": run_id,
        "cycle_id": "c001",
        "status": "submitted",
        "entrypoint": {"type": "slurm", "command": "python train.py"},
        "resources": {"gpu": 1, "cpus": 1, "mem_gb": 4, "time": "04:00:00", "preferred_partitions": ["preferred"], "fallback_partitions": ["fallback"]},
    }
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state.setdefault("runs", {})[run_id] = run
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True)
    write_json(run_dir / "manifest.json", run)
    write_yaml(run_dir / "manifest.yaml", run)
    (run_dir / "monitor.jsonl").write_text("")
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [{"run_id": run_id, "cycle_id": "c001", "backend": "slurm", "job_id": "111", "partition": "preferred", "resource_request": run["resources"]}]})

    class FakeBackend:
        name = "slurm"

        def poll(self, launch):
            return PollResult(
                "pending",
                False,
                {"wait_verdict": {"verdict": "fallback_better_available", "recommended_partition": "fallback", "recommended_estimated_start_plus_run_hours": 8}},
            )

        def cancel(self, launch):
            return {"returncode": 0, "job_id": launch.get("job_id")}

        def submit(self, submitted_run_id, *, dry=False):
            manifest = read_json(tmp_path / ".vibe" / "runs" / submitted_run_id / "manifest.json", {})
            return {
                "run_id": submitted_run_id,
                "cycle_id": "c001",
                "backend": "slurm",
                "job_id": "222",
                "status": "submitted",
                "partition": manifest["resources"]["force_partition"],
                "resource_request": manifest["resources"],
            }

    monkeypatch.setattr("vibe_research.scheduler.get_backend", lambda paths, backend_name=None: FakeBackend())
    assert invoke("monitor", "--target", str(tmp_path)).exit_code == 0
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert active["active"][0]["job_id"] == "222"
    assert active["active"][0]["partition"] == "fallback"
    manifest = read_json(run_dir / "manifest.json", {})
    assert manifest["resources"]["force_partition"] == "fallback"
    completed = read_jsonl(tmp_path / ".vibe" / "scheduler" / "completed_jobs.jsonl")
    assert completed[-1]["status"] == "cancelled_for_fallback_requeue"


def test_v087_compile_preserves_active_job_next_action(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [{"run_id": "r999_active", "status": "running", "backend": "slurm"}]})
    assert invoke("decision", "write", "c001", "--type", "collect_more_metrics", "--action", "collect metrics", "--target", str(tmp_path)).exit_code == 0
    assert invoke("compile-decision", "c001", "--target", str(tmp_path)).exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert state["status"] == "jobs_active"
    assert state["next_action"] == "vibe monitor"
    assert "Next action: `vibe monitor`" in invoke("status", "--target", str(tmp_path)).output


def test_v087_slurm_poll_records_wait_evidence(tmp_path: Path, monkeypatch):
    def fake_run(args, **kwargs):
        if args[:2] == ["squeue", "-j"]:
            return subprocess.CompletedProcess(args, 0, stdout="PENDING|Resources\n", stderr="")
        if args[:2] == ["squeue", "--start"]:
            return subprocess.CompletedProcess(args, 0, stdout="2099-01-01T00:00:00\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    backend = SlurmBackend(VibePaths(tmp_path), {"execution": {"slurm": {"max_pending_start_plus_run_hours": 24}}})
    poll = backend.poll({"job_id": "123", "resource_request": {"time": "04:00:00"}})
    assert poll.status == "pending"
    assert poll.finished is False
    assert poll.details["squeue_start_stdout"] == "2099-01-01T00:00:00"
    assert poll.details["requested_walltime"] == "04:00:00"
    assert poll.details["wait_policy"]["verdict"] == "exceeds_policy"


def test_v087_slurm_poll_uses_default_wait_policy(tmp_path: Path, monkeypatch):
    def fake_run(args, **kwargs):
        if args[:2] == ["squeue", "-j"]:
            return subprocess.CompletedProcess(args, 0, stdout="PENDING|Resources\n", stderr="")
        if args[:2] == ["squeue", "--start"]:
            return subprocess.CompletedProcess(args, 0, stdout="2099-01-01T00:00:00\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    backend = SlurmBackend(VibePaths(tmp_path), ProjectConfig().model_dump())
    poll = backend.poll({"job_id": "123", "resource_request": {"time": "04:00:00"}})
    assert poll.details["wait_policy"]["max_start_plus_run_hours"] == 24.0
    assert poll.details["wait_policy"]["verdict"] == "exceeds_policy"


def test_v087_slurm_naive_start_time_uses_local_timezone(monkeypatch):
    import vibe_research.backends as backends

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 30, 16, 0, 0, tzinfo=tz)

    monkeypatch.setattr(backends, "datetime", FakeDateTime)
    assert backends.start_plus_run_hours("2026-05-30T17:00:00", "04:00:00") == 5.0


def test_v089_slurm_poll_records_fallback_wait_verdict(tmp_path: Path, monkeypatch):
    def fake_run(args, **kwargs):
        if args[:2] == ["squeue", "-j"]:
            return subprocess.CompletedProcess(args, 0, stdout="PENDING|Priority\n", stderr="")
        if args[:2] == ["squeue", "--start"]:
            return subprocess.CompletedProcess(args, 0, stdout="2099-01-01T00:00:00\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    backend = SlurmBackend(
        VibePaths(tmp_path),
        {
            "execution": {
                "slurm": {
                    "max_pending_start_plus_run_hours": 24,
                    "fallback_partition_estimates": {"fallback": 12},
                }
            }
        },
    )
    poll = backend.poll({"job_id": "123", "partition": "preferred", "resource_request": {"time": "04:00:00", "fallback_partitions": ["fallback"]}})
    assert poll.details["wait_verdict"]["verdict"] == "fallback_better_available"
    assert poll.details["wait_verdict"]["recommended_partition"] == "fallback"


def test_v089_slurm_fallback_estimates_use_sbatch_test_only(tmp_path: Path, monkeypatch):
    import vibe_research.backends as backends

    script = tmp_path / "run.sbatch"
    script.write_text("#!/usr/bin/env bash\n")

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 30, 16, 0, 0, tzinfo=tz)

    def fake_run(args, **kwargs):
        assert args[:3] == ["sbatch", "--test-only", "--partition=a100-gpu"]
        assert "--gres=gpu:nvidia_a100-pcie-40gb:1" in args
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="sbatch: Job 1 to start at 2026-05-30T18:00:00 a using 8 processors on nodes g1 in partition a100-gpu\n")

    monkeypatch.setattr(backends, "datetime", FakeDateTime)
    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    rows = backends.fallback_completion_estimates(
        {"sbatch_path": str(script), "resource_request": {"gpu": 1, "time": "04:00:00", "qos": "gpu_access"}},
        {"execution": {"slurm": {"gres_by_partition": {"a100-gpu": "gpu:nvidia_a100-pcie-40gb:{gpu}"}}}},
        ["a100-gpu"],
    )
    assert rows == [{"partition": "a100-gpu", "estimated_start_plus_run_hours": 6.0, "source": "sbatch_test_only"}]


def test_v0837_missing_start_estimate_uses_fallback_candidates(tmp_path: Path, monkeypatch):
    script = tmp_path / "run.sbatch"
    script.write_text("#!/usr/bin/env bash\n")

    def fake_run(args, **kwargs):
        if args[:3] == ["scontrol", "show", "job"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"JobId=123 WorkDir={tmp_path}\n", stderr="")
        if args[:2] == ["squeue", "-j"]:
            return subprocess.CompletedProcess(args, 0, stdout="PENDING|Priority\n", stderr="")
        if args[:2] == ["squeue", "--start"]:
            return subprocess.CompletedProcess(args, 0, stdout="N/A\n", stderr="")
        if args[:3] == ["sbatch", "--test-only", "--partition=volta-gpu"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="sbatch: Job 1 to start at 2026-05-30T18:00:00 x\n")
        if args[:3] == ["sbatch", "--test-only", "--partition=htzhulab"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="sbatch: Job 1 to start at 2026-05-31T18:00:00 x\n")
        if args[:3] == ["sbatch", "--test-only", "--partition=a100-gpu"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="sbatch: Job 1 to start at 2027-05-30T18:00:00 x\n")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    import vibe_research.backends as backends

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 30, 16, 0, 0, tzinfo=tz)

    monkeypatch.setattr(backends, "datetime", FakeDateTime)
    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    backend = SlurmBackend(VibePaths(tmp_path), {"execution": {"slurm": {"max_pending_start_plus_run_hours": 12, "fallback_partitions": ["a100-gpu", "volta-gpu"]}}})
    poll = backend.poll(
        {
            "job_id": "123",
            "partition": "htzhulab",
            "sbatch_path": str(script),
            "launch_workdir": str(tmp_path),
            "resource_request": {"gpu": 1, "time": "04:00:00", "preferred_partitions": ["htzhulab"], "fallback_partitions": ["a100-gpu", "volta-gpu"]},
        }
    )
    assert poll.details["candidate_partitions"] == ["htzhulab", "a100-gpu", "volta-gpu"]
    assert poll.details["wait_verdict"]["verdict"] == "fallback_better_available"
    assert poll.details["wait_verdict"]["recommended_partition"] == "volta-gpu"


def test_v0837_fallback_comparison_keeps_original_preferred_and_excludes_self():
    import vibe_research.backends as backends

    launch = {
        "partition": "volta-gpu",
        "resource_request": {
            "time": "04:00:00",
            "preferred_partitions": ["htzhulab"],
            "fallback_partitions": ["a100-gpu", "volta-gpu"],
            "fallback_partition_estimates": {"volta-gpu": 20, "htzhulab": 8, "a100-gpu": 400},
        },
    }
    config = {"execution": {"slurm": {"default_partition": "htzhulab", "max_pending_start_plus_run_hours": 12}}}
    verdict = backends.evaluate_wait_policy(launch, config, {"max_start_plus_run_hours": 12, "estimated_start_plus_run_hours": 20}, ["volta-gpu", "htzhulab", "a100-gpu"])
    assert verdict["recommended_partition"] == "htzhulab"
    assert verdict["recommended_partition"] != "volta-gpu"


def test_v0847_missing_squeue_start_does_not_requeue_outside_wait_policy():
    config = {"execution": {"slurm": {"auto_requeue_to_better_fallback": True, "max_wait_hours_for_fallback": 12}}}
    job = {"backend": "slurm", "partition": "preferred"}
    assert not should_requeue_to_fallback(
        config,
        job,
        {"wait_verdict": {"verdict": "fallback_better_available", "recommended_partition": "a100-gpu", "recommended_estimated_start_plus_run_hours": None}},
    )
    assert not should_requeue_to_fallback(
        config,
        job,
        {"wait_verdict": {"verdict": "fallback_better_available", "recommended_partition": "a100-gpu", "recommended_estimated_start_plus_run_hours": 20}},
    )
    assert should_requeue_to_fallback(
        config,
        job,
        {"wait_verdict": {"verdict": "fallback_better_available", "recommended_partition": "a100-gpu", "recommended_estimated_start_plus_run_hours": 8}},
    )
    override = {"execution": {"slurm": {"auto_requeue_to_better_fallback": True, "max_wait_hours_for_fallback": 12, "allow_fallback_outside_wait_policy": True}}}
    assert should_requeue_to_fallback(
        override,
        job,
        {"wait_verdict": {"verdict": "fallback_better_available", "recommended_partition": "a100-gpu", "recommended_estimated_start_plus_run_hours": None}},
    )


def test_v0853_fallback_better_but_outside_wait_policy_has_distinct_verdict():
    import vibe_research.backends as backends

    launch = {
        "partition": "a100-gpu",
        "resource_request": {
            "time": "04:00:00",
            "fallback_partitions": ["htzhulab"],
            "fallback_partition_estimates": {"a100-gpu": 40, "htzhulab": 20},
        },
    }
    verdict = backends.evaluate_wait_policy(
        launch,
        {"execution": {"slurm": {"max_pending_start_plus_run_hours": 12}}},
        {"max_start_plus_run_hours": 12, "estimated_start_plus_run_hours": None},
        ["a100-gpu", "htzhulab"],
    )
    assert verdict["verdict"] == "fallback_better_but_outside_wait_policy"
    assert verdict["preferred_estimated_start_plus_run_hours"] == 40.0
    assert verdict["recommended_partition"] == "htzhulab"
    assert verdict["recommended_estimated_start_plus_run_hours"] == 20.0
    assert verdict["max_start_plus_run_hours"] == 12.0


def test_v0847_slurm_poll_timeout_returns_unknown_not_hang(tmp_path: Path, monkeypatch):
    def fake_run(args, **kwargs):
        if args[:3] == ["scontrol", "show", "job"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"JobId=123 WorkDir={tmp_path}\n", stderr="")
        if args[:2] == ["squeue", "-j"]:
            raise subprocess.TimeoutExpired(args, timeout=10)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    backend = SlurmBackend(VibePaths(tmp_path), {"execution": {"slurm": {}}})
    poll = backend.poll({"job_id": "123", "backend": "slurm", "launch_workdir": str(tmp_path), "resource_request": {"time": "01:00:00"}})
    assert poll.status == "unknown"
    assert poll.finished is False
    assert poll.details["poll_timeout"] is True
    assert poll.details["command"] == "squeue"


def test_v0851_squeue_socket_error_returns_unknown_without_sacct(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args[0])
        if args[:3] == ["scontrol", "show", "job"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"JobId=123 WorkDir={tmp_path}\n", stderr="")
        if args[:2] == ["squeue", "-j"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="Error creating slurm stream socket: Operation not permitted\n")
        if args[:2] == ["sacct", "-j"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="accounting unavailable\n")
        raise AssertionError(f"unexpected call: {args}")

    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    backend = SlurmBackend(VibePaths(tmp_path), {"execution": {"slurm": {}}})
    poll = backend.poll({"job_id": "123", "backend": "slurm", "launch_workdir": str(tmp_path), "resource_request": {"time": "01:00:00"}})
    assert poll.status == "unknown"
    assert poll.finished is False
    assert poll.details["reason"] == "slurm_accounting_record_unavailable"
    assert calls == ["scontrol", "squeue", "sacct"]


def test_v0851_empty_sacct_record_returns_unknown_not_finished(tmp_path: Path, monkeypatch):
    def fake_run(args, **kwargs):
        if args[:3] == ["scontrol", "show", "job"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"JobId=123 WorkDir={tmp_path}\n", stderr="")
        if args[:2] == ["squeue", "-j"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:2] == ["sacct", "-j"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    backend = SlurmBackend(VibePaths(tmp_path), {"execution": {"slurm": {}}})
    poll = backend.poll({"job_id": "123", "backend": "slurm", "launch_workdir": str(tmp_path), "resource_request": {"time": "01:00:00"}})
    assert poll.status == "unknown"
    assert poll.finished is False
    assert poll.details["reason"] == "slurm_accounting_record_unavailable"


def test_v0824_slurm_wait_policy_defaults_and_naive_start_is_local(tmp_path: Path, monkeypatch):
    future_local = (datetime.now().astimezone() + timedelta(hours=1)).replace(tzinfo=None, microsecond=0).isoformat()
    total = start_plus_run_hours(future_local, "04:00:00")
    assert total is not None
    assert 4.9 <= total <= 5.1

    def fake_run(args, **kwargs):
        if args[:3] == ["scontrol", "show", "job"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"JobId=123 WorkDir={tmp_path}\n", stderr="")
        if args[:2] == ["squeue", "-j"]:
            return subprocess.CompletedProcess(args, 0, stdout="PENDING|Priority\n", stderr="")
        if args[:2] == ["squeue", "--start"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"{future_local}\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    backend = SlurmBackend(VibePaths(tmp_path), {"execution": {"slurm": {}}})
    poll = backend.poll({"job_id": "123", "partition": "preferred", "launch_workdir": str(tmp_path), "resource_request": {"time": "04:00:00"}})
    assert poll.details["wait_policy"]["max_start_plus_run_hours"] == 24.0
    assert poll.details["wait_policy"]["verdict"] == "within_policy"


def test_v0810_daemon_auto_cycle_command_uses_online_real_submit_flags(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    captured: list[list[str]] = []
    started = {"value": False}

    def fake_run(args, **kwargs):
        captured.append(list(args))
        if args[:2] == ["tmux", "has-session"]:
            return subprocess.CompletedProcess(args, 0 if started["value"] else 1, stdout="", stderr="")
        if args[:3] == ["tmux", "new-session", "-d"]:
            started["value"] = True
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.daemon.shutil.which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr("vibe_research.daemon.subprocess.run", fake_run)
    result = invoke("daemon", "start", "--target", str(tmp_path), "--online", "--real-submit", "--mode", "auto-cycle", "--max-steps", "7")
    assert result.exit_code == 0
    command = captured[1][-1]
    assert "auto-cycle" in command
    assert "--real-submit" in command
    assert "--offline" not in command
    assert "--max-steps 7" in command
    assert "status --target" in command


def test_v0811_daemon_uses_current_python_interpreter(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    captured: list[list[str]] = []
    started = {"value": False}

    def fake_run(args, **kwargs):
        captured.append(list(args))
        if args[:2] == ["tmux", "has-session"]:
            return subprocess.CompletedProcess(args, 0 if started["value"] else 1, stdout="", stderr="")
        if args[:3] == ["tmux", "new-session", "-d"]:
            started["value"] = True
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.daemon.shutil.which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr("vibe_research.daemon.subprocess.run", fake_run)
    assert invoke("daemon", "start", "--target", str(tmp_path)).exit_code == 0
    command = captured[1][-1]
    assert shlex_quote(sys.executable) in command
    daemon = read_json(tmp_path / ".vibe" / "state" / "daemon.json", {})
    assert daemon["interpreter"] == sys.executable


def test_v0812_daemon_launches_command_through_explicit_shell(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    captured: list[list[str]] = []
    started = {"value": False}

    def fake_run(args, **kwargs):
        captured.append(list(args))
        if args[:2] == ["tmux", "has-session"]:
            return subprocess.CompletedProcess(args, 0 if started["value"] else 1, stdout="", stderr="")
        if args[:3] == ["tmux", "new-session", "-d"]:
            started["value"] = True
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.daemon.shutil.which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr("vibe_research.daemon.subprocess.run", fake_run)
    assert invoke("daemon", "start", "--target", str(tmp_path)).exit_code == 0
    launch_args = captured[1]
    assert "-c" in launch_args
    assert launch_args[launch_args.index("-c") + 1] == str(tmp_path.resolve())
    assert launch_args[-3] in {"/usr/bin/bash", "sh"}
    assert launch_args[-2] == "-lc"
    assert "auto-cycle" in launch_args[-1]
    assert "PYTHONPATH=" in launch_args[-1]
    assert "VIBE_DAEMON_TARGET=" in launch_args[-1]
    assert str(Path(__file__).resolve().parents[1]) in launch_args[-1]
    daemon = read_json(tmp_path / ".vibe" / "state" / "daemon.json", {})
    assert daemon["shell"] == launch_args[-3]
    assert daemon["framework_root"] == str(Path(__file__).resolve().parents[1])


def test_v0838_daemon_bash_loop_with_matching_sentinel_is_managed(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0

    def fake_run(args, **kwargs):
        if args[:2] == ["tmux", "has-session"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:3] == ["tmux", "display-message", "-p"] and args[-1] == "#{pane_current_path}":
            return subprocess.CompletedProcess(args, 0, stdout=f"{tmp_path}\n", stderr="")
        if args[:3] == ["tmux", "display-message", "-p"] and args[-1] == "#{pane_current_command}":
            return subprocess.CompletedProcess(args, 0, stdout="bash\n", stderr="")
        if args[:2] == ["tmux", "capture-pane"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"VIBE_DAEMON_TARGET={tmp_path}\nsleep 300\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.daemon.shutil.which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr("vibe_research.daemon.subprocess.run", fake_run)
    status = daemon_status(VibePaths(tmp_path))
    assert status["running"] is True
    assert status["managed_loop"] is True
    assert status["target_match"] is True


def test_v0813_daemon_rejects_existing_session_bound_to_other_target(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0

    def fake_run(args, **kwargs):
        if args[:2] == ["tmux", "has-session"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:3] == ["tmux", "display-message", "-p"] and args[-1] == "#{pane_current_path}":
            return subprocess.CompletedProcess(args, 0, stdout="/tmp/other-target\n", stderr="")
        if args[:3] == ["tmux", "display-message", "-p"] and args[-1] == "#{pane_current_command}":
            return subprocess.CompletedProcess(args, 0, stdout="bash\n", stderr="")
        if args[:2] == ["tmux", "capture-pane"]:
            return subprocess.CompletedProcess(args, 0, stdout="vibe auto-cycle --target /tmp/other-target\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.daemon.shutil.which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr("vibe_research.daemon.subprocess.run", fake_run)
    try:
        daemon_start(VibePaths(tmp_path))
    except RuntimeError as exc:
        assert "target_mismatch" in str(exc)
    else:
        raise AssertionError("expected target mismatch")


def test_v01015_daemon_rejects_mode_change_without_stop(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    write_json(
        tmp_path / ".vibe" / "state" / "daemon.json",
        {
            "target_root": str(tmp_path.resolve()),
            "mode": "auto-cycle",
            "interval": 300,
            "auto_next": True,
            "offline": False,
            "dry_submit": False,
            "max_steps": 30,
        },
    )

    def fake_run(args, **kwargs):
        if args[:2] == ["tmux", "has-session"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:3] == ["tmux", "display-message", "-p"] and args[-1] == "#{pane_current_path}":
            return subprocess.CompletedProcess(args, 0, stdout=f"{tmp_path}\n", stderr="")
        if args[:3] == ["tmux", "display-message", "-p"] and args[-1] == "#{pane_current_command}":
            return subprocess.CompletedProcess(args, 0, stdout="bash\n", stderr="")
        if args[:2] == ["tmux", "capture-pane"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"VIBE_DAEMON_TARGET={tmp_path}\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.daemon.shutil.which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr("vibe_research.daemon.subprocess.run", fake_run)
    result = invoke("daemon", "start", "--target", str(tmp_path), "--mode", "monitor", "--interval", "300", "--no-auto-next")
    assert result.exit_code != 0
    assert "daemon_option_mismatch" in result.output
    status = daemon_status(VibePaths(tmp_path))
    assert status["mode"] == "auto-cycle"
    assert status["auto_next"] is True


def test_v0813_slurm_poll_marks_mismatched_workdir_unsafe(tmp_path: Path, monkeypatch):
    def fake_run(args, **kwargs):
        if args[:3] == ["scontrol", "show", "job"]:
            return subprocess.CompletedProcess(args, 0, stdout="JobId=123 WorkDir=/tmp/other-target\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("vibe_research.backends.subprocess.run", fake_run)
    backend = SlurmBackend(VibePaths(tmp_path), {"execution": {"slurm": {}}})
    poll = backend.poll({"job_id": "123", "partition": "preferred", "resource_request": {"time": "04:00:00"}, "launch_workdir": str(tmp_path)})
    assert poll.finished is True
    assert poll.status == "unsafe_stale"
    assert poll.details["reason"] == "slurm_workdir_target_mismatch"


def test_v0814_adapter_profile_recovers_blocked_adapter_without_basename_match(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("Project policy: no upload. Trusted metric is score.\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "train.py").write_text("print('train')\n")
    (tmp_path / ".vibe_profile.yaml").write_text(
        "project_id: generic_profile_project\n"
        "project_name: Generic Profile Project\n"
        "evidence:\n"
        "  required_files:\n"
        "    - AGENTS.md\n"
        "    - scripts/train.py\n"
        "  required_text:\n"
        "    - path: AGENTS.md\n"
        "      contains:\n"
        "        - no upload\n"
        "answers:\n"
        "  q_primary_metric: score\n"
        "  q_data_path: local trusted data\n"
        "  q_baseline: baseline registry\n"
        "  q_gpu_permission: short local jobs only\n"
        "  q_metrics_format: JSON with score\n"
        "  q_trusted_outputs: .vibe/profile_metrics/*.json\n"
        "capabilities:\n"
        "  - id: profile_eval_smoke\n"
        "    status: active\n"
        "    task_type: evaluation_smoke\n"
        "    supported_decisions: [collect_more_metrics]\n"
        "    description: Profile-declared evaluation smoke capability.\n"
        "    dryrun:\n"
        "      command: sh -c 'mkdir -p .vibe/profile_metrics && printf \"{\\\"score\\\": 1.0}\\n\" > .vibe/profile_metrics/eval.json'\n"
        "    entrypoint:\n"
        "      type: local\n"
        "      command: sh -c 'mkdir -p .vibe/profile_metrics && printf \"{\\\"score\\\": 1.0}\\n\" > .vibe/profile_metrics/eval.json'\n"
        "    outputs:\n"
        "      expected_output_path: .vibe/profile_metrics/eval.json\n"
        "      metrics_file_path: .vibe/profile_metrics/eval.json\n"
        "    metrics_schema:\n"
        "      required: [score]\n"
        "      types: {score: number}\n"
        "      primary_metric: score\n"
        "      version: profile\n"
        "    artifact_rules:\n"
        "      expected_outputs: [.vibe/profile_metrics/eval.json]\n"
        "      trusted_path_patterns: [.vibe/profile_metrics/*.json]\n"
        "      version: profile\n"
        "    resources:\n"
        "      automatic_submission_allowed: false\n"
        "      user_confirmation_required: false\n"
        "      allowed_backends: [local]\n"
        "      default: {gpu: 0, cpus: 1, mem_gb: 1, time: '00:05:00'}\n"
        "    trust_checks: [schema_valid_metrics, expected_output_exists]\n"
    )
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    readiness = read_json(tmp_path / ".vibe" / "adapter_readiness.json", {})
    assert readiness["ready_for_real_experiments"] is True
    assert not readiness["missing_user_answers"]
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "vibe plan-cycle" in result.output


def test_v0815_synthesized_decision_uses_training_capability_decision(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    paths = VibePaths(tmp_path)
    command = "sh -c 'mkdir -p .vibe/train_metrics && printf \"{\\\"primary\\\": 1.0}\\n\" > .vibe/train_metrics/train.json'"
    cap = AdapterCapability(
        id="train_smoke_cap",
        version="test",
        status="active",
        task_type="train_smoke",
        supported_decisions=["launch_gpu_gate"],
        description="Generic training smoke capability.",
        dryrun={"command": command},
        entrypoint={"type": "local", "command": command},
        outputs={"expected_output_path": ".vibe/train_metrics/train.json", "metrics_file_path": ".vibe/train_metrics/train.json"},
        metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="test"),
        artifact_rules=ArtifactRules(expected_outputs=[".vibe/train_metrics/train.json"], trusted_path_patterns=[".vibe/train_metrics/*.json"], version="test"),
        resources=ResourcePolicy(
            automatic_submission_allowed=True,
            user_confirmation_required=False,
            allowed_backends=["slurm"],
            default={"gpu": 1, "cpus": 2, "mem_gb": 4, "time": "00:10:00", "preferred_partitions": ["gpu_short"]},
        ),
        trust_checks=["schema_valid_metrics", "expected_output_exists"],
        contract_tests=["train_smoke_cap"],
        activation={"contract_status": "passed", "contract_test_result_id": "test"},
    )
    write_adapter_manifest(paths, AdapterManifest(project_id=tmp_path.name, project_name=tmp_path.name, open_questions=[], capabilities=[cap]))
    write_json(tmp_path / ".vibe" / "contract_tests" / "train_smoke_cap.json", {"capability_id": "train_smoke_cap", "status": "passed", "created_at": "test"})
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    decision = read_json(tmp_path / ".vibe" / "cycles" / "c001" / "cycle_decision.json", {})
    assert decision["decision_type"] == "launch_gpu_gate"
    plan = read_yaml(tmp_path / ".vibe" / "cycles" / "c001" / "resource_plan.yaml", {})
    assert sorted(plan["runs"]) == ["train_smoke_cap"]
    assert plan["runs"]["train_smoke_cap"]["adapter_metadata"]["task_type"] == "train_smoke"


def test_v0815_default_candidates_use_capability_supported_decision(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    paths = VibePaths(tmp_path)
    cap = AdapterCapability(
        id="train_smoke_cap",
        version="test",
        status="active",
        task_type="train_smoke",
        supported_decisions=["launch_gpu_gate"],
        description="Generic training smoke capability.",
        dryrun={"command": "python -c 'print(1)'"},
        entrypoint={"type": "local", "command": "python -c 'print(1)'"},
        outputs={"expected_output_path": ".vibe/train_metrics/train.json", "metrics_file_path": ".vibe/train_metrics/train.json"},
        metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="test"),
        artifact_rules=ArtifactRules(expected_outputs=[".vibe/train_metrics/train.json"], trusted_path_patterns=[".vibe/train_metrics/*.json"], version="test"),
        resources=ResourcePolicy(automatic_submission_allowed=True, user_confirmation_required=False, allowed_backends=["slurm"], default={"gpu": 1, "cpus": 2, "mem_gb": 4, "time": "00:10:00"}),
        trust_checks=["schema_valid_metrics", "expected_output_exists"],
        contract_tests=["train_smoke_cap"],
        activation={"contract_status": "passed", "contract_test_result_id": "test"},
    )
    write_adapter_manifest(paths, AdapterManifest(project_id=tmp_path.name, project_name=tmp_path.name, open_questions=[], capabilities=[cap]))
    assert invoke("research", "init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--autonomy-level", "bounded_continuous", "--force").exit_code == 0
    assert invoke("hypothesis", "create", "train smoke candidate", "--stage", "smoke", "--target", str(tmp_path)).exit_code == 0
    candidates = default_candidates(paths)
    assert candidates
    assert candidates[0]["capability_id"] == "train_smoke_cap"
    assert candidates[0]["decision_type"] == "launch_gpu_gate"


def test_v0817_new_cycle_clears_stale_top_level_block(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    state_path = tmp_path / ".vibe" / "state" / "state.json"
    state = read_json(state_path, {})
    state["status"] = "blocked_missing_decision"
    state["blocked_reason"] = "offline fallback cannot make a structured research decision"
    state["next_action"] = "vibe decision show r001_stale"
    write_json(state_path, state)

    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    state = read_json(state_path, {})
    cycle_id = state["current_cycle_id"]
    assert state["blocked_reason"] == ""
    assert state["status"] == "cycle_planned"
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert f"vibe review-cycle {cycle_id}" in result.output
    assert "offline fallback cannot make a structured research decision" not in result.output


def test_v0818_submit_queue_uses_run_entrypoint_backend_when_not_overridden(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "1").exit_code == 0
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    run_id = sorted(state["runs"])[0]
    assert state["runs"][run_id]["entrypoint"]["type"] == "slurm"
    assert invoke("branch", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("dryrun", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("queue", run_id, "--target", str(tmp_path)).exit_code == 0
    assert invoke("submit-queue", "--target", str(tmp_path), "--dry").exit_code == 0
    launch = read_json(tmp_path / ".vibe" / "runs" / run_id / "launch.json", {})
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert launch["backend"] == "slurm"
    assert state["runs"][run_id]["backend"] == "slurm"
    assert "#SBATCH --qos=gpu_access" in Path(launch["sbatch_path"]).read_text()


def test_v0840_slurm_submit_blocks_missing_downstream_dependencies_until_override(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    paths = VibePaths(tmp_path)
    manifest = load_adapter_manifest(paths)
    manifest.capabilities[0].inputs = {"required_dirs": ["data/nnunet_raw"]}
    write_adapter_manifest(paths, manifest)
    run = {
        "run_id": "r001_dep",
        "cycle_id": "c001",
        "direction_id": "train-smoke",
        "branch": "",
        "hypothesis": "dependency gated run",
        "status": "queued",
        "entrypoint": {"type": "slurm", "command": "python3 -c 'print(1)'"},
        "dryrun": {"command": "python3 -c 'print(1)'"},
        "resources": {"gpu": 1, "cpus": 1, "mem_gb": 1, "time": "00:10:00"},
        "outputs": {"expected_output_path": ".vibe/train_metrics.json"},
        "evaluation": {"metrics_file_path": ".vibe/train_metrics.json", "metrics_schema": {"primary": "number"}},
        "adapter_metadata": {"capability_id": "train-smoke", "task_type": "train_smoke"},
    }
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["cycles"] = {"c001": {"status": "reviewed"}}
    state["runs"] = {"r001_dep": run}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    write_json(tmp_path / ".vibe" / "scheduler" / "queue.json", {"queued": [{"run_id": "r001_dep", "priority": 1, "status": "queued"}]})
    result = invoke("submit-queue", "--target", str(tmp_path), "--backend", "slurm", "--dry")
    assert result.exit_code == 0
    queue = read_json(tmp_path / ".vibe" / "scheduler" / "queue.json", {})
    assert queue["queued"][0]["status"] == "waiting_on_downstream_dependency"

    state["runs"]["r001_dep"]["adapter_metadata"]["dependency_override_confirmed"] = True
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    write_json(tmp_path / ".vibe" / "scheduler" / "queue.json", {"queued": [{"run_id": "r001_dep", "priority": 1, "status": "queued"}]})
    result = invoke("submit-queue", "--target", str(tmp_path), "--backend", "slurm", "--dry")
    assert result.exit_code == 0
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert active["active"][0]["run_id"] == "r001_dep"


def test_v0843_collect_ignores_stale_metrics_for_dry_submitted_launch(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    run_id = "r001_dry"
    metrics_path = tmp_path / ".vibe" / "real_metrics" / "stale.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text('{"primary": 0.99}\n')
    run = {
        "run_id": run_id,
        "cycle_id": "c001",
        "direction_id": "dry-test",
        "status": "finished",
        "run_kind": "real_experiment",
        "backend": "slurm",
        "entrypoint": {"type": "slurm", "command": "python train.py"},
        "dryrun": {"command": "python -c 'print(1)'"},
        "resources": {"gpu": 1, "cpus": 1, "mem_gb": 1, "time": "00:10:00"},
        "outputs": {"expected_output_path": ".vibe/real_metrics/stale.json"},
        "evaluation": {"metrics_file_path": ".vibe/real_metrics/stale.json", "metrics_schema": {"primary": "number"}},
        "adapter_metadata": {"capability_id": "train-smoke", "task_type": "train_smoke"},
    }
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {run_id: run}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(run_dir / "manifest.yaml", run)
    write_json(run_dir / "launch.json", {"run_id": run_id, "backend": "slurm", "status": "dry_submitted", "job_id": f"slurm-dry-{run_id}"})

    collect_run(VibePaths(tmp_path), run_id)
    metrics = read_json(run_dir / "metrics.json", {})
    assert metrics["missing_metrics"] is True
    assert metrics["schema_status"] == "missing"
    assert metrics["trust_status"] == "untrusted_missing_metrics"
    assert metrics["primary_metric"] == 0.0
    assert metrics["provenance"]["dry_launch_metrics_ignored"] is True
    assert metrics["provenance"]["ignored_metrics_file_path"] == ".vibe/real_metrics/stale.json"


def test_v0846_next_and_submit_queue_ignore_abandoned_stale_queue_item(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {"r001_abandoned": {"run_id": "r001_abandoned", "cycle_id": "c001", "status": "abandoned"}}
    state["next_action"] = "vibe submit-queue"
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    write_json(tmp_path / ".vibe" / "scheduler" / "queue.json", {"queued": [{"run_id": "r001_abandoned", "priority": 1, "status": "queued"}]})

    next_result = invoke("next", "--target", str(tmp_path))
    assert next_result.exit_code == 0
    assert "vibe submit-queue" not in next_result.output
    submit_result = invoke("submit-queue", "--target", str(tmp_path), "--dry")
    assert submit_result.exit_code == 0
    queue = read_json(tmp_path / ".vibe" / "scheduler" / "queue.json", {})
    assert queue["queued"] == []


def test_v0849_paused_direction_uses_latest_registry_status(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    append_jsonl(tmp_path / ".vibe" / "directions" / "registry.jsonl", {"direction_id": "d001", "status": "paused", "reason": "max failed runs reached"})
    assert paused_direction(VibePaths(tmp_path), "d001") is True
    append_jsonl(tmp_path / ".vibe" / "directions" / "registry.jsonl", {"direction_id": "d001", "status": "promoted", "reason": "manual resume"})
    assert paused_direction(VibePaths(tmp_path), "d001") is False


def test_v0849_submit_queue_auto_resumes_required_input_repair(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    required = tmp_path / "data" / "required.csv"
    required.parent.mkdir(parents=True, exist_ok=True)
    required.write_text("ok\n")
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["runs"] = {
        "r001_failed": {
            "run_id": "r001_failed",
            "cycle_id": "c001",
            "direction_id": "d001",
            "status": "blocked",
            "non_counting_classification": "missing_required_input:data/required.csv",
        },
        "r002_repair": {
            "run_id": "r002_repair",
            "cycle_id": "c002",
            "direction_id": "d001",
            "branch": "",
            "hypothesis": "replacement after required input repair",
            "status": "queued",
            "entrypoint": {"type": "local", "command": "python -c 'print(1)'"},
            "dryrun": {"command": "python -c 'print(1)'"},
            "resources": {"gpu": 0, "cpus": 1, "mem_gb": 1, "time": "00:01:00", "required_files": ["data/required.csv"]},
            "outputs": {},
            "evaluation": {},
        },
    }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    run_dir = tmp_path / ".vibe" / "runs" / "r002_repair"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "manifest.json", state["runs"]["r002_repair"])
    write_yaml(run_dir / "manifest.yaml", state["runs"]["r002_repair"])
    write_json(tmp_path / ".vibe" / "scheduler" / "queue.json", {"queued": [{"run_id": "r002_repair", "priority": 1, "status": "queued"}]})
    append_jsonl(tmp_path / ".vibe" / "directions" / "registry.jsonl", {"direction_id": "d001", "status": "paused", "reason": "max failed runs reached"})

    result = invoke("submit-queue", "--target", str(tmp_path), "--dry")
    assert result.exit_code == 0
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert active["active"][0]["run_id"] == "r002_repair"
    directions = read_jsonl(tmp_path / ".vibe" / "directions" / "registry.jsonl")
    assert directions[-1]["status"] == "promoted"
    assert directions[-1]["reason"] == "auto-resumed after required input repair"


def test_v0852_cycle_reflect_prompt_includes_external_resource_context(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    append_jsonl(
        tmp_path / ".vibe" / "research" / "sources.jsonl",
        {"title": "Useful Segmentation Paper", "source": "openalex", "source_url": "https://example.test/paper"},
    )
    write_json(tmp_path / ".vibe" / "research" / "auto_method_search.json", {"query": "segmentation method", "status": "searched"})
    repo = tmp_path / ".vibe" / "research" / "external_repos" / "upstream-method"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("# Upstream Method\n\nIntegration notes for the method.\n")
    (repo / "train.py").write_text("print('train')\n")
    append_jsonl(
        tmp_path / ".vibe" / "research" / "external_repos.jsonl",
        {"name": "upstream-method", "status": "cloned", "url": "https://example.test/upstream.git", "path": ".vibe/research/external_repos/upstream-method", "commit": "abc123"},
    )
    packet = prompt_packet(VibePaths(tmp_path), "cycle_reflect", "c001")
    assert "External Research Resources" in packet
    assert "Useful Segmentation Paper" in packet
    assert "segmentation method" in packet
    assert "upstream-method" in packet
    assert "Upstream Method" in packet
    assert "train.py" in packet


def test_v0854_external_analyze_repo_creates_artifacts_and_context(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    repo = tmp_path / ".vibe" / "research" / "external_repos" / "upstream-method"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("# Upstream Method\n\nIntegration notes.\n")
    (repo / "pyproject.toml").write_text("[project]\nname='upstream'\n")
    (repo / "train_model.py").write_text("print('train')\n")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    append_jsonl(
        tmp_path / ".vibe" / "research" / "external_repos.jsonl",
        {"name": "upstream-method", "status": "cloned", "url": "https://example.test/upstream.git", "path": ".vibe/research/external_repos/upstream-method", "commit": "abc123"},
    )

    result = invoke("external", "analyze-repo", "upstream-method", "--target", str(tmp_path))
    assert result.exit_code == 0
    analysis = read_json(tmp_path / ".vibe" / "research" / "external_repo_analyses" / "upstream-method.json", {})
    assert "pyproject.toml" in analysis["setup_files"]
    assert "pkg/__init__.py" in analysis["package_roots"]
    assert "train_model.py" in analysis["likely_entrypoints"]
    assert "external code was not imported" in " ".join(analysis["risk_notes"])
    packet = prompt_packet(VibePaths(tmp_path), "cycle_reflect", "c001")
    assert "External Repo Integration Analyses" in packet
    assert "train_model.py" in packet


def test_v0854_sustained_audit_flags_cloned_repo_without_analysis(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    append_jsonl(
        tmp_path / ".vibe" / "research" / "external_repos.jsonl",
        {"name": "upstream-method", "status": "cloned", "url": "https://example.test/upstream.git", "path": ".vibe/research/external_repos/upstream-method", "commit": "abc123"},
    )
    result = invoke("research", "sustained-audit", "--target", str(tmp_path))
    assert result.exit_code == 0
    audit = read_json(tmp_path / ".vibe" / "research" / "sustained_round_audit.json", {})
    assert "cloned_external_repo_without_integration_analysis" in audit["issues"]
    assert audit["framework_capabilities"]["cloned_repos_without_analysis"] == ["upstream-method"]


def test_v0821_active_jobs_only_monitor_when_prequeue_disabled(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    write_yaml(
        tmp_path / ".vibe" / "scheduler" / "budget.yaml",
        {"max_parallel_jobs": 3, "max_gpu_jobs": 2, "prequeue_when_capacity_full": False},
    )
    state_path = tmp_path / ".vibe" / "state" / "state.json"
    state = read_json(state_path, {})
    state["status"] = "initialized"
    state["blocked_reason"] = ""
    state["next_action"] = "vibe monitor"
    write_json(state_path, state)
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [{"run_id": "r001", "resource_request": {"gpu": 1}, "status": "pending"}]})
    one_job = invoke("next", "--target", str(tmp_path))
    assert one_job.exit_code == 0
    assert "vibe plan-cycle" in one_job.output

    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {
            "active": [
                {"run_id": "r001", "resource_request": {"gpu": 1}, "status": "pending"},
                {"run_id": "r002", "resource_request": {"gpu": 1}, "status": "pending"},
            ]
        },
    )
    full = invoke("next", "--target", str(tmp_path))
    assert full.exit_code == 0
    assert "vibe monitor" in full.output


def test_v0827_capacity_full_allows_bounded_prequeue_then_monitors_queue(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    write_yaml(
        tmp_path / ".vibe" / "scheduler" / "budget.yaml",
        {
            "max_parallel_jobs": 3,
            "max_gpu_jobs": 2,
            "prequeue_when_capacity_full": True,
            "max_prequeued_runs_when_full": 1,
        },
    )
    active_jobs = {
        "active": [
            {"run_id": "r001", "resource_request": {"gpu": 1}, "status": "running"},
            {"run_id": "r002", "resource_request": {"gpu": 1}, "status": "running"},
        ]
    }
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", active_jobs)
    first = invoke("next", "--target", str(tmp_path))
    assert first.exit_code == 0
    assert "vibe plan-cycle" in first.output

    result = invoke("auto-cycle", "--offline", "--dry-submit", "--max-steps", "12", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "queued r001_train_smoke" in result.output
    assert "monitored" in result.output
    assert "submitted r001_train_smoke" not in result.output
    queue = read_json(tmp_path / ".vibe" / "scheduler" / "queue.json", {})
    assert [item["run_id"] for item in queue["queued"]] == ["r001_train_smoke"]

    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", active_jobs)
    queued_full = invoke("next", "--target", str(tmp_path))
    assert queued_full.exit_code == 0
    assert "vibe monitor" in queued_full.output

    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [active_jobs["active"][0]]})
    capacity_free = invoke("next", "--target", str(tmp_path))
    assert capacity_free.exit_code == 0
    assert "vibe submit-queue" in capacity_free.output


def test_v0822_synthesized_decision_prefers_less_used_capability(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    paths = VibePaths(tmp_path)
    caps = []
    command = "python3 -c 'import json, pathlib; pathlib.Path(\".vibe/train_metrics.json\").write_text(json.dumps({\"primary\": 1.0}))'"
    for cap_id in ["cap_a", "cap_b"]:
        caps.append(
            AdapterCapability(
                id=cap_id,
                version="test",
                status="active",
                task_type="train_smoke",
                supported_decisions=["launch_gpu_gate"],
                description=f"Training capability {cap_id}",
                dryrun={"command": "python3 -c 'print(\"dry\")'"},
                entrypoint={"type": "slurm", "command": command},
                outputs={"expected_output_path": ".vibe/train_metrics.json", "metrics_file_path": ".vibe/train_metrics.json"},
                metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="test"),
                artifact_rules=ArtifactRules(expected_outputs=[".vibe/train_metrics.json"], trusted_path_patterns=[".vibe/*.json"], version="test"),
                resources=ResourcePolicy(automatic_submission_allowed=True, user_confirmation_required=False, allowed_backends=["slurm"], default={"gpu": 1, "cpus": 1, "mem_gb": 1, "time": "00:10:00"}),
                trust_checks=["schema_valid_metrics", "expected_output_exists"],
                contract_tests=[cap_id],
                activation={"contract_status": "passed", "contract_test_result_id": "test"},
            )
        )
        write_json(tmp_path / ".vibe" / "contract_tests" / f"{cap_id}.json", {"capability_id": cap_id, "status": "passed", "created_at": "test"})
    write_adapter_manifest(paths, AdapterManifest(project_id=tmp_path.name, project_name=tmp_path.name, open_questions=[], capabilities=caps))
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    state_path = tmp_path / ".vibe" / "state" / "state.json"
    state = read_json(state_path, {})
    state.setdefault("runs", {})["r001_existing"] = {"adapter_metadata": {"capability_id": "cap_a"}, "status": "submitted"}
    write_json(state_path, state)
    ok, message = ensure_executable_resource_plan(paths, "c001")
    assert ok, message
    decision = read_json(tmp_path / ".vibe" / "cycles" / "c001" / "cycle_decision.json", {})
    assert decision["selected_direction"] == "cap_b"


def test_v0839_synthesized_cycle_decision_compiles_multiroute_capabilities(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    paths = VibePaths(tmp_path)
    manifest = load_adapter_manifest(paths)
    base = manifest.capabilities[0]
    for cap_id in ["train-smoke-b", "train-smoke-c"]:
        cap = base.model_copy(deep=True)
        cap.id = cap_id
        cap.outputs = {"expected_output_path": f".vibe/{cap_id}.json", "metrics_file_path": f".vibe/{cap_id}.json"}
        cap.artifact_rules.expected_outputs = [f".vibe/{cap_id}.json"]
        cap.activation = {**cap.activation, "contract_test_result_id": cap_id}
        manifest.capabilities.append(cap)
        write_json(tmp_path / ".vibe" / "contract_tests" / f"{cap_id}.json", {"capability_id": cap_id, "status": "passed", "created_at": "test"})
    write_adapter_manifest(paths, manifest)
    (tmp_path / ".vibe" / "cycles" / "c001").mkdir(parents=True, exist_ok=True)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["current_cycle_id"] = "c001"
    state["cycles"] = {"c001": {"status": "reviewed"}}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    ok, message = ensure_executable_resource_plan(paths, "c001")
    assert ok, message
    plan = read_yaml(tmp_path / ".vibe" / "cycles" / "c001" / "resource_plan.yaml", {})
    assert set(plan["runs"]) == {"train-smoke", "train-smoke-b", "train-smoke-c"}
    decision = read_json(tmp_path / ".vibe" / "cycles" / "c001" / "cycle_decision.json", {})
    assert decision["resource_intent"]["source"] == "auto_compile_multi_route"


def test_v0845_synthesized_cycle_decision_blocks_exact_noncounting_multiroute_repeat(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy").exit_code == 0
    enable_train_smoke_adapter(tmp_path)
    paths = VibePaths(tmp_path)
    manifest = load_adapter_manifest(paths)
    base = manifest.capabilities[0]
    for cap_id in ["train-smoke-b", "train-smoke-c"]:
        cap = base.model_copy(deep=True)
        cap.id = cap_id
        cap.outputs = {"expected_output_path": f".vibe/{cap_id}.json", "metrics_file_path": f".vibe/{cap_id}.json"}
        cap.artifact_rules.expected_outputs = [f".vibe/{cap_id}.json"]
        cap.activation = {**cap.activation, "contract_test_result_id": cap_id}
        manifest.capabilities.append(cap)
        write_json(tmp_path / ".vibe" / "contract_tests" / f"{cap_id}.json", {"capability_id": cap_id, "status": "passed", "created_at": "test"})
    write_adapter_manifest(paths, manifest)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["cycles"] = {"c001": {"status": "reviewed"}}
    state["runs"] = {
        f"r00{idx}_{cap_id}": {
            "run_id": f"r00{idx}_{cap_id}",
            "cycle_id": "c001",
            "status": "blocked",
            "non_counting_classification": "non_counting_execution_failure:failed",
            "adapter_metadata": {"capability_id": cap_id, "task_type": "train_smoke"},
        }
        for idx, cap_id in enumerate(["train-smoke", "train-smoke-b", "train-smoke-c"], start=1)
    }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)

    decision = synthesize_cycle_decision(paths, "c002")
    assert decision.decision_type == "blocked_missing_capability"
    assert decision.provenance["source"] == "deterministic_auto_compile_multi_route_repeat_guard"


def test_v0839_next_monitors_fragmented_active_sustained_round(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy", "--no-root-portal").exit_code == 0
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {
            "active": [
                {"run_id": "r001", "cycle_id": "c001", "resource_request": {"gpu": 1}, "status": "pending"},
                {"run_id": "r002", "cycle_id": "c002", "resource_request": {"gpu": 1}, "status": "pending"},
                {"run_id": "r003", "cycle_id": "c003", "resource_request": {"gpu": 1}, "status": "pending"},
            ]
        },
    )
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "vibe monitor" in result.output


def test_v0850_next_abandons_empty_preplanned_cycle_while_active_round_runs(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "Improve validation", "--background", "Toy", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["current_cycle_id"] = "c002"
    state["cycles"] = {"c001": {"status": "reviewed"}, "c002": {"status": "planned"}}
    state["runs"] = {"r001_active": {"run_id": "r001_active", "cycle_id": "c001", "status": "submitted", "resource_request": {"gpu": 1}}}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    write_json(
        tmp_path / ".vibe" / "scheduler" / "active_jobs.json",
        {"active": [{"run_id": "r001_active", "cycle_id": "c001", "resource_request": {"gpu": 1}, "status": "running"}]},
    )
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "vibe monitor" in result.output
    updated = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    assert updated["current_cycle_id"] == "c001"
    assert updated["cycles"]["c002"]["status"] == "abandoned"
    assert updated["cycles"]["c002"]["provenance"]["source"] == "next_action_empty_preplanned_cycle_guard"


def test_v0855_next_collects_finished_sibling_before_monitoring_active_jobs(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    write_yaml(tmp_path / ".vibe" / "scheduler" / "budget.yaml", {"max_parallel_jobs": 1, "max_gpu_jobs": 1})
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["current_cycle_id"] = "c001"
    state["cycles"] = {"c001": {"status": "reviewed"}}
    state["runs"] = {
        "r001_done": {"run_id": "r001_done", "cycle_id": "c001", "status": "finished"},
        "r002_active": {"run_id": "r002_active", "cycle_id": "c001", "status": "submitted"},
    }
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [{"run_id": "r002_active", "cycle_id": "c001", "resource_request": {"gpu": 1}, "status": "running"}]})
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "vibe collect r001_done" in result.output
    active = read_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {})
    assert active["active"][0]["run_id"] == "r002_active"


def test_v0855_next_monitors_active_jobs_when_no_sibling_output_ready(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    write_yaml(tmp_path / ".vibe" / "scheduler" / "budget.yaml", {"max_parallel_jobs": 1, "max_gpu_jobs": 1})
    state = read_json(tmp_path / ".vibe" / "state" / "state.json", {})
    state["current_cycle_id"] = "c001"
    state["cycles"] = {"c001": {"status": "reviewed"}}
    state["runs"] = {"r001_active": {"run_id": "r001_active", "cycle_id": "c001", "status": "submitted"}}
    write_json(tmp_path / ".vibe" / "state" / "state.json", state)
    write_json(tmp_path / ".vibe" / "scheduler" / "active_jobs.json", {"active": [{"run_id": "r001_active", "cycle_id": "c001", "resource_request": {"gpu": 1}, "status": "running"}]})
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "vibe monitor" in result.output


def test_v0823_auto_cycle_stops_after_single_monitor(monkeypatch, tmp_path: Path):
    calls = {"count": 0}

    def fake_auto_next(paths, *, offline=False, dry_submit=True):
        calls["count"] += 1
        return "monitored"

    monkeypatch.setattr("vibe_research.automation.auto_next", fake_auto_next)
    assert auto_cycle(VibePaths(tmp_path), max_steps=10) == ["monitored"]
    assert calls["count"] == 1


def test_v0842_research_sustained_next_dry_submit_fails_closed(monkeypatch, tmp_path: Path):
    calls = []

    def fake_auto_next(paths, *, offline=False, dry_submit=True):
        calls.append(dry_submit)
        return f"dry_submit={dry_submit}"

    monkeypatch.setattr("vibe_research.cli.run_auto_next", fake_auto_next)
    dry = invoke("research", "sustained-next", "--dry-submit", "--target", str(tmp_path))
    assert dry.exit_code == 0
    assert calls[-1] is True
    real = invoke("research", "sustained-next", "--real-submit", "--target", str(tmp_path))
    assert real.exit_code == 0
    assert calls[-1] is False


def test_v0842_research_sustained_cycle_real_submit_is_explicit(monkeypatch, tmp_path: Path):
    calls = []

    def fake_auto_cycle(paths, *, offline=False, dry_submit=True, max_steps=30):
        calls.append({"dry_submit": dry_submit, "max_steps": max_steps})
        return [f"dry_submit={dry_submit}"]

    monkeypatch.setattr("vibe_research.cli.run_auto_cycle", fake_auto_cycle)
    dry = invoke("research", "sustained-cycle", "--dry-submit", "--max-steps", "2", "--target", str(tmp_path))
    assert dry.exit_code == 0
    assert calls[-1] == {"dry_submit": True, "max_steps": 2}
    real = invoke("research", "sustained-cycle", "--real-submit", "--max-steps", "2", "--target", str(tmp_path))
    assert real.exit_code == 0
    assert calls[-1] == {"dry_submit": False, "max_steps": 2}


def test_v0825_online_monitor_triggers_method_search_once(monkeypatch, tmp_path: Path):
    calls = {"monitor": 0, "search": 0}

    def fake_next_action(paths):
        return "vibe monitor", ""

    def fake_monitor(paths):
        calls["monitor"] += 1

    def fake_search(paths, offline=False):
        calls["search"] += 1
        return {"status": "searched"}

    monkeypatch.setattr("vibe_research.automation.compute_next_action", fake_next_action)
    monkeypatch.setattr("vibe_research.automation.monitor", fake_monitor)
    monkeypatch.setattr("vibe_research.automation.auto_method_search", fake_search)
    assert auto_next(VibePaths(tmp_path), offline=False) == "monitored"
    assert calls == {"monitor": 1, "search": 1}
    assert auto_next(VibePaths(tmp_path), offline=True) == "monitored"
    assert calls == {"monitor": 2, "search": 1}


def test_v0825_auto_method_search_writes_provenance_and_ideas(monkeypatch, tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "improve segmentation", "--background", "medical imaging", "--no-root-portal").exit_code == 0

    def fake_paper_search(paths, query, *, source="arxiv", limit=10, offline=False, add_candidates=False):
        return [{"title": "New Segmentation Method", "source_url": "https://example.test/paper", "source": source, "year": "2026"}]

    monkeypatch.setattr("vibe_research.papers.paper_search", fake_paper_search)
    result = auto_method_search(VibePaths(tmp_path))
    assert result["status"] == "searched"
    assert result["idea_ids"]
    marker = read_json(tmp_path / ".vibe" / "research" / "auto_method_search.json", {})
    assert marker["query"]
    sources = read_jsonl(tmp_path / ".vibe" / "research" / "sources.jsonl")
    assert any(row.get("source") == "auto_method_search" for row in sources)
    ideas = read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")
    assert any("New Segmentation Method" in row["raw_text"] and row["source"] == "auto_method_search" for row in ideas)
    skipped = auto_method_search(VibePaths(tmp_path))
    assert skipped["status"] == "already_done"


def test_v0826_lit_refresh_idea_makes_online_idea_actionable(monkeypatch, tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "CARE myocardium", "--background", "cardiac MRI", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    idea = auto_method_search(VibePaths(tmp_path), offline=True, force=True)
    assert idea["status"] == "skipped_offline"
    from vibe_research.ideas import create_idea

    created = create_idea(
        VibePaths(tmp_path),
        "Evaluate online method candidate for a future experiment: New Segmentation Method (https://example.test/paper)",
        source="auto_method_search",
        status="needs_literature_refresh",
    )
    next_result = invoke("next", "--target", str(tmp_path))
    assert next_result.exit_code == 0
    assert f"vibe lit-refresh-idea {created['idea_id']}" in next_result.output

    def fake_paper_search(paths, query, *, source="openalex", limit=5, offline=False, add_candidates=False):
        assert "New Segmentation Method" in query
        return [{"title": "New Segmentation Method", "source_url": "https://example.test/paper", "source": source}]

    monkeypatch.setattr("vibe_research.research.paper_search", fake_paper_search)
    refresh = invoke("lit-refresh-idea", created["idea_id"], "--target", str(tmp_path))
    assert refresh.exit_code == 0
    ideas = read_jsonl(tmp_path / ".vibe" / "ideas" / "registry.jsonl")
    refreshed = next(row for row in ideas if row["idea_id"] == created["idea_id"])
    assert refreshed["status"] == "actionable_next_run"
    assert refreshed["linked_evidence"]

    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    plan = (tmp_path / ".vibe" / "cycles" / "c001" / "portfolio_plan.md").read_text()
    assert "## Idea pool candidates considered" in plan
    assert "New Segmentation Method" in plan


def test_v088_multi_capability_compile_emits_multiple_runs(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    (tmp_path / ".vibe" / "config.local.yaml").write_text("adapter:\n  kind: config\n")
    script_dir = tmp_path / ".vibe" / "scripts"
    script_dir.mkdir(exist_ok=True)
    for cap_id in ["cap_a", "cap_b"]:
        (script_dir / f"{cap_id}.py").write_text(
            "import argparse, json, pathlib\n"
            "p=argparse.ArgumentParser(); p.add_argument('--out'); p.add_argument('--dryrun', action='store_true'); p.add_argument('--smoke', action='store_true'); a=p.parse_args()\n"
            "out=pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps({'primary': 1.0})+'\\n')\n"
        )
    caps = []
    for cap_id in ["cap_a", "cap_b"]:
        out = f".vibe/bootstrap_metrics/{cap_id}.json"
        command = f"python .vibe/scripts/{cap_id}.py --out {out}"
        caps.append(
            AdapterCapability(
                id=cap_id,
                status="active",
                task_type="metrics_export",
                supported_decisions=["collect_more_metrics"],
                description=f"Generic candidate {cap_id}",
                dryrun={"command": command + " --dryrun"},
                entrypoint={"type": "local", "command": command + " --smoke"},
                outputs={"expected_output_path": out, "metrics_file_path": out, "baseline_comparison_target": "baseline_proxy"},
                metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="test"),
                artifact_rules=ArtifactRules(expected_outputs=[out], trusted_path_patterns=[".vibe/bootstrap_metrics/*.json"], baseline_target_provenance="baseline_proxy", version="test"),
                resources=ResourcePolicy(automatic_submission_allowed=False, user_confirmation_required=False, allowed_backends=["local"], default={"gpu": 0, "cpus": 1, "mem_gb": 1, "time": "00:05:00"}),
                trust_checks=["schema_valid_metrics", "expected_output_exists"],
                contract_tests=[cap_id],
                activation={"contract_status": "passed", "contract_test_result_id": "test", "command_template_hash": "test", "metrics_schema_hash": "test", "artifact_rule_hash": "test"},
            )
        )
        write_json(tmp_path / ".vibe" / "contract_tests" / f"{cap_id}.json", {"capability_id": cap_id, "status": "passed", "created_at": "test"})
    write_adapter_manifest(VibePaths(tmp_path), AdapterManifest(project_id=tmp_path.name, project_name=tmp_path.name, open_questions=[], capabilities=caps))

    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("review-cycle", "c001", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("decision", "write", "c001", "--type", "collect_more_metrics", "--action", "compare active candidates", "--target", str(tmp_path)).exit_code == 0
    assert invoke("compile-decision", "c001", "--target", str(tmp_path)).exit_code == 0
    plan = read_yaml(tmp_path / ".vibe" / "cycles" / "c001" / "resource_plan.yaml", {})
    assert sorted(plan["runs"]) == ["cap_a", "cap_b"]
    assert invoke("generate-runs", "c001", "--target", str(tmp_path), "--count", "2").exit_code == 0
    assert len(read_json(tmp_path / ".vibe" / "state" / "state.json", {})["runs"]) == 2


def test_blocking_deep_research_blocks_next(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    assert invoke("deep-request-cycle", "c001", "route selection", "--blocking", "--offline", "--target", str(tmp_path)).exit_code == 0
    result = invoke("next", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "blocked_waiting_deep_research" in result.output


def test_auto_cycle_reaches_first_submission(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    result = invoke("auto-cycle", "--offline", "--dry-submit", "--max-steps", "12", "--target", str(tmp_path))
    assert result.exit_code == 0
    assert "planned c001" in result.output
    assert "reviewed c001" in result.output
    assert "generated r001_toy_audit" in result.output
    assert "submitted r001_toy_audit" in result.output


def test_auto_cycle_stops_after_monitor_step(tmp_path: Path, monkeypatch):
    from vibe_research import automation

    calls = {"count": 0}

    def fake_auto_next(paths, *, offline=False, dry_submit=True):
        calls["count"] += 1
        return "monitored"

    monkeypatch.setattr(automation, "auto_next", fake_auto_next)
    assert automation.auto_cycle(VibePaths(tmp_path), max_steps=30) == ["monitored"]
    assert calls["count"] == 1


def test_auto_next_monitor_repairs_empty_cycle_plan(tmp_path: Path, monkeypatch):
    from vibe_research import automation

    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    create_idea(VibePaths(tmp_path), "online method candidate", status="actionable_next_run")
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    plan_path = tmp_path / ".vibe" / "cycles" / "c001" / "portfolio_plan.md"
    plan_path.write_text("")

    monkeypatch.setattr(automation, "compute_next_action", lambda paths: ("vibe monitor", ""))
    monkeypatch.setattr(automation, "monitor", lambda paths: None)

    result = auto_next(VibePaths(tmp_path), offline=True)
    assert result == "monitored repaired=c001"
    repaired = plan_path.read_text()
    assert "## Idea pool candidates considered" in repaired
    assert "online method candidate" in repaired


def test_codex_runner_uses_fake_codex_and_writes_artifact(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    enable_toy_adapter(tmp_path)
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "args=sys.argv\n"
        "out=pathlib.Path(args[args.index('--output-last-message')+1])\n"
        "out.write_text('# Portfolio Plan for c001\\n\\n## Stage\\nexploration\\n\\n## Current leaderboard summary\\nnone\\n\\n## User ideas and directives considered\\nnone\\n\\n## Candidate directions\\n- baseline\\n\\n## Selected runs\\n- r001\\n\\n## Dependency graph\\nnone\\n\\n## Resource budget\\ndefault\\n\\n## Portfolio success criteria\\nlearn\\n\\n## Stop or shrink criteria\\nstop failures\\n\\n## Idea pool update\\n- no changes\\n')\n"
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH','')}")
    result = run_codex(VibePaths(tmp_path), "portfolio_planner", "c001")
    assert result.ok
    assert "Portfolio Plan" in (tmp_path / ".vibe" / "cycles" / "c001" / "portfolio_plan.md").read_text()
    assert not validate_artifact(VibePaths(tmp_path), "portfolio_planner", "c001")


def test_codex_runner_preserves_existing_plan_on_empty_response(tmp_path: Path, monkeypatch):
    assert invoke("init", "--target", str(tmp_path), "--goal", "g", "--background", "b", "--no-root-portal").exit_code == 0
    enable_toy_adapter(tmp_path)
    create_idea(VibePaths(tmp_path), "online method candidate", status="actionable_next_run")
    assert invoke("plan-cycle", "--offline", "--target", str(tmp_path)).exit_code == 0
    plan_path = tmp_path / ".vibe" / "cycles" / "c001" / "portfolio_plan.md"
    original = plan_path.read_text()
    assert "## Idea pool candidates considered" in original
    assert "online method candidate" in original

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_codex = fake_bin / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "args=sys.argv\n"
        "out=pathlib.Path(args[args.index('--output-last-message')+1])\n"
        "out.write_text('')\n"
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH','')}")

    result = run_codex(VibePaths(tmp_path), "portfolio_planner", "c001")
    assert result.ok
    assert plan_path.read_text() == original
    assert result.last_message == original


def test_todo_cli_commands_exist():
    result = invoke("--help")
    help_text = result.output
    for command in [
        "init",
        "audit",
        "config",
        "ideas",
        "portal",
        "dashboard",
        "status",
        "idea",
        "adapter",
        "script",
        "directive",
        "vendor-runtime",
        "decision",
        "validate-decision",
        "compile-decision",
        "validate-resource-plan",
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
        "deep-request-from-idea",
        "ingest-deep-research",
        "wiki-ingest",
        "export-meeting",
        "dogfood",
        "leaderboard",
        "timeline",
        "merge",
        "abandon",
        "next",
    ]:
        assert command in help_text
