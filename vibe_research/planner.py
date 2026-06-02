"""Planner Session draft-plan generation and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .decision_debt import planner_debt_diagnostic
from .human_guidance import active_human_guidance, guidance_tokens, mark_guidance_considered
from .immune_registry import planner_registry_diagnostic
from .io import read_json, read_jsonl, utc_now, write_json
from .knowledge_lifecycle import mark_card_plan_candidate
from .kernel import missing_kernel_files
from .paths import VibePaths
from .scout import validate_mechanism_card


GENERATION_MODES = {"exploit", "recombine", "invent"}
CONFIDENCE_CLASSES = {"high_value_candidate", "speculative_mechanism", "maintenance_action", "background_reading"}
REVIEWABLE_CONFIDENCE = {"high_value_candidate", "speculative_mechanism"}
REQUIRED_FIELDS = (
    "failure_anchor",
    "hypothesis",
    "mechanism",
    "minimum_experiment",
    "expected_artifact",
    "expected_belief_update",
    "compute_cost",
    "risk",
    "fallback",
    "stop_condition",
)


def read_kernel_text(paths: VibePaths, name: str) -> str:
    path = paths.kernel / name
    return path.read_text() if path.exists() else ""


def planner_context(paths: VibePaths) -> dict[str, Any]:
    missing = missing_kernel_files(paths)
    return {
        "missing_kernel_files": missing,
        "project_kernel": read_kernel_text(paths, "PROJECT_KERNEL.md"),
        "problem_state": read_kernel_text(paths, "PROBLEM_STATE.md"),
        "failure_signatures": read_kernel_text(paths, "FAILURE_SIGNATURES.md"),
        "negative_memory": read_kernel_text(paths, "NEGATIVE_MEMORY.md"),
        "open_debts": read_kernel_text(paths, "OPEN_DEBTS.md"),
        "evidence_count": len(read_jsonl(paths.kernel / "EVIDENCE_LEDGER.jsonl")),
        "active_human_guidance": active_human_guidance(paths),
    }


def build_draft_plan(
    paths: VibePaths,
    *,
    mode: str,
    failure_anchor: str,
    hypothesis: str,
    mechanism: str,
    minimum_experiment: str,
    expected_artifact: str,
    expected_belief_update: str,
    compute_cost: str,
    risk: str,
    fallback: str,
    stop_condition: str,
    confidence: str,
    source: str = "manual",
) -> dict[str, Any]:
    context = planner_context(paths)
    normalized_mode = mode.strip().lower()
    normalized_confidence = confidence.strip().lower()
    plan = {
        "schema_version": 1,
        "created_at": utc_now(),
        "session_role": "planner",
        "source": source,
        "mode": normalized_mode,
        "confidence": normalized_confidence,
        "review_route": "reviewer" if normalized_confidence in REVIEWABLE_CONFIDENCE else "non_executable",
        "plan": {
            "failure_anchor": failure_anchor.strip(),
            "hypothesis": hypothesis.strip(),
            "mechanism": mechanism.strip(),
            "minimum_experiment": minimum_experiment.strip(),
            "expected_artifact": expected_artifact.strip(),
            "expected_belief_update": expected_belief_update.strip(),
            "compute_cost": compute_cost.strip(),
            "risk": risk.strip(),
            "fallback": fallback.strip(),
            "stop_condition": stop_condition.strip(),
        },
        "kernel_context": {
            "missing_kernel_files": context["missing_kernel_files"],
            "evidence_count": context["evidence_count"],
            "has_negative_memory": bool(context["negative_memory"].strip()),
            "has_open_debts": bool(context["open_debts"].strip()),
            "active_human_guidance_count": len(context["active_human_guidance"]),
        },
        "human_guidance_considered": human_guidance_considered(context["active_human_guidance"], {
            "failure_anchor": failure_anchor,
            "hypothesis": hypothesis,
            "mechanism": mechanism,
            "minimum_experiment": minimum_experiment,
            "fallback": fallback,
            "stop_condition": stop_condition,
        }),
        "diagnostics": [],
    }
    plan["diagnostics"] = planner_diagnostics(plan, context)
    debt_diagnostic = planner_debt_diagnostic(paths, plan)
    if debt_diagnostic:
        plan["diagnostics"].append(debt_diagnostic)
    registry_diagnostic = planner_registry_diagnostic(paths, plan)
    if registry_diagnostic:
        plan["diagnostics"].append(registry_diagnostic)
    if any(item["code"] in {"smoke_only", "negative_memory_overlap", "non_reviewable_confidence"} for item in plan["diagnostics"]):
        plan["review_route"] = "requires_revision"
    if any(item["code"] in {"registry_repeat_route"} for item in plan["diagnostics"]):
        plan["review_route"] = "requires_revision"
    if any(item["code"] in {"open_decision_debt_priority"} for item in plan["diagnostics"]):
        plan["review_route"] = "requires_revision"
    if any(item["code"] in {"human_guidance_unaddressed"} for item in plan["diagnostics"]):
        plan["review_route"] = "requires_revision"
    mark_guidance_considered(paths, plan)
    return plan


def human_guidance_considered(guidance: list[dict[str, Any]], plan_fields: dict[str, str]) -> list[dict[str, str]]:
    plan_text = " ".join(str(value).lower() for value in plan_fields.values())
    considered = []
    for row in guidance[-20:]:
        tokens = guidance_tokens(row)
        absorbed = bool(tokens and any(token in plan_text for token in tokens))
        considered.append(
            {
                "guidance_id": str(row.get("guidance_id", "")),
                "status": "absorbed" if absorbed else "not_used",
                "reason": "plan text references this guidance" if absorbed else "Planner must explain or revise before execution",
            }
        )
    return considered


def build_draft_from_mechanism_card(
    paths: VibePaths,
    card: dict[str, Any],
    *,
    confidence: str = "speculative_mechanism",
) -> dict[str, Any]:
    issues = validate_mechanism_card(card)
    if issues:
        raise ValueError("; ".join(issues))
    artifact_slug = str(card.get("card_id") or "mechanism_card").replace("_", "-")
    plan = build_draft_plan(
        paths,
        mode="recombine",
        failure_anchor=str(card.get("failure_anchor", "")),
        hypothesis=f"If {card.get('claim', '')}, then {card.get('mechanism_extraction', '')} can change belief on the failure anchor.",
        mechanism=str(card.get("mechanism_extraction", "")),
        minimum_experiment=str(card.get("possible_mve", "")),
        expected_artifact=f".vibe/runs/{artifact_slug}/mechanism_card_metrics.json",
        expected_belief_update=f"Decide whether mechanism card {card.get('card_id', '')} provides transferable mechanism evidence.",
        compute_cost="local cpu under 10 minutes unless Reviewer approves more",
        risk="; ".join(str(item) for item in card.get("risks", [])) or "external knowledge may not transfer",
        fallback=f"archive mechanism card {card.get('card_id', '')} as negative or background evidence",
        stop_condition=str(card.get("stop_reason", "")),
        confidence=confidence,
        source=f"mechanism_card:{card.get('card_id', '')}",
    )
    plan["mechanism_card"] = card
    mark_card_plan_candidate(paths, card, draft_id=plan["created_at"])
    return plan


def planner_diagnostics(plan: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    mode = plan.get("mode", "")
    confidence = plan.get("confidence", "")
    body = plan.get("plan", {})
    if mode not in GENERATION_MODES:
        diagnostics.append({"level": "error", "code": "invalid_mode", "message": f"mode `{mode}` is not supported"})
    if confidence not in CONFIDENCE_CLASSES:
        diagnostics.append({"level": "error", "code": "invalid_confidence", "message": f"confidence `{confidence}` is not supported"})
    for field in REQUIRED_FIELDS:
        if not str(body.get(field, "")).strip():
            diagnostics.append({"level": "error", "code": f"missing_{field}", "message": f"`{field}` is required"})
    if "smoke" in str(body.get("minimum_experiment", "")).lower() and not meaningful_artifact(str(body.get("expected_artifact", ""))):
        diagnostics.append({"level": "warning", "code": "smoke_only", "message": "smoke-only plans are diagnostic and cannot enter Reviewer as progress"})
    mechanism = str(body.get("mechanism", "")).lower()
    negative = str(context.get("negative_memory", "")).lower()
    if mechanism and mechanism in negative:
        diagnostics.append({"level": "warning", "code": "negative_memory_overlap", "message": "mechanism overlaps negative memory; Reviewer needs a new mechanism justification"})
    open_debts = str(context.get("open_debts", "")).lower()
    if ("watch" in open_debts or "refine" in open_debts) and not mentions_debt(body, open_debts):
        diagnostics.append({"level": "warning", "code": "open_debt_not_addressed", "message": "open WATCH/REFINE debt exists and is not referenced by this draft"})
    if confidence not in REVIEWABLE_CONFIDENCE:
        diagnostics.append({"level": "info", "code": "non_reviewable_confidence", "message": "maintenance/background drafts are non-executable"})
    guidance = context.get("active_human_guidance", [])
    considered = plan.get("human_guidance_considered", [])
    if guidance and not any(item.get("status") == "absorbed" for item in considered):
        diagnostics.append({"level": "warning", "code": "human_guidance_unaddressed", "message": "active human guidance exists but is not absorbed or explained"})
    return diagnostics


def meaningful_artifact(value: str) -> bool:
    text = value.strip().lower()
    return bool(text and text not in {"none", "n/a", "smoke", "smoke output"})


def mentions_debt(plan: dict[str, Any], open_debts: str) -> bool:
    plan_text = " ".join(str(value).lower() for value in plan.values())
    return "watch" in plan_text or "refine" in plan_text or any(token.startswith("debt") and token in plan_text for token in open_debts.split())


def validate_draft_plan(plan: dict[str, Any]) -> tuple[bool, list[dict[str, str]]]:
    diagnostics = list(plan.get("diagnostics", []))
    body = plan.get("plan", {})
    for field in REQUIRED_FIELDS:
        if not str(body.get(field, "")).strip() and not any(item.get("code") == f"missing_{field}" for item in diagnostics):
            diagnostics.append({"level": "error", "code": f"missing_{field}", "message": f"`{field}` is required"})
    if plan.get("mode") not in GENERATION_MODES:
        diagnostics.append({"level": "error", "code": "invalid_mode", "message": "unsupported generation mode"})
    if plan.get("confidence") not in CONFIDENCE_CLASSES:
        diagnostics.append({"level": "error", "code": "invalid_confidence", "message": "unsupported confidence class"})
    ok = not any(item.get("level") == "error" for item in diagnostics)
    return ok, diagnostics


def write_draft_plan(paths: VibePaths, plan: dict[str, Any], output: str = "draft_plan_manifest.json") -> Path:
    path = paths.kernel / output
    write_json(path, plan)
    return path


def load_draft_plan(path: Path) -> dict[str, Any]:
    return read_json(path, {})
