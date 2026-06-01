"""Final convergence policy and freeze gates."""

from __future__ import annotations

from typing import Any

from .io import append_jsonl, ensure_dir, read_json, read_jsonl, utc_now, write_json, write_text
from .paths import VibePaths
from .presentation import build_reproducibility_package, load_internal_capabilities, load_lineage_records, load_owned_records, presentation_paths
from .research_manager import load_evidence, research_paths


CONVERGENCE_STAGES = [
    "open_exploration",
    "dual_track_optimization",
    "owned_candidate_focus",
    "external_regression_only",
    "final_owned_freeze",
]
LATE_STAGES = {"owned_candidate_focus", "external_regression_only", "final_owned_freeze"}
BLOCKING_LATE_RISKS = {"protected_metric_risk", "reproducibility_risk", "large_external_method_addition", "core_mechanism_change"}


def convergence_dir(paths: VibePaths):
    return ensure_dir(paths.research / "convergence")


def convergence_paths(paths: VibePaths) -> dict[str, Any]:
    base = convergence_dir(paths)
    return {
        "state": base / "state.json",
        "history": base / "stage_history.jsonl",
        "freeze_checks": base / "freeze_checks.jsonl",
        "risk_gates": base / "risk_gates.jsonl",
        "dependency_audit": base / "dependency_audit.json",
        "overrides": base / "overrides.jsonl",
        "budget_closure": base / "budget_closure.json",
        "risk_review": base / "known_risk_review.md",
    }


def current_convergence_state(paths: VibePaths) -> dict[str, Any]:
    state = read_json(convergence_paths(paths)["state"], {})
    if not isinstance(state, dict) or not state:
        return {"stage": "open_exploration", "frozen": False, "updated_at": ""}
    state.setdefault("stage", "open_exploration")
    state.setdefault("frozen", state.get("stage") == "final_owned_freeze")
    return state


def set_convergence_stage(paths: VibePaths, stage: str, *, rationale: str = "", user_approved: bool = False) -> dict[str, Any]:
    if stage not in CONVERGENCE_STAGES:
        raise ValueError(f"unsupported convergence stage: {stage}")
    files = convergence_paths(paths)
    previous = current_convergence_state(paths)
    blockers: list[str] = []
    if stage == "final_owned_freeze":
        check = freeze_check(paths, user_approved=user_approved, known_risk_review=rationale, write=False)
        blockers.extend(check.get("blockers", []))
    record = {
        "created_at": utc_now(),
        "previous_stage": previous.get("stage", "open_exploration"),
        "stage": stage,
        "rationale": rationale,
        "user_approved": user_approved,
        "accepted": not blockers,
        "blockers": blockers,
    }
    append_jsonl(files["history"], record)
    if blockers:
        return record
    state = {"stage": stage, "frozen": stage == "final_owned_freeze", "rationale": rationale, "user_approved": user_approved, "updated_at": record["created_at"]}
    write_json(files["state"], state)
    return {**record, "state": state}


