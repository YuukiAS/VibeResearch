"""Decision-to-execution compiler."""

from __future__ import annotations

from typing import Any

from .adapters import get_adapter, validate_compiled_plan
from .decisions import EXECUTABLE_DECISIONS, ResearchDecision, load_decision, write_block_decision
from .io import read_json, read_yaml, utc_now, write_json, write_yaml
from .paths import VibePaths
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
        block_type = result.block_type if result.block_type in {"blocked_missing_adapter", "blocked_missing_resource_plan"} else "blocked_missing_resource_plan"
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


def validate_resource_plan(paths: VibePaths, cycle_id: str) -> list[str]:
    plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
    if not isinstance(plan, dict):
        return [f"{cycle_id}: resource_plan.yaml is not a mapping"]
    return [f"{cycle_id}: {error}" for error in validate_compiled_plan(plan)]


def resource_plan_is_compiled(paths: VibePaths, cycle_id: str) -> bool:
    plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
    return isinstance(plan, dict) and bool(plan.get("decision_id")) and not validate_compiled_plan(plan)
