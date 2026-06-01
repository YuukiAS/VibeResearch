"""Project initialization and shared state operations."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import re
import sys
from typing import Any

from .adapter_onboarding import adapter_readiness, bootstrap_adapter_on_init, clear_adapter_block_if_ready, set_adapter_block, write_real_experiment_gap_report
from .dashboard import sync_dashboard
from .config import command_probe, load_config, parse_gpu_names, parse_sinfo_partitions, write_config_schema
from .decisions import write_block_decision
from .ideas import create_idea as create_pool_idea
from .ideas import ensure_idea_pool
from .ideas import render_idea_views
from .io import append_jsonl, ensure_dir, next_numeric_id, read_json, read_jsonl, read_yaml, slugify, utc_now, write_json, write_text, write_yaml
from .kernel import initialize_kernel
from .models import IdeaRecord, ProjectConfig, RunManifest, default_budget, default_state
from .papers import connect
from .paths import VibePaths
from .portal import build_portal, install_agents_snippet, write_agents_files, write_portal_text
from .promotion import ensure_executable_resource_plan, select_executable_decision_for_capability, validate_resource_plan
from .research_manager import research_init
from .resource_policy import normalize_run_resources
from .timeline import record_event


DIRS = [
    "inbox",
    "state",
    "project",
    "ideas",
    "cycles",
    "runs",
    "directions",
    "branches",
    "leaderboard/snapshots",
    "scheduler",
    "executor/templates",
    "kernel",
    "resources",
    "research/deep_requests",
    "policies",
    "memos",
    "research/raw/papers_pdf",
    "research/raw/papers_md",
    "research/raw/deep_reports",
    "research/raw/repos",
    "research/raw/weights",
    "research/raw/notes",
    "research/raw/assets",
    "research/wiki/papers",
    "research/wiki/concepts",
    "research/wiki/entities",
    "research/wiki/comparisons",
    "research/wiki/gaps",
    "research/wiki/synthesis",
    "dashboard",
    "site",
    "portal",
    "reports/dev",
    "prompts",
]

RECOVERABLE_RESOURCE_BLOCKS = {
    "blocked_missing_resource_plan",
    "blocked_missing_capability",
    "blocked_missing_script",
    "blocked_missing_metrics_schema",
    "blocked_contract_test_failed",
    "blocked_resource_policy",
}

_RESOURCE_PROBE_CACHE: dict[str, dict[str, Any]] = {}


def init_project(
    target: str | Path = ".",
    *,
    project_name: str | None = None,
    force: bool = False,
    minimal: bool = False,
    root_portal: str = "copy",
    install_agents: bool = False,
    goal: str = "",
    background: str = "",
    brief_file: str | Path | None = None,
    initial_ideas: list[str] | None = None,
    idea_file: str | Path | None = None,
    preferred_partitions: list[str] | None = None,
    fallback_partitions: list[str] | None = None,
    partition_gres: dict[str, str] | None = None,
    max_pending_start_plus_run_hours: float | None = None,
    max_run_hours_per_experiment: float | None = None,
    mature_max_run_hours_per_experiment: float | None = None,
    delivery_max_run_hours_per_experiment: float | None = None,
    max_epochs_per_experiment: int | None = None,
    delivery_max_epochs_per_experiment: int | None = None,
) -> VibePaths:
    paths = VibePaths(target)
    ensure_dir(paths.root)
    if paths.vibe.exists() and not force:
        paths.require_initialized()
    for rel in DIRS:
        ensure_dir(paths.vibe / rel)

    project_brief = load_project_brief(paths, goal=goal, background=background, brief_file=brief_file, minimal=minimal)
    config = ProjectConfig(project_name=project_name or paths.root.name)
    config_data = config.model_dump()
    config_data["project_name"] = project_name or paths.root.name
    config_data["project"] = {
        "name": project_name or paths.root.name,
        "goal": project_brief["goal"],
        "background": project_brief["background"],
        "brief_path": ".vibe/project/brief.md",
        "brief_missing": project_brief["missing"],
    }
    apply_init_resource_policy(
        config_data,
        preferred_partitions=preferred_partitions or [],
        fallback_partitions=fallback_partitions or [],
        partition_gres=partition_gres or {},
        max_pending_start_plus_run_hours=max_pending_start_plus_run_hours,
        max_run_hours_per_experiment=max_run_hours_per_experiment,
        mature_max_run_hours_per_experiment=mature_max_run_hours_per_experiment,
        delivery_max_run_hours_per_experiment=delivery_max_run_hours_per_experiment,
        max_epochs_per_experiment=max_epochs_per_experiment,
        delivery_max_epochs_per_experiment=delivery_max_epochs_per_experiment,
    )
    config_data.setdefault("portal", {})["root_mode"] = root_portal
    config_data.setdefault("execution", {}).setdefault("python", {})["executable"] = sys.executable
    write_yaml(paths.vibe / "config.yaml", config_data)
    write_json(paths.vibe / "config.json", config_data)
    write_yaml(paths.vibe / "config.local.yaml", {"local": {"notes": "local-only overrides; not auto-merged into config.yaml"}})
    write_text(
        paths.vibe / ".gitignore",
        "# Local config overrides\n"
        "config.local.yaml\n"
        "config.detected.yaml\n\n"
        "# Local runtime environments\n"
        "runtime/env\n\n"
        "# Adapter contract-test scratch output\n"
        "bootstrap_metrics/\n"
        "run_contracts/\n",
    )
    write_config_schema(paths)
    resource_init = initialize_resource_environment(paths, config_data)

    state = default_state()
    state["updated_at"] = utc_now()
    state["next_action"] = "vibe plan-cycle"
    state["project_brief_missing"] = project_brief["missing"]
    if project_brief["missing"]:
        state["next_action"] = "add project goal/background with vibe init --goal ... --background ..."
    write_json(paths.state / "state.json", state)
    write_json(paths.state / "lock.json", {"locked": False, "updated_at": utc_now()})
    write_text(paths.state / "memory.md", "# Vibe Memory\n\n")
    touch_jsonl(paths.state / "decisions.jsonl")
    touch_jsonl(paths.state / "open_questions.jsonl")
    initialize_kernel(paths, project_goal=project_brief["goal"])

    write_text(paths.inbox / "ideas.md", "## New Ideas Inbox\n\n- [ ] idea:\n")
    write_text(paths.inbox / "user_prompts.md", "# User Prompts\n\n")
    write_text(paths.inbox / "questions.md", "# Questions\n\n")
    touch_jsonl(paths.inbox / "triage.jsonl")
    ensure_idea_pool(paths)
    render_idea_views(paths)
    write_project_brief(paths, project_brief)
    for text in collect_initial_ideas(initial_ideas or [], idea_file):
        add_idea(paths, text, source="init")

    touch_jsonl(paths.directions / "registry.jsonl")
    write_json(paths.branches / "active.json", {})
    touch_jsonl(paths.branches / "merged.jsonl")
    touch_jsonl(paths.branches / "abandoned.jsonl")

    write_yaml(paths.leaderboard / "goals.yaml", default_goals(paths.root.name))
    write_yaml(paths.leaderboard / "metrics_schema.yaml", default_metric_schema())
    write_json(paths.leaderboard / "best.json", {})
    write_json(paths.leaderboard / "best_by_direction.json", {})
    touch_jsonl(paths.leaderboard / "history.jsonl")

    write_json(paths.scheduler / "queue.json", {"queued": []})
    budget = default_budget()
    scheduler_config = config_data.get("scheduler", {})
    for key in [
        "max_parallel_jobs",
        "max_parallel_gpu_jobs",
        "max_total_gpus",
        "max_walltime_hours_per_cycle",
        "max_run_hours_per_experiment",
        "mature_max_run_hours_per_experiment",
        "delivery_max_run_hours_per_experiment",
        "max_epochs_per_experiment",
        "mature_max_epochs_per_experiment",
        "delivery_max_epochs_per_experiment",
        "max_failed_runs_before_pause",
        "prequeue_when_capacity_full",
        "max_prequeued_runs_when_full",
        "allow_strict_preferred_partition",
    ]:
        if key in scheduler_config:
            budget[key] = scheduler_config[key]
    budget["fallback_partitions"] = config_data.get("execution", {}).get("slurm", {}).get("fallback_partitions", budget.get("fallback_partitions", []))
    write_yaml(paths.scheduler / "budget.yaml", budget)
    write_json(paths.scheduler / "active_jobs.json", {"active": []})
    touch_jsonl(paths.scheduler / "completed_jobs.jsonl")

    write_text(paths.research / "sources.jsonl", "")
    connect(paths).close()
    write_text(paths.research / "wiki" / "index.md", "# Research Wiki\n\n")
    write_text(paths.research / "wiki" / "log.md", "# Research Wiki Log\n\n")
    write_text(paths.research / "wiki" / "overview.md", "# Research Overview\n\n")
    write_text(paths.research / "deep_requests" / "registry.jsonl", "")

    write_default_templates(paths)
    write_default_prompts(paths)
    write_run_md(paths)
    write_agents_files(paths, config_data["project_name"])
    bootstrap_adapter_on_init(paths, minimal=minimal)
    research_init(
        paths,
        goal=project_brief["goal"],
        background=project_brief["background"],
        memo_language=config_data.get("research", {}).get("memo_language", "zh-CN"),
        autonomy_level=config_data.get("research", {}).get("autonomy_level", "analysis_only"),
    )
    record_event(paths, "initialized", "Initialized VibeResearch control layer", status="ok")
    record_event(paths, "resource_policy_initialized", "Initialized GPU/Slurm resource onboarding", status=resource_init["status"], payload=resource_init)
    sync_dashboard(paths)
    if root_portal != "none":
        build_portal(paths, mode=root_portal, force=force)
    if install_agents:
        install_agents_snippet(paths)
    return paths


def apply_init_resource_policy(
    config_data: dict[str, Any],
    *,
    preferred_partitions: list[str],
    fallback_partitions: list[str],
    partition_gres: dict[str, str],
    max_pending_start_plus_run_hours: float | None,
    max_run_hours_per_experiment: float | None,
    mature_max_run_hours_per_experiment: float | None,
    delivery_max_run_hours_per_experiment: float | None,
    max_epochs_per_experiment: int | None,
    delivery_max_epochs_per_experiment: int | None,
) -> None:
    execution_slurm = config_data.setdefault("execution", {}).setdefault("slurm", {})
    root_slurm = config_data.setdefault("slurm", {})
    scheduler = config_data.setdefault("scheduler", {})
    if preferred_partitions:
        execution_slurm["default_partition"] = preferred_partitions[0]
        execution_slurm["preferred_partitions"] = preferred_partitions
        root_slurm["default_partition"] = preferred_partitions[0]
        root_slurm["preferred_partitions"] = preferred_partitions
    if fallback_partitions:
        execution_slurm["fallback_partitions"] = fallback_partitions
        root_slurm["fallback_partitions"] = fallback_partitions
    if partition_gres:
        execution_slurm["gres_by_partition"] = dict(partition_gres)
        root_slurm["gres_by_partition"] = dict(partition_gres)
        profiles = [row for row in execution_slurm.get("partitions", []) if isinstance(row, dict)]
        by_name = {row.get("name"): row for row in profiles if row.get("name")}
        for name, gres in partition_gres.items():
            row = by_name.get(name)
            if row is None:
                row = {"name": name}
                profiles.append(row)
                by_name[name] = row
            row["gres"] = gres
        execution_slurm["partitions"] = profiles
    if max_pending_start_plus_run_hours is not None:
        execution_slurm["max_pending_start_plus_run_hours"] = max_pending_start_plus_run_hours
        root_slurm["max_pending_start_plus_run_hours"] = max_pending_start_plus_run_hours
    if max_run_hours_per_experiment is not None:
        scheduler["max_run_hours_per_experiment"] = max_run_hours_per_experiment
    if mature_max_run_hours_per_experiment is not None:
        scheduler["mature_max_run_hours_per_experiment"] = mature_max_run_hours_per_experiment
    if delivery_max_run_hours_per_experiment is not None:
        scheduler["delivery_max_run_hours_per_experiment"] = delivery_max_run_hours_per_experiment
    if max_epochs_per_experiment is not None:
        scheduler["max_epochs_per_experiment"] = max_epochs_per_experiment
    if delivery_max_epochs_per_experiment is not None:
        scheduler["delivery_max_epochs_per_experiment"] = delivery_max_epochs_per_experiment


def initialize_resource_environment(paths: VibePaths, config_data: dict[str, Any]) -> dict[str, Any]:
    """Create default resource discovery and confirmation files for every init."""

    probes = resource_probe(paths)
    sinfo = probes["sinfo"]
    nvidia = probes["nvidia-smi"]
    partitions = parse_sinfo_partitions(str(sinfo.get("stdout", ""))) if sinfo.get("ok") else []
    gpu_models = parse_gpu_names(str(nvidia.get("stdout", ""))) if nvidia.get("ok") else []
    gres_by_partition = {row["name"]: row["gres"] for row in partitions if row.get("gres")}
    detected = {
        "detected_at": utc_now(),
        "commands": {
            "sinfo": sinfo,
            "nvidia-smi": nvidia,
        },
        "slurm": {
            "available": bool(sinfo.get("available")),
            "probe_ok": bool(sinfo.get("ok")),
            "partitions": partitions,
            "suggested_gres_by_partition": gres_by_partition,
        },
        "gpu": {
            "available": bool(nvidia.get("available")),
            "probe_ok": bool(nvidia.get("ok")),
            "count": len(gpu_models),
            "models": gpu_models,
        },
    }
    write_yaml(paths.vibe / "config.detected.yaml", {"resource_detection": detected, "suggested_config": {"execution": {"slurm": {"partitions": partitions, "gres_by_partition": gres_by_partition}}}})
    write_yaml(paths.vibe / "resources" / "detected.yaml", detected)
    questions = resource_policy_questions(config_data, detected)
    status = "configured_needs_confirmation" if resource_policy_has_gpu_config(config_data) else "needs_resource_answers"
    payload = {
        "status": status,
        "created_at": utc_now(),
        "principles": [
            "GPU/Slurm policy is initialized for every project.",
            "Partition names do not imply GPU model or GRES.",
            "Automatic GPU/Slurm submission remains disabled until policy and adapter readiness allow it.",
        ],
        "configured": {
            "execution_slurm": config_data.get("execution", {}).get("slurm", {}),
            "scheduler": config_data.get("scheduler", {}),
        },
        "detected": detected,
        "questions": questions,
    }
    write_yaml(paths.vibe / "resources" / "policy_questions.yaml", payload)
    write_text(paths.vibe / "resources" / "README.md", render_resource_readme(payload))
    return payload


def resource_probe(paths: VibePaths) -> dict[str, Any]:
    cache_key = os.environ.get("PATH", "")
    cached = _RESOURCE_PROBE_CACHE.get(cache_key)
    if cached is not None:
        return deepcopy(cached)
    probes = {
        "sinfo": command_probe("sinfo", ["-h", "-o", "%P %G"], cwd=paths.root, timeout=3),
        "nvidia-smi": command_probe("nvidia-smi", ["--query-gpu=name", "--format=csv,noheader"], cwd=paths.root, timeout=3),
    }
    _RESOURCE_PROBE_CACHE[cache_key] = deepcopy(probes)
    return probes


def resource_policy_has_gpu_config(config_data: dict[str, Any]) -> bool:
    slurm = config_data.get("execution", {}).get("slurm", {}) if isinstance(config_data.get("execution"), dict) else {}
    return bool(slurm.get("preferred_partitions") or slurm.get("fallback_partitions") or slurm.get("gres_by_partition") or slurm.get("partitions"))


def resource_policy_questions(config_data: dict[str, Any], detected: dict[str, Any]) -> list[dict[str, Any]]:
    slurm = config_data.get("execution", {}).get("slurm", {}) if isinstance(config_data.get("execution"), dict) else {}
    scheduler = config_data.get("scheduler", {}) if isinstance(config_data.get("scheduler"), dict) else {}
    suggested_partitions = [row.get("name", "") for row in detected.get("slurm", {}).get("partitions", []) if row.get("name")]
    return [
        {
            "id": "q_resource_mode",
            "question": "Will this project use GPU/Slurm execution, local CPU execution, or both?",
            "default": "gpu_slurm_if_available",
            "current_answer": "",
            "blocks": ["automatic_gpu_submission", "slurm_resource_plan_selection"],
        },
        {
            "id": "q_slurm_partitions",
            "question": "Which Slurm partitions should be preferred and which should be fallback?",
            "detected_candidates": suggested_partitions,
            "configured_preferred": slurm.get("preferred_partitions", []),
            "configured_fallback": slurm.get("fallback_partitions", []),
            "current_answer": "",
            "blocks": ["partition_selection", "fallback_requeue_policy"],
        },
        {
            "id": "q_slurm_gres",
            "question": "What exact GRES template should be used for each GPU partition?",
            "detected_suggestions": detected.get("slurm", {}).get("suggested_gres_by_partition", {}),
            "configured_gres_by_partition": slurm.get("gres_by_partition", {}),
            "example_format": "partition-name=gpu:gpu_type:{gpu}",
            "current_answer": "",
            "blocks": ["gpu_sbatch_rendering"],
        },
        {
            "id": "q_slurm_wait_limit",
            "question": "How long may a queued job wait, including requested runtime, before preferring fallback?",
            "configured_hours": slurm.get("max_pending_start_plus_run_hours", 24),
            "examples": [12, 24],
            "current_answer": "",
            "blocks": ["fallback_partition_policy"],
        },
        {
            "id": "q_experiment_runtime_caps",
            "question": "What walltime and epoch caps should exploratory/ordinary experiments obey?",
            "configured_max_run_hours": scheduler.get("max_run_hours_per_experiment", 12),
            "configured_max_epochs": scheduler.get("max_epochs_per_experiment", 200),
            "current_answer": "",
            "blocks": ["run_resource_normalization"],
        },
        {
            "id": "q_delivery_runtime_caps",
            "question": "What larger walltime and epoch caps are allowed only for final delivery/submission-stage runs?",
            "configured_delivery_max_run_hours": scheduler.get("delivery_max_run_hours_per_experiment", 72),
            "configured_delivery_max_epochs": scheduler.get("delivery_max_epochs_per_experiment", 5000),
            "only_applies_when_maturity_is_one_of": ["delivery", "submission", "submit", "final", "final_delivery", "production_delivery"],
            "current_answer": "",
            "blocks": ["final_delivery_resource_policy"],
        },
        {
            "id": "q_gpu_submission_permission",
            "question": "May VibeResearch submit GPU/Slurm jobs automatically after adapter and contract gates pass?",
            "default": "no",
            "current_answer": "",
            "blocks": ["automatic_submission_allowed"],
        },
    ]


def render_resource_readme(payload: dict[str, Any]) -> str:
    detected = payload.get("detected", {})
    slurm = detected.get("slurm", {})
    gpu = detected.get("gpu", {})
    lines = [
        "# Resource Initialization",
        "",
        "VibeResearch initializes GPU/Slurm resource policy for every project, even when the final answer is CPU-only.",
        "",
        f"- Status: `{payload.get('status', '')}`",
        f"- Slurm detected: `{slurm.get('available', False)}`; probe ok: `{slurm.get('probe_ok', False)}`",
        f"- GPU detected: `{gpu.get('available', False)}`; probe ok: `{gpu.get('probe_ok', False)}`; count: `{gpu.get('count', 0)}`",
        "",
        "Partition names are examples, not hardware truth. Confirm exact GRES templates from the target cluster before enabling GPU submission.",
        "",
        "## Questions",
    ]
    for question in payload.get("questions", []):
        lines.append(f"- `{question.get('id')}`: {question.get('question')}")
    lines.append("")
    return "\n".join(lines)


def touch_jsonl(path: Path) -> None:
    ensure_dir(path.parent)
    if not path.exists():
        path.write_text("")


def load_project_brief(
    paths: VibePaths,
    *,
    goal: str = "",
    background: str = "",
    brief_file: str | Path | None = None,
    minimal: bool = False,
) -> dict[str, Any]:
    if brief_file:
        source = Path(brief_file).expanduser()
        text = source.read_text()
        parsed_goal = first_nonempty_after(text, ["# Goal", "## Goal", "Goal:"]) or goal
        parsed_background = first_nonempty_after(text, ["# Background", "## Background", "Background:"]) or background or text[:2000]
        return {"goal": parsed_goal, "background": parsed_background, "body": text, "missing": False}
    missing = minimal and not (goal or background)
    if not goal and not background and not minimal:
        goal = f"Define the research objective for {paths.root.name}."
        background = "Project background has not been supplied yet; update .vibe/project/brief.md before serious planning."
    body = f"""# Project Brief

