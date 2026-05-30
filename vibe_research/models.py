"""Pydantic models and default state for VibeResearch."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


PortfolioMode = Literal["exploration", "balanced", "exploitation"]


class ProjectConfig(BaseModel):
    project_name: str = "Generic Research Repo"
    vibe_version: str = "0.8.15"
    project: dict[str, Any] = Field(
        default_factory=lambda: {
            "name": "Generic Research Repo",
            "goal": "",
            "background": "",
            "brief_path": ".vibe/project/brief.md",
            "brief_missing": True,
        }
    )
    portal: dict[str, Any] = Field(
        default_factory=lambda: {
            "root_mode": "copy",
            "generated_notice": True,
        }
    )
    execution: dict[str, Any] = Field(
        default_factory=lambda: {
            "backend": "local",
            "local": {
                "launcher": "auto",
                "tmux_session_prefix": "vibe",
            },
            "slurm": {
                "enabled": True,
                "default_partition": "gpu_short",
                "fallback_partitions": ["gpu", "a100", "general_gpu"],
                "account": "",
                "qos": "",
                "partitions": [
                    {"name": "gpu_short", "priority": 100, "max_time": "08:00:00", "gpu": "generic"},
                    {"name": "gpu", "priority": 80, "max_time": "24:00:00", "gpu": "generic"},
                    {"name": "a100", "priority": 70, "max_time": "24:00:00", "gpu": "a100"},
                    {"name": "general_gpu", "priority": 50, "max_time": "24:00:00", "gpu": "generic"},
                ],
            },
        }
    )
    portfolio: dict[str, Any] = Field(
        default_factory=lambda: {
            "mode": "exploration",
            "max_runs_per_cycle": 6,
            "min_distinct_directions": 3,
            "max_same_direction_runs": 2,
            "require_low_cost_baseline": True,
            "allow_parallel_runs": True,
            "require_portfolio_review": True,
        }
    )
    scheduler: dict[str, Any] = Field(
        default_factory=lambda: {
            "max_parallel_jobs": 3,
            "max_parallel_gpu_jobs": 2,
            "max_total_gpus": 4,
            "max_walltime_hours_per_cycle": 48,
            "max_failed_runs_before_pause": 3,
            "queue_policy": "priority_then_resource_fit",
        }
    )
    slurm: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "default_partition": "gpu_short",
            "fallback_partitions": ["gpu", "a100", "general_gpu"],
            "account": "",
            "qos": "",
        }
    )
    leaderboard: dict[str, Any] = Field(
        default_factory=lambda: {
            "primary_metric": "primary",
            "primary_direction": "max",
            "require_metric_provenance": True,
            "allow_leaderboard_feedback": False,
        }
    )
    monitor: dict[str, Any] = Field(
        default_factory=lambda: {
            "loop_interval_seconds": 300,
            "auto_next": False,
            "log_tail_lines": 80,
        }
    )
    dashboard: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "static_site_dir": ".vibe/site",
            "serve_host": "127.0.0.1",
            "serve_port": 8765,
            "codex_quota_display": "unknown/manual",
        }
    )
    ideas: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "max_active_ideas": 20,
            "stale_after_days": 30,
            "require_cleanup_each_cycle": True,
        }
    )
    deep_research: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "default_blocking": False,
            "allow_pdf_ingest": True,
            "allow_markdown_ingest": True,
        }
    )
    adapter: dict[str, Any] = Field(
        default_factory=lambda: {
            "kind": "config",
            "config_path": ".vibe/adapter.yaml",
            "require_for_experiments": True,
            "script_dir": ".vibe/scripts",
            "max_autonomy": "adapter_ready",
        }
    )
    loop_guard: dict[str, Any] = Field(
        default_factory=lambda: {
            "repeated_threshold": 2,
            "default_primary_metric": 0.0,
        }
    )
    research: dict[str, Any] = Field(
        default_factory=lambda: {
            "offline": True,
            "max_search_results": 10,
            "require_pdf_checksum": True,
            "manager_enabled": True,
            "memo_language": "zh-CN",
            "autonomy_level": "analysis_only",
        }
    )
    codex: dict[str, Any] = Field(
        default_factory=lambda: {
            "provider": "cli",
            "model": "",
            "approval_policy": "never",
            "enable_search_for_literature": True,
            "sandbox": {
                "read_roles": "read-only",
                "patch_role": "workspace-write",
            },
        }
    )


class TimelineEvent(BaseModel):
    event: str
    created_at: str
    cycle_id: str = ""
    run_id: str = ""
    direction_id: str = ""
    status: str = ""
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class IdeaRecord(BaseModel):
    idea_id: str
    created_at: str
    source: str
    raw_text: str
    status: str = "new"
    linked_cycle_id: str = ""
    linked_run_id: str = ""
    linked_direction_id: str = ""
    linked_paper_id: str = ""
    linked_deep_request_id: str = ""
    triage_decision: str = ""


class RunManifest(BaseModel):
    run_id: str
    cycle_id: str
    direction_id: str
    branch: str
    hypothesis: str
    change_summary: str = ""
    expected_learning: str = ""
    run_kind: str = "unknown"
    status: str = "generated"
    entrypoint: dict[str, Any] = Field(default_factory=lambda: {"type": "local", "command": ""})
    dryrun: dict[str, Any] = Field(default_factory=lambda: {"command": "", "max_minutes": 20})
    resources: dict[str, Any] = Field(
        default_factory=lambda: {
            "gpu": 0,
            "cpus": 1,
            "mem_gb": 4,
            "time": "01:00:00",
            "preferred_partitions": ["gpu_short"],
            "fallback_partitions": ["gpu", "a100", "general_gpu"],
        }
    )
    dependencies: dict[str, Any] = Field(default_factory=lambda: {"run_after": [], "cancel_if_failed": []})
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    adapter_metadata: dict[str, Any] = Field(default_factory=dict)
    research_metadata: dict[str, Any] = Field(default_factory=dict)
    provenance_required: dict[str, bool] = Field(
        default_factory=lambda: {
            "git_diff": True,
            "env_export": True,
            "slurm_record": True,
            "metric_schema": True,
        }
    )


def default_state() -> dict[str, Any]:
    return {
        "current_cycle_id": "",
        "portfolio_mode": "exploration",
        "status": "initialized",
        "runs": {},
        "cycles": {},
        "updated_at": "",
        "next_action": "plan-cycle",
        "blocked_reason": "",
        "schema_version": 3,
    }


def default_budget() -> dict[str, Any]:
    return {
        "max_parallel_jobs": 3,
        "max_gpu_jobs": 2,
        "max_total_gpus": 4,
        "max_walltime_hours_per_cycle": 48,
        "max_failed_runs_before_pause": 3,
        "queue_policy": "priority_then_resource_fit",
        "partition_priority": {},
        "fallback_partitions": ["gpu", "a100", "general_gpu"],
        "cancel_rules": [],
    }
