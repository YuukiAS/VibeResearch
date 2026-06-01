"""Structured research decision contracts."""

from __future__ import annotations

import json
import re
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
    "blocked_missing_artifact_adapter",
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
    "blocked_missing_artifact_adapter",
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
        existing = load_decision(paths, target_id)
        artifact_guard = artifact_only_promotion_guard_decision(paths, target_id, existing.decision_type)
        if artifact_guard:
            write_decision(paths, artifact_guard)
            return artifact_guard
        guard = metrics_reflection_guard_decision(paths, target_id, existing.decision_type)
        if existing.decision_type == "promote_to_baseline_compare" and guard:
            write_decision(paths, guard)
            return guard
        return existing
    if offline:
        if offline_run_has_trusted_candidate_metrics(paths, target_id):
            decision = make_decision(
                paths,
                target_id,
                "collect_more_metrics",
                rationale="Offline revised-plan fallback preserved trusted candidate metrics without inventing a promotion or stop decision.",
                required_action="hand schema-valid metrics to run and cycle reflection",
                metrics_requirements={"required": []},
                provenance={"source": "offline_revise_trusted_candidate_guard"},
                confidence="low",
            )
            write_decision(paths, decision)
            return decision
        return write_block_decision(paths, target_id, "offline fallback cannot make a structured research decision", decision_type="blocked_missing_decision")
    decision_type = infer_decision_type(markdown_text)
    if decision_type == "blocked_missing_artifact_adapter":
        decision = make_artifact_adapter_block_decision(paths, target_id, markdown_text)
        write_decision(paths, decision)
        set_block_state(paths, target_id, decision.rationale, decision.decision_type)
        return decision
    artifact_guard = artifact_only_promotion_guard_decision(paths, target_id, decision_type)
    if artifact_guard:
        write_decision(paths, artifact_guard)
        return artifact_guard
    guard = metrics_reflection_guard_decision(paths, target_id, decision_type, markdown_text=markdown_text)
    if guard:
        write_decision(paths, guard)
        return guard
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


def make_artifact_adapter_block_decision(paths: VibePaths, target_id: str, text: str) -> ResearchDecision:
    directions = artifact_adapter_directions(text)
    rationale = "Cycle artifacts diagnose a missing artifact adapter; this is a local framework/adapter repair route, not a collect-more-metrics request."
    if directions:
        rationale += " Missing artifact directions: " + ", ".join(directions)
    return make_decision(
        paths,
        target_id,
        "blocked_missing_artifact_adapter",
        rationale=rationale,
        blocking_questions=directions or ["repair or enable the local artifact adapter for the requested artifact-only work"],
        expected_evidence={"artifact_adapter_directions": directions, "reference_only_valid": "reference_only" in text.lower()},
        provenance={"source": "artifact_adapter_diagnosis", "directions": directions},
        confidence="blocked",
    )


def artifact_adapter_directions(text: str) -> list[str]:
    directions: list[str] = []
    for token in re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)*_repair\b", text.lower()):
        if token not in directions:
            directions.append(token)
    return directions


def artifact_only_promotion_guard_decision(paths: VibePaths, target_id: str, inferred_decision_type: str) -> ResearchDecision | None:
    if inferred_decision_type != "promote_to_baseline_compare" or not target_id.startswith("r"):
        return None
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(target_id, {}) if isinstance(state.get("runs"), dict) else {}
    metadata = run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata"), dict) else {}
    if run.get("run_kind") != "artifact_only" and not metadata.get("no_job"):
        return None
    return make_decision(
        paths,
        target_id,
        "collect_more_metrics",
        rationale="Artifact-only/no-job runs record local analysis artifacts and must not be promoted to baseline comparison from Markdown text alone.",
        required_action="review artifact output and continue artifact-only closure",
        expected_evidence={"artifact_only": True, "no_job": bool(metadata.get("no_job"))},
        metrics_requirements={"required": ["schema_valid_artifact_output"]},
        provenance={"source": "artifact_only_promotion_guard", "inferred_decision_type": inferred_decision_type},
        confidence="medium",
    )


