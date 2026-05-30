"""Structured research decision contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from .io import append_jsonl, ensure_dir, next_numeric_id, read_json, read_jsonl, utc_now, write_json
from .paths import VibePaths
from .timeline import record_event


DecisionType = Literal[
    "collect_more_metrics",
    "launch_gpu_gate",
    "promote_to_baseline_compare",
    "stop_direction",
    "request_deep_research",
    "ask_user",
    "blocked_missing_decision",
    "blocked_missing_adapter",
    "blocked_missing_capability",
    "blocked_missing_script",
    "blocked_missing_metrics_schema",
    "blocked_missing_user_answer",
    "blocked_contract_test_failed",
    "blocked_resource_policy",
    "blocked_missing_resource_plan",
    "blocked_repeating_evidence",
]
TargetType = Literal["run", "cycle"]
Confidence = Literal["low", "medium", "high", "blocked"]


BLOCK_DECISIONS = {
    "blocked_missing_decision",
    "blocked_missing_adapter",
    "blocked_missing_capability",
    "blocked_missing_script",
    "blocked_missing_metrics_schema",
    "blocked_missing_user_answer",
    "blocked_contract_test_failed",
    "blocked_resource_policy",
    "blocked_missing_resource_plan",
    "blocked_repeating_evidence",
}
EXECUTABLE_DECISIONS = {"collect_more_metrics", "launch_gpu_gate", "promote_to_baseline_compare"}


class ResearchDecision(BaseModel):
    decision_id: str
    target_type: TargetType
    target_id: str
    decision_type: DecisionType
    rationale: str = ""
    selected_direction: str = ""
    required_action: str = ""
    expected_evidence: dict[str, Any] = Field(default_factory=dict)
    resource_intent: dict[str, Any] = Field(default_factory=dict)
    metrics_requirements: dict[str, Any] = Field(default_factory=dict)
    baseline_comparison_target: str = ""
    hypothesis_id: str = ""
    experiment_id: str = ""
    policy_eval_id: str = ""
    budget_reservation_id: str = ""
    stage: str = ""
    blocking_questions: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str

    @model_validator(mode="after")
    def validate_decision_contract(self) -> "ResearchDecision":
        if self.decision_type in EXECUTABLE_DECISIONS and not self.required_action:
            raise ValueError("required_action is required for executable decisions")
        if self.decision_type == "promote_to_baseline_compare" and not self.baseline_comparison_target:
            raise ValueError("baseline_comparison_target is required for baseline comparison decisions")
        if self.decision_type in BLOCK_DECISIONS and not (self.rationale or self.blocking_questions):
            raise ValueError("block decisions require rationale or blocking_questions")
        return self


def decision_path(paths: VibePaths, target_id: str) -> Path:
    if target_id.startswith("r"):
        return paths.runs / target_id / "decision.json"
    if target_id.startswith("c"):
        return paths.cycles / target_id / "cycle_decision.json"
    raise ValueError(f"Unsupported decision target: {target_id}")


def target_type_for(target_id: str) -> TargetType:
    if target_id.startswith("r"):
        return "run"
    if target_id.startswith("c"):
        return "cycle"
    raise ValueError(f"Unsupported decision target: {target_id}")


def next_decision_id(paths: VibePaths) -> str:
    existing = [row.get("decision_id", "") for row in read_jsonl(paths.state / "decisions.jsonl")]
    return next_numeric_id(existing, "decision_")


def make_decision(
    paths: VibePaths,
    target_id: str,
    decision_type: DecisionType,
    *,
    rationale: str = "",
    selected_direction: str = "",
    required_action: str = "",
    expected_evidence: dict[str, Any] | None = None,
    resource_intent: dict[str, Any] | None = None,
    metrics_requirements: dict[str, Any] | None = None,
    baseline_comparison_target: str = "",
    hypothesis_id: str = "",
    experiment_id: str = "",
    policy_eval_id: str = "",
    budget_reservation_id: str = "",
    stage: str = "",
    blocking_questions: list[str] | None = None,
    confidence: Confidence = "medium",
    provenance: dict[str, Any] | None = None,
) -> ResearchDecision:
    return ResearchDecision(
        decision_id=next_decision_id(paths),
        target_type=target_type_for(target_id),
        target_id=target_id,
        decision_type=decision_type,
        rationale=rationale,
        selected_direction=selected_direction,
        required_action=required_action,
        expected_evidence=expected_evidence or {},
        resource_intent=resource_intent or {},
        metrics_requirements=metrics_requirements or {},
        baseline_comparison_target=baseline_comparison_target,
        hypothesis_id=hypothesis_id,
        experiment_id=experiment_id,
        policy_eval_id=policy_eval_id,
        budget_reservation_id=budget_reservation_id,
        stage=stage,
        blocking_questions=blocking_questions or [],
        confidence=confidence,
        provenance=provenance or {},
        created_at=utc_now(),
    )


def write_decision(paths: VibePaths, decision: ResearchDecision) -> Path:
    path = decision_path(paths, decision.target_id)
    write_json(path, decision.model_dump())
    append_jsonl(paths.state / "decisions.jsonl", decision.model_dump())
    event = "decision_blocked" if decision.decision_type in BLOCK_DECISIONS else "decision_written"
    record_event(
        paths,
        event,
        f"{decision.target_id}: {decision.decision_type}",
        cycle_id=decision.target_id if decision.target_type == "cycle" else "",
        run_id=decision.target_id if decision.target_type == "run" else "",
        status=decision.decision_type,
        payload=decision.model_dump(),
    )
    return path


def write_block_decision(paths: VibePaths, target_id: str, reason: str, *, decision_type: DecisionType = "blocked_missing_decision") -> ResearchDecision:
    if decision_type not in BLOCK_DECISIONS:
        raise ValueError(f"{decision_type} is not a block decision")
    decision = make_decision(
        paths,
        target_id,
        decision_type,
        rationale=reason,
        blocking_questions=[reason],
        confidence="blocked",
        provenance={"source": "deterministic_block"},
    )
    write_decision(paths, decision)
    set_block_state(paths, target_id, reason, decision_type)
    return decision


def set_block_state(paths: VibePaths, target_id: str, reason: str, status: str) -> None:
    state = read_json(paths.state / "state.json", {})
    state["blocked_reason"] = reason
    state["status"] = status
    if target_id.startswith("r"):
        state.setdefault("runs", {}).setdefault(target_id, {})["status"] = "blocked"
        state["next_action"] = f"vibe decision show {target_id}"
    elif target_id.startswith("c"):
        state.setdefault("cycles", {}).setdefault(target_id, {})["status"] = "blocked"
        state["next_action"] = f"vibe decision show {target_id}"
    else:
        state["next_action"] = "vibe decision show <target_id>"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)


def load_decision(paths: VibePaths, target_id: str) -> ResearchDecision:
    data = read_json(decision_path(paths, target_id), {})
    if not data:
        raise ValueError(f"missing decision for {target_id}")
    return ResearchDecision.model_validate(data)


def validate_decision_file(paths: VibePaths, target_id: str) -> list[str]:
    try:
        load_decision(paths, target_id)
        return []
    except ValidationError as exc:
        return [f"{target_id}: {'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()]
    except Exception as exc:
        return [f"{target_id}: {exc}"]


def decision_json(paths: VibePaths, target_id: str) -> str:
    return json.dumps(load_decision(paths, target_id).model_dump(), indent=2, sort_keys=True) + "\n"


def ensure_decision_after_revise(paths: VibePaths, target_id: str, markdown_text: str, *, offline: bool = False) -> ResearchDecision:
    existing_path = decision_path(paths, target_id)
    if existing_path.exists() and existing_path.read_text().strip():
        return load_decision(paths, target_id)
    if offline:
        return write_block_decision(paths, target_id, "offline fallback cannot make a structured research decision", decision_type="blocked_missing_decision")
    decision_type = infer_decision_type(markdown_text)
    if decision_type in BLOCK_DECISIONS:
        return write_block_decision(paths, target_id, f"Markdown plan inferred {decision_type}", decision_type=decision_type)
    decision = make_decision(
        paths,
        target_id,
        decision_type,
        rationale="Derived from revised-plan Markdown; operator should review structured fields before scheduling.",
        required_action=decision_type,
        metrics_requirements={"required": []},
        baseline_comparison_target="trusted_baseline" if decision_type == "promote_to_baseline_compare" else "",
        provenance={"source": "markdown_inference"},
        confidence="low",
    )
    write_decision(paths, decision)
    return decision


def infer_decision_type(text: str) -> DecisionType:
    lowered = text.lower()
    if "deep_research_needed" in lowered or "deep research: yes" in lowered:
        return "request_deep_research"
    if "ask_user" in lowered:
        return "ask_user"
    if "stop_branch" in lowered:
        return "stop_direction"
    if "merge_candidate" in lowered or "baseline" in lowered:
        return "promote_to_baseline_compare"
    if "gpu" in lowered and "gate" in lowered:
        return "launch_gpu_gate"
    if "collect_more_metrics" in lowered:
        return "collect_more_metrics"
    return "blocked_missing_decision"
