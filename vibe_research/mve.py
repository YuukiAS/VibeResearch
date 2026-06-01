"""Minimum viable experiment contracts and promotion rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json, write_json


BIG_EXPERIMENT_TERMS = {"large training", "5-fold", "five-fold", "hosted validation", "packaging", "full training", "multi-fold"}


def infer_mve_level(plan: dict[str, Any]) -> str:
    text = " ".join(str(value).lower() for value in plan.values())
    if "component" in text or "verifier" in text:
        return "component_dataset"
    if "cine" in text or "hybrid" in text or "route" in text:
        return "route_manifest_fold0"
    if "train" in text or "training" in text:
        return "small_split_or_dry_run"
    if "subset" in text:
        return "subset"
    return "one_case"


def build_mve_contract(plan: dict[str, Any], *, expected_artifact: str, metric_reader: str, minimal_command: str, cost_cap: dict[str, Any]) -> dict[str, Any]:
    level = infer_mve_level(plan)
    return {
        "schema_version": 1,
        "level": level,
        "input_asset": ".vibe/kernel/reviewed_plan_manifest.json",
        "minimal_command": minimal_command,
        "expected_artifact": expected_artifact,
        "metric_or_evidence_reader": metric_reader,
        "success_condition": plan.get("expected_belief_update", "evidence changes belief"),
        "failure_condition": plan.get("stop_condition", "MVE artifact missing or evidence is negative"),
        "cost_cap": cost_cap,
        "next_promotion_rule": next_promotion_rule(level),
    }


def next_promotion_rule(level: str) -> str:
    rules = {
        "one_case": "create subset evidence debt",
        "subset": "create fold0 evidence debt",
        "component_dataset": "create subset or fold0 component evidence debt",
        "route_manifest_fold0": "create multi-route or fold0 comparison debt",
        "small_split_or_dry_run": "create fold0 training evidence debt",
    }
    return rules.get(level, "create next evidence debt")


def validate_mve_contract(manifest: dict[str, Any]) -> list[str]:
    if manifest.get("safety_checks", {}).get("user_approved_mve_exception"):
        return []
    contract = manifest.get("mve_contract", {})
    if not isinstance(contract, dict) or not contract:
        return ["mve_contract is required"]
    required = (
        "input_asset",
        "minimal_command",
        "expected_artifact",
        "metric_or_evidence_reader",
        "success_condition",
        "failure_condition",
        "cost_cap",
        "next_promotion_rule",
    )
    issues = [f"mve_contract.{field} is required" for field in required if not contract.get(field)]
    text = " ".join(str(value).lower() for value in manifest.values())
    if any(term in text for term in BIG_EXPERIMENT_TERMS) and not contract.get("level"):
        issues.append("large experiments require an explicit MVE level or human exception")
    return issues


def validate_mve_completion(root: Path, manifest: dict[str, Any]) -> list[str]:
    issues = validate_mve_contract(manifest)
    if issues:
        return issues
    artifact = manifest.get("mve_contract", {}).get("expected_artifact", "")
    if artifact and not (root / artifact).exists():
        issues.append(f"MVE artifact missing: {artifact}")
    return issues


def promotion_debt_for_success(manifest: dict[str, Any]) -> dict[str, Any]:
    contract = manifest.get("mve_contract", {})
    level = contract.get("level", "one_case")
    return {
        "status": "open",
        "source": "mve_success",
        "current_level": level,
        "next_debt": next_promotion_rule(level),
        "must_not_declare_mainline_success": True,
        "expected_artifact": contract.get("expected_artifact", ""),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    return read_json(path, {})


def write_promotion_debt(path: Path, debt: dict[str, Any]) -> None:
    write_json(path, debt)
