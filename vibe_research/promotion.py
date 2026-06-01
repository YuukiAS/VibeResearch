"""Decision-to-execution compiler."""

from __future__ import annotations

import re
from typing import Any

from .adapters import get_adapter, validate_compiled_plan
from .config import load_config
from .decisions import BLOCK_DECISIONS, EXECUTABLE_DECISIONS, ResearchDecision, load_decision, make_decision, write_block_decision, write_decision
from .io import read_json, read_yaml, utc_now, write_json, write_yaml
from .paths import VibePaths
from .real_experiments import REAL_EXPERIMENT_TASKS
from .timeline import record_event


PREFERRED_DECISIONS_BY_TASK = {
    "evaluation_smoke": ["collect_more_metrics"],
    "metrics_export": ["collect_more_metrics"],
    "baseline_compare": ["promote_to_baseline_compare", "collect_more_metrics"],
    "train_smoke": ["launch_gpu_gate"],
    "train_gate": ["launch_gpu_gate"],
    "long_run_submit": ["launch_gpu_gate"],
}


def capability_baseline_target(capability: Any) -> str:
    rules = getattr(capability, "artifact_rules", None)
    outputs = getattr(capability, "outputs", {}) or {}
    return str(getattr(rules, "baseline_target_provenance", "") or outputs.get("baseline_comparison_target", ""))


def select_executable_decision_for_capability(capability: Any) -> str:
    supported = [decision for decision in getattr(capability, "supported_decisions", []) if decision in EXECUTABLE_DECISIONS]
    if not supported:
        return ""
    preferred = PREFERRED_DECISIONS_BY_TASK.get(getattr(capability, "task_type", ""), [])
    for decision in preferred + supported:
        if decision not in supported:
            continue
        if decision == "promote_to_baseline_compare" and not capability_baseline_target(capability):
            continue
        return decision
    return ""


def capability_run_counts(paths: VibePaths) -> dict[str, int]:
    state = read_json(paths.state / "state.json", {})
    counts: dict[str, int] = {}
    for run in state.get("runs", {}).values():
        metadata = run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata"), dict) else {}
        capability_id = metadata.get("capability_id")
        if capability_id:
            counts[capability_id] = counts.get(capability_id, 0) + 1
    return counts


def compile_decision(paths: VibePaths, cycle_id: str) -> tuple[bool, str]:
    try:
        decision = load_decision(paths, cycle_id)
    except Exception as exc:
        write_block_decision(paths, cycle_id, f"Cannot compile without a valid cycle decision: {exc}", decision_type="blocked_missing_decision")
        record_event(paths, "resource_plan_blocked", f"{cycle_id}: missing decision", cycle_id=cycle_id, status="blocked_missing_decision")
        return False, f"missing decision: {exc}"
    if decision.decision_type not in EXECUTABLE_DECISIONS:
        reason = f"Decision {decision.decision_type} is not executable; no resource plan can be compiled"
        write_block_decision(paths, cycle_id, reason, decision_type="blocked_missing_resource_plan")
        record_event(paths, "resource_plan_blocked", f"{cycle_id}: non-executable decision", cycle_id=cycle_id, status="blocked_missing_resource_plan")
        return False, reason
    adapter = get_adapter(paths)
    result = adapter.compile_decision(decision, cycle_id)
    if not result.ok or not result.plan:
        allowed_blocks = {
            "blocked_missing_adapter",
            "blocked_missing_resource_plan",
            "blocked_missing_capability",
            "blocked_missing_script",
            "blocked_missing_metrics_schema",
            "blocked_missing_user_answer",
            "blocked_contract_test_failed",
            "blocked_resource_policy",
        }
        block_type = result.block_type if result.block_type in allowed_blocks else "blocked_missing_resource_plan"
        write_block_decision(paths, cycle_id, result.block_reason or "compiler failed", decision_type=block_type)
        record_event(paths, "resource_plan_blocked", f"{cycle_id}: {result.block_reason}", cycle_id=cycle_id, status=block_type)
        return False, result.block_reason
    errors = validate_compiled_plan(result.plan)
    if errors:
        reason = "; ".join(errors)
        write_block_decision(paths, cycle_id, reason, decision_type="blocked_missing_resource_plan")
        record_event(paths, "resource_plan_blocked", f"{cycle_id}: {reason}", cycle_id=cycle_id, status="blocked_missing_resource_plan")
        return False, reason
    write_yaml(paths.cycles / cycle_id / "resource_plan.yaml", result.plan)
    state = read_json(paths.state / "state.json", {})
    state.setdefault("cycles", {}).setdefault(cycle_id, {})["compiled_decision_id"] = decision.decision_id
    state["blocked_reason"] = ""
    active_jobs = read_json(paths.scheduler / "active_jobs.json", {"active": []}).get("active", [])
    if active_jobs:
        state["status"] = "jobs_active"
        state["next_action"] = "vibe monitor"
    else:
        state["next_action"] = f"vibe generate-runs {cycle_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "resource_plan_compiled", f"Compiled {cycle_id} using {adapter.kind} adapter", cycle_id=cycle_id, status="compiled", payload={"decision_id": decision.decision_id})
    return True, str(paths.cycles / cycle_id / "resource_plan.yaml")


def ensure_executable_resource_plan(paths: VibePaths, cycle_id: str) -> tuple[bool, str]:
    """Compile a cycle plan if it is missing or still a placeholder."""

    if resource_plan_is_compiled(paths, cycle_id):
        return True, str(paths.cycles / cycle_id / "resource_plan.yaml")
    existing_plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
    if isinstance(existing_plan, dict) and existing_plan.get("runs") and not validate_compiled_plan(existing_plan):
        return True, str(paths.cycles / cycle_id / "resource_plan.yaml")
    decision = load_or_synthesize_cycle_decision(paths, cycle_id)
    if decision.decision_type not in EXECUTABLE_DECISIONS:
        return compile_decision(paths, cycle_id)
    return compile_decision(paths, cycle_id)


def load_or_synthesize_cycle_decision(paths: VibePaths, cycle_id: str) -> ResearchDecision:
    try:
        existing = load_decision(paths, cycle_id)
        if existing.decision_type in EXECUTABLE_DECISIONS:
            return existing
        if existing.decision_type not in BLOCK_DECISIONS:
            return existing
    except Exception:
        pass
    decision = synthesize_cycle_decision(paths, cycle_id)
    write_decision(paths, decision)
    record_event(paths, "cycle_decision_synthesized", f"Synthesized executable decision for {cycle_id}", cycle_id=cycle_id, status=decision.decision_type, payload=decision.model_dump())
    return decision


def synthesize_cycle_decision(paths: VibePaths, cycle_id: str) -> ResearchDecision:
    from .adapter_schema import load_adapter_manifest
    from .adapter_onboarding import write_real_experiment_gap_report

    manifest = load_adapter_manifest(paths)
    active_real = [
        cap
        for cap in manifest.capabilities
        if cap.status == "active"
        and cap.task_type in REAL_EXPERIMENT_TASKS
        and select_executable_decision_for_capability(cap)
    ]
    if not active_real:
        write_real_experiment_gap_report(paths)
        return make_decision(
            paths,
            cycle_id,
            "blocked_missing_capability",
            rationale="No active real-experiment capability has an executable supported decision; complete adapter_real_experiment_gaps.md",
            blocking_questions=["complete adapter_real_experiment_gaps.md"],
            confidence="blocked",
            provenance={"source": "deterministic_auto_compile"},
        )
    config = load_config(paths)
    min_routes = int(config.get("research", {}).get("sustained_min_routes_per_round", 3) or 3)
    by_decision: dict[str, list[Any]] = {}
    for cap in active_real:
        decision_type = select_executable_decision_for_capability(cap)
        if decision_type:
            by_decision.setdefault(decision_type, []).append(cap)
    multi_route_groups = [group for group in by_decision.values() if len(group) >= min_routes]
    if multi_route_groups:
        group = sorted(multi_route_groups, key=lambda rows: (-len(rows), rows[0].id))[0]
        caps = sorted(group, key=lambda cap: cap.id)
        repeated = latest_noncounting_multiroute_capability_set(paths, min_routes)
        if repeated and set(cap.id for cap in caps) == repeated:
            return make_decision(
                paths,
                cycle_id,
                "blocked_missing_capability",
                rationale="Active real-experiment capabilities exactly repeat the latest non-counting multi-route cycle; change capabilities, repair missing inputs, or provide an explicit override decision before repeating.",
                blocking_questions=[
                    "activate a genuinely changed executable capability, repair the non-counting cause, or write an explicit adapter decision to override the repeat guard"
                ],
                confidence="blocked",
                provenance={"source": "deterministic_auto_compile_multi_route_repeat_guard", "capability_ids": sorted(repeated)},
            )
        decision_type = select_executable_decision_for_capability(caps[0])
        return make_decision(
            paths,
            cycle_id,
            decision_type,
            rationale="deterministic multi-route cycle decision synthesized from active real-experiment adapter capabilities",
            selected_direction="",
            required_action="run a bounded multi-route portfolio across active capabilities",
            resource_intent={
                "capability_ids": [cap.id for cap in caps],
                "task_type": caps[0].task_type,
                "source": "auto_compile_multi_route",
                "min_routes_per_round": min_routes,
            },
            provenance={"source": "deterministic_auto_compile_multi_route", "capability_ids": [cap.id for cap in caps]},
        )
    run_counts = capability_run_counts(paths)
    capability = sorted(active_real, key=lambda cap: (run_counts.get(cap.id, 0), int(cap.resources.default.get("gpu", 0) or 0), cap.id))[0]
    decision_type = select_executable_decision_for_capability(capability)
    baseline = capability_baseline_target(capability)
    return make_decision(
        paths,
        cycle_id,
        decision_type,
        rationale="deterministic cycle decision synthesized from an active real-experiment adapter capability",
        selected_direction=capability.id,
        required_action=capability.description or f"run {capability.id}",
        baseline_comparison_target=baseline,
        resource_intent={"capability_id": capability.id, "task_type": capability.task_type, "source": "auto_compile"},
        provenance={"source": "deterministic_auto_compile", "capability_id": capability.id},
    )