def freeze_check(
    paths: VibePaths,
    *,
    user_approved: bool = False,
    known_risk_review: str = "",
    budget_closed: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    files = convergence_paths(paths)
    blockers: list[str] = []
    warnings: list[str] = []
    evidence = load_evidence(paths)
    trusted = [row for row in evidence.values() if row.get("trusted") and row.get("schema_valid")]
    if not trusted:
        blockers.append("missing_trusted_evidence")
    if any(row.get("protected_metric_regressions") for row in trusted):
        blockers.append("protected_metric_instability")
    reproducibility = read_json(presentation_paths(paths)["reproducibility"], {})
    if not reproducibility.get("evidence_rows"):
        try:
            reproducibility = build_reproducibility_package(paths)
        except Exception:
            reproducibility = {}
    if not reproducibility.get("evidence_rows"):
        blockers.append("missing_reproducibility_package")
    elif reproducibility.get("untraceable_evidence_ids"):
        blockers.append("reproducibility_package_has_untraceable_evidence")
    budget_record = read_json(files["budget_closure"], {})
    if not (budget_closed or budget_record.get("status") == "closed"):
        blockers.append("budget_not_closed")
    risk_text = known_risk_review.strip() or (files["risk_review"].read_text().strip() if files["risk_review"].exists() else "")
    if not risk_text:
        blockers.append("missing_known_risk_review")
    if not user_approved:
        blockers.append("missing_user_approval")
    dependency_audit = read_json(files["dependency_audit"], {})
    if dependency_audit and not dependency_audit.get("main_path_sufficiently_owned"):
        warnings.append("external_dependency_audit_says_main_path_not_sufficiently_owned")
    result = {
        "created_at": utc_now(),
        "accepted": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "trusted_evidence_ids": [row.get("evidence_id", "") for row in trusted],
        "reproducibility_package": ".vibe/research/presentation/reproducibility_package.json" if reproducibility else "",
        "budget_closed": budget_closed or budget_record.get("status") == "closed",
        "known_risk_review_present": bool(risk_text),
        "user_approved": user_approved,
    }
    if write:
        append_jsonl(files["freeze_checks"], result)
        if result["accepted"]:
            set_convergence_stage(paths, "final_owned_freeze", rationale=risk_text, user_approved=True)
    return result


def close_convergence_budget(paths: VibePaths, *, rationale: str = "") -> dict[str, Any]:
    record = {"created_at": utc_now(), "status": "closed", "rationale": rationale}
    write_json(convergence_paths(paths)["budget_closure"], record)
    return record


def write_known_risk_review(paths: VibePaths, text: str) -> dict[str, Any]:
    record = {"created_at": utc_now(), "path": ".vibe/research/convergence/known_risk_review.md", "present": bool(text.strip())}
    write_text(convergence_paths(paths)["risk_review"], text.rstrip() + "\n")
    return record


def risk_gate(
    paths: VibePaths,
    *,
    change_type: str,
    stage: str | None = None,
    protected_metric_risk: bool = False,
    reproducibility_risk: bool = False,
    core_mechanism_change: bool = False,
    external_method_size: str = "none",
    override_id: str = "",
    rationale: str = "",
) -> dict[str, Any]:
    files = convergence_paths(paths)
    state = current_convergence_state(paths)
    active_stage = stage or state.get("stage", "open_exploration")
    risks = []
    if protected_metric_risk:
        risks.append("protected_metric_risk")
    if reproducibility_risk:
        risks.append("reproducibility_risk")
    if core_mechanism_change:
        risks.append("core_mechanism_change")
    if external_method_size in {"large", "major", "new_direction"}:
        risks.append("large_external_method_addition")
    override = find_valid_override(paths, override_id, risks, change_type)
    late = active_stage in LATE_STAGES
    decision = "allow"
    blockers: list[str] = []
    ask_user: list[str] = []
    if late and risks and not override:
        for risk in risks:
            if active_stage == "final_owned_freeze" or risk in {"protected_metric_risk", "reproducibility_risk", "large_external_method_addition"}:
                blockers.append(risk)
            else:
                ask_user.append(risk)
        decision = "block" if blockers else "ask_user"
    if active_stage == "external_regression_only" and change_type in {"external_exploration", "new_external_method"} and not override:
        blockers.append("stage_allows_external_regression_only")
        decision = "block"
    result = {
        "created_at": utc_now(),
        "stage": active_stage,
        "change_type": change_type,
        "decision": "allow" if override else decision,
        "risks": risks,
        "blockers": [] if override else blockers,
        "ask_user": [] if override else ask_user,
        "override_id": override.get("override_id", "") if override else "",
        "rationale": rationale,
    }
    append_jsonl(files["risk_gates"], result)
    return result


def dependency_audit(paths: VibePaths) -> dict[str, Any]:
    files = convergence_paths(paths)
    lineage = load_lineage_records(paths)
    internal_caps = load_internal_capabilities(paths)
    owned = load_owned_records(paths)
    dependencies = []
    for asset in lineage.get("external_assets", []):
        dependencies.append(classify_external_asset(asset))
    for cap in internal_caps:
        dependencies.append({"dependency_id": cap.get("capability_id", ""), "kind": "internal_capability", "classification": "owned_core", "source": cap.get("entrypoint", ""), "rationale": "repo-local internal capability"})
    for scaffold in owned.get("scaffolds", []):
        dependencies.append({"dependency_id": scaffold.get("proposal_id", ""), "kind": "owned_scaffold", "classification": "owned_core", "source": scaffold.get("framework_name", ""), "rationale": "owned framework scaffold"})
    necessary_external = [row for row in dependencies if row.get("kind") == "external_asset" and row.get("classification") == "necessary_dependency"]
    owned_signals = [row for row in dependencies if row.get("classification") == "owned_core"]
    audit = {
        "created_at": utc_now(),
        "dependencies": dependencies,
        "counts": count_by_classification(dependencies),
        "main_path_sufficiently_owned": bool(owned_signals) and not necessary_external,
        "owned_core_dependency_ids": [row.get("dependency_id", "") for row in owned_signals],
        "blocking_external_dependency_ids": [row.get("dependency_id", "") for row in necessary_external],
    }
    write_json(files["dependency_audit"], audit)
    return audit


def record_override(paths: VibePaths, *, target: str, reason: str, approved_by_user: bool, scope: list[str] | None = None) -> dict[str, Any]:
    files = convergence_paths(paths)
    existing = [row.get("override_id", "") for row in read_jsonl(files["overrides"])]
    override_id = f"override_{len([item for item in existing if item.startswith('override_')]) + 1:03d}"
    record = {
        "override_id": override_id,
        "created_at": utc_now(),
        "target": target,
        "reason": reason,
        "approved_by_user": approved_by_user,
        "scope": scope or [],
        "active": bool(approved_by_user),
    }
    append_jsonl(files["overrides"], record)
    return record


def find_valid_override(paths: VibePaths, override_id: str, risks: list[str], change_type: str) -> dict[str, Any] | None:
    if not override_id:
        return None
    for row in read_jsonl(convergence_paths(paths)["overrides"]):
        if row.get("override_id") != override_id or not row.get("active") or not row.get("approved_by_user"):
            continue
        scope = set(row.get("scope", []))
        if not scope or change_type in scope or scope.intersection(risks):
            return row
    return None


def classify_external_asset(asset: dict[str, Any]) -> dict[str, Any]:
    purpose = asset.get("purpose", "")
    mode = asset.get("dependency_mode", "")
    level = asset.get("current_internalization_level", "")
    classification = "reference_dependency"
    if mode in {"required", "core", "production"} or purpose in {"dependency", "temporary_wrapper"}:
        classification = "necessary_dependency"
    if mode in {"none", "regression_only"} or purpose in {"baseline", "comparison_target", "ablation_target"}:
        classification = "regression_dependency"
    if purpose in {"inspiration", "reference_implementation", "implementation_reference"} and mode not in {"required", "core", "production"}:
        classification = "reference_dependency"
    if asset.get("replacement_plan") and level in {"owned_core_candidate", "owned_core", "final_owned"}:
        classification = "removal_candidate"
    return {
        "dependency_id": asset.get("asset_id", ""),
        "kind": "external_asset",
        "classification": classification,
        "source": asset.get("source", ""),
        "purpose": purpose,
        "dependency_mode": mode,
        "replacement_plan": asset.get("replacement_plan", ""),
        "rationale": classification.replace("_", " "),
    }


def count_by_classification(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = row.get("classification", "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts
