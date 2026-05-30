"""Anti-loop detection for fake progress."""

from __future__ import annotations

import re
from typing import Any

from .config import load_config
from .decisions import write_block_decision
from .io import read_json, read_jsonl, read_yaml
from .paths import VibePaths
from .adapters import validate_compiled_plan
from .timeline import record_event


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def detect_repeating_evidence(paths: VibePaths) -> tuple[bool, str]:
    config = load_config(paths)
    threshold = int(config.get("loop_guard", {}).get("repeated_threshold", 2))
    decisions = read_jsonl(paths.state / "decisions.jsonl")
    recent_decisions = [row for row in decisions if row.get("decision_type") in {"collect_more_metrics", "blocked_missing_decision", "blocked_missing_adapter"}][-threshold:]
    if len(recent_decisions) >= threshold and len({row.get("decision_type") for row in recent_decisions}) == 1:
        return True, f"same decision repeated {threshold} times: {recent_decisions[-1].get('decision_type')}"
    state = read_json(paths.state / "state.json", {})
    runs = list(state.get("runs", {}).items())[-threshold:]
    hypotheses = [normalize(run.get("hypothesis", "")) for _run_id, run in runs]
    if len(hypotheses) >= threshold and len(set(hypotheses)) == 1 and hypotheses[0]:
        return True, f"same run hypothesis repeated {threshold} times"
    history = read_jsonl(paths.leaderboard / "history.jsonl")[-threshold:]
    if len(history) >= threshold and all((not row.get("trusted")) and float(row.get("primary_metric", 0.0) or 0.0) == 0.0 for row in history):
        return True, f"untrusted default primary_metric=0.0 repeated {threshold} times"
    all_history = read_jsonl(paths.leaderboard / "history.jsonl")
    has_trusted = any(row.get("trusted") for row in all_history)
    cycle_ids = list(state.get("cycles", {}).keys())[-threshold:]
    plan_texts = []
    invalid_plans = []
    for cycle_id in cycle_ids:
        plan_path = paths.cycles / cycle_id / "portfolio_plan.md"
        if plan_path.exists():
            plan_texts.append(normalize(plan_path.read_text()))
        resource_plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
        if not isinstance(resource_plan, dict) or validate_compiled_plan(resource_plan):
            invalid_plans.append(cycle_id)
    if len(plan_texts) >= threshold and len(set(plan_texts)) == 1 and not has_trusted:
        return True, f"same portfolio plan repeated {threshold} times without trusted metrics"
    if len(invalid_plans) >= threshold and not has_trusted:
        return True, f"resource plan missing or placeholder for {threshold} recent cycles without trusted metrics"
    return False, ""


def apply_loop_guard(paths: VibePaths, target_id: str) -> bool:
    triggered, reason = detect_repeating_evidence(paths)
    if not triggered:
        return False
    write_block_decision(paths, target_id, reason, decision_type="blocked_repeating_evidence")
    record_event(paths, "blocked_repeating_evidence", reason, cycle_id=target_id if target_id.startswith("c") else "", run_id=target_id if target_id.startswith("r") else "", status="blocked_repeating_evidence")
    return True