def latest_noncounting_multiroute_capability_set(paths: VibePaths, min_routes: int) -> set[str]:
    state = read_json(paths.state / "state.json", {})
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    cycles = state.get("cycles", {}) if isinstance(state.get("cycles"), dict) else {}
    for cycle_id in sorted(cycles, reverse=True):
        cycle_runs = [run for run in runs.values() if isinstance(run, dict) and run.get("cycle_id") == cycle_id]
        if len(cycle_runs) < min_routes:
            continue
        capability_ids = {
            str((run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata"), dict) else {}).get("capability_id") or "")
            for run in cycle_runs
        }
        capability_ids = {capability_id for capability_id in capability_ids if capability_id}
        if len(capability_ids) < min_routes:
            continue
        if all(run_is_noncounting_terminal(run) for run in cycle_runs):
            return capability_ids
    return set()


def run_is_noncounting_terminal(run: dict[str, Any]) -> bool:
    if run.get("non_counting_classification") or run.get("classification"):
        return True
    status = str(run.get("status", ""))
    return status == "blocked" and bool(run.get("blocked_reason"))


def validate_resource_plan(paths: VibePaths, cycle_id: str) -> list[str]:
    plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
    if not isinstance(plan, dict):
        return [f"{cycle_id}: resource_plan.yaml is not a mapping"]
    errors = validate_compiled_plan(plan)
    explicit_actions = explicit_local_portfolio_actions_for_guard(paths, cycle_id)
    if explicit_actions and generic_placeholder_resource_plan_for_guard(plan):
        errors.append(
            "portfolio_plan.md contains explicit local/no-job actions "
            f"{', '.join(explicit_actions)} but resource_plan.yaml is still a generic placeholder"
        )
    return [f"{cycle_id}: {error}" for error in errors]


def resource_plan_is_compiled(paths: VibePaths, cycle_id: str) -> bool:
    plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
    return isinstance(plan, dict) and bool(plan.get("decision_id")) and not validate_compiled_plan(plan)


def explicit_local_portfolio_actions_for_guard(paths: VibePaths, cycle_id: str) -> list[str]:
    path = paths.cycles / cycle_id / "portfolio_plan.md"
    if not path.exists():
        return []
    text = path.read_text()
    lowered = text.lower()
    if not any(token in lowered for token in ("no long-running jobs", "no slurm", "no slurm submissions", "no gpu", "no_gpu_no_slurm", "local/no-job", "local no-job")):
        return []
    actions: list[str] = []
    seen: set[str] = set()
    stopwords = {"no_gpu", "no_slurm", "no_gpu_no_slurm", "long_running", "resource_plan", "baseline_check", "diagnostic_check", "first_hypothesis"}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("-", "*", "1.", "2.", "3.")) and "run " not in stripped.lower():
            continue
        for token in re.findall(r"`([a-z][a-z0-9]*(?:[_-][a-z0-9]+)+)`|\b([a-z][a-z0-9]*(?:[_-][a-z0-9]+)+)\b", stripped):
            candidate = next(part for part in token if part)
            action = candidate.strip("`").replace("-", "_").lower()
            if action in stopwords:
                continue
            if action not in seen:
                actions.append(action)
                seen.add(action)
    return actions


def generic_placeholder_resource_plan_for_guard(plan: dict[str, Any]) -> bool:
    runs = plan.get("runs", {}) if isinstance(plan.get("runs"), dict) else {}
    names = set(runs)
    return bool(names) and names.issubset({"baseline-check", "diagnostic-check", "first-hypothesis"})
