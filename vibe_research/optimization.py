"""Owned optimization, champion/challenger, ablation, and regression records."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from .io import append_jsonl, ensure_dir, next_numeric_id, read_json, read_jsonl, utc_now, write_json
from .paths import VibePaths
from .research_manager import load_evidence


class ChampionRecord(BaseModel):
    stage: str
    candidate_id: str
    candidate_type: str = "owned"
    evidence_ids: list[str] = Field(default_factory=list)
    protected_metric_gate: dict[str, Any] = Field(default_factory=dict)
    budget_policy_ok: bool = False
    rationale: str
    created_at: str = Field(default_factory=utc_now)


class ChallengerRecord(BaseModel):
    challenger_id: str
    stage: str
    candidate_id: str
    candidate_type: str = "owned"
    against_champion_id: str = ""
    rationale: str = ""
    created_at: str = Field(default_factory=utc_now)


class AblationRecord(BaseModel):
    ablation_id: str
    candidate_id: str
    ablation_key: str
    hypothesis: str
    expected_effect: str
    metrics_target: str
    protected_metric_risk: str
    rollback_plan: str
    status: str = "planned"
    memory_warning: str = ""
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_required_fields(self) -> "AblationRecord":
        missing = [key for key in ["hypothesis", "expected_effect", "metrics_target", "protected_metric_risk", "rollback_plan"] if not getattr(self, key)]
        if missing:
            raise ValueError("ablation missing fields: " + ", ".join(missing))
        return self


def optimization_dir(paths: VibePaths):
    return ensure_dir(paths.research / "optimization")


def optimization_paths(paths: VibePaths) -> dict[str, Any]:
    base = optimization_dir(paths)
    return {
        "champions": base / "champions.json",
        "challengers": base / "challengers.jsonl",
        "ablations": base / "ablations.jsonl",
        "regressions": base / "regression_suites.jsonl",
        "memory": base / "optimization_memory.jsonl",
        "external_deemphasis": base / "external_deemphasis.jsonl",
    }


def promote_champion(
    paths: VibePaths,
    *,
    stage: str,
    candidate_id: str,
    candidate_type: str = "owned",
    evidence_ids: list[str] | None = None,
    protected_metric_gate: dict[str, Any] | None = None,
    budget_policy_ok: bool = False,
    rationale: str = "",
) -> dict[str, Any]:
    blockers = []
    if not trusted_evidence_records(paths, evidence_ids or []):
        blockers.append("missing_trusted_evidence")
    if protected_metric_gate and protected_metric_gate.get("passed") is False:
        blockers.append("protected_metric_regression")
    if not budget_policy_ok:
        blockers.append("budget_policy_not_approved")
    if not rationale:
        blockers.append("missing_agent_rationale")
    result = {"created_at": utc_now(), "stage": stage, "candidate_id": candidate_id, "candidate_type": candidate_type, "promoted": not blockers, "blockers": blockers}
    if blockers:
        return result
    record = ChampionRecord(stage=stage, candidate_id=candidate_id, candidate_type=candidate_type, evidence_ids=evidence_ids or [], protected_metric_gate=protected_metric_gate or {}, budget_policy_ok=budget_policy_ok, rationale=rationale).model_dump()
    champions = read_json(optimization_paths(paths)["champions"], {})
    champions[stage] = record
    write_json(optimization_paths(paths)["champions"], champions)
    return {**result, "champion": record}


def register_challenger(paths: VibePaths, *, stage: str, candidate_id: str, candidate_type: str = "owned", against_champion_id: str = "", rationale: str = "") -> dict[str, Any]:
    file = optimization_paths(paths)["challengers"]
    existing = [row.get("challenger_id", "") for row in read_jsonl(file)]
    record = ChallengerRecord(challenger_id=next_numeric_id(existing, "challenger_"), stage=stage, candidate_id=candidate_id, candidate_type=candidate_type, against_champion_id=against_champion_id, rationale=rationale).model_dump()
    append_jsonl(file, record)
    return record


def plan_ablation(
    paths: VibePaths,
    *,
    candidate_id: str,
    ablation_key: str,
    hypothesis: str,
    expected_effect: str,
    metrics_target: str,
    protected_metric_risk: str,
    rollback_plan: str,
) -> dict[str, Any]:
    warning = repeated_failed_ablation_warning(paths, ablation_key)
    file = optimization_paths(paths)["ablations"]
    existing = [row.get("ablation_id", "") for row in read_jsonl(file)]
    record = AblationRecord(
        ablation_id=next_numeric_id(existing, "ablation_"),
        candidate_id=candidate_id,
        ablation_key=ablation_key,
        hypothesis=hypothesis,
        expected_effect=expected_effect,
        metrics_target=metrics_target,
        protected_metric_risk=protected_metric_risk,
        rollback_plan=rollback_plan,
        memory_warning=warning,
    ).model_dump()
    append_jsonl(file, record)
    return record


def record_regression_suite(paths: VibePaths, *, candidate_id: str, stage: str, checks: dict[str, bool], champion_comparison: dict[str, Any] | None = None) -> dict[str, Any]:
    passed = all(checks.values()) and bool(checks)
    record = {"created_at": utc_now(), "candidate_id": candidate_id, "stage": stage, "checks": checks, "champion_comparison": champion_comparison or {}, "passed": passed, "blocks_larger_stage": not passed}
    append_jsonl(optimization_paths(paths)["regressions"], record)
    return record


def record_optimization_memory(paths: VibePaths, *, ablation_key: str, outcome: str, metric_effects: dict[str, Any] | None = None, side_effects: list[str] | None = None, conditions: dict[str, Any] | None = None, rationale: str = "") -> dict[str, Any]:
    record = {"created_at": utc_now(), "ablation_key": ablation_key, "outcome": outcome, "metric_effects": metric_effects or {}, "side_effects": side_effects or [], "conditions": conditions or {}, "rationale": rationale}
    append_jsonl(optimization_paths(paths)["memory"], record)
    return record


def external_deemphasis_plan(paths: VibePaths, *, proposed_external_ratio: float, policy_allowed: bool, rationale: str, keep_periodic_regression: bool = True) -> dict[str, Any]:
    blockers = []
    if not policy_allowed:
        blockers.append("policy_does_not_allow_external_deemphasis")
    if not rationale:
        blockers.append("missing_rationale")
    if not keep_periodic_regression:
        blockers.append("external_baseline_regression_must_remain_scheduled")
    record = {"created_at": utc_now(), "proposed_external_ratio": proposed_external_ratio, "policy_allowed": policy_allowed, "rationale": rationale, "keep_periodic_regression": keep_periodic_regression, "approved": not blockers, "blockers": blockers}
    append_jsonl(optimization_paths(paths)["external_deemphasis"], record)
    return record


def repeated_failed_ablation_warning(paths: VibePaths, ablation_key: str) -> str:
    failures = [row for row in read_jsonl(optimization_paths(paths)["memory"]) if row.get("ablation_key") == ablation_key and row.get("outcome") in {"failed", "negative", "regressed"}]
    if failures:
        return "repeated_failed_ablation_requires_new_rationale"
    return ""


def trusted_evidence_records(paths: VibePaths, evidence_ids: list[str]) -> list[dict[str, Any]]:
    ids = set(evidence_ids)
    return [row for row in load_evidence(paths).values() if row.get("evidence_id") in ids and row.get("trusted") and row.get("schema_valid")]