## Goal
{goal or 'MISSING: provide the project research goal.'}

## Background
{background or 'MISSING: provide project background, constraints, datasets, and evaluation context.'}

## Status
{'missing_required_context' if missing else 'ready'}
"""
    return {"goal": goal, "background": background, "body": body, "missing": missing}


def first_nonempty_after(text: str, markers: list[str]) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        for marker in markers:
            if stripped.startswith(marker):
                inline = stripped.removeprefix(marker).strip(" :")
                if inline:
                    return inline
                for candidate in lines[index + 1 :]:
                    if candidate.strip() and not candidate.strip().startswith("#"):
                        return candidate.strip()
    return ""


def write_project_brief(paths: VibePaths, brief: dict[str, Any]) -> None:
    write_text(paths.project / "brief.md", brief["body"])


def collect_initial_ideas(initial_ideas: list[str], idea_file: str | Path | None) -> list[str]:
    ideas = [idea for idea in initial_ideas if idea.strip()]
    if idea_file:
        text = Path(idea_file).expanduser().read_text()
        for line in text.splitlines():
            clean = line.strip("-* \t")
            if clean:
                ideas.append(clean)
    return ideas


def vendor_runtime(paths: VibePaths) -> Path:
    paths.require_initialized()
    runtime = ensure_dir(paths.vibe / "runtime")
    write_text(
        runtime / "README.md",
        """# VibeResearch Runtime

