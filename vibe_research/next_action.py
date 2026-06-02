"""Operator next-action decision logic."""

from __future__ import annotations

from .adapter_onboarding import adapter_readiness, apply_project_adapter_profile, clear_adapter_block_if_ready
from .config import load_config
from .io import read_json, read_jsonl, read_yaml, utc_now, write_json
from .paths import VibePaths
from .real_experiments import summarize_real_experiment_progress
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
    queue = actionable_queue_rows(state, read_json(paths.scheduler / "queue.json", {"queued": []}).get("queued", []))
    readiness = adapter_readiness(paths)
    if state.get("project_brief_missing"):
        return "add project goal/background with vibe init --goal ... --background ...", "project_brief_missing"
    if abandon_empty_preplanned_cycle_for_active_round(paths, state, active):
        return "vibe monitor", ""
    if active_jobs_fragment_sustained_round(paths, active):
        return "vibe monitor", ""
    pending_output = pending_current_cycle_output_step(state)
    if pending_output:
        return pending_output, ""
    if any(row.get("status") == "new" for row in read_jsonl(paths.ideas / "registry.jsonl")):
        return "vibe ideas triage", ""
    if any(row.get("status") == "needs_literature_refresh" for row in read_jsonl(paths.ideas / "registry.jsonl")):
        idea_id = next(row.get("idea_id", "<idea_id>") for row in read_jsonl(paths.ideas / "registry.jsonl") if row.get("status") == "needs_literature_refresh")
        return f"vibe lit-refresh-idea {idea_id}", ""
    if any(row.get("status") == "needs_deep_research" and not row.get("linked_deep_request_id") for row in read_jsonl(paths.ideas / "registry.jsonl")):
        idea_id = next(row.get("idea_id", "<idea_id>") for row in read_jsonl(paths.ideas / "registry.jsonl") if row.get("status") == "needs_deep_research" and not row.get("linked_deep_request_id"))
        return f"vibe deep-request-from-idea {idea_id}", ""
    if not readiness.get("ready_for_real_experiments"):
        profile = apply_project_adapter_profile(paths)
        if profile.get("applied"):
            readiness = adapter_readiness(paths)
    if not readiness.get("ready_for_real_experiments"):
        return "vibe adapter doctor", "real_experiment_adapter_readiness_incomplete"
    if state.get("status") == "blocked_missing_adapter":
        clear_adapter_block_if_ready(paths)
        state = read_json(paths.state / "state.json", {})
    ready_output = active_scope_output_action(state, active)
    if ready_output:
        return ready_output, ""
    if active_jobs_have_outside_policy_fallback(active):
        return "vibe scheduler-requeue-fallback --allow-outside-policy", ""
    if active_scope_should_monitor(state, active):
        return "vibe monitor", ""
    state_status = str(state.get("status", ""))
    next_action = str(state.get("next_action", ""))
    active_block = state_status.startswith("blocked_") or (bool(state.get("blocked_reason")) and next_action.startswith("vibe decision show"))
    if active_block:
        if clear_stale_terminal_decision_block(paths, state):
            state = read_json(paths.state / "state.json", {})
            state_status = str(state.get("status", ""))
            next_action = str(state.get("next_action", ""))
            active_block = state_status.startswith("blocked_") or (bool(state.get("blocked_reason")) and next_action.startswith("vibe decision show"))
        elif clear_recovered_round_block(paths, state, active):
            state = read_json(paths.state / "state.json", {})
            state_status = str(state.get("status", ""))
            next_action = str(state.get("next_action", ""))
            active_block = state_status.startswith("blocked_") or (bool(state.get("blocked_reason")) and next_action.startswith("vibe decision show"))
    if active_block:
        if state_status in RECOVERABLE_RESOURCE_BLOCKS and state.get("current_cycle_id"):
            return f"vibe generate-runs {state['current_cycle_id']}", ""
        return state.get("next_action") or "vibe decision show <target_id>", state.get("blocked_reason") or state.get("status", "blocked")
    active_capacity_full = active and active_jobs_exhaust_capacity(paths, active)
    if queue:
        if active_capacity_full:
            return "vibe monitor", ""
        return "vibe submit-queue", ""
    if active_capacity_full and not allow_prequeue_planning(paths, state):
        return "vibe monitor", ""
    for request in read_jsonl(paths.research / "deep_requests" / "registry.jsonl"):
        if request.get("blocking") and request.get("status") != "ingested":
            return "vibe ingest-deep-research " + request.get("request_id", "<request_id>"), "blocked_waiting_deep_research"
    current_run_step = current_cycle_run_lifecycle_step(paths, state)
    if current_run_step:
        return current_run_step, ""
    cycle_id = state.get("current_cycle_id", "")
    progress = summarize_real_experiment_progress(paths)
    if blocking_real_experiment_repairs(progress, current_cycle_id=str(cycle_id or "")):
        return "vibe experiment real-progress", "real_experiment_repair_required"
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
        if terminal_inactive_run(run):
            continue
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
        all_terminal = bool(cycle_runs) and all(run.get("status") in terminal or terminal_inactive_run(run) for run in cycle_runs)
        if all_terminal and not has_text(cycle_dir / "cycle_reflect.md"):
            return f"vibe reflect-cycle {cycle_id}", ""
        if all_terminal and not has_text(cycle_dir / "cycle_revised_plan.md"):
            return f"vibe revise-cycle {cycle_id}", ""
    fallback = state.get("next_action") or "vibe plan-cycle"
    if active and fallback == "vibe monitor":
        return "vibe plan-cycle", ""
    return fallback, ""


def blocking_real_experiment_repairs(progress: dict, *, current_cycle_id: str = "") -> list[dict]:
    blocking_statuses = {"failed", "timeout", "cancelled", "dryrun_failed"}
    countable = progress.get("countable_runs", [])
    if len(countable) >= int(progress.get("target_count", 3) or 3):
        return []
    return [
        row
        for row in progress.get("non_counting_real_experiment_runs", [])
        if row.get("requires_repair") and row.get("status") in blocking_statuses
        and row_is_current_or_unsuperseded(row, countable, current_cycle_id=current_cycle_id)
    ]


def row_is_current_or_unsuperseded(row: dict, countable: list[dict], *, current_cycle_id: str) -> bool:
    if current_cycle_id and row.get("cycle_id") == current_cycle_id:
        return True
    row_capability = str(row.get("capability_id") or "")
    row_direction = str(row.get("direction_id") or "")
    for later in countable:
        if row_capability and later.get("capability_id") == row_capability:
            return False
        if row_direction and later.get("direction_id") == row_direction:
            return False
    return not current_cycle_id


def actionable_queue_rows(state: dict, queue: list[dict]) -> list[dict]:
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    actionable = []
    for item in queue:
        run = runs.get(item.get("run_id", ""))
        if not isinstance(run, dict):
            continue
        if run.get("status") == "queued" and item.get("status", "queued") == "queued":
            actionable.append(item)
    return actionable


def active_scope_output_action(state: dict, active: list[dict]) -> str:
    if not active:
        return ""
    active_cycle_ids = {str(job.get("cycle_id") or "") for job in active if job.get("cycle_id")}
    cycle_id = next(iter(active_cycle_ids)) if len(active_cycle_ids) == 1 else str(state.get("current_cycle_id") or "")
    if not cycle_id:
        return ""
    runs = sorted((state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}).items())
    for run_id, run in runs:
        if run.get("cycle_id") != cycle_id or terminal_inactive_run(run):
            continue
        status = str(run.get("status", ""))
        if status in {"finished", "submitted_dry"}:
            return f"vibe collect {run_id}"
        if status == "collected":
            return f"vibe reflect {run_id}"
        if status == "reflected":
            return f"vibe revise-plan {run_id}"
    return ""


def pending_current_cycle_output_step(state: dict) -> str:
    cycle_id = str(state.get("current_cycle_id") or "")
    if not cycle_id:
        return ""
    runs = sorted((state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}).items())
    for run_id, run in runs:
        if run.get("cycle_id") != cycle_id or terminal_inactive_run(run):
            continue
        status = str(run.get("status", ""))
        if status in {"finished", "submitted_dry"}:
            return f"vibe collect {run_id}"
        if status == "collected":
            return f"vibe reflect {run_id}"
        if status == "reflected":
            return f"vibe revise-plan {run_id}"
    return ""


def current_cycle_run_lifecycle_step(paths: VibePaths, state: dict) -> str:
    cycle_id = str(state.get("current_cycle_id") or "")
    if not cycle_id:
        return ""
    runs = sorted((state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}).items())
    for run_id, run in runs:
        if run.get("cycle_id") != cycle_id or terminal_inactive_run(run):
            continue
        status = str(run.get("status", ""))
        if status == "generated":
            return f"vibe review {run_id}"
        if status == "reviewed":
            return f"vibe branch {run_id}"
        if status in {"branched", "branch_recorded_no_git"}:
            return f"vibe patch {run_id}"
        if status == "patched":
            return f"vibe dryrun {run_id}"
        if status == "dryrun_passed":
            return f"vibe queue {run_id}"
        if status in {"finished", "submitted_dry"}:
            return f"vibe collect {run_id}"
        if status == "collected":
            return f"vibe reflect {run_id}"
        if status == "reflected":
            return f"vibe revise-plan {run_id}"
        if status and not has_text(paths.runs / run_id / "review.md") and status not in {"queued", "submitted", "pending", "running", "dry_submitted"}:
            return f"vibe review {run_id}"
    return ""


def active_jobs_have_outside_policy_fallback(active: list[dict]) -> bool:
    for job in active:
        details = job.get("poll_details", {}) if isinstance(job.get("poll_details"), dict) else {}
        verdict = details.get("wait_verdict", {}) if isinstance(details.get("wait_verdict"), dict) else {}
        if verdict.get("verdict") == "fallback_better_but_outside_wait_policy":
            return True
    return False


def active_scope_should_monitor(state: dict, active: list[dict]) -> bool:
    if not active:
        return False
    active_cycle_ids = {str(job.get("cycle_id") or "") for job in active if job.get("cycle_id")}
    if len(active_cycle_ids) != 1:
        return False
    cycle_id = next(iter(active_cycle_ids))
    runs = (state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}).values()
    active_statuses = {"submitted", "pending", "running", "dry_submitted", "submitted_dry"}
    return any(run.get("cycle_id") == cycle_id and run.get("status") in active_statuses for run in runs)


def abandon_empty_preplanned_cycle_for_active_round(paths: VibePaths, state: dict, active: list[dict]) -> bool:
    if not active:
        return False
    active_cycle_ids = {str(job.get("cycle_id") or "") for job in active if job.get("cycle_id")}
    if len(active_cycle_ids) != 1:
        return False
    active_cycle_id = next(iter(active_cycle_ids))
    current_cycle_id = str(state.get("current_cycle_id") or "")
    if not current_cycle_id or current_cycle_id == active_cycle_id:
        return False
    cycles = state.get("cycles", {}) if isinstance(state.get("cycles"), dict) else {}
    current_cycle = cycles.get(current_cycle_id, {})
    if current_cycle.get("status") not in {"planned", "reviewed"}:
        return False
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    if any(run.get("cycle_id") == current_cycle_id for run in runs.values()):
        return False
    current_cycle["status"] = "abandoned"
    current_cycle["abandoned_reason"] = "empty preplanned cycle superseded by active attempted cycle"
    current_cycle["abandoned_at"] = utc_now()
    current_cycle["provenance"] = {
        "source": "next_action_empty_preplanned_cycle_guard",
        "active_cycle_id": active_cycle_id,
    }
    cycles[current_cycle_id] = current_cycle
    state["cycles"] = cycles
    state["current_cycle_id"] = active_cycle_id
    state["next_action"] = "vibe monitor"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    return True


def clear_stale_terminal_decision_block(paths: VibePaths, state: dict) -> bool:
    next_action = str(state.get("next_action", ""))
    if not next_action.startswith("vibe decision show "):
        return False
    target_id = next_action.split()[-1]
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    cycles = state.get("cycles", {}) if isinstance(state.get("cycles"), dict) else {}
    cycle_id = target_id
    if target_id in runs:
        run = runs[target_id]
        if not terminal_run_for_cycle_close(run):
            return False
        cycle_id = str(run.get("cycle_id") or "")
    if not cycle_id or cycle_id not in cycles:
        return False
    if not cycle_closed_with_revision(paths, cycle_id):
        return False
    cycle_runs = [run for run in runs.values() if run.get("cycle_id") == cycle_id]
    if cycle_runs and not all(terminal_run_for_cycle_close(run) for run in cycle_runs):
        return False
    state["status"] = "initialized"
    state["blocked_reason"] = ""
    state["next_action"] = "vibe plan-cycle"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    return True


def clear_recovered_round_block(paths: VibePaths, state: dict, active: list[dict]) -> bool:
    if active:
        return False
    cycle_id = str(state.get("current_cycle_id") or "")
    if not cycle_id:
        return False
    cycles = state.get("cycles", {}) if isinstance(state.get("cycles"), dict) else {}
    if cycle_id not in cycles or not cycle_closed_with_revision(paths, cycle_id):
        return False
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    cycle_runs = [run for run in runs.values() if run.get("cycle_id") == cycle_id]
    if cycle_runs and not all(terminal_run_for_cycle_close(run) for run in cycle_runs):
        return False
    audit = read_json(paths.research / "sustained_round_audit.json", {})
    if isinstance(audit, dict) and audit.get("issues"):
        return False
    state["status"] = "initialized"
    state["blocked_reason"] = ""
    if str(state.get("next_action", "")).startswith("vibe decision show"):
        state["next_action"] = "vibe plan-cycle"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    return True


def cycle_closed_with_revision(paths: VibePaths, cycle_id: str) -> bool:
    cycle_dir = paths.cycles / cycle_id
    return has_text(cycle_dir / "cycle_reflect.md") and has_text(cycle_dir / "cycle_revised_plan.md")


def terminal_run_for_cycle_close(run: dict) -> bool:
    status = str(run.get("status", ""))
    terminal = {"collected", "reflected", "revised", "merged", "abandoned", "cancelled", "failed", "timeout"}
    if status in terminal:
        return True
    return status == "blocked" and bool(run.get("non_counting_classification") or run.get("classification"))


def terminal_inactive_run(run: dict) -> bool:
    status = str(run.get("status", ""))
    if status in {"abandoned", "cancelled", "failed", "timeout", "revised", "merged"}:
        return True
    return status == "blocked" and bool(run.get("non_counting_classification") or run.get("classification"))


def has_text(path) -> bool:
    return path.exists() and bool(path.read_text().strip())


def next_action_run_scope(state: dict, cycle_id: str) -> list[tuple[str, dict]]:
    runs = sorted(state.get("runs", {}).items())
    if not cycle_id:
        return runs
    current = [(run_id, run) for run_id, run in runs if run.get("cycle_id") == cycle_id]
    terminal = {"revised", "merged", "abandoned", "cancelled"}
    if any(run.get("status") not in terminal and not terminal_inactive_run(run) for _, run in current):
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


def active_jobs_fragment_sustained_round(paths: VibePaths, active: list[dict]) -> bool:
    """Prefer monitoring over planning when active jobs look like a split attempted round."""

    if not active:
        return False
    config = load_config(paths)
    min_routes = int(config.get("research", {}).get("sustained_min_routes_per_round", 3) or 3)
    if len(active) < min_routes:
        return False
    counts: dict[str, int] = {}
    for job in active:
        cycle_id = str(job.get("cycle_id") or "")
        if cycle_id:
            counts[cycle_id] = counts.get(cycle_id, 0) + 1
    if len(counts) <= 1:
        return False
    return max(counts.values()) < min_routes


def allow_prequeue_planning(paths: VibePaths, state: dict) -> bool:
    """Allow bounded non-submitting prep while active jobs fill capacity."""

    config = load_config(paths)
    scheduler = config.get("scheduler", {}) if isinstance(config.get("scheduler"), dict) else {}
    budget = read_yaml(paths.scheduler / "budget.yaml", {}) or {}
    scheduler = {**scheduler, **budget}
    if scheduler.get("prequeue_when_capacity_full", True) is False:
        return False
    max_prequeued = int(scheduler.get("max_prequeued_runs_when_full", 1))
    if max_prequeued <= 0:
        return False
    prep_statuses = {"generated", "reviewed", "branched", "branch_recorded_no_git", "patched", "dryrun_passed"}
    waiting_count = sum(1 for run in state.get("runs", {}).values() if run.get("status") in prep_statuses)
    if waiting_count:
        return waiting_count <= max_prequeued
    cycle_id = state.get("current_cycle_id", "")
    cycle_status = state.get("cycles", {}).get(cycle_id, {}).get("status", "") if cycle_id else ""
    if cycle_status in {"planned", "reviewed"}:
        return True
    terminal = {"revised", "merged", "abandoned", "cancelled"}
    return not cycle_id or cycle_status in terminal