def metrics_reflection_guard_decision(
    paths: VibePaths,
    target_id: str,
    inferred_decision_type: str,
    *,
    markdown_text: str = "",
) -> ResearchDecision | None:
    if not target_id.startswith("r"):
        return None
    metrics = read_json(paths.runs / target_id / "metrics.json", {})
    if not isinstance(metrics, dict) or not metrics:
        return None
    reflection_text = read_reflection_verdict_text(paths, target_id, markdown_text)
    explicit_no_promote = any(token in reflection_text for token in ("do_not_promote", "failed_stop_or_redesign", "route_exhausted", "needs_new_hypothesis"))
    untrusted = metrics_are_untrusted(metrics)
    negative_delta = primary_delta_is_negative(metrics)
    if not (explicit_no_promote or untrusted or negative_delta):
        return None
    if inferred_decision_type != "promote_to_baseline_compare" and not (explicit_no_promote and negative_delta):
        return None
    if explicit_no_promote or negative_delta:
        return make_decision(
            paths,
            target_id,
            "stop_direction",
            rationale="Collected metrics or reflection verdict reject promotion; the route needs redesign before another launch.",
            selected_direction="failed_stop_or_redesign",
            expected_evidence={"negative_primary_delta": negative_delta, "untrusted_metrics": untrusted, "reflection_no_promote": explicit_no_promote},
            metrics_requirements={"required": ["trusted_non_negative_baseline_delta"]},
            provenance={"source": "metrics_reflection_guard", "inferred_decision_type": inferred_decision_type},
            confidence="medium",
        )
    return make_decision(
        paths,
        target_id,
        "collect_more_metrics",
        rationale="Untrusted collected metrics cannot promote a run to baseline comparison.",
        required_action="collect trusted schema-valid metrics before promotion",
        expected_evidence={"untrusted_metrics": True},
        metrics_requirements={"required": ["trusted_metrics"]},
        provenance={"source": "metrics_trust_guard", "inferred_decision_type": inferred_decision_type},
        confidence="medium",
    )


def read_reflection_verdict_text(paths: VibePaths, target_id: str, markdown_text: str) -> str:
    parts = [markdown_text]
    for filename in ("reflect.md", "revised_plan.md", "review.md"):
        path = paths.runs / target_id / filename
        if path.exists():
            parts.append(path.read_text())
    return "\n".join(parts).lower()


def metrics_are_untrusted(metrics: dict[str, Any]) -> bool:
    trust_status = str(metrics.get("trust_status") or metrics.get("trust") or metrics.get("trust_level") or "").lower()
    if trust_status == "untrusted":
        return True
    if metrics.get("trusted") is False or metrics.get("trusted_candidate") is False:
        return True
    return False


def primary_delta_is_negative(metrics: dict[str, Any]) -> bool:
    candidates = [
        metrics.get("primary"),
        metrics.get("primary_delta"),
        metrics.get("delta_primary"),
        nested_get(metrics, "metrics", "primary"),
        nested_get(metrics, "metric_delta", "primary"),
        nested_get(metrics, "metric_deltas", "primary"),
        nested_get(metrics, "metrics", "metric_delta", "primary"),
        nested_get(metrics, "metrics", "metric_deltas", "primary"),
    ]
    return any(is_negative_number(value) for value in candidates)


def nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def is_negative_number(value: Any) -> bool:
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False


def offline_run_has_trusted_candidate_metrics(paths: VibePaths, target_id: str) -> bool:
    if not target_id.startswith("r"):
        return False
    metrics = read_json(paths.runs / target_id / "metrics.json", {})
    return bool(
        metrics.get("schema_status") == "valid"
        and not metrics.get("missing_metrics")
        and (metrics.get("trusted_candidate") or metrics.get("trusted") or metrics.get("schema_valid"))
    )


def infer_decision_type(text: str) -> DecisionType:
    lowered = text.lower()
    if "blocked_missing_artifact_adapter" in lowered or "patch_required_artifact_adapter_repair" in lowered:
        return "blocked_missing_artifact_adapter"
    if "reference_only" in lowered:
        return "stop_direction"
    if "failed_stop_or_redesign" in lowered or "route_exhausted" in lowered or "needs_new_hypothesis" in lowered or "do_not_promote" in lowered:
        return "stop_direction"
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
