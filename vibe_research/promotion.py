"""Decision-to-execution compiler."""

from __future__ import annotations

from typing import Any

from .adapters import get_adapter, validate_compiled_plan
from .decisions import BLOCK_DECISIONS, EXECUTABLE_DECISIONS, ResearchDecision, load_decision, make_decision, write_block_decision, write_decision
from .io import read_json, read_yaml, utc_now, write_json, write_yaml
from .paths import VibePaths
from .real_experiments import REAL_EXPERIMENT_TASKS
from .timeline import record_event


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
    active_real = [cap for cap in manifest.capabilities if cap.status == "active" and cap.task_type in REAL_EXPERIMENT_TASKS]
    if not active_real:
        write_real_experiment_gap_report(paths)
        return make_decision(
            paths,
            cycle_id,
            "blocked_missing_capability",
            rationale="No active real-experiment capability can compile this cycle; complete adapter_real_experiment_gaps.md",
            blocking_questions=["complete adapter_real_experiment_gaps.md"],
            confidence="blocked",
            provenance={"source": "deterministic_auto_compile"},
        )
    capability = sorted(active_real, key=lambda cap: (int(cap.resources.default.get("gpu", 0) or 0), cap.id))[0]
    baseline = capability.artifact_rules.baseline_target_provenance or capability.outputs.get("baseline_comparison_target", "")
    return make_decision(
        paths,
        cycle_id,
        "collect_more_metrics",
        rationale="deterministic cycle decision synthesized from an active real-experiment adapter capability",
        selected_direction=capability.id,
        required_action=capability.description or f"run {capability.id}",
        baseline_comparison_target=baseline,
        resource_intent={"capability_id": capability.id, "task_type": capability.task_type, "source": "auto_compile"},
        provenance={"source": "deterministic_auto_compile", "capability_id": capability.id},
    )


def validate_resource_plan(paths: VibePaths, cycle_id: str) -> list[str]:
    plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
    if not isinstance(plan, dict):
        return [f"{cycle_id}: resource_plan.yaml is not a mapping"]
    return [f"{cycle_id}: {error}" for error in validate_compiled_plan(plan)]


def resource_plan_is_compiled(paths: VibePaths, cycle_id: str) -> bool:
    plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
    return isinstance(plan, dict) and bool(plan.get("decision_id")) and not validate_compiled_plan(plan)
