"""Operator next-action decision logic."""

from __future__ import annotations

from .adapter_onboarding import adapter_readiness, apply_project_adapter_profile, clear_adapter_block_if_ready
from .config import load_config
from .io import read_json, read_jsonl, read_yaml
from .paths import VibePaths
from .scheduler import active_gpu_count


RECOVERABLE_RESOURCE_BLOCKS = {
    "blocked_missing_resource_plan",
    "blocked_missing_capability",
    "blocked_missing_script",
    "blocked_missing_metrics_schema",
    "blocked_contract_test_failed",
    "blocked_resource_policy",
}


def compute_next_action(paths: VibePaths) -> tuple[str, str]:
    state = read_json(paths.state / "state.json", {})
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []}).get("active", [])
    queue = read_json(paths.scheduler / "queue.json", {"queued": []}).get("queued", [])
    readiness = adapter_readiness(paths)
    if not readiness.get("ready_for_real_experiments"):
        profile = apply_project_adapter_profile(paths)
        if profile.get("applied"):
            readiness = adapter_readiness(paths)
    if not readiness.get("ready_for_real_experiments"):
        return "vibe adapter doctor", "real_experiment_adapter_readiness_incomplete"
    if state.get("status") == "blocked_missing_adapter":
        clear_adapter_block_if_ready(paths)
        state = read_json(paths.state / "state.json", {})
    if state.get("project_brief_missing"):
        return "add project goal/background with vibe init --goal ... --background ...", "project_brief_missing"
    state_status = str(state.get("status", ""))
    next_action = str(state.get("next_action", ""))
    active_block = state_status.startswith("blocked_") or (bool(state.get("blocked_reason")) and next_action.startswith("vibe decision show"))
    if active_block:
        if state_status in RECOVERABLE_RESOURCE_BLOCKS and state.get("current_cycle_id"):
            return f"vibe generate-runs {state['current_cycle_id']}", ""
        return state.get("next_action") or "vibe decision show <target_id>", state.get("blocked_reason") or state.get("status", "blocked")
    if any(row.get("status") == "new" for row in read_jsonl(paths.ideas / "registry.jsonl")):
        return "vibe ideas triage", ""
    if any(row.get("status") == "needs_deep_research" and not row.get("linked_deep_request_id") for row in read_jsonl(paths.ideas / "registry.jsonl")):
        idea_id = next(row.get("idea_id", "<idea_id>") for row in read_jsonl(paths.ideas / "registry.jsonl") if row.get("status") == "needs_deep_research" and not row.get("linked_deep_request_id"))
        return f"vibe deep-request-from-idea {idea_id}", ""
    if queue:
        return "vibe submit-queue", ""
    active_capacity_full = active and active_jobs_exhaust_capacity(paths, active)
    if active_capacity_full:
        return "vibe monitor", ""
    for request in read_jsonl(paths.research / "deep_requests" / "registry.jsonl"):
        if request.get("blocking") and request.get("status") != "ingested":
            return "vibe ingest-deep-research " + request.get("request_id", "<request_id>"), "blocked_waiting_deep_research"
    cycle_id = state.get("current_cycle_id", "")
    if cycle_id:
        cycle = state.get("cycles", {}).get(cycle_id, {})
        if cycle.get("status") == "blocked":
            return f"revise portfolio {cycle_id}", state.get("blocked_reason", "portfolio_blocked")
        if cycle.get("status") == "planned":
            return f"vibe review-cycle {cycle_id}", ""
        cycle_run_ids = [run_id for run_id, run in state.get("runs", {}).items() if run.get("cycle_id") == cycle_id]
        if cycle.get("status") == "reviewed" and not cycle_run_ids:
            return f"vibe generate-runs {cycle_id}", ""
    scoped_runs = next_action_run_scope(state, cycle_id)
    for run_id, run in scoped_runs:
        run_dir = paths.runs / run_id
        status = run.get("status", "")
        if not has_text(run_dir / "review.md"):
            return f"vibe review {run_id}", ""
        if status in {"generated"}:
            return f"vibe review {run_id}", ""
        if status in {"reviewed"}:
            return f"vibe branch {run_id}", ""
        if status in {"branched", "branch_recorded_no_git"}:
            return f"vibe patch {run_id}", ""
        if status == "patched":
            return f"vibe dryrun {run_id}", ""
        if status == "dryrun_passed":
            return f"vibe queue {run_id}", ""
        if status in {"finished", "submitted_dry"}:
            return f"vibe collect {run_id}", ""
        if status == "collected":
            return f"vibe reflect {run_id}", ""
        if status == "reflected":
            return f"vibe revise-plan {run_id}", ""
        if status == "revised":
            continue
    if cycle_id:
        cycle_dir = paths.cycles / cycle_id
        cycle_runs = [run for run in state.get("runs", {}).values() if run.get("cycle_id") == cycle_id]
        terminal = {"revised", "merged", "abandoned", "cancelled"}
        all_terminal = bool(cycle_runs) and all(run.get("status") in terminal for run in cycle_runs)
        if all_terminal and not has_text(cycle_dir / "cycle_reflect.md"):
            return f"vibe reflect-cycle {cycle_id}", ""
        if all_terminal and not has_text(cycle_dir / "cycle_revised_plan.md"):
            return f"vibe revise-cycle {cycle_id}", ""
    fallback = state.get("next_action") or "vibe plan-cycle"
    if active and fallback == "vibe monitor":
        return "vibe plan-cycle", ""
    return fallback, ""


def has_text(path) -> bool:
    return path.exists() and bool(path.read_text().strip())


def next_action_run_scope(state: dict, cycle_id: str) -> list[tuple[str, dict]]:
    runs = sorted(state.get("runs", {}).items())
    if not cycle_id:
        return runs
    current = [(run_id, run) for run_id, run in runs if run.get("cycle_id") == cycle_id]
    terminal = {"revised", "merged", "abandoned", "cancelled"}
    if any(run.get("status") not in terminal for _, run in current):
        return current
    return runs


def active_jobs_exhaust_capacity(paths: VibePaths, active: list[dict]) -> bool:
    config = load_config(paths)
    budget = read_yaml(paths.scheduler / "budget.yaml", {}) or config.get("scheduler", {})
    max_parallel = int(budget.get("max_parallel_jobs", 3))
    max_gpu = int(budget.get("max_parallel_gpu_jobs", budget.get("max_gpu_jobs", 2)))
    if len(active) >= max_parallel:
        return True
    return active_gpu_count(active) >= max_gpu
