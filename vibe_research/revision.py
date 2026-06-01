"""Planner-Reviewer revision loop helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import append_jsonl, read_json, utc_now, write_json
from .paths import VibePaths
from .planner import REQUIRED_FIELDS


DEFAULT_REVISION_LIMIT = 2


def build_revision_packet(review: dict[str, Any], *, max_rounds: int = DEFAULT_REVISION_LIMIT) -> dict[str, Any]:
    criteria = [item for item in review.get("criteria", []) if item.get("outcome") in {"revise", "ask_human"}]
    required_changes = review.get("required_changes") or [item.get("message", "") for item in criteria if item.get("outcome") == "revise"]
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "verdict": review.get("verdict", ""),
        "failed_criteria": criteria,
        "required_changes": required_changes,
        "allowed_fields": allowed_fields_from_criteria(criteria),
        "optional_suggestions": optional_suggestions_from_review(review),
        "blocking_risks": review.get("blocking_risks", []),
        "evidence_gaps": evidence_gaps_from_criteria(criteria),
        "resubmission_deadline": "before Compiler or Executor receives this plan",
        "max_revision_rounds": max_rounds,
    }


def allowed_fields_from_criteria(criteria: list[dict[str, str]]) -> list[str]:
    fields: list[str] = []
    for item in criteria:
        code = item.get("code", "")
        if code.startswith("missing_"):
            field = code.removeprefix("missing_")
            if field in REQUIRED_FIELDS and field not in fields:
                fields.append(field)
        if code in {"weak_belief_update"} and "expected_belief_update" not in fields:
            fields.append("expected_belief_update")
        if code in {"missing_progress_artifact", "metadata_or_smoke_only"}:
            for field in ("minimum_experiment", "expected_artifact"):
                if field not in fields:
                    fields.append(field)
        if code in {"expensive_without_mve"} and "minimum_experiment" not in fields:
            fields.append("minimum_experiment")
        if code in {"failure_signature_mismatch"} and "failure_anchor" not in fields:
            fields.append("failure_anchor")
    return fields


def optional_suggestions_from_review(review: dict[str, Any]) -> list[str]:
    suggestions = []
    for item in review.get("criteria", []):
        if item.get("outcome") == "revise" and item.get("code") == "expensive_without_mve":
            suggestions.append("Prefer one-case or subset MVE before GPU/Slurm execution.")
    return suggestions


def evidence_gaps_from_criteria(criteria: list[dict[str, str]]) -> list[str]:
    gaps: list[str] = []
    for item in criteria:
        code = item.get("code", "")
        if code in {"missing_progress_artifact", "metadata_or_smoke_only"}:
            gaps.append("progress artifact")
        if code == "weak_belief_update":
            gaps.append("belief update")
        if code == "failure_signature_mismatch":
            gaps.append("current failure signature")
    return sorted(set(gaps))


def resubmit_draft(
    draft: dict[str, Any],
    revision_packet: dict[str, Any],
    updates: dict[str, str],
    *,
    addressed: list[str] | None = None,
    not_addressed: list[str] | None = None,
) -> dict[str, Any]:
    allowed = set(revision_packet.get("allowed_fields", []))
    disallowed = sorted(set(updates) - allowed)
    if disallowed:
        raise ValueError("resubmission tried to modify fields outside revision packet: " + ", ".join(disallowed))
    revised = dict(draft)
    body = dict(revised.get("plan", {}))
    for field, value in updates.items():
        body[field] = value
    revised["plan"] = body
    history = list(revised.get("revision_history", []))
    history.append(
        {
            "created_at": utc_now(),
            "revision_round": len(history) + 1,
            "allowed_fields": sorted(allowed),
            "updated_fields": sorted(updates),
            "addressed": addressed or [],
            "not_addressed": not_addressed or [],
            "source_verdict": revision_packet.get("verdict", ""),
        }
    )
    revised["revision_history"] = history
    revised["created_at"] = utc_now()
    return revised


def revision_round_count(draft: dict[str, Any]) -> int:
    return len(draft.get("revision_history", []) if isinstance(draft.get("revision_history"), list) else [])


def enforce_loop_limit(draft: dict[str, Any], review: dict[str, Any], *, max_rounds: int = DEFAULT_REVISION_LIMIT) -> dict[str, Any]:
    if review.get("verdict") != "REVISE":
        return review
    if revision_round_count(draft) < max_rounds:
        return review
    limited = dict(review)
    limited["verdict"] = "ASK_HUMAN"
    limited["allow_compiler"] = False
    limited.setdefault("blocking_risks", [])
    limited["blocking_risks"] = list(limited["blocking_risks"]) + [f"revision loop exceeded {max_rounds} rounds"]
    limited.setdefault("criteria", [])
    limited["criteria"] = list(limited["criteria"]) + [
        {"outcome": "ask_human", "code": "revision_loop_limit", "message": f"revision loop exceeded {max_rounds} rounds"}
    ]
    return limited


def write_revision_packet(paths: VibePaths, packet: dict[str, Any], output: str = "revision_packet.json") -> Path:
    path = paths.kernel / output
    write_json(path, packet)
    append_jsonl(paths.kernel / "PLAN_REVISION_REGISTRY.jsonl", {"created_at": utc_now(), "event": "revision_packet", "packet": packet})
    return path


def write_resubmitted_draft(paths: VibePaths, draft: dict[str, Any], output: str = "draft_plan_manifest.json") -> Path:
    path = paths.kernel / output
    write_json(path, draft)
    append_jsonl(paths.kernel / "PLAN_REVISION_REGISTRY.jsonl", {"created_at": utc_now(), "event": "resubmitted_draft", "revision_history": draft.get("revision_history", [])})
    return path


def load_revision_packet(path: Path) -> dict[str, Any]:
    return read_json(path, {})
