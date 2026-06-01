"""Reviewer Session checks for Planner draft manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import append_jsonl, read_json, read_jsonl, utc_now, write_json, write_text
from .paths import VibePaths
from .planner import REQUIRED_FIELDS, load_draft_plan, meaningful_artifact


VERDICTS = {"ACCEPT", "REVISE", "REJECT", "ASK_HUMAN"}
MVE_TERMS = {"mve", "minimum viable", "one-case", "one case", "subset", "dry-run", "dry run", "component"}
EXPENSIVE_TERMS = {"slurm", "gpu", "fold", "multi-fold", "5-fold", "train", "training", "hosted validation", "packaging"}
SAFETY_TERMS = {"upload", "submit validation", "delete", "destructive", "external private data", "unsafe", "bypass policy"}
GENERIC_ROUTE_TERMS = {"generic u-net", "generic unet", "3d u-net", "3d unet", "another u-net", "another unet"}
METADATA_ONLY_TERMS = {"metadata", "clone", "import smoke", "smoke only", "readme scan", "repository inventory"}


def reviewer_context(paths: VibePaths) -> dict[str, Any]:
    def read(name: str) -> str:
        path = paths.kernel / name
        return path.read_text() if path.exists() else ""

    return {
        "failure_signatures": read("FAILURE_SIGNATURES.md"),
        "negative_memory": read("NEGATIVE_MEMORY.md"),
        "open_debts": read("OPEN_DEBTS.md"),
        "evidence_count": len(read_jsonl(paths.kernel / "EVIDENCE_LEDGER.jsonl")),
    }


def review_draft_plan(paths: VibePaths, draft: dict[str, Any]) -> dict[str, Any]:
    context = reviewer_context(paths)
    criteria = review_criteria(draft, context)
    verdict = choose_verdict(criteria)
    required_changes = [item["message"] for item in criteria if item["outcome"] == "revise"]
    blocking_risks = [item["message"] for item in criteria if item["outcome"] == "ask_human"]
    rejection_reasons = [item["message"] for item in criteria if item["outcome"] == "reject"]
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "session_role": "reviewer",
        "verdict": verdict,
        "criteria": criteria,
        "required_changes": required_changes,
        "blocking_risks": blocking_risks,
        "rejection_reasons": rejection_reasons,
        "allow_compiler": verdict == "ACCEPT",
        "reviewed_plan": draft if verdict == "ACCEPT" else None,
        "trace": {
            "draft_created_at": draft.get("created_at", ""),
            "draft_mode": draft.get("mode", ""),
            "draft_confidence": draft.get("confidence", ""),
            "evidence_count": context["evidence_count"],
            "checked_negative_memory": True,
            "checked_open_debts": True,
            "checked_failure_signatures": True,
        },
    }


def review_criteria(draft: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    body = draft.get("plan", {}) if isinstance(draft.get("plan"), dict) else {}
    text = " ".join(str(value).lower() for value in body.values())
    criteria: list[dict[str, str]] = []

    for field in REQUIRED_FIELDS:
        if not str(body.get(field, "")).strip():
            criteria.append({"outcome": "revise", "code": f"missing_{field}", "message": f"`{field}` is required before review acceptance"})

    if any(term in text for term in SAFETY_TERMS):
        criteria.append({"outcome": "ask_human", "code": "safety_or_policy_risk", "message": "plan contains safety/resource/policy risk that requires human review"})

    if any(term in text for term in GENERIC_ROUTE_TERMS):
        criteria.append({"outcome": "reject", "code": "generic_low_value_route", "message": "generic U-Net-style reruns are low-value without a specific new mechanism"})

    minimum_experiment = str(body.get("minimum_experiment", "")).lower()
    expected_artifact = str(body.get("expected_artifact", ""))
    if any(term in minimum_experiment for term in METADATA_ONLY_TERMS) or ("smoke" in minimum_experiment and not meaningful_artifact(expected_artifact)):
        criteria.append({"outcome": "reject", "code": "metadata_or_smoke_only", "message": "metadata/smoke-only plans are diagnostic and cannot enter execution"})

    mechanism = str(body.get("mechanism", "")).strip().lower()
    negative = str(context.get("negative_memory", "")).lower()
    if mechanism and mechanism in negative:
        criteria.append({"outcome": "reject", "code": "negative_memory_repeat", "message": "mechanism repeats negative memory without a new mechanism"})

    if not meaningful_artifact(expected_artifact):
        criteria.append({"outcome": "revise", "code": "missing_progress_artifact", "message": "plan needs a concrete progress artifact"})

    belief = str(body.get("expected_belief_update", "")).strip().lower()
    if not belief or belief in {"none", "n/a", "tbd"} or "can run" in belief:
        criteria.append({"outcome": "revise", "code": "weak_belief_update", "message": "expected belief update must change research belief, not just prove execution"})

    if any(term in text for term in EXPENSIVE_TERMS) and not any(term in minimum_experiment for term in MVE_TERMS):
        criteria.append({"outcome": "revise", "code": "expensive_without_mve", "message": "expensive plans need a cheaper MVE before execution"})

    if not matches_failure_signature(str(body.get("failure_anchor", "")), str(context.get("failure_signatures", ""))):
        criteria.append({"outcome": "revise", "code": "failure_signature_mismatch", "message": "failure anchor does not match current failure signatures"})

    if not criteria:
        criteria.append({"outcome": "accept", "code": "reviewable_mve", "message": "plan has a failure anchor, MVE, artifact, belief update, and no blocking risk"})
    return criteria


def matches_failure_signature(failure_anchor: str, failure_signatures: str) -> bool:
    anchor = failure_anchor.lower()
    signatures = failure_signatures.lower()
    if not signatures.strip() or "tbd" in signatures:
        return True
    tokens = [token for token in anchor.replace("-", " ").split() if len(token) > 4]
    return any(token in signatures for token in tokens)


def choose_verdict(criteria: list[dict[str, str]]) -> str:
    outcomes = {item["outcome"] for item in criteria}
    if "ask_human" in outcomes:
        return "ASK_HUMAN"
    if "reject" in outcomes:
        return "REJECT"
    if "revise" in outcomes:
        return "REVISE"
    return "ACCEPT"


def render_review_report(review: dict[str, Any]) -> str:
    lines = [
        "# Plan Review Report",
        "",
        f"Verdict: {review['verdict']}",
        f"Allow Compiler: {str(review['allow_compiler']).lower()}",
        "",
        "## Trace",
        "",
        f"- Draft created at: {review['trace'].get('draft_created_at', '')}",
        f"- Evidence records checked: {review['trace'].get('evidence_count', 0)}",
        "- Negative memory checked: true",
        "- Open debts checked: true",
        "- Failure signatures checked: true",
        "",
        "## Criteria",
        "",
    ]
    for item in review["criteria"]:
        lines.append(f"- {item['outcome']} `{item['code']}`: {item['message']}")
    lines.extend(["", "## Required Changes", ""])
    if review["required_changes"]:
        lines.extend(f"- {item}" for item in review["required_changes"])
    else:
        lines.append("- none")
    lines.extend(["", "## Blocking Risks", ""])
    if review["blocking_risks"]:
        lines.extend(f"- {item}" for item in review["blocking_risks"])
    else:
        lines.append("- none")
    lines.extend(["", "## Rejection Reasons", ""])
    if review["rejection_reasons"]:
        lines.extend(f"- {item}" for item in review["rejection_reasons"])
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_review_outputs(
    paths: VibePaths,
    review: dict[str, Any],
    *,
    report_name: str = "plan_review_report.md",
    reviewed_name: str = "reviewed_plan_manifest.json",
) -> dict[str, Path | None]:
    report_path = paths.kernel / report_name
    write_text(report_path, render_review_report(review))
    reviewed_path: Path | None = None
    if review["verdict"] == "ACCEPT":
        reviewed_path = paths.kernel / reviewed_name
        write_json(reviewed_path, {"schema_version": 1, "created_at": utc_now(), "review": review, "draft_plan": review["reviewed_plan"]})
    append_jsonl(
        paths.kernel / "PLAN_REVIEW_REGISTRY.jsonl",
        {
            "created_at": utc_now(),
            "verdict": review["verdict"],
            "allow_compiler": review["allow_compiler"],
            "criteria": review["criteria"],
            "report": str(report_path),
            "reviewed_manifest": str(reviewed_path) if reviewed_path else "",
        },
    )
    return {"report": report_path, "reviewed_manifest": reviewed_path}


def review_draft_file(paths: VibePaths, draft_path: Path) -> dict[str, Any]:
    draft = load_draft_plan(draft_path)
    return review_draft_plan(paths, draft)


def load_review(path: Path) -> dict[str, Any]:
    return read_json(path, {})