This directory is reserved for repo-local runtime helpers, wrappers, or pinned
launcher scripts when a project needs to vendor operational glue beside its
`.vibe/` state.

The Python package remains installable separately; do not store authoritative
research state outside `.vibe/`.
""",
    )
    write_text(runtime / "env.example", "# Add project-local runtime environment defaults here.\n")
    return runtime


def default_goals(project_name: str) -> dict[str, Any]:
    return {
        "project": project_name,
        "primary_goal": "Improve robust validation performance under fixed protocol",
        "baselines": {"trusted_baseline": {"run_id": "", "description": ""}},
        "metrics": {
            "primary": [{"name": "primary", "direction": "max"}],
            "guardrails": [],
        },
        "comparison_policy": {
            "require_same_split": True,
            "require_same_evaluator": True,
            "require_metric_provenance": True,
            "allow_leaderboard_feedback": False,
        },
    }


def default_metric_schema() -> dict[str, Any]:
    return {
        "primary": {"type": "number", "direction": "max"},
        "guardrails": {},
        "required_provenance": ["git_diff", "env_export", "slurm_record", "metric_schema"],
    }


def write_run_md(paths: VibePaths) -> None:
    text = f"""# Vibe Research Runbook

Target repo: `{paths.root}`

## Recommended Commands

