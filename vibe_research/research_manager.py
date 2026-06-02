"""Bounded autonomous research manager state, policies, and exports."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .adapter_onboarding import adapter_readiness
from .adapter_schema import load_adapter_manifest
from .config import load_config
from .io import append_jsonl, ensure_dir, next_numeric_id, read_json, read_jsonl, read_yaml, utc_now, write_json, write_text, write_yaml
from .paths import VibePaths
from .promotion import select_executable_decision_for_capability
from .real_experiments import summarize_real_experiment_progress
from .scheduler_approvals import fallback_requeue_command
from .timeline import record_event


HYPOTHESIS_STATUSES = {"proposed", "active", "needs_analysis", "downscoped", "promoted", "stopped", "archived", "blocked"}
DECISION_OUTCOMES = {"continue", "promote", "revise", "downscope", "stop", "ask_user", "request_deep_research", "blocked"}
FAILURE_KINDS = {"scientific", "engineering", "schema", "resource", "policy", "insufficient_evidence", "none"}
AUTONOMY_LEVELS = {"diagnosis_only", "analysis_only", "smoke_only", "gated_experiments", "bounded_continuous", "manual_approval_required"}


class HypothesisRecord(BaseModel):
    hypothesis_id: str
    title: str
    short_name: str = ""
    status: str = "active"
    origin: str = "operator"
    rationale: str = ""
    expected_mechanism: str = ""
    target_metrics: list[str] = Field(default_factory=list)
    protected_metrics: dict[str, Any] = Field(default_factory=dict)
    known_risks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    stage: str = "idea"
    current_stage: str = "idea"
    best_evidence: list[str] = Field(default_factory=list)
    negative_evidence: list[str] = Field(default_factory=list)
    remaining_upside: dict[str, Any] = Field(default_factory=dict)
    failure_analysis: dict[str, Any] = Field(default_factory=dict)
    next_testable_change: str = ""
    linked_experiments: list[str] = Field(default_factory=list)
    decision_history: list[str] = Field(default_factory=list)
    stop_reason: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def validate_status(self) -> "HypothesisRecord":
        if self.status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"unsupported hypothesis status: {self.status}")
        return self


class ExperimentRecord(BaseModel):
    experiment_id: str
    hypothesis_id: str
    design_summary: str
    stage: str = "smoke"
    decision_id: str = ""
    capability_id: str = ""
    adapter_revision: str = ""
    execution_script: str = ""
    script_revision: str = ""
    resource_plan_id: str = ""
    resource_plan: dict[str, Any] = Field(default_factory=dict)
    expected_evidence: dict[str, Any] = Field(default_factory=dict)
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    failure_criteria: dict[str, Any] = Field(default_factory=dict)
    baseline_target: str = ""
    protected_metric_constraints: dict[str, Any] = Field(default_factory=dict)
    linked_run_ids: list[str] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    trusted_evidence_ids: list[str] = Field(default_factory=list)
    untrusted_evidence_ids: list[str] = Field(default_factory=list)
    status: str = "planned"
    analysis_summary: str = ""
    failure_analysis: dict[str, Any] = Field(default_factory=dict)
    cost_actual: dict[str, Any] = Field(default_factory=dict)
    cost_estimated: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class EvidenceRecord(BaseModel):
    evidence_id: str
    experiment_id: str
    run_id: str = ""
    kind: str = "metrics"
    trusted: bool = False
    schema_valid: bool = False
    metrics_schema_version: str = ""
    metrics_file: str = ""
    artifact_refs: list[str] = Field(default_factory=list)
    summary: str = ""
    baseline_comparison: dict[str, Any] = Field(default_factory=dict)
    metric_deltas: dict[str, Any] = Field(default_factory=dict)
    protected_metric_regressions: list[dict[str, Any]] = Field(default_factory=list)
    uncertainty_notes: str = ""
    analysis_notes: str = ""
    failure_kind: str = "none"
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str

    @model_validator(mode="after")
    def validate_failure_kind(self) -> "EvidenceRecord":
        if self.failure_kind not in FAILURE_KINDS:
            raise ValueError(f"unsupported failure kind: {self.failure_kind}")
        return self


class ResearchDecisionRecord(BaseModel):
    decision_id: str
    hypothesis_id: str = ""
    experiment_id: str = ""
    decision_type: str
    agent_judgment: dict[str, Any] = Field(default_factory=dict)
    policy_eval_id: str = ""
    budget_reservation_id: str = ""
    promotion_or_stop_reason: str = ""
    final_outcome: str = "continue"
    rationale: str = ""
    alternatives_considered: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    budget_impact: dict[str, Any] = Field(default_factory=dict)
    expected_next_step: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str

    @model_validator(mode="after")
    def validate_outcome(self) -> "ResearchDecisionRecord":
        if self.final_outcome not in DECISION_OUTCOMES:
            raise ValueError(f"unsupported final outcome: {self.final_outcome}")
        return self


def research_paths(paths: VibePaths) -> dict[str, Path]:
    return {
        "events": paths.research / "events.jsonl",
        "hypotheses": paths.research / "hypotheses.json",
        "experiments": paths.research / "experiments.json",
        "evidence": paths.research / "evidence.json",
        "decisions": paths.research / "decisions.jsonl",
        "budget": paths.research / "budget_ledger.jsonl",
        "questions": paths.research / "questions.jsonl",
        "portfolio": paths.research / "portfolio_plan.json",
        "memory_json": paths.research / "memory_pack.json",
        "memory_md": paths.research / "memory_pack.md",
    }


def ensure_research_dirs(paths: VibePaths) -> None:
    for rel in ["research", "policies", "memos", "dashboard"]:
        ensure_dir(paths.vibe / rel)


def research_init(
    paths: VibePaths,
    *,
    goal: str = "",
    background: str = "",
    memo_language: str = "zh-CN",
    timezone: str = "local",
    autonomy_level: str = "analysis_only",
    force: bool = False,
) -> dict[str, Any]:
    paths.require_initialized()
    ensure_research_dirs(paths)
    now = utc_now()
    files = research_paths(paths)
    for key in ["events", "decisions", "budget", "questions"]:
        if force or not files[key].exists():
            write_text(files[key], "")
    for key in ["hypotheses", "experiments", "evidence"]:
        if force or not files[key].exists():
            write_json(files[key], {})
    project_brief = read_project_brief(paths)
    goal = goal or project_brief.get("goal", "")
    background = background or project_brief.get("background", "")
    sync_config_project_context(paths, goal=goal, background=background)
    constraints = scan_repo_constraints(paths)
    write_text(
        paths.research / "research_brief.md",
        f"# Research Brief\n\n## Goal\n{goal or 'MISSING'}\n\n## Background\n{background or 'MISSING'}\n\n## Repository Constraints\n{render_constraints(constraints)}\n",
    )
    policies = write_default_policies(paths, memo_language=memo_language, timezone=timezone, autonomy_level=autonomy_level, force=force)
    blockers = []
    if missing_goal_text(goal):
        blockers.append("q_init_project_goal")
    if missing_background_text(background):
        blockers.append("q_init_project_background")
    existing_questions = read_jsonl(files["questions"])
    if existing_questions:
        write_text(files["questions"], "")
        for row in existing_questions:
            if row.get("question_id") in blockers:
                row["status"] = "open"
                row["updated_at"] = now
            elif row.get("question_id") in {"missing_project_goal", "missing_project_background", "q_init_project_goal", "q_init_project_background"}:
                row["status"] = "resolved"
                row["resolved_at"] = now
            append_jsonl(files["questions"], row)
    ensure_initial_policy_questions(paths, policies)
    append_research_event(paths, "research_initialized", {"goal": goal, "background_present": bool(background), "blockers": blockers, "constraints": constraints})
    status = research_readiness(paths)
    status["policies"] = policies
    return status


def sync_config_project_context(paths: VibePaths, *, goal: str, background: str) -> None:
    if missing_goal_text(goal) and missing_background_text(background):
        return
    for path, writer in [(paths.vibe / "config.yaml", write_yaml), (paths.vibe / "config.json", write_json)]:
        data = read_yaml(path, {}) if path.suffix in {".yaml", ".yml"} else read_json(path, {})
        if not isinstance(data, dict):
            continue
        project = data.setdefault("project", {})
        changed = False
        if goal and not missing_goal_text(goal) and project.get("goal") != goal:
            project["goal"] = goal
            changed = True
        if background and not missing_background_text(background) and project.get("background") != background:
            project["background"] = background
            changed = True
        if changed:
            project["brief_path"] = ".vibe/project/brief.md"
            project["brief_missing"] = missing_goal_text(project.get("goal", "")) or missing_background_text(project.get("background", ""))
            writer(path, data)


def missing_goal_text(value: str) -> bool:
    text = str(value or "").strip()
    return not text or "Define the research objective" in text or text.startswith("MISSING")


def missing_background_text(value: str) -> bool:
    text = str(value or "").strip()
    return not text or "not been supplied" in text or text.startswith("MISSING")


def ensure_initial_policy_questions(paths: VibePaths, policies: dict[str, Any] | None = None) -> None:
    files = research_paths(paths)
    existing = read_jsonl(files["questions"])
    by_id = {row.get("question_id"): row for row in existing if row.get("question_id")}
    now = utc_now()
    for question in default_initial_policy_questions(paths, policies or {}):
        old = by_id.get(question["question_id"], {})
        if old.get("status") in {"answered", "resolved"}:
            continue
        if old.get("status") == "open":
            continue
        append_jsonl(files["questions"], {**question, "status": "open", "created_at": now, "updated_at": now})


def default_initial_policy_questions(paths: VibePaths, policies: dict[str, Any]) -> list[dict[str, Any]]:
    budget = policies.get("budget") or read_yaml(paths.vibe / "policies" / "budget.yaml", {})
    stage = policies.get("stage_gates") or read_yaml(paths.vibe / "policies" / "stage_gates.yaml", {})
    autonomy = policies.get("autonomy") or read_yaml(paths.vibe / "policies" / "autonomy.yaml", {})
    resource_questions = read_yaml(paths.vibe / "resources" / "policy_questions.yaml", {}) or {}
    resource_by_id = {row.get("id"): row for row in resource_questions.get("questions", []) if isinstance(row, dict)}
    project_brief = read_project_brief(paths)
    return [
        {
            "question_id": "q_init_project_goal",
            "question": "What is the required project research goal?",
            "why_needed": "the research objective is mandatory context for planning and stopping criteria",
            "blocks": ["project_brief", "portfolio_planning", "bounded_autonomy"],
            "current_goal": project_brief.get("goal", ""),
            "requires_user_answer": True,
        },
        {
            "question_id": "q_init_project_background",
            "question": "What project background, constraints, datasets, evaluation context, and current baseline should guide initialization?",
            "why_needed": "background and constraints are mandatory context before adapter, metrics, or resource choices can be trusted",
            "blocks": ["project_brief", "adapter_mapping", "metrics_schema", "resource_policy"],
            "current_background": project_brief.get("background", ""),
            "requires_user_answer": True,
        },
        {
            "question_id": "q_init_initial_ideas",
            "question": "Do you have any initial research ideas to seed the idea pool? Answer 'none' if not.",
            "why_needed": "initial ideas are optional, but Codex should explicitly ask instead of assuming the seed pool is empty",
            "blocks": ["idea_pool_seed_confirmation"],
            "answer_can_be": "none",
            "requires_user_answer": True,
        },
        {
            "question_id": "q_init_resource_mode",
            "question": "Should this project use GPU/Slurm execution, local CPU execution, or both?",
            "why_needed": "resource mode must be a user policy decision before execution planning",
            "blocks": ["resource_policy", "automatic_execution"],
            "default": resource_by_id.get("q_resource_mode", {}).get("default", "gpu_slurm_if_available"),
        },
        {
            "question_id": "q_init_slurm_partitions",
            "question": "Which Slurm partitions should be preferred and which should be fallback?",
            "why_needed": "partition selection is a target-cluster policy decision; sinfo can provide candidates but cannot choose for the user",
            "blocks": ["partition_selection", "fallback_requeue_policy"],
            "detected_candidates": resource_by_id.get("q_slurm_partitions", {}).get("detected_candidates", []),
            "configured_preferred": resource_by_id.get("q_slurm_partitions", {}).get("configured_preferred", []),
            "configured_fallback": resource_by_id.get("q_slurm_partitions", {}).get("configured_fallback", []),
            "requires_user_answer": True,
        },
        {
            "question_id": "q_init_slurm_gres",
            "question": "What exact GRES template should be used for each GPU partition?",
            "why_needed": "GPU names in partition labels are examples only; Slurm submission must use confirmed target-cluster GRES",
            "blocks": ["gpu_sbatch_rendering", "automatic_gpu_submission"],
            "detected_suggestions": resource_by_id.get("q_slurm_gres", {}).get("detected_suggestions", {}),
            "configured_gres_by_partition": resource_by_id.get("q_slurm_gres", {}).get("configured_gres_by_partition", {}),
            "example_format": resource_by_id.get("q_slurm_gres", {}).get("example_format", "partition-name=gpu:gpu_type:{gpu}"),
            "requires_user_answer": True,
        },
        {
            "question_id": "q_init_queue_wait_limit",
            "question": "What maximum queued start-plus-run time is acceptable before preferring fallback or asking again?",
            "why_needed": "queue wait tolerance is a user budget and scheduling preference",
            "blocks": ["slurm_fallback_policy"],
            "configured_hours": resource_by_id.get("q_slurm_wait_limit", {}).get("configured_hours", 24),
        },
        {
            "question_id": "q_init_experiment_runtime_cap",
            "question": "What walltime and epoch caps should ordinary exploratory experiments obey?",
            "why_needed": "exploratory experiments should stay bounded and cheap",
            "blocks": ["run_resource_normalization"],
            "configured_max_run_hours": resource_by_id.get("q_experiment_runtime_caps", {}).get("configured_max_run_hours", 12),
            "configured_max_epochs": resource_by_id.get("q_experiment_runtime_caps", {}).get("configured_max_epochs", 200),
        },
        {
            "question_id": "q_init_delivery_runtime_cap",
            "question": "What larger walltime and epoch caps are allowed only for final delivery/submission-stage runs?",
            "why_needed": "final delivery limits must not leak into exploratory cycles",
            "blocks": ["final_delivery_resource_policy"],
            "configured_delivery_max_run_hours": resource_by_id.get("q_delivery_runtime_caps", {}).get("configured_delivery_max_run_hours", 72),
            "configured_delivery_max_epochs": resource_by_id.get("q_delivery_runtime_caps", {}).get("configured_delivery_max_epochs", 5000),
        },
        {
            "question_id": "q_init_gpu_submission_permission",
            "question": "May VibeResearch submit GPU/Slurm jobs automatically after adapter, budget, and readiness gates pass?",
            "why_needed": "automatic GPU submission is high risk and must be explicitly authorized",
            "blocks": ["automatic_submission_allowed"],
            "default": "no",
        },
        {
            "question_id": "q_init_budget_caps",
            "question": "What daily, per-experiment, per-hypothesis, and total budget caps should VibeResearch enforce?",
            "why_needed": "budget policy should be confirmed before queueing work",
            "blocks": ["budget_policy"],
            "configured_defaults": {
                "daily_job_cap": budget.get("daily_job_cap"),
                "daily_gpu_hour_cap": budget.get("daily_gpu_hour_cap"),
                "per_experiment_gpu_hour_cap": budget.get("per_experiment_gpu_hour_cap"),
                "per_hypothesis_gpu_hour_cap": budget.get("per_hypothesis_gpu_hour_cap"),
                "total_gpu_hour_cap": budget.get("total_gpu_hour_cap"),
            },
        },
        {
            "question_id": "q_init_autonomy_level",
            "question": "What autonomy level and automatic actions are allowed?",
            "why_needed": "Codex must not choose autonomy boundaries for the user",
            "blocks": ["autonomy_policy"],
            "configured_level": autonomy.get("level", "analysis_only"),
            "configured_automatic_actions": autonomy.get("allowed_automatic_actions", []),
        },
        {
            "question_id": "q_init_primary_metric",
            "question": "What is the trusted primary metric, direction, and required metric file schema?",
            "why_needed": "trusted evidence and leaderboard updates require confirmed metric semantics",
            "blocks": ["metrics_schema", "trusted_leaderboard"],
            "configured_metric": stage.get("target_metric_improvement", {}).get("metric", "primary"),
            "configured_direction": stage.get("target_metric_improvement", {}).get("direction", "max"),
        },
        {
            "question_id": "q_init_protected_metrics",
            "question": "Which protected metrics or guardrails must not regress, and what tolerances are allowed?",
            "why_needed": "promotion must block harmful regressions even when the primary metric improves",
            "blocks": ["stage_gate_policy", "promotion_policy"],
            "configured_protected_metrics": stage.get("protected_metrics", {}),
        },
        {
            "question_id": "q_init_adapter_execution_surface",
            "question": "Which project scripts, commands, or wrappers should form the first adapter/script execution surface?",
            "why_needed": "adapter and script drafts are required before VibeResearch can run experiment iterations",
            "blocks": ["adapter_script_bootstrap", "contract_tests", "real_experiment_readiness"],
            "expected_answer": "name the first low-risk probe/evaluation/training command, or state what wrapper Codex should draft first",
            "requires_user_answer": True,
        },
    ]


def answer_research_question(paths: VibePaths, question_id: str, answer: str, *, confirm: bool = True, source: str = "user") -> dict[str, Any]:
    files = research_paths(paths)
    rows = read_jsonl(files["questions"])
    now = utc_now()
    found = False
    updated: list[dict[str, Any]] = []
    for row in rows:
        if row.get("question_id") == question_id:
            row["answer"] = answer
            row["answer_source"] = source
            row["status"] = "answered" if confirm else "open"
            row["confirmed"] = bool(confirm)
            row["updated_at"] = now
            if confirm:
                row["resolved_at"] = now
            found = True
        updated.append(row)
    if not found:
        updated.append(
            {
                "question_id": question_id,
                "question": question_id.replace("_", " "),
                "answer": answer,
                "answer_source": source,
                "status": "answered" if confirm else "open",
                "confirmed": bool(confirm),
                "created_at": now,
                "updated_at": now,
                "resolved_at": now if confirm else "",
            }
        )
    write_text(files["questions"], "")
    for row in updated:
        append_jsonl(files["questions"], row)
    append_research_event(paths, "research_question_answered", {"question_id": question_id, "confirmed": confirm, "source": source})
    return next(row for row in updated if row.get("question_id") == question_id)


def read_project_brief(paths: VibePaths) -> dict[str, str]:
    text = (paths.project / "brief.md").read_text() if (paths.project / "brief.md").exists() else ""
    return {"goal": first_section(text, "Goal"), "background": first_section(text, "Background")}


def first_section(text: str, name: str) -> str:
    lines = text.splitlines()
    capture = False
    out: list[str] = []
    for line in lines:
        if line.strip().lower() in {f"## {name}".lower(), f"# {name}".lower()}:
            capture = True
            continue
        if capture and line.startswith("#"):
            break
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def scan_repo_constraints(paths: VibePaths) -> dict[str, Any]:
    keywords = ["budget", "gpu", "slurm", "resource", "forbid", "forbidden", "do not", "language", "memo", "禁止", "预算", "资源", "中文", "不要"]
    result: dict[str, Any] = {"sources": []}
    for rel in ["README.md", "AGENTS.md"]:
        path = paths.root / rel
        if not path.exists() or not path.is_file():
            continue
        matches = []
        for line in path.read_text(errors="ignore").splitlines():
            text = line.strip()
            if text and any(keyword.lower() in text.lower() for keyword in keywords):
                matches.append(text[:240])
            if len(matches) >= 20:
                break
        result["sources"].append({"path": rel, "constraint_lines": matches})
    return result


def render_constraints(constraints: dict[str, Any]) -> str:
    lines: list[str] = []
    for source in constraints.get("sources", []):
        lines.append(f"### {source.get('path', '')}")
        values = source.get("constraint_lines", [])
        lines.extend(f"- {value}" for value in values)
        if not values:
            lines.append("- no budget, autonomy, language, or resource constraints detected")
        lines.append("")
    return "\n".join(lines).strip() or "- no README/AGENTS constraints detected"


def write_default_policies(
    paths: VibePaths,
    *,
    memo_language: str = "zh-CN",
    timezone: str = "local",
    autonomy_level: str = "analysis_only",
    force: bool = False,
) -> dict[str, Any]:
    autonomy_level = autonomy_level if autonomy_level in AUTONOMY_LEVELS else "analysis_only"
    budget = {
        "version": 1,
        "daily_job_cap": 4,
        "daily_gpu_hour_cap": 8.0,
        "per_hypothesis_gpu_hour_cap": 12.0,
        "per_experiment_gpu_hour_cap": 4.0,
        "total_gpu_hour_cap": 40.0,
        "resource_units": ["gpu_hours", "cpu_hours", "memory_gb_hours", "walltime_hours", "storage_gb"],
        "unknown_cost_behavior": "block",
        "long_run_confirmation_gpu_hours": 2.0,
        "cooldown_after_failed_runs": 1,
        "max_consecutive_untrusted_runs": 2,
        "max_same_hypothesis_gate_runs": 2,
        "allow_night_submissions": False,
    }
    stage_gates = {
        "version": 1,
        "stages": ["idea", "analysis", "smoke", "single_unit_gate", "replicated_gate", "full_eval", "submission_ready"],
        "default_stage": "smoke",
        "require_trusted_evidence_for_promotion": True,
        "require_valid_metrics_schema": True,
        "target_metric_improvement": {"metric": "primary", "direction": "max", "min_delta": 0.0},
        "protected_metrics": {},
        "minimum_replication": 1,
        "max_failed_gates_before_reassessment": 2,
        "allow_protected_metric_override": False,
    }
    autonomy = {
        "version": 1,
        "level": autonomy_level,
        "allowed_automatic_actions": ["analyze", "memo", "memory_build"] if autonomy_level in {"diagnosis_only", "analysis_only"} else ["analyze", "memo", "memory_build", "smoke"],
        "requires_user_approval": ["long_run", "protected_metric_override", "unknown_cost", "full_eval", "submission_ready"],
        "max_concurrent_jobs": 1,
        "max_automatic_queue_depth": 1,
        "allowed_backends": ["local"],
        "allowed_adapter_capabilities": [],
        "scripts_may_be_edited_automatically": False,
        "jobs_may_be_submitted_automatically": False,
        "archive_may_run_automatically": True,
        "hypotheses_may_be_stopped_automatically": False,
    }
    memo = {"version": 1, "language": memo_language, "timezone": timezone, "daily_memo_time": "18:00"}
    policies = {"budget": budget, "stage_gates": stage_gates, "autonomy": autonomy, "memo": memo}
    targets = {
        "budget": paths.vibe / "policies" / "budget.yaml",
        "stage_gates": paths.vibe / "policies" / "stage_gates.yaml",
        "autonomy": paths.vibe / "policies" / "autonomy.yaml",
        "memo": paths.research / "memo_config.yaml",
    }
    for key, data in policies.items():
        if force or not targets[key].exists():
            write_yaml(targets[key], data)
            append_jsonl(paths.vibe / "policies" / "policy_history.jsonl", {"event": "policy_written", "policy": key, "version": data["version"], "created_at": utc_now(), "data": data})
    return policies


def research_readiness(paths: VibePaths) -> dict[str, Any]:
    ensure_research_dirs(paths)
    missing = []
    for path in [paths.vibe / "policies" / "budget.yaml", paths.vibe / "policies" / "stage_gates.yaml", paths.vibe / "policies" / "autonomy.yaml", paths.research / "research_brief.md"]:
        if not path.exists():
            missing.append(str(path.relative_to(paths.vibe)))
    open_questions = [row for row in read_jsonl(research_paths(paths)["questions"]) if row.get("status", "open") == "open"]
    adapter = adapter_readiness(paths)
    ready = not missing and not open_questions and adapter.get("ready_for_real_experiments", False)
    return {
        "ready_for_bounded_autonomy": ready,
        "missing_files": missing,
        "open_questions": open_questions,
        "adapter_ready": adapter.get("ready_for_real_experiments", False),
        "adapter_maturity": adapter.get("maturity_level", "missing"),
    }


def sustained_round_audit(paths: VibePaths, *, target_rounds: int = 3, min_routes_per_round: int = 3) -> dict[str, Any]:
    """Audit sustained multi-route progress instead of raw concurrent job count."""

    state = read_json(paths.state / "state.json", {})
    config = load_config(paths)
    manifest = load_adapter_manifest(paths)
    active_caps = [cap for cap in manifest.capabilities if cap.status == "active" and select_executable_decision_for_capability(cap)]
    candidates = default_candidates(paths)
    cycles = state.get("cycles", {}) if isinstance(state.get("cycles"), dict) else {}
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    active_jobs = read_json(paths.scheduler / "active_jobs.json", {"active": []}).get("active", [])
    cycle_rows = [audit_cycle_round(paths, cycle_id, runs, min_routes_per_round) for cycle_id in sorted(cycles)]
    completed_rounds = [row for row in cycle_rows if row["round_complete"]]
    active_cycle_counts: dict[str, int] = defaultdict(int)
    for job in active_jobs:
        cycle_id = str(job.get("cycle_id") or "")
        if cycle_id:
            active_cycle_counts[cycle_id] += 1

    issues: list[str] = []
    portfolio_cfg = config.get("portfolio", {}) if isinstance(config.get("portfolio"), dict) else {}
    if int(portfolio_cfg.get("max_runs_per_cycle", 0) or 0) < min_routes_per_round:
        issues.append("portfolio_max_runs_per_cycle_below_min_routes")
    if len(candidates) < min_routes_per_round:
        issues.append("default_portfolio_generates_too_few_routes")
    if active_jobs and max(active_cycle_counts.values() or [0]) < min_routes_per_round and len(active_jobs) >= min_routes_per_round:
        issues.append("active_jobs_fragmented_across_cycles_not_one_round")
    if active_jobs_with_outside_wait_fallback(active_jobs):
        issues.append("fallback_better_but_outside_wait_policy")
    source_rows = read_jsonl(paths.research / "sources.jsonl")
    external_repo_rows = read_jsonl(paths.research / "external_repos.jsonl")
    repo_analysis_rows = read_jsonl(paths.research / "external_repo_analyses.jsonl")
    method_marker = read_json(paths.research / "auto_method_search.json", {})
    if not source_rows and not external_repo_rows and not method_marker:
        issues.append("no_external_resource_provenance_recorded")
    analyzed_repos = {row.get("name", "") for row in repo_analysis_rows}
    cloned_without_analysis = [
        row.get("name", "")
        for row in external_repo_rows
        if row.get("status") == "cloned" and row.get("name", "") not in analyzed_repos
    ]
    if cloned_without_analysis:
        issues.append("cloned_external_repo_without_integration_analysis")
    state_status = str(state.get("status", ""))
    if state_status == "blocked_missing_capability" or str(state.get("blocked_reason", "")).startswith("blocked_missing_capability"):
        issues.append("blocked_missing_capability")
    real_progress = summarize_real_experiment_progress(paths)
    current_cycle_id = str(state.get("current_cycle_id") or "")
    countable_real_runs = real_progress.get("countable_runs", [])
    real_repair_blockers = [
        row
        for row in real_progress.get("non_counting_real_experiment_runs", [])
        if row.get("requires_repair")
        and row.get("status") in {"failed", "timeout", "cancelled", "dryrun_failed"}
        and real_repair_blocker_in_active_scope(row, countable_real_runs, current_cycle_id=current_cycle_id)
    ]
    if real_repair_blockers:
        issues.append("real_experiment_repair_required")

    result = {
        "created_at": utc_now(),
        "target_rounds": target_rounds,
        "min_routes_per_round": min_routes_per_round,
        "completed_round_count": len(completed_rounds),
        "complete": len(completed_rounds) >= target_rounds and not issues,
        "issues": issues,
        "framework_capabilities": {
            "active_executable_capabilities": [cap.id for cap in active_caps],
            "default_candidate_count": len(candidates),
            "portfolio_max_runs_per_cycle": portfolio_cfg.get("max_runs_per_cycle"),
            "external_search_contexts": sorted((method_marker.get("searches") or {}).keys()) if isinstance(method_marker.get("searches"), dict) else [],
            "external_source_records": len(source_rows),
            "external_repo_records": len(external_repo_rows),
            "external_repo_analysis_records": len(repo_analysis_rows),
            "cloned_repos_without_analysis": cloned_without_analysis,
        },
        "real_experiment_progress": {
            "observed_count": real_progress.get("observed_count", 0),
            "target_count": real_progress.get("target_count", 0),
            "repair_blockers": real_repair_blockers,
            "next_action": real_progress.get("next_action", ""),
        },
        "active_jobs_by_cycle": dict(sorted(active_cycle_counts.items())),
        "active_resource_issues": active_resource_issue_rows(paths, active_jobs),
        "cycles": cycle_rows,
        "completed_rounds": completed_rounds,
        "next_action": sustained_round_next_action(len(completed_rounds), target_rounds, issues, active_jobs),
    }
    write_json(paths.research / "sustained_round_audit.json", result)
    write_text(paths.research / "sustained_round_audit.md", render_sustained_round_audit(result))
    append_research_event(paths, "sustained_round_audit", {"complete": result["complete"], "issues": issues, "completed_round_count": len(completed_rounds)})
    return result


def real_repair_blocker_in_active_scope(row: dict[str, Any], countable_rows: list[dict[str, Any]], *, current_cycle_id: str) -> bool:
    if len(countable_rows) >= 1:
        row_capability = str(row.get("capability_id") or "")
        row_direction = str(row.get("direction_id") or "")
        for counted in countable_rows:
            if row_capability and counted.get("capability_id") == row_capability:
                return False
            if row_direction and counted.get("direction_id") == row_direction:
                return False
    if current_cycle_id:
        return row.get("cycle_id") == current_cycle_id
    return True


def audit_cycle_round(paths: VibePaths, cycle_id: str, runs: dict[str, Any], min_routes_per_round: int) -> dict[str, Any]:
    cycle_runs = {run_id: run for run_id, run in runs.items() if isinstance(run, dict) and run.get("cycle_id") == cycle_id}
    route_ids = {
        str(run.get("direction_id") or (run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata"), dict) else {}).get("capability_id") or run_id)
        for run_id, run in cycle_runs.items()
    }
    capability_ids = {
        str(run.get("adapter_metadata", {}).get("capability_id") or "")
        for run in cycle_runs.values()
        if isinstance(run.get("adapter_metadata"), dict)
    }
    all_finished = bool(cycle_runs) and all(round_terminal_run(run) for run in cycle_runs.values())
    attempted_runs = [run for run in cycle_runs.values() if str(run.get("status", "")) != "abandoned"]
    reflect_path = paths.cycles / cycle_id / "cycle_reflect.md"
    revised_path = paths.cycles / cycle_id / "cycle_revised_plan.md"
    reflect_text = reflect_path.read_text(errors="ignore") if reflect_path.exists() else ""
    revised_text = revised_path.read_text(errors="ignore") if revised_path.exists() else ""
    has_reflection = "## Run comparison" in reflect_text and "## Route classification" in reflect_text
    has_revision = "## Next-cycle diversity requirement" in revised_text
    route_count = len(route_ids)
    return {
        "cycle_id": cycle_id,
        "run_count": len(cycle_runs),
        "route_count": route_count,
        "capability_count": len({item for item in capability_ids if item}),
        "all_runs_finished": all_finished,
        "attempted_route_count": len(attempted_runs),
        "all_runs_abandoned": bool(cycle_runs) and not attempted_runs,
        "has_cycle_reflection": has_reflection,
        "has_cycle_revision": has_revision,
        "round_complete": route_count >= min_routes_per_round and all_finished and bool(attempted_runs) and has_reflection and has_revision,
    }


def round_terminal_run(run: dict[str, Any]) -> bool:
    status = str(run.get("status", ""))
    terminal_statuses = {"collected", "reflected", "revised", "merged", "abandoned", "cancelled", "failed", "timeout"}
    if status in terminal_statuses:
        return True
    return status == "blocked" and bool(run.get("non_counting_classification") or run.get("classification"))


def sustained_round_next_action(completed_count: int, target_rounds: int, issues: list[str], active_jobs: list[dict[str, Any]]) -> str:
    if completed_count >= target_rounds and not issues:
        return "sustained round target met"
    if "real_experiment_repair_required" in issues:
        return "repair or classify non-counting real experiment failures before planning another round"
    if "blocked_missing_capability" in issues:
        return "run adapter doctor, activate a changed executable capability, or repair missing inputs before scheduling another sustained round"
    if "fallback_better_but_outside_wait_policy" in issues:
        return "run vibe scheduler-requeue-fallback --allow-outside-policy to review fallback candidates before any explicit execute"
    if "cloned_external_repo_without_integration_analysis" in issues:
        return "run vibe external analyze-repo <name> for cloned external repositories before relying on them"
    if active_jobs:
        return "monitor active jobs, then collect metrics and run cycle reflection/revision before planning the next round"
    if "default_portfolio_generates_too_few_routes" in issues:
        return "create or promote more hypotheses/capabilities before scheduling the next portfolio"
    return "plan the next multi-route portfolio, then audit again after reflection/revision"


def render_sustained_round_audit(result: dict[str, Any]) -> str:
    lines = [
        "# Sustained Round Audit",
        "",
        f"Complete: `{result.get('complete')}`",
        f"Completed rounds: `{result.get('completed_round_count')}` / `{result.get('target_rounds')}`",
        f"Minimum routes per round: `{result.get('min_routes_per_round')}`",
        f"Next action: {result.get('next_action')}",
        "",
        "## Issues",
    ]
    lines.extend([f"- `{issue}`" for issue in result.get("issues", [])] or ["- none"])
    issue_rows = result.get("active_resource_issues", []) if isinstance(result.get("active_resource_issues"), list) else []
    if issue_rows:
        lines.extend(["", "## Active Resource Issues"])
        for row in issue_rows:
            lines.extend(
                [
                    f"- `{row.get('run_id', '')}` job `{row.get('job_id', '')}`: `{row.get('verdict', '')}`",
                    f"  - command: `{row.get('executable_command', '')}`",
                ]
            )
    lines.extend(["", "## Cycles"])
    for row in result.get("cycles", []):
        lines.append(
            f"- `{row['cycle_id']}` runs={row['run_count']} routes={row['route_count']} "
            f"finished={row['all_runs_finished']} reflected={row['has_cycle_reflection']} "
            f"revised={row['has_cycle_revision']} complete={row['round_complete']}"
        )
    if not result.get("cycles"):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def active_jobs_with_outside_wait_fallback(active_jobs: list[dict[str, Any]]) -> bool:
    for job in active_jobs:
        details = job.get("poll_details", {}) if isinstance(job.get("poll_details"), dict) else {}
        verdict = details.get("wait_verdict", job.get("wait_verdict", {}))
        if isinstance(verdict, dict) and verdict.get("verdict") == "fallback_better_but_outside_wait_policy":
            return True
    return False


def active_resource_issue_rows(paths: VibePaths, active_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in active_jobs:
        details = job.get("poll_details", {}) if isinstance(job.get("poll_details"), dict) else {}
        verdict = details.get("wait_verdict", job.get("wait_verdict", {}))
        if not isinstance(verdict, dict) or verdict.get("verdict") != "fallback_better_but_outside_wait_policy":
            continue
        rows.append(
            {
                "issue": "fallback_better_but_outside_wait_policy",
                "run_id": str(job.get("run_id", "")),
                "job_id": str(job.get("job_id", "")),
                "current_partition": str(job.get("partition", "")),
                "recommended_partition": str(verdict.get("recommended_partition", "")),
                "verdict": str(verdict.get("verdict", "")),
                "executable_command": fallback_requeue_command(
                    paths.root,
                    str(job.get("run_id", "")),
                    allow_outside_policy=True,
                    allow_carried_forward=bool(details.get("carried_forward_wait_verdict")),
                    execute=True,
                ),
            }
        )
    return rows


def policy_completeness(paths: VibePaths) -> dict[str, Any]:
    """Check whether policy files are complete enough for safe automation."""

    budget = read_yaml(paths.vibe / "policies" / "budget.yaml", {})
    stage = read_yaml(paths.vibe / "policies" / "stage_gates.yaml", {})
    autonomy = read_yaml(paths.vibe / "policies" / "autonomy.yaml", {})
    memo = read_yaml(paths.research / "memo_config.yaml", {}) or read_yaml(paths.vibe / "memos" / "memo_config.yaml", {})
    issues: list[str] = []
    warnings: list[str] = []
    budget_required = [
        "daily_job_cap",
        "daily_gpu_hour_cap",
        "per_hypothesis_gpu_hour_cap",
        "per_experiment_gpu_hour_cap",
        "long_run_confirmation_gpu_hours",
        "unknown_cost_behavior",
        "cooldown_after_failed_runs",
        "max_consecutive_untrusted_runs",
    ]
    stage_required = ["stages", "target_metric_improvement", "max_failed_gates_before_reassessment", "allow_protected_metric_override"]
    autonomy_required = ["level", "requires_user_approval", "max_concurrent_jobs", "max_automatic_queue_depth", "allowed_backends"]
    if not budget:
        issues.append("missing budget policy blocks queue submission")
    else:
        issues.extend(f"budget policy missing {key}" for key in budget_required if key not in budget)
    if not stage:
        issues.append("missing stage-gate policy blocks promotion")
    else:
        issues.extend(f"stage-gate policy missing {key}" for key in stage_required if key not in stage)
        if not stage.get("protected_metrics"):
            warnings.append("protected metrics are not configured; automatic higher-stage promotion is blocked")
    if not autonomy:
        issues.append("missing autonomy policy blocks automatic execution")
    else:
        issues.extend(f"autonomy policy missing {key}" for key in autonomy_required if key not in autonomy)
        if "scripts_may_be_edited_automatically" not in autonomy:
            warnings.append("autonomy policy should explicitly answer whether scripts may be edited automatically")
        if "jobs_may_be_submitted_automatically" not in autonomy:
            warnings.append("autonomy policy should explicitly answer whether jobs may be submitted automatically")
        if "hypotheses_may_be_stopped_automatically" not in autonomy:
            warnings.append("autonomy policy should explicitly answer whether hypotheses may be stopped automatically")
    if not memo:
        warnings.append("memo config missing; daily memo language/timezone may be incomplete")
    safe_low_risk = bool(budget and autonomy and not any(item.startswith("missing budget") or item.startswith("missing autonomy") for item in issues))
    return {
        "complete": not issues and not warnings,
        "safe_for_low_risk_execution": safe_low_risk,
        "safe_for_promotion": bool(stage) and not issues and bool(stage.get("protected_metrics")),
        "issues": issues,
        "warnings": warnings,
        "statuses": {
            "budget": "passed" if budget and not any(item.startswith("budget") or item.startswith("missing budget") for item in issues) else "blocked",
            "stage_gates": "passed" if stage and not any(item.startswith("stage") or item.startswith("missing stage") for item in issues) else "blocked",
            "autonomy": "passed" if autonomy and not any(item.startswith("autonomy") or item.startswith("missing autonomy") for item in issues) else "blocked",
            "memo": "passed" if memo else "untrusted",
            "protected_metrics": "passed" if stage.get("protected_metrics") else "requires_user_answer",
        },
    }


def append_research_event(paths: VibePaths, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    files = research_paths(paths)
    existing = [row.get("event_id", "") for row in read_jsonl(files["events"])]
    row = {"event_id": next_numeric_id(existing, "event_"), "event_type": event_type, "created_at": utc_now(), "payload": payload}
    append_jsonl(files["events"], row)
    return row


def load_hypotheses(paths: VibePaths) -> dict[str, Any]:
    data = read_json(research_paths(paths)["hypotheses"], {})
    return data if isinstance(data, dict) else {}


def save_hypotheses(paths: VibePaths, data: dict[str, Any]) -> None:
    write_json(research_paths(paths)["hypotheses"], data)


def load_experiments(paths: VibePaths) -> dict[str, Any]:
    data = read_json(research_paths(paths)["experiments"], {})
    return data if isinstance(data, dict) else {}


def save_experiments(paths: VibePaths, data: dict[str, Any]) -> None:
    write_json(research_paths(paths)["experiments"], data)


def load_evidence(paths: VibePaths) -> dict[str, Any]:
    data = read_json(research_paths(paths)["evidence"], {})
    return data if isinstance(data, dict) else {}


def save_evidence(paths: VibePaths, data: dict[str, Any]) -> None:
    write_json(research_paths(paths)["evidence"], data)


def create_hypothesis(paths: VibePaths, title: str, *, rationale: str = "", stage: str = "idea", target_metrics: list[str] | None = None, protected_metrics: dict[str, Any] | None = None, origin: str = "operator") -> dict[str, Any]:
    ensure_research_dirs(paths)
    hypotheses = load_hypotheses(paths)
    hyp_id = next_numeric_id(hypotheses.keys(), "hyp_")
    now = utc_now()
    record = HypothesisRecord(
        hypothesis_id=hyp_id,
        title=title,
        short_name=title[:48],
        status="active",
        origin=origin,
        rationale=rationale,
        target_metrics=target_metrics or [],
        protected_metrics=protected_metrics or {},
        stage=stage,
        current_stage=stage,
        provenance={"source": "vibe hypothesis create"},
        created_at=now,
        updated_at=now,
    ).model_dump()
    hypotheses[hyp_id] = record
    save_hypotheses(paths, hypotheses)
    append_research_event(paths, "hypothesis_created", record)
    record_event(paths, "hypothesis_created", title, status="active", payload={"hypothesis_id": hyp_id})
    return record


def update_hypothesis(paths: VibePaths, hypothesis_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    hypotheses = load_hypotheses(paths)
    if hypothesis_id not in hypotheses:
        raise ValueError(f"Unknown hypothesis: {hypothesis_id}")
    current = dict(hypotheses[hypothesis_id])
    current.update({key: value for key, value in updates.items() if value is not None})
    current["updated_at"] = utc_now()
    record = HypothesisRecord.model_validate(current).model_dump()
    hypotheses[hypothesis_id] = record
    save_hypotheses(paths, hypotheses)
    append_research_event(paths, "hypothesis_updated", {"hypothesis_id": hypothesis_id, "updates": updates})
    return record


def write_research_decision(paths: VibePaths, data: dict[str, Any]) -> dict[str, Any]:
    files = research_paths(paths)
    existing = [row.get("decision_id", "") for row in read_jsonl(files["decisions"])]
    payload = {"decision_id": data.get("decision_id") or next_numeric_id(existing, "research_decision_"), "created_at": utc_now(), **data}
    record = ResearchDecisionRecord.model_validate(payload).model_dump()
    append_jsonl(files["decisions"], record)
    append_research_event(paths, "research_decision_recorded", record)
    return record


def trusted_evidence_for_hypothesis(paths: VibePaths, hypothesis_id: str, *, negative: bool | None = None) -> list[dict[str, Any]]:
    experiments = load_experiments(paths)
    evidence = load_evidence(paths)
    exp_ids = {exp_id for exp_id, exp in experiments.items() if exp.get("hypothesis_id") == hypothesis_id}
    rows = [row for row in evidence.values() if row.get("experiment_id") in exp_ids and row.get("trusted") and row.get("schema_valid")]
    if negative is True:
        rows = [row for row in rows if row.get("failure_kind") == "scientific" or row.get("metric_deltas", {}).get("primary", 0) < 0]
    if negative is False:
        rows = [row for row in rows if row.get("failure_kind") in {"none", ""} and not row.get("protected_metric_regressions")]
    return rows


def change_hypothesis_status(paths: VibePaths, hypothesis_id: str, outcome: str, *, reason: str, user_decision: bool = False, remaining_upside: dict[str, Any] | None = None, failure_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    if outcome == "promote":
        completeness = policy_completeness(paths)
        if not completeness.get("safe_for_promotion"):
            decision = write_research_decision(paths, {"hypothesis_id": hypothesis_id, "decision_type": "promote", "final_outcome": "blocked", "rationale": reason, "blocked_reasons": completeness.get("issues", []) + completeness.get("warnings", [])})
            raise RuntimeError("promotion blocked by policy completeness: " + "; ".join(decision["blocked_reasons"]))
        trusted = trusted_evidence_for_hypothesis(paths, hypothesis_id, negative=False)
        regressions = [ev for ev in trusted if ev.get("protected_metric_regressions")]
        if not trusted or regressions:
            decision = write_research_decision(paths, {"hypothesis_id": hypothesis_id, "decision_type": "promote", "final_outcome": "blocked", "rationale": reason, "blocked_reasons": ["promotion_requires_trusted_schema_valid_evidence_without_protected_regression"]})
            raise RuntimeError(f"promotion blocked: {decision['blocked_reasons'][0]}")
        status = "promoted"
    elif outcome == "stop":
        if not user_decision and not trusted_evidence_for_hypothesis(paths, hypothesis_id, negative=True):
            decision = write_research_decision(paths, {"hypothesis_id": hypothesis_id, "decision_type": "stop", "final_outcome": "blocked", "rationale": reason, "blocked_reasons": ["stopping_requires_trusted_negative_evidence_or_user_decision"]})
            raise RuntimeError(f"stop blocked: {decision['blocked_reasons'][0]}")
        status = "stopped"
    elif outcome == "downscope":
        status = "downscoped"
    else:
        status = "needs_analysis"
    decision = write_research_decision(
        paths,
        {
            "hypothesis_id": hypothesis_id,
            "decision_type": outcome,
            "final_outcome": outcome,
            "rationale": reason,
            "promotion_or_stop_reason": reason,
            "agent_judgment": {"remaining_upside": remaining_upside or {}, "failure_analysis": failure_analysis or {}},
        },
    )
    updates: dict[str, Any] = {"status": status, "decision_history": list(load_hypotheses(paths).get(hypothesis_id, {}).get("decision_history", [])) + [decision["decision_id"]]}
    if outcome == "stop":
        updates["stop_reason"] = reason
    if remaining_upside is not None:
        updates["remaining_upside"] = remaining_upside
    if failure_analysis is not None:
        updates["failure_analysis"] = failure_analysis
    record = update_hypothesis(paths, hypothesis_id, updates)
    append_research_event(paths, f"hypothesis_{status}", {"hypothesis_id": hypothesis_id, "decision_id": decision["decision_id"], "reason": reason})
    return record


def create_experiment(
    paths: VibePaths,
    hypothesis_id: str,
    design_summary: str,
    *,
    stage: str = "smoke",
    capability_id: str = "",
    decision_id: str = "",
    resource_plan: dict[str, Any] | None = None,
    expected_evidence: dict[str, Any] | None = None,
    success_criteria: dict[str, Any] | None = None,
    failure_criteria: dict[str, Any] | None = None,
    baseline_target: str = "",
    protected_metric_constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hypotheses = load_hypotheses(paths)
    if hypothesis_id not in hypotheses:
        raise ValueError(f"Unknown hypothesis: {hypothesis_id}")
    experiments = load_experiments(paths)
    exp_id = next_numeric_id(experiments.keys(), "exp_")
    manifest = load_adapter_manifest(paths)
    cap = next((cap for cap in manifest.capabilities if cap.id == capability_id), None)
    now = utc_now()
    record = ExperimentRecord(
        experiment_id=exp_id,
        hypothesis_id=hypothesis_id,
        design_summary=design_summary,
        stage=stage,
        decision_id=decision_id,
        capability_id=capability_id,
        adapter_revision=str(manifest.adapter_revision),
        execution_script=(cap.entrypoint.get("command", "") if cap else ""),
        resource_plan=resource_plan or {},
        expected_evidence=expected_evidence or {},
        success_criteria=success_criteria or {},
        failure_criteria=failure_criteria or {},
        baseline_target=baseline_target,
        protected_metric_constraints=protected_metric_constraints or {},
        cost_estimated=(resource_plan or {}).get("resource_units", {}) if isinstance(resource_plan, dict) else {},
        provenance={"source": "vibe experiment create"},
        created_at=now,
        updated_at=now,
    ).model_dump()
    experiments[exp_id] = record
    save_experiments(paths, experiments)
    hyp = hypotheses[hypothesis_id]
    hyp.setdefault("linked_experiments", []).append(exp_id)
    hyp["updated_at"] = now
    save_hypotheses(paths, hypotheses)
    append_research_event(paths, "experiment_created", record)
    return record


def link_run_to_experiment(paths: VibePaths, experiment_id: str, run_id: str) -> dict[str, Any]:
    experiments = load_experiments(paths)
    if experiment_id not in experiments:
        raise ValueError(f"Unknown experiment: {experiment_id}")
    exp = experiments[experiment_id]
    for key in ["linked_run_ids", "run_ids"]:
        exp.setdefault(key, [])
        if run_id not in exp[key]:
            exp[key].append(run_id)
    exp["updated_at"] = utc_now()
    experiments[experiment_id] = exp
    save_experiments(paths, experiments)
    append_research_event(paths, "experiment_run_linked", {"experiment_id": experiment_id, "run_id": run_id})
    return exp


def add_evidence(
    paths: VibePaths,
    experiment_id: str,
    *,
    run_id: str = "",
    kind: str = "metrics",
    trusted: bool = False,
    schema_valid: bool = False,
    metrics_schema_version: str = "",
    metrics_file: str = "",
    summary: str = "",
    metric_deltas: dict[str, Any] | None = None,
    protected_metric_regressions: list[dict[str, Any]] | None = None,
    failure_kind: str = "none",
    analysis_notes: str = "",
) -> dict[str, Any]:
    experiments = load_experiments(paths)
    if experiment_id not in experiments:
        raise ValueError(f"Unknown experiment: {experiment_id}")
    evidence = load_evidence(paths)
    evidence_id = next_numeric_id(evidence.keys(), "ev_")
    record = EvidenceRecord(
        evidence_id=evidence_id,
        experiment_id=experiment_id,
        run_id=run_id,
        kind=kind,
        trusted=trusted,
        schema_valid=schema_valid,
        metrics_schema_version=metrics_schema_version,
        metrics_file=metrics_file,
        summary=summary,
        metric_deltas=metric_deltas or {},
        protected_metric_regressions=protected_metric_regressions or [],
        failure_kind=failure_kind,
        analysis_notes=analysis_notes,
        provenance={"source": "vibe experiment analyze"},
        created_at=utc_now(),
    ).model_dump()
    evidence[evidence_id] = record
    save_evidence(paths, evidence)
    exp = experiments[experiment_id]
    if run_id:
        for key in ["linked_run_ids", "run_ids"]:
            exp.setdefault(key, [])
            if run_id not in exp[key]:
                exp[key].append(run_id)
    key = "trusted_evidence_ids" if trusted and schema_valid else "untrusted_evidence_ids"
    exp.setdefault(key, []).append(evidence_id)
    exp["status"] = "evidence_recorded"
    exp["analysis_summary"] = summary or analysis_notes
    exp["updated_at"] = utc_now()
    experiments[experiment_id] = exp
    save_experiments(paths, experiments)
    update_hypothesis_evidence_index(paths, exp["hypothesis_id"])
    append_research_event(paths, "evidence_recorded", record)
    return record


def update_hypothesis_evidence_index(paths: VibePaths, hypothesis_id: str) -> None:
    hypotheses = load_hypotheses(paths)
    if hypothesis_id not in hypotheses:
        return
    trusted_positive = trusted_evidence_for_hypothesis(paths, hypothesis_id, negative=False)
    trusted_negative = trusted_evidence_for_hypothesis(paths, hypothesis_id, negative=True)
    hyp = hypotheses[hypothesis_id]
    hyp["best_evidence"] = [row["evidence_id"] for row in trusted_positive]
    hyp["negative_evidence"] = [row["evidence_id"] for row in trusted_negative]
    if trusted_negative:
        hyp["status"] = "needs_analysis" if hyp.get("status") == "active" else hyp.get("status", "needs_analysis")
    hyp["updated_at"] = utc_now()
    save_hypotheses(paths, hypotheses)


def audit_registry(paths: VibePaths) -> dict[str, Any]:
    hypotheses = load_hypotheses(paths)
    experiments = load_experiments(paths)
    evidence = load_evidence(paths)
    decisions = read_jsonl(research_paths(paths)["decisions"])
    issues: list[str] = []
    for exp_id, exp in experiments.items():
        if exp.get("hypothesis_id") not in hypotheses:
            issues.append(f"{exp_id}: orphan experiment without hypothesis")
        if exp.get("status") in {"evidence_recorded", "completed"} and not (exp.get("trusted_evidence_ids") or exp.get("untrusted_evidence_ids")):
            issues.append(f"{exp_id}: experiment status implies evidence but no evidence ids are linked")
    for ev_id, ev in evidence.items():
        if ev.get("experiment_id") not in experiments:
            issues.append(f"{ev_id}: orphan evidence without experiment")
    for row in decisions:
        if row.get("experiment_id") and row["experiment_id"] not in experiments:
            issues.append(f"{row.get('decision_id')}: decision references missing experiment")
        if row.get("hypothesis_id") and row["hypothesis_id"] not in hypotheses:
            issues.append(f"{row.get('decision_id')}: decision references missing hypothesis")
        if row.get("final_outcome") in {"promote", "stop"} and not (row.get("experiment_id") or trusted_evidence_for_hypothesis(paths, row.get("hypothesis_id", ""))):
            issues.append(f"{row.get('decision_id')}: terminal decision has no trusted evidence link")
    duplicate_warnings = duplicate_risk_warnings(paths)
    result = {"ok": not issues, "issues": issues, "duplicate_risk_warnings": duplicate_warnings, "counts": {"hypotheses": len(hypotheses), "experiments": len(experiments), "evidence": len(evidence), "decisions": len(decisions)}}
    write_json(paths.research / "audit.json", result)
    return result


def load_budget_policy(paths: VibePaths) -> dict[str, Any]:
    return read_yaml(paths.vibe / "policies" / "budget.yaml", {}) or {}


def resource_gpu_hours(resource_units: dict[str, Any]) -> float | None:
    if not resource_units:
        return None
    if "gpu_hours" in resource_units:
        return float(resource_units.get("gpu_hours") or 0.0)
    gpu = resource_units.get("gpu", resource_units.get("gpus", 0))
    wall = resource_units.get("walltime_hours", resource_units.get("hours", 0))
    if gpu is None or wall is None:
        return None
    try:
        return float(gpu or 0) * float(wall or 0)
    except (TypeError, ValueError):
        return None


def budget_status(paths: VibePaths) -> dict[str, Any]:
    policy = load_budget_policy(paths)
    ledger = read_jsonl(research_paths(paths)["budget"])
    today = datetime.now().date().isoformat()
    reserved_gpu = 0.0
    actual_gpu = 0.0
    reservations = 0
    per_hyp: dict[str, float] = defaultdict(float)
    for row in ledger:
        status = row.get("status")
        created = str(row.get("reservation_time", row.get("created_at", "")))[:10]
        units = row.get("resource_units", {}) if isinstance(row.get("resource_units"), dict) else {}
        gpu_hours = resource_gpu_hours(units) or 0.0
        if status == "reserved":
            if created == today:
                reservations += 1
                reserved_gpu += gpu_hours
        if status == "reconciled":
            actual = row.get("actual_cost", {}) if isinstance(row.get("actual_cost"), dict) else {}
            actual_gpu += float(actual.get("gpu_hours", gpu_hours) or 0.0)
        hyp = row.get("hypothesis_id", "")
        if hyp:
            per_hyp[hyp] += gpu_hours
    return {
        "policy": policy,
        "reserved_today_gpu_hours": reserved_gpu,
        "actual_gpu_hours": actual_gpu,
        "reservations_today": reservations,
        "remaining_daily_gpu_hours": float(policy.get("daily_gpu_hour_cap", 0.0) or 0.0) - reserved_gpu,
        "remaining_daily_jobs": int(policy.get("daily_job_cap", 0) or 0) - reservations,
        "per_hypothesis_gpu_hours": dict(per_hyp),
        "ledger_count": len(ledger),
    }


def reserve_budget(paths: VibePaths, *, decision_id: str = "", experiment_id: str = "", hypothesis_id: str = "", resource_units: dict[str, Any] | None = None, estimated_cost: dict[str, Any] | None = None, requires_long_run: bool = False, confirmed: bool = False) -> dict[str, Any]:
    policy = load_budget_policy(paths)
    units = resource_units or {}
    gpu_hours = resource_gpu_hours(units)
    blocked: list[str] = []
    status = budget_status(paths)
    if gpu_hours is None and policy.get("unknown_cost_behavior", "block") == "block":
        blocked.append("unknown_cost")
    gpu_hours = gpu_hours or 0.0
    if status["remaining_daily_jobs"] <= 0:
        blocked.append("daily_job_cap")
    if gpu_hours > status["remaining_daily_gpu_hours"]:
        blocked.append("daily_gpu_hour_cap")
    if hypothesis_id and status["per_hypothesis_gpu_hours"].get(hypothesis_id, 0.0) + gpu_hours > float(policy.get("per_hypothesis_gpu_hour_cap", 0.0) or 0.0):
        blocked.append("per_hypothesis_gpu_hour_cap")
    if gpu_hours > float(policy.get("per_experiment_gpu_hour_cap", 0.0) or 0.0):
        blocked.append("per_experiment_gpu_hour_cap")
    if requires_long_run or gpu_hours >= float(policy.get("long_run_confirmation_gpu_hours", 999999.0) or 999999.0):
        if not confirmed:
            blocked.append("long_run_confirmation_required")
    existing = [row.get("budget_event_id", "") for row in read_jsonl(research_paths(paths)["budget"])]
    row = {
        "budget_event_id": next_numeric_id(existing, "budget_"),
        "decision_id": decision_id,
        "experiment_id": experiment_id,
        "hypothesis_id": hypothesis_id,
        "resource_units": units,
        "estimated_cost": estimated_cost or {"gpu_hours": gpu_hours},
        "actual_cost": {},
        "status": "blocked" if blocked else "reserved",
        "blocked_reasons": blocked,
        "reservation_time": utc_now(),
        "reconciliation_time": "",
    }
    append_jsonl(research_paths(paths)["budget"], row)
    append_research_event(paths, "budget_reserved" if not blocked else "budget_blocked", row)
    return row


def reconcile_budget(paths: VibePaths, budget_event_id: str, actual_cost: dict[str, Any]) -> dict[str, Any]:
    ledger_path = research_paths(paths)["budget"]
    rows = read_jsonl(ledger_path)
    found = None
    for row in rows:
        if row.get("budget_event_id") == budget_event_id:
            row["actual_cost"] = actual_cost
            row["status"] = "reconciled"
            row["reconciliation_time"] = utc_now()
            found = row
    if not found:
        raise ValueError(f"Unknown budget event: {budget_event_id}")
    write_text(ledger_path, "")
    for row in rows:
        append_jsonl(ledger_path, row)
    append_research_event(paths, "budget_reconciled", found)
    return found


def duplicate_risk_warnings(paths: VibePaths) -> list[dict[str, Any]]:
    experiments = load_experiments(paths)
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for exp in experiments.values():
        key = (exp.get("hypothesis_id", ""), exp.get("stage", ""), exp.get("design_summary", ""), exp.get("capability_id", ""))
        grouped[key].append(exp)
    warnings = []
    for (hyp, stage, design, cap), rows in grouped.items():
        failed = [row for row in rows if row.get("status") in {"failed", "blocked", "needs_analysis", "evidence_recorded"} and not row.get("failure_analysis", {}).get("changed_variable")]
        if len(failed) >= 2:
            warnings.append({"hypothesis_id": hyp, "stage": stage, "design_summary": design, "capability_id": cap, "count": len(failed), "reason": "same hypothesis, stage, design, and capability repeated without changed variable"})
    return warnings


def build_memory_pack(paths: VibePaths) -> dict[str, Any]:
    hypotheses = load_hypotheses(paths)
    experiments = load_experiments(paths)
    evidence = load_evidence(paths)
    active_h = [row for row in hypotheses.values() if row.get("status") in {"active", "needs_analysis", "blocked"}]
    stopped_h = [row for row in hypotheses.values() if row.get("status") in {"stopped", "archived"}]
    downscoped_h = [row for row in hypotheses.values() if row.get("status") == "downscoped"]
    trusted_positive = [row for row in evidence.values() if row.get("trusted") and row.get("schema_valid") and row.get("failure_kind") in {"none", ""}]
    trusted_negative = [row for row in evidence.values() if row.get("trusted") and row.get("schema_valid") and row.get("failure_kind") == "scientific"]
    untrusted = [row for row in evidence.values() if not row.get("trusted") or not row.get("schema_valid")]
    readiness = adapter_readiness(paths)
    pack = {
        "created_at": utc_now(),
        "active_hypotheses": active_h,
        "stopped_hypotheses": stopped_h,
        "downscoped_hypotheses": downscoped_h,
        "current_stage_by_hypothesis": {hid: row.get("current_stage", row.get("stage", "")) for hid, row in hypotheses.items()},
        "trusted_positive_evidence": trusted_positive,
        "trusted_negative_evidence": trusted_negative,
        "untrusted_or_schema_invalid_evidence": untrusted,
        "unresolved_blockers": [row for row in read_jsonl(research_paths(paths)["questions"]) if row.get("status", "open") == "open"],
        "active_adapter_capabilities": readiness.get("active_capabilities", []),
        "adapter_maturity": readiness.get("maturity_level", "missing"),
        "protected_metrics": read_yaml(paths.vibe / "policies" / "stage_gates.yaml", {}).get("protected_metrics", {}),
        "budget_status": budget_status(paths),
        "duplicate_risk_warnings": duplicate_risk_warnings(paths),
        "open_questions_for_user": [row.get("question", "") for row in read_jsonl(research_paths(paths)["questions"]) if row.get("status", "open") == "open"],
        "recently_rejected_ideas": [row for row in read_jsonl(paths.ideas / "registry.jsonl") if row.get("status") in {"rejected", "archived"}][-10:],
        "failure_taxonomy": sorted(FAILURE_KINDS),
        "experiment_index": experiments,
    }
    write_json(research_paths(paths)["memory_json"], pack)
    write_text(research_paths(paths)["memory_md"], render_memory_markdown(pack))
    append_research_event(paths, "memory_pack_built", {"active_hypotheses": len(active_h), "duplicate_warnings": len(pack["duplicate_risk_warnings"])})
    return pack


def render_memory_markdown(pack: dict[str, Any]) -> str:
    lines = ["# Research Memory Pack", "", f"Created: `{pack['created_at']}`", ""]
    for title, key in [
        ("Active Hypotheses", "active_hypotheses"),
        ("Stopped Hypotheses", "stopped_hypotheses"),
        ("Trusted Positive Evidence", "trusted_positive_evidence"),
        ("Trusted Negative Evidence", "trusted_negative_evidence"),
        ("Untrusted Or Schema-Invalid Evidence", "untrusted_or_schema_invalid_evidence"),
        ("Duplicate-Risk Warnings", "duplicate_risk_warnings"),
        ("Open Questions", "open_questions_for_user"),
    ]:
        lines.extend([f"## {title}", ""])
        values = pack.get(key, [])
        if not values:
            lines.append("- none")
        else:
            for row in values:
                if isinstance(row, dict):
                    ident = row.get("hypothesis_id") or row.get("evidence_id") or row.get("reason") or row.get("question") or "item"
                    desc = row.get("title") or row.get("summary") or row.get("design_summary") or row.get("reason") or ""
                    lines.append(f"- `{ident}` {desc}")
                else:
                    lines.append(f"- {row}")
        lines.append("")
    return "\n".join(lines)


def active_capability_ids(paths: VibePaths) -> set[str]:
    manifest = load_adapter_manifest(paths)
    return {cap.id for cap in manifest.capabilities if cap.status == "active"}


def evaluate_candidate(paths: VibePaths, candidate: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    hypothesis_id = candidate.get("hypothesis_id", "")
    capability_id = candidate.get("capability_id", "")
    decision_type = candidate.get("decision_type", "launch_gpu_gate")
    stage = candidate.get("stage", "smoke")
    manifest = load_adapter_manifest(paths)
    caps = {cap.id: cap for cap in manifest.capabilities if cap.status == "active"}
    cap = caps.get(capability_id)
    if not cap:
        reasons.append("blocked_missing_capability")
    elif decision_type not in cap.supported_decisions:
        reasons.append("blocked_missing_capability")
    elif not cap.entrypoint.get("command") or not cap.dryrun.get("command"):
        reasons.append("blocked_missing_script")
    elif not (cap.metrics_schema.required or cap.metrics_schema.types):
        reasons.append("blocked_missing_metrics_schema")
    autonomy = read_yaml(paths.vibe / "policies" / "autonomy.yaml", {}) or {}
    level = autonomy.get("level", "analysis_only")
    if level in {"diagnosis_only", "analysis_only"} and stage not in {"idea", "analysis"}:
        reasons.append("blocked_autonomy_level")
    if candidate.get("promotion"):
        if not trusted_evidence_for_hypothesis(paths, hypothesis_id, negative=False):
            reasons.append("blocked_no_trusted_evidence")
    resources = candidate.get("resource_units", {})
    budget_reasons = budget_block_reasons(paths, hypothesis_id, resources, bool(candidate.get("requires_long_run")), bool(candidate.get("confirmed")))
    reasons.extend(budget_reasons)
    if duplicate_candidate(paths, candidate):
        reasons.append("blocked_repeating_experiment")
    selected = not reasons
    return {"candidate": candidate, "status": "selected" if selected else "blocked", "blocked_reasons": reasons, "selection_reason": candidate.get("rationale", "") or "fits active capability, budget, stage, and autonomy policies"}


def budget_block_reasons(paths: VibePaths, hypothesis_id: str, resource_units: dict[str, Any], requires_long_run: bool, confirmed: bool) -> list[str]:
    policy = load_budget_policy(paths)
    status = budget_status(paths)
    reasons: list[str] = []
    gpu_hours = resource_gpu_hours(resource_units)
    if gpu_hours is None and policy.get("unknown_cost_behavior", "block") == "block":
        return ["blocked_unknown_cost"]
    gpu_hours = gpu_hours or 0.0
    if status["remaining_daily_jobs"] <= 0:
        reasons.append("blocked_daily_job_cap")
    if gpu_hours > status["remaining_daily_gpu_hours"]:
        reasons.append("blocked_daily_gpu_hour_cap")
    if hypothesis_id and status["per_hypothesis_gpu_hours"].get(hypothesis_id, 0.0) + gpu_hours > float(policy.get("per_hypothesis_gpu_hour_cap", 0.0) or 0.0):
        reasons.append("blocked_per_hypothesis_budget")
    if gpu_hours > float(policy.get("per_experiment_gpu_hour_cap", 0.0) or 0.0):
        reasons.append("blocked_per_experiment_budget")
    if (requires_long_run or gpu_hours >= float(policy.get("long_run_confirmation_gpu_hours", 999999.0) or 999999.0)) and not confirmed:
        reasons.append("blocked_long_run_confirmation")
    return reasons


def duplicate_candidate(paths: VibePaths, candidate: dict[str, Any]) -> bool:
    for exp in load_experiments(paths).values():
        if exp.get("hypothesis_id") != candidate.get("hypothesis_id"):
            continue
        if exp.get("stage") != candidate.get("stage"):
            continue
        if exp.get("design_summary") != candidate.get("design_summary"):
            continue
        if exp.get("capability_id") != candidate.get("capability_id"):
            continue
        if candidate.get("changed_variable") or candidate.get("failure_analysis"):
            return False
        return True
    return False


def portfolio_plan(paths: VibePaths, candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if candidates is None:
        candidates = default_candidates(paths)
    evaluations = [evaluate_candidate(paths, row) for row in candidates]
    plan = {
        "created_at": utc_now(),
        "selected": [row for row in evaluations if row["status"] == "selected"],
        "blocked": [row for row in evaluations if row["status"] == "blocked"],
        "running": [],
        "completed": [],
        "budget_status": budget_status(paths),
        "adapter_capabilities": sorted(active_capability_ids(paths)),
    }
    write_json(research_paths(paths)["portfolio"], plan)
    write_json(paths.dashboard / "portfolio_state.json", plan)
    append_research_event(paths, "portfolio_planned", {"selected": len(plan["selected"]), "blocked": len(plan["blocked"])})
    return plan


def default_candidates(paths: VibePaths) -> list[dict[str, Any]]:
    hypotheses = [row for row in load_hypotheses(paths).values() if row.get("status") in {"active", "needs_analysis"}]
    manifest = load_adapter_manifest(paths)
    caps = sorted(
        [
            cap
            for cap in manifest.capabilities
            if cap.status == "active" and select_executable_decision_for_capability(cap)
        ],
        key=lambda cap: (int(cap.resources.default.get("gpu", 0) or 0), cap.id),
    )
    if not hypotheses or not caps:
        return []
    config = load_config(paths)
    portfolio_cfg = config.get("portfolio", {}) if isinstance(config.get("portfolio"), dict) else {}
    research_cfg = config.get("research", {}) if isinstance(config.get("research"), dict) else {}
    max_candidates = int(research_cfg.get("portfolio_candidate_count", portfolio_cfg.get("max_runs_per_cycle", 6)) or 6)
    candidates: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        for capability in caps:
            decision_type = select_executable_decision_for_capability(capability)
            if not decision_type:
                continue
            base_change = hypothesis.get("next_testable_change") or hypothesis.get("title", "next bounded experiment")
            candidates.append(
                {
                    "hypothesis_id": hypothesis["hypothesis_id"],
                    "design_summary": f"{base_change} via {capability.id}",
                    "stage": hypothesis.get("current_stage", "smoke"),
                    "capability_id": capability.id,
                    "decision_type": decision_type,
                    "expected_evidence": {"kind": "schema_valid_metrics"},
                    "resource_units": {"gpu_hours": 0.0, "cpu_hours": 0.1},
                    "changed_variable": capability.id,
                    "rationale": "default diversified bounded candidate across active hypotheses and capabilities",
                }
            )
            if len(candidates) >= max_candidates:
                return candidates
    return candidates


def portfolio_schedule(paths: VibePaths) -> dict[str, Any]:
    plan = read_json(research_paths(paths)["portfolio"], {}) or portfolio_plan(paths)
    scheduled = []
    blocked = list(plan.get("blocked", []))
    for row in plan.get("selected", []):
        candidate = row["candidate"]
        experiment = create_experiment(
            paths,
            candidate["hypothesis_id"],
            candidate["design_summary"],
            stage=candidate.get("stage", "smoke"),
            capability_id=candidate.get("capability_id", ""),
            decision_id=candidate.get("decision_id", ""),
            resource_plan={"resource_units": candidate.get("resource_units", {})},
            expected_evidence=candidate.get("expected_evidence", {}),
            success_criteria=candidate.get("success_criteria", {}),
            failure_criteria=candidate.get("failure_criteria", {}),
            baseline_target=candidate.get("baseline_target", ""),
            protected_metric_constraints=candidate.get("protected_metric_constraints", {}),
        )
        reservation = reserve_budget(
            paths,
            decision_id=candidate.get("decision_id", ""),
            experiment_id=experiment["experiment_id"],
            hypothesis_id=candidate.get("hypothesis_id", ""),
            resource_units=candidate.get("resource_units", {}),
            estimated_cost=candidate.get("estimated_cost", {}),
            requires_long_run=bool(candidate.get("requires_long_run")),
            confirmed=bool(candidate.get("confirmed")),
        )
        if reservation.get("status") == "blocked":
            experiments = load_experiments(paths)
            experiments[experiment["experiment_id"]]["status"] = "blocked"
            experiments[experiment["experiment_id"]]["updated_at"] = utc_now()
            save_experiments(paths, experiments)
            blocked.append({"candidate": candidate, "status": "blocked", "blocked_reasons": reservation.get("blocked_reasons", [])})
            continue
        experiments = load_experiments(paths)
        experiments[experiment["experiment_id"]]["resource_plan"]["budget_reservation_id"] = reservation["budget_event_id"]
        experiments[experiment["experiment_id"]]["resource_plan_id"] = reservation["budget_event_id"]
        experiments[experiment["experiment_id"]]["updated_at"] = utc_now()
        save_experiments(paths, experiments)
        scheduled.append({"experiment_id": experiment["experiment_id"], "budget_reservation_id": reservation["budget_event_id"], "candidate": candidate, "reason_for_scheduling": row.get("selection_reason", "")})
    state = {"created_at": utc_now(), "scheduled": scheduled, "blocked": blocked, "running": [], "completed": []}
    write_json(paths.dashboard / "portfolio_state.json", state)
    append_research_event(paths, "portfolio_scheduled", {"scheduled": len(scheduled), "blocked": len(blocked)})
    return state


def portfolio_audit(paths: VibePaths) -> dict[str, Any]:
    plan = read_json(research_paths(paths)["portfolio"], {})
    issues = []
    for row in plan.get("selected", []):
        candidate = row.get("candidate", {})
        if candidate.get("capability_id") not in active_capability_ids(paths):
            issues.append(f"{candidate.get('design_summary', '')}: selected candidate no longer has active capability")
    result = {"ok": not issues, "issues": issues, "duplicate_risk_warnings": duplicate_risk_warnings(paths)}
    write_json(paths.research / "portfolio_audit.json", result)
    return result


def policy_lint(paths: VibePaths) -> dict[str, Any]:
    issues = []
    for name in ["budget", "stage_gates", "autonomy"]:
        path = paths.vibe / "policies" / f"{name}.yaml"
        data = read_yaml(path, {})
        if not data:
            issues.append(f"missing or empty {path.relative_to(paths.vibe)}")
        if data and not data.get("version"):
            issues.append(f"{name}: missing version")
    autonomy = read_yaml(paths.vibe / "policies" / "autonomy.yaml", {}) or {}
    if autonomy.get("level") not in AUTONOMY_LEVELS:
        issues.append("autonomy.level is unsupported")
    result = {"ok": not issues, "issues": issues}
    write_json(paths.vibe / "policies" / "lint.json", result)
    return result


def render_daily_memo(paths: VibePaths, *, date: str | None = None, language: str | None = None) -> dict[str, Any]:
    ensure_dir(paths.vibe / "memos")
    date = date or datetime.now().date().isoformat()
    config = read_yaml(paths.research / "memo_config.yaml", {}) or {}
    language = language or config.get("language", "zh-CN")
    hypotheses = load_hypotheses(paths)
    experiments = load_experiments(paths)
    evidence = load_evidence(paths)
    ledger = read_jsonl(research_paths(paths)["budget"])
    decisions = read_jsonl(research_paths(paths)["decisions"])
    today_evidence = [row for row in evidence.values() if str(row.get("created_at", "")).startswith(date)]
    trusted = [row for row in today_evidence if row.get("trusted") and row.get("schema_valid")]
    untrusted = [row for row in today_evidence if row not in trusted]
    today_budget = [row for row in ledger if str(row.get("reservation_time", "")).startswith(date) or str(row.get("reconciliation_time", "")).startswith(date)]
    data = {
        "date": date,
        "language": language,
        "bootstrap": bootstrap_memo_state(paths, date),
        "hypothesis_changes": [row for row in read_jsonl(research_paths(paths)["events"]) if str(row.get("created_at", "")).startswith(date) and "hypothesis" in row.get("event_type", "")],
        "experiments": [row for row in experiments.values() if str(row.get("created_at", "")).startswith(date) or str(row.get("updated_at", "")).startswith(date)],
        "trusted_evidence": trusted,
        "untrusted_evidence": untrusted,
        "budget_events": today_budget,
        "decisions": [row for row in decisions if str(row.get("created_at", "")).startswith(date)],
        "blockers": research_readiness(paths).get("open_questions", []) + audit_registry(paths).get("duplicate_risk_warnings", []),
        "next_actions": suggested_next_actions(paths),
        "active_hypothesis_count": len([row for row in hypotheses.values() if row.get("status") in {"active", "needs_analysis"}]),
    }
    text = render_memo_markdown(data, zh=language.startswith("zh"))
    write_json(paths.vibe / "memos" / f"{date}.json", data)
    write_text(paths.vibe / "memos" / f"{date}.md", text)
    append_research_event(paths, "daily_memo_written", {"date": date, "language": language, "trusted_evidence": len(trusted)})
    return {"path": str(paths.vibe / "memos" / f"{date}.md"), "json_path": str(paths.vibe / "memos" / f"{date}.json"), "data": data}


def render_memo_markdown(data: dict[str, Any], *, zh: bool) -> str:
    bootstrap = data.get("bootstrap", {})
    if zh:
        onboarding = "今日主要完成初始化/接入工作，尚未产生可信科学 evidence。" if bootstrap.get("phase_records") and not data["trusted_evidence"] else ""
        no_progress = "今天没有可信科学进展；完成的工程动作不能等同于假设被支持。" if not data["trusted_evidence"] else ""
        lines = [f"# 每日研究日志 {data['date']}", "", no_progress, "", "## 今天做了什么"]
        if onboarding:
            lines.append(f"- {onboarding}")
        if bootstrap.get("phase_records"):
            lines.append(f"- bootstrap readiness：{bootstrap.get('readiness_level', 'unknown')}")
            lines.extend(f"- bootstrap phase `{row.get('phase')}`: `{row.get('status')}`" for row in bootstrap.get("phase_records", [])[-8:])
        lines.append(f"- 活跃 hypothesis 数量：{data['active_hypothesis_count']}")
        lines.append(f"- 今日相关实验：{len(data['experiments'])}")
        lines.extend(["", "## 可信 evidence"])
        lines.extend([f"- `{row['evidence_id']}` {row.get('summary', '')}" for row in data["trusted_evidence"]] or ["- 无可信 evidence"])
        lines.extend(["", "## 不可信或 schema-invalid evidence"])
        lines.extend([f"- `{row['evidence_id']}` {row.get('failure_kind', '')}: {row.get('summary', '')}" for row in data["untrusted_evidence"]] or ["- 无"])
        lines.extend(["", "## 预算"])
        lines.append(f"- 今日预算事件：{len(data['budget_events'])}")
        lines.extend(["", "## 决策、阻塞与下一步"])
        lines.append(f"- 今日决策：{len(data['decisions'])}")
        lines.extend([f"- blocker: {row}" for row in data["blockers"]] or ["- blocker: 无"])
        lines.extend([f"- 下一步：{item}" for item in data["next_actions"]] or ["- 下一步：构建 memory pack 或创建 hypothesis"])
        return "\n".join(line for line in lines if line is not None) + "\n"
    onboarding = "Today mainly produced onboarding or engineering progress; no trusted scientific evidence was produced." if bootstrap.get("phase_records") and not data["trusted_evidence"] else ""
    no_progress = "No trusted scientific progress was recorded today; completed jobs are not counted as hypothesis support." if not data["trusted_evidence"] else ""
    lines = [f"# Daily Research Memo {data['date']}", "", no_progress, "", "## Work Summary"]
    if onboarding:
        lines.append(f"- {onboarding}")
    if bootstrap.get("phase_records"):
        lines.append(f"- bootstrap readiness: {bootstrap.get('readiness_level', 'unknown')}")
        lines.extend(f"- bootstrap phase `{row.get('phase')}`: `{row.get('status')}`" for row in bootstrap.get("phase_records", [])[-8:])
    lines.append(f"- Active hypotheses: {data['active_hypothesis_count']}")
    lines.append(f"- Experiments touched today: {len(data['experiments'])}")
    lines.extend(["", "## Trusted Evidence"])
    lines.extend([f"- `{row['evidence_id']}` {row.get('summary', '')}" for row in data["trusted_evidence"]] or ["- No trusted evidence"])
    lines.extend(["", "## Untrusted Or Schema-Invalid Evidence"])
    lines.extend([f"- `{row['evidence_id']}` {row.get('failure_kind', '')}: {row.get('summary', '')}" for row in data["untrusted_evidence"]] or ["- None"])
    lines.extend(["", "## Budget"])
    lines.append(f"- Budget events today: {len(data['budget_events'])}")
    lines.extend(["", "## Decisions, Blockers, Next Actions"])
    lines.append(f"- Decisions today: {len(data['decisions'])}")
    lines.extend([f"- blocker: {row}" for row in data["blockers"]] or ["- blocker: none"])
    lines.extend([f"- next: {item}" for item in data["next_actions"]] or ["- next: build memory pack or create a hypothesis"])
    return "\n".join(line for line in lines if line is not None) + "\n"


def bootstrap_memo_state(paths: VibePaths, date: str) -> dict[str, Any]:
    state = read_json(paths.vibe / "bootstrap" / "state.json", {})
    if not state:
        return {}
    records = [row for row in state.get("phase_records", []) if str(row.get("finished_at", "")).startswith(date)]
    if not records and state.get("phase_records"):
        records = state.get("phase_records", [])[-8:]
    readiness = read_json(paths.vibe / "bootstrap" / "readiness.json", {})
    return {
        "session_id": state.get("session_id", ""),
        "readiness_level": readiness.get("readiness_level", state.get("readiness_level", "")),
        "phase_records": records,
        "generated_artifacts": state.get("generated_artifacts", []),
        "active_capabilities": readiness.get("active_capabilities", []),
        "blocked_capabilities": readiness.get("blocked_capabilities", []),
        "contract_test_summary": state.get("contract_test_summary", {}),
        "next_actions": readiness.get("next_actions", []),
    }


def suggested_next_actions(paths: VibePaths) -> list[str]:
    if not load_hypotheses(paths):
        return ["vibe hypothesis create"]
    if not (paths.research / "memory_pack.json").exists():
        return ["vibe memory build"]
    audit = audit_registry(paths)
    if audit.get("duplicate_risk_warnings"):
        return ["write failure analysis before repeating blocked designs"]
    return ["vibe portfolio plan"]


def export_research_dashboard(paths: VibePaths) -> dict[str, Any]:
    registry = {
        "hypotheses": load_hypotheses(paths),
        "experiments": load_experiments(paths),
        "evidence": load_evidence(paths),
        "decisions": read_jsonl(research_paths(paths)["decisions"]),
        "budget_ledger": read_jsonl(research_paths(paths)["budget"]),
        "policies": {
            "budget": read_yaml(paths.vibe / "policies" / "budget.yaml", {}),
            "stage_gates": read_yaml(paths.vibe / "policies" / "stage_gates.yaml", {}),
            "autonomy": read_yaml(paths.vibe / "policies" / "autonomy.yaml", {}),
        },
    }
    graph = research_graph(registry)
    portfolio = read_json(paths.dashboard / "portfolio_state.json", {}) or read_json(research_paths(paths)["portfolio"], {})
    write_json(paths.dashboard / "research_registry.json", registry)
    write_json(paths.dashboard / "hypothesis_graph.json", graph)
    write_json(paths.dashboard / "portfolio_state.json", portfolio)
    write_json(paths.dashboard / "budget_ledger.json", registry["budget_ledger"])
    return {"registry": str(paths.dashboard / "research_registry.json"), "graph": str(paths.dashboard / "hypothesis_graph.json"), "portfolio": str(paths.dashboard / "portfolio_state.json"), "budget": str(paths.dashboard / "budget_ledger.json"), "graph_counts": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])}}


def research_graph(registry: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    edges = []
    for hid, hyp in registry["hypotheses"].items():
        nodes.append({"id": hid, "type": "hypothesis", "status": hyp.get("status"), "title": hyp.get("title", "")})
    for exp_id, exp in registry["experiments"].items():
        nodes.append({"id": exp_id, "type": "experiment", "status": exp.get("status"), "title": exp.get("design_summary", "")})
        edges.append({"source": exp.get("hypothesis_id", ""), "target": exp_id, "type": "hypothesis_to_experiment"})
        for run_id in exp.get("run_ids", []) or exp.get("linked_run_ids", []):
            nodes.append({"id": run_id, "type": "run", "status": ""})
            edges.append({"source": exp_id, "target": run_id, "type": "experiment_to_run"})
    for ev_id, ev in registry["evidence"].items():
        nodes.append({"id": ev_id, "type": "evidence", "trusted": ev.get("trusted"), "schema_valid": ev.get("schema_valid")})
        if ev.get("run_id"):
            edges.append({"source": ev.get("run_id"), "target": ev_id, "type": "run_to_evidence"})
        else:
            edges.append({"source": ev.get("experiment_id"), "target": ev_id, "type": "experiment_to_evidence"})
    for decision in registry["decisions"]:
        did = decision.get("decision_id", "")
        nodes.append({"id": did, "type": "decision", "outcome": decision.get("final_outcome")})
        if decision.get("experiment_id"):
            edges.append({"source": decision["experiment_id"], "target": did, "type": "experiment_to_decision"})
        elif decision.get("hypothesis_id"):
            edges.append({"source": decision["hypothesis_id"], "target": did, "type": "hypothesis_to_decision"})
    return {"nodes": dedupe_nodes(nodes), "edges": [edge for edge in edges if edge.get("source") and edge.get("target")]}


def dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {}
    for node in nodes:
        seen.setdefault(node["id"], node)
    return list(seen.values())


def collect_run_evidence_if_research_linked(paths: VibePaths, run_id: str, metrics: dict[str, Any]) -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id, {})
    metadata = run.get("research_metadata", {}) if isinstance(run.get("research_metadata"), dict) else {}
    experiment_id = metadata.get("experiment_id", "")
    if not experiment_id:
        return
    if experiment_id not in load_experiments(paths):
        record = {
            "created_at": utc_now(),
            "run_id": run_id,
            "experiment_id": experiment_id,
            "reason": "unknown_experiment",
            "action": "skipped_research_manager_evidence_link",
            "mechanism_card_id": metadata.get("mechanism_card_id", ""),
            "metrics_file": metrics.get("metrics_file_path", ""),
        }
        append_jsonl(paths.research / "evidence_link_skipped.jsonl", record)
        record_event(
            paths,
            "research_evidence_link_skipped",
            f"{run_id}: unknown experiment {experiment_id}",
            cycle_id=run.get("cycle_id", ""),
            run_id=run_id,
            status="skipped_unknown_experiment",
            payload=record,
        )
        return
    add_evidence(
        paths,
        experiment_id,
        run_id=run_id,
        trusted=bool(metrics.get("trusted")),
        schema_valid=metrics.get("schema_status") == "valid",
        metrics_schema_version=run.get("adapter_metadata", {}).get("metrics_schema_version", ""),
        metrics_file=metrics.get("metrics_file_path", ""),
        summary=f"Collected run {run_id}: trust={metrics.get('trust_status')}, schema={metrics.get('schema_status')}",
        metric_deltas={"primary": metrics.get("primary_metric", 0)},
        failure_kind="none" if metrics.get("trusted") and metrics.get("schema_status") == "valid" else ("schema" if metrics.get("schema_status") != "valid" else "engineering"),
    )