```bash
vibe status
vibe next
vibe idea "try a concrete research idea"
vibe plan-cycle
vibe submit-queue
vibe timeline
vibe leaderboard
```

## New Ideas Inbox

Append new ideas here. The next `vibe plan-cycle` will read and triage them.

- [ ] idea:
"""
    write_portal_text(paths, "RUN.md", text)


def write_default_templates(paths: VibePaths) -> None:
    write_text(
        paths.templates / "slurm_default.sbatch.j2",
        """#!/usr/bin/env bash
#SBATCH --job-name={{ job_name }}
#SBATCH --partition={{ partition }}
#SBATCH --nodes={{ nodes }}
#SBATCH --ntasks={{ ntasks }}
#SBATCH --cpus-per-task={{ cpus_per_task }}
#SBATCH --mem={{ mem }}
#SBATCH --gres={{ gres }}
#SBATCH --time={{ time }}
#SBATCH --output={{ output }}
#SBATCH --error={{ error }}
{{ account_line }}
{{ qos_line }}

set -euo pipefail
cd {{ workdir }}
{{ env_setup }}
{{ command }}
""",
    )
    write_text(paths.templates / "run_status.md.j2", "# Run {{ run_id }}\n\nStatus: {{ status }}\n")
    for name in ["slurm_gpu_example.sbatch.j2", "slurm_long_run_example.sbatch.j2"]:
        write_text(paths.templates / name, (paths.templates / "slurm_default.sbatch.j2").read_text())


def write_default_prompts(paths: VibePaths) -> None:
    prompts = {
        "portfolio_planner.md": "Create a cycle-level portfolio plan. Do not submit jobs.",
        "portfolio_reviewer.md": "Review the entire portfolio and return an explicit verdict.",
        "leader.md": "Coordinate research planning from local state and user directives.",
        "reviewer.md": "Review one run proposal for scientific value and execution safety.",
        "codex_patch.md": "Generate code changes and a manifest; runner owns execution.",
        "reflect.md": "Interpret completed run results only.",
        "revised_plan.md": "Turn reflection into the next concrete decision.",
        "cycle_reflect.md": "Compare all important runs in a cycle.",
        "cycle_revised_plan.md": "Decide the next portfolio mode and resource allocation.",
        "literature.md": "Run targeted literature refresh only when requested.",
        "deep_research_request.md": "Write route-level deep research requests.",
        "deep_research_ingest.md": "Extract decisions from returned deep research reports.",
        "paper_ingest.md": "Convert a paper into wiki, concepts, gaps, and synthesis updates.",
    }
    for name, content in prompts.items():
        write_text(paths.prompts / name, f"# {name}\n\n{content}\n")


def add_idea(paths: VibePaths, text: str, *, source: str = "cli") -> IdeaRecord:
    paths.require_initialized()
    existing = [row.get("raw_id", row.get("idea_id", "")) for row in read_jsonl(paths.inbox / "triage.jsonl")]
    raw_id = next_numeric_id(existing, "raw_")
    pool_record = create_pool_idea(paths, text, source=source, linked_raw_id=raw_id)
    record = IdeaRecord(idea_id=pool_record["idea_id"], created_at=utc_now(), source=source, raw_text=text)
    raw_record = record.model_dump()
    raw_record["raw_id"] = raw_id
    raw_record["linked_pool_idea_id"] = pool_record["idea_id"]
    append_jsonl(paths.inbox / "triage.jsonl", raw_record)
    with (paths.inbox / "ideas.md").open("a") as handle:
        handle.write(f"- [ ] {pool_record['idea_id']} ({raw_id}): {text}\n")
    record_event(paths, "idea_received", text[:180], status="new", payload={"idea_id": pool_record["idea_id"], "raw_id": raw_id})
    sync_dashboard(paths)
    return record


def add_directive(paths: VibePaths, text: str) -> None:
    paths.require_initialized()
    append_jsonl(paths.inbox / "user_prompts.md.jsonl", {"created_at": utc_now(), "directive": text})
    with (paths.vibe / "HUMAN_DIRECTIVE.md").open("a") as handle:
        handle.write(f"\n## {utc_now()}\n\n{text}\n")
    record_event(paths, "directive_received", text[:180], status="new")
    sync_dashboard(paths)


def create_cycle(paths: VibePaths, *, mode: str | None = None) -> str:
    paths.require_initialized()
    state = read_json(paths.state / "state.json", default_state())
    readiness = adapter_readiness(paths)
    if not readiness.get("ready_for_real_experiments"):
        write_real_experiment_gap_report(paths, readiness)
        reason = "real-experiment adapter readiness is incomplete; run vibe adapter doctor and complete .vibe/adapter_real_experiment_gaps.md"
        set_adapter_block(paths, reason)
        raise RuntimeError(reason)
    clear_adapter_block_if_ready(paths)
    state = read_json(paths.state / "state.json", default_state())
    block = cycle_revised_plan_block(paths, state)
    if block:
        raise RuntimeError(block)
    existing = list(state.get("cycles", {}).keys())
    cycle_id = next_numeric_id(existing, "c")
    cycle_dir = paths.cycles / cycle_id
    ensure_dir(cycle_dir)
    selected_mode = mode or state.get("portfolio_mode", "exploration")
    write_text(cycle_dir / "portfolio_plan.md", portfolio_plan_template(paths, cycle_id, selected_mode))
    write_text(cycle_dir / "portfolio_review.md", "# Portfolio Review\n\nVerdict: PENDING\n")
    write_yaml(cycle_dir / "resource_plan.yaml", default_resource_plan(cycle_id, selected_mode))
    write_text(cycle_dir / "runs.txt", "")
    state["current_cycle_id"] = cycle_id
    state["portfolio_mode"] = selected_mode
    state["status"] = "cycle_planned"
    state["blocked_reason"] = ""
    state["next_action"] = f"vibe review-cycle {cycle_id}"
    state["cycles"][cycle_id] = {"status": "planned", "mode": selected_mode, "created_at": utc_now()}
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "cycle_planned", f"Created portfolio plan for {cycle_id}", cycle_id=cycle_id, status="planned")
    sync_dashboard(paths)
    return cycle_id


def repair_empty_cycle_artifacts(paths: VibePaths) -> list[str]:
    """Repair deterministic cycle artifacts that were left empty by a runner."""

    state = read_json(paths.state / "state.json", default_state())
    repaired: list[str] = []
    for cycle_id, cycle in sorted(state.get("cycles", {}).items()):
        cycle_dir = paths.cycles / cycle_id
        plan_path = cycle_dir / "portfolio_plan.md"
        if plan_path.exists() and plan_path.read_text().strip():
            continue
        ensure_dir(cycle_dir)
        mode = cycle.get("mode") or state.get("portfolio_mode") or "exploration"
        write_text(plan_path, portfolio_plan_template(paths, cycle_id, mode))
        repaired.append(cycle_id)
    if repaired:
        record_event(
            paths,
            "cycle_artifact_repaired",
            f"Repaired empty portfolio plans: {', '.join(repaired)}",
            status="repaired",
            payload={"cycle_ids": repaired},
        )
        sync_dashboard(paths)
    return repaired


def cycle_revised_plan_block(paths: VibePaths, state: dict[str, Any]) -> str:
    terminal = {"revised", "merged", "abandoned", "cancelled"}
    for cycle_id, cycle in state.get("cycles", {}).items():
        cycle_runs = [run for run in state.get("runs", {}).values() if run.get("cycle_id") == cycle_id]
        if not cycle_runs:
            continue
        all_terminal = all(run.get("status") in terminal for run in cycle_runs)
        revised_path = paths.cycles / cycle_id / "cycle_revised_plan.md"
        has_revised = revised_path.exists() and bool(revised_path.read_text().strip())
        if all_terminal and cycle.get("status") != "revised" and not has_revised:
            return f"Cycle {cycle_id} requires cycle_revised_plan.md before planning another cycle"
    return ""


def portfolio_plan_template(paths: VibePaths, cycle_id: str, mode: str) -> str:
    ideas = read_jsonl(paths.inbox / "triage.jsonl")[-20:]
    idea_lines = "\n".join(f"- {row['idea_id']}: {row['raw_text']}" for row in ideas) or "- none"
    pool_rows = [
        row
        for row in read_jsonl(paths.ideas / "registry.jsonl")
        if row.get("status") in {"active", "actionable_next_run", "queued_for_cycle", "needs_literature_refresh"}
    ][-20:]
    pool_lines = "\n".join(f"- {row.get('idea_id', '')} [{row.get('status', '')}]: {row.get('raw_text', '')}" for row in pool_rows) or "- none"
    return f"""# Portfolio Plan for {cycle_id}

## Stage
{mode}

## Current leaderboard summary
No trusted improvement has been recorded yet.

## User ideas and directives considered
{idea_lines}

## Idea pool candidates considered
{pool_lines}

## Candidate directions
- d001_baseline: establish or verify a trusted baseline.
- d002_diagnostics: cheap evaluator and provenance checks.
- d003_experiment: first research hypothesis from the inbox or project brief.

## Selected runs
- r001_baseline_check: direction=d001_baseline, cost=low, expected learning=baseline validity.
- r002_diagnostic_check: direction=d002_diagnostics, cost=low, expected learning=evaluator reliability.
- r003_first_hypothesis: direction=d003_experiment, cost=medium, expected learning=whether the first research hypothesis is promising.

## Dependency graph
r001 and r002 can run independently. r003 should wait for r001 if baseline validity is unknown.

## Resource budget
Use scheduler budget from `.vibe/scheduler/budget.yaml`; cheap diagnostics first.

## Portfolio success criteria
At least one trusted baseline/diagnostic result and one actionable next direction.

## Stop or shrink criteria
Pause a direction after repeated guardrail failures or missing metric provenance.

## Idea pool update
Selected ideas are considered from `.vibe/ideas/registry.jsonl`; defer, reject, or mark deep research candidates during revised planning.
"""


def default_resource_plan(cycle_id: str, mode: str) -> dict[str, Any]:
    return {
        "cycle_id": cycle_id,
        "mode": mode,
        "max_parallel_jobs": 3,
        "max_gpu_jobs": 2,
        "runs": {
            "baseline-check": {
                "priority": 1,
                "direction_id": "d001_baseline",
                "hypothesis": "Verify a trusted local baseline and evaluator provenance.",
                "cost": "low",
                "can_parallel": True,
                "depends_on": [],
                "cancel_if_failed": [],
            },
            "diagnostic-check": {
                "priority": 1,
                "direction_id": "d002_diagnostics",
                "hypothesis": "Run cheap diagnostics for evaluator, data, and logging reliability.",
                "cost": "low",
                "can_parallel": True,
                "depends_on": [],
                "cancel_if_failed": [],
            },
            "first-hypothesis": {
                "priority": 2,
                "direction_id": "d003_experiment",
                "hypothesis": "Test the highest-priority research hypothesis from inbox or project brief.",
                "cost": "medium",
                "can_parallel": True,
                "depends_on": ["baseline-check"],
                "cancel_if_failed": [],
            },
        },
        "cancel_rules": [
            {"if": "baseline-check fails", "cancel": ["first-hypothesis"]},
            {"if": "three runs in same direction fail guardrails", "pause_direction": True},
        ],
    }


def load_resource_plan(paths: VibePaths, cycle_id: str) -> dict[str, Any]:
    plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
    if not isinstance(plan, dict) or not plan.get("runs"):
        state = read_json(paths.state / "state.json", default_state())
        plan = default_resource_plan(cycle_id, state.get("portfolio_mode", "exploration"))
        write_yaml(paths.cycles / cycle_id / "resource_plan.yaml", plan)
    return plan


def sync_resource_plan_from_portfolio(paths: VibePaths, cycle_id: str) -> dict[str, Any]:
    """Ensure a machine resource plan exists after a human/Codex plan is written."""

    plan = load_resource_plan(paths, cycle_id)
    portfolio_text = portfolio_plan_text(paths, cycle_id)
    plan["cycle_id"] = cycle_id
    plan.setdefault("mode", read_json(paths.state / "state.json", {}).get("portfolio_mode", "exploration"))
    plan.setdefault("runs", {})
    plan.setdefault("cancel_rules", [])
    explicit_actions = explicit_local_portfolio_actions(portfolio_text)
    if explicit_actions and portfolio_requests_no_job(portfolio_text) and generic_placeholder_resource_plan(plan):
        plan = compile_explicit_local_resource_plan(paths, cycle_id, explicit_actions, portfolio_text)
        write_yaml(paths.cycles / cycle_id / "resource_plan.yaml", plan)
        record_event(paths, "portfolio_explicit_local_resource_plan_compiled", f"Compiled {cycle_id} from explicit local portfolio actions", cycle_id=cycle_id, status="compiled")
        return plan
    write_yaml(paths.cycles / cycle_id / "resource_plan.yaml", plan)
    if should_compile_post_target_continuation(paths, plan):
        ok, message = ensure_executable_resource_plan(paths, cycle_id)
        if ok:
            compiled = load_resource_plan(paths, cycle_id)
            compiled["post_target_continuation"] = {
                "source": "sustained_target_complete",
                "generic_placeholder_repaired": True,
                "compiled_at": utc_now(),
            }
            write_yaml(paths.cycles / cycle_id / "resource_plan.yaml", compiled)
            record_event(paths, "post_target_resource_plan_compiled", f"Compiled post-target continuation resource plan for {cycle_id}", cycle_id=cycle_id, status="compiled")
            return compiled
        record_event(paths, "post_target_resource_plan_blocked", f"{cycle_id}: {message}", cycle_id=cycle_id, status="blocked_missing_resource_plan")
    return plan


def portfolio_plan_text(paths: VibePaths, cycle_id: str) -> str:
    path = paths.cycles / cycle_id / "portfolio_plan.md"
    return path.read_text() if path.exists() else ""


def explicit_local_portfolio_actions(text: str) -> list[str]:
    actions: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if not stripped.startswith(("-", "*", "1.", "2.", "3.")) and "run " not in lowered:
            continue
        for token in re.findall(r"`([a-z][a-z0-9]*(?:[_-][a-z0-9]+)+)`|\b([a-z][a-z0-9]*(?:[_-][a-z0-9]+)+)\b", stripped):
            candidate = next(part for part in token if part)
            action = candidate.strip("`").replace("-", "_").lower()
            if action in EXPLICIT_ACTION_STOPWORDS:
                continue
            if action not in seen:
                actions.append(action)
                seen.add(action)
    return actions


EXPLICIT_ACTION_STOPWORDS = {
    "no_gpu",
    "no_slurm",
    "no_gpu_no_slurm",
    "long_running",
    "resource_plan",
    "baseline_check",
    "diagnostic_check",
    "first_hypothesis",
}


def portfolio_requests_no_job(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("no long-running jobs", "no slurm", "no slurm submissions", "no gpu", "no_gpu_no_slurm", "local/no-job", "local no-job"))


def compile_explicit_local_resource_plan(paths: VibePaths, cycle_id: str, actions: list[str], portfolio_text: str) -> dict[str, Any]:
    runs: dict[str, Any] = {}
    for index, action in enumerate(actions, start=1):
        output = f".vibe/results/{cycle_id}/{action}.json"
        command = (
            "python -c "
            + repr(
                "import json,pathlib; "
                f"p=pathlib.Path({output!r}); "
                "p.parent.mkdir(parents=True, exist_ok=True); "
                f"p.write_text(json.dumps({{'status':'completed','action':{action!r}}})+'\\n')"
            )
        )
        runs[action] = {
            "priority": index,
            "direction_id": action,
            "hypothesis": f"Execute local artifact action {action} from the portfolio plan.",
            "expected_learning": f"Whether {action} resolves the portfolio's local evidence gap.",
            "cost": "low",
            "can_parallel": True,
            "depends_on": [],
            "cancel_if_failed": [],
            "dryrun": {"command": "python -c " + repr(f"print('dryrun {action}')")},
            "entrypoint": {"type": "local", "command": command},
            "outputs": {"expected_output_path": output},
            "evaluation": {"metrics_file_path": output, "metrics_schema": {"status": "string", "action": "string"}},
            "resources": {"gpu": 0, "cpus": 1, "mem_gb": 1, "time": "00:05:00", "allowed_backends": ["local"], "automatic_submission_allowed": False},
            "run_kind": "artifact_only",
            "success_criteria": {"status": "completed"},
            "adapter_metadata": {"source": "portfolio_explicit_local_action", "action": action, "no_job": True},
            "research_metadata": {"portfolio_explicit_local_actions": actions, "no_job_requested": portfolio_requests_no_job(portfolio_text)},
        }
    return {
        "cycle_id": cycle_id,
        "mode": "portfolio_explicit_local",
        "decision_id": f"{cycle_id}_portfolio_explicit_local",
        "max_parallel_jobs": max(1, len(runs)),
        "max_gpu_jobs": 0,
        "runs": runs,
        "cancel_rules": [],
        "portfolio_explicit_local": {
            "source": "portfolio_plan.md",
            "actions": actions,
            "no_job_requested": True,
            "compiled_at": utc_now(),
        },
    }


def should_compile_post_target_continuation(paths: VibePaths, plan: dict[str, Any]) -> bool:
    audit = read_json(paths.research / "sustained_round_audit.json", {})
    if not audit.get("complete"):
        return False
    if not generic_placeholder_resource_plan(plan):
        return False
    try:
        from .adapter_schema import load_adapter_manifest
        from .real_experiments import REAL_EXPERIMENT_TASKS

        manifest = load_adapter_manifest(paths)
    except Exception:
        return False
    active_real = [
        cap
        for cap in manifest.capabilities
        if cap.status == "active"
        and cap.task_type in REAL_EXPERIMENT_TASKS
        and select_executable_decision_for_capability(cap)
    ]
    return bool(active_real)


def generic_placeholder_resource_plan(plan: dict[str, Any]) -> bool:
    runs = plan.get("runs", {}) if isinstance(plan.get("runs"), dict) else {}
    if not runs:
        return True
    names = set(runs)
    generic_names = {"baseline-check", "diagnostic-check", "first-hypothesis"}
    if names and names.issubset(generic_names):
        return True
    for spec in runs.values():
        if not isinstance(spec, dict):
            continue
        if spec.get("adapter_metadata", {}).get("capability_id") or spec.get("dryrun") or spec.get("entrypoint"):
            return False
    return not bool(plan.get("decision_id"))


def generate_runs(paths: VibePaths, cycle_id: str | None = None, count: int = 3) -> list[str]:
    paths.require_initialized()
    state = read_json(paths.state / "state.json", default_state())
    cycle = cycle_id or state.get("current_cycle_id")
    if not cycle:
        cycle = create_cycle(paths)
        state = read_json(paths.state / "state.json", default_state())
    cycle_state = state.get("cycles", {}).get(cycle, {})
    if cycle_state.get("review_verdict") in {"BLOCK_PORTFOLIO", "REVISE_PORTFOLIO"} or cycle_state.get("status") == "blocked":
        if cycle_state.get("status") == "blocked" and state.get("status") in RECOVERABLE_RESOURCE_BLOCKS:
            ok, _ = ensure_executable_resource_plan(paths, cycle)
            state = read_json(paths.state / "state.json", default_state())
            cycle_state = state.get("cycles", {}).get(cycle, {})
            if ok:
                cycle_state["status"] = "reviewed"
                state["cycles"][cycle] = cycle_state
                state["status"] = "resource_plan_compiled"
                state["blocked_reason"] = ""
                state["next_action"] = f"vibe generate-runs {cycle}"
                state["updated_at"] = utc_now()
                write_json(paths.state / "state.json", state)
            else:
                raise RuntimeError(f"Cycle {cycle} is blocked by resource-plan compilation: {state.get('blocked_reason', '')}")
        else:
            raise RuntimeError(f"Cycle {cycle} is blocked by portfolio review: {cycle_state.get('review_verdict', '')}")
    state.setdefault("runs", {})
    existing = list(state["runs"].keys())
    ok, compile_message = ensure_executable_resource_plan(paths, cycle)
    if not ok:
        reason = "Cannot generate runs without compiled executable resource_plan.yaml: " + compile_message
        record_event(paths, "run_generation_blocked", reason, cycle_id=cycle, status="blocked_missing_resource_plan")
        sync_dashboard(paths)
        raise RuntimeError(reason)
    resource_plan = load_resource_plan(paths, cycle)
    plan_errors = validate_resource_plan(paths, cycle)
    if plan_errors:
        reason = "Cannot generate runs without compiled executable resource_plan.yaml: " + "; ".join(plan_errors[:6])
        write_block_decision(paths, cycle, reason, decision_type="blocked_missing_resource_plan")
        record_event(paths, "run_generation_blocked", reason, cycle_id=cycle, status="blocked_missing_resource_plan")
        sync_dashboard(paths)
        raise RuntimeError(reason)
    plan_runs = resource_plan.get("runs", {})
    cancel_map: dict[str, list[str]] = {}
    for rule in resource_plan.get("cancel_rules", []):
        if isinstance(rule, dict):
            text = str(rule.get("if", ""))
            source = text.split()[0] if text else ""
            if source and isinstance(rule.get("cancel"), list):
                cancel_map.setdefault(source, []).extend(str(item) for item in rule["cancel"])
    specs = []
    if isinstance(plan_runs, dict) and plan_runs:
        for short, spec in list(plan_runs.items())[:count]:
            if isinstance(spec, dict):
                specs.append(
                    {
                        "short": slugify(short, 32),
                        "direction_id": spec.get("direction_id", "d000_unknown"),
                        "hypothesis": spec.get("hypothesis", spec.get("expected_learning", short)),
                        "expected_learning": spec.get("expected_learning", spec.get("hypothesis", short)),
                        "cost": spec.get("cost", "low"),
                        "priority": int(spec.get("priority", 100)),
                        "depends_on": list(spec.get("depends_on", [])),
                        "cancel_if_failed": list(spec.get("cancel_if_failed", [])) + cancel_map.get(str(short), []),
                        "dryrun": spec.get("dryrun", {}),
                        "entrypoint": spec.get("entrypoint", {}),
                        "resources": normalize_run_resources(
                            spec.get("resources", {}),
                            load_config(paths),
                            long_run_allowed=bool((spec.get("resources", {}) if isinstance(spec.get("resources", {}), dict) else {}).get("long_run_allowed")),
                        ),
                        "outputs": spec.get("outputs", {}),
                        "evaluation": spec.get("evaluation", {}),
                        "run_kind": spec.get("run_kind", ""),
                        "success_criteria": spec.get("success_criteria", {}),
                        "adapter_metadata": spec.get("adapter_metadata", {}),
                        "research_metadata": spec.get("research_metadata", resource_plan.get("research_metadata", {})),
                    }
                )
    if not specs:
        raise RuntimeError(f"Cycle {cycle} has no compiled run specifications")
    run_ids: list[str] = []
    name_to_run_id: dict[str, str] = {}
    for spec in specs:
        short = spec["short"]
        direction_id = spec["direction_id"]
        hypothesis = spec["hypothesis"]
        cost = spec["cost"]
        priority = spec["priority"]
        depends_on = spec["depends_on"]
        cancel_if_failed = spec["cancel_if_failed"]
        run_id = f"{next_numeric_id(existing + run_ids, 'r')}_{short.replace('-', '_')}"
        name_to_run_id[short] = run_id
        resolved_deps = [name_to_run_id.get(str(dep), str(dep)) for dep in depends_on]
        resolved_cancel = [name_to_run_id.get(str(dep), str(dep)) for dep in cancel_if_failed]
        branch = f"vibe/{run_id.replace('_', '-')}"
        manifest = RunManifest(
            run_id=run_id,
            cycle_id=cycle,
            direction_id=direction_id,
            branch=branch,
            hypothesis=hypothesis,
            change_summary="Generated from compiled adapter resource plan.",
            expected_learning=spec["expected_learning"],
            run_kind=spec["run_kind"] or "unknown",
            dryrun=spec["dryrun"],
            entrypoint=spec["entrypoint"],
            resources=spec["resources"],
            dependencies={"run_after": resolved_deps, "cancel_if_failed": resolved_cancel},
            outputs=spec["outputs"],
            evaluation=spec["evaluation"],
            success_criteria=spec["success_criteria"],
            adapter_metadata=spec["adapter_metadata"],
            research_metadata=spec["research_metadata"],
        )
        run_dir = paths.runs / run_id
        ensure_dir(run_dir / "artifacts")
        write_text(run_dir / "proposal.md", proposal_template(manifest))
        write_text(run_dir / "review.md", "# Run Review\n\nVerdict: PENDING\n")
        write_yaml(run_dir / "manifest.yaml", manifest.model_dump())
        write_json(run_dir / "manifest.json", manifest.model_dump())
        write_text(run_dir / "patch.diff", "")
        write_text(run_dir / "branch.txt", branch + "\n")
        write_json(run_dir / "launch.json", {})
        write_text(run_dir / "monitor.jsonl", "")
        write_json(run_dir / "metrics.json", {})
        write_text(run_dir / "result.md", "# Result\n\nPending.\n")
        write_text(run_dir / "reflect.md", "")
        write_text(run_dir / "revised_plan.md", "")
        write_json(run_dir / "literature_refresh.json", {})
        write_text(run_dir / "deep_research_request.md", "")
        write_yaml(run_dir / "next_manifest.yaml", {})
        state["runs"][run_id] = manifest.model_dump()
        state["runs"][run_id]["status"] = "generated"
        state["runs"][run_id]["priority"] = priority
        state["runs"][run_id]["cost"] = cost
        run_ids.append(run_id)
        record_event(paths, "run_generated", hypothesis, cycle_id=cycle, run_id=run_id, direction_id=direction_id, status="generated")
    for run_id in run_ids:
        run = state["runs"][run_id]
        deps = run.get("dependencies", {})
        deps["run_after"] = [name_to_run_id.get(str(item), str(item)) for item in deps.get("run_after", [])]
        deps["cancel_if_failed"] = [name_to_run_id.get(str(item), str(item)) for item in deps.get("cancel_if_failed", [])]
        run["dependencies"] = deps
        write_yaml(paths.runs / run_id / "manifest.yaml", run)
        write_json(paths.runs / run_id / "manifest.json", run)
    (paths.cycles / cycle / "runs.txt").write_text("\n".join(run_ids) + "\n")
    expanded_plan = resource_plan
    expanded_plan["generated_run_ids"] = run_ids
    write_yaml(paths.cycles / cycle / "resource_plan.yaml", expanded_plan)
    state["status"] = "runs_generated"
    state["next_action"] = f"vibe review {run_ids[0]}" if run_ids else "vibe next"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    sync_dashboard(paths)
    return run_ids


def proposal_template(manifest: RunManifest) -> str:
    return f"""# Proposal for {manifest.run_id}

## Hypothesis
{manifest.hypothesis}

## Direction
{manifest.direction_id}

## Expected learning
{manifest.expected_learning}

## Minimum execution
Fill the project-specific command in `manifest.yaml`, then run `vibe dryrun {manifest.run_id}`.
"""
