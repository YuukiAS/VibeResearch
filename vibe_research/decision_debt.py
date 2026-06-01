"""Decision debt records and TTL clearing for WATCH/REFINE outcomes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .immune_registry import record_registry_event
from .io import append_jsonl, read_json, read_jsonl, utc_now, write_json, write_text
from .paths import VibePaths


DEBT_LOG_FILE = "DECISION_DEBTS.jsonl"
DEBT_STATE_FILE = "DECISION_DEBTS_OPEN.json"
PLAN_SEEDS_FILE = "PLAN_SEEDS.jsonl"
DEBT_ACTION_TYPES = {"refinement_debt", "watch_debt"}
DEFAULT_TTL_ROUNDS = 2


def kernel_path(paths: VibePaths, name: str) -> Path:
    return paths.kernel / name


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def debt_id_for(record: dict[str, Any]) -> str:
    fields = {
        "source_reflect_id": record.get("source_reflect_id", ""),
        "watched_mechanism": record.get("watched_mechanism", ""),
        "repayment_mve": record.get("repayment_mve", ""),
        "owner_session": record.get("owner_session", ""),
    }
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:12]
    return "debt-" + digest


def debt_record_from_reflection(reflection: dict[str, Any], *, ttl_rounds: int = DEFAULT_TTL_ROUNDS) -> dict[str, Any]:
    action = reflection.get("next_action", {}) if isinstance(reflection.get("next_action"), dict) else {}
    evidence = reflection.get("evidence", {}) if isinstance(reflection.get("evidence"), dict) else {}
    metric = reflection.get("metric", {}) if isinstance(reflection.get("metric"), dict) else {}
    record = {
        "schema_version": 1,
        "created_at": utc_now(),
        "status": "open",
        "source_reflect_id": normalize_text(reflection.get("reflect_id") or reflection.get("created_at") or reflection.get("source_result")),
        "watched_mechanism": normalize_text(action.get("watched_mechanism") or reflection.get("accepted_plan_id") or action.get("mechanism") or "unknown"),
        "current_evidence": normalize_text(evidence.get("summary") or metric.get("summary") or reflection.get("belief_update")),
        "missing_evidence": normalize_text(action.get("missing_evidence") or action.get("next_debt") or action.get("reason")),
        "repayment_mve": normalize_text(action.get("repayment_mve") or action.get("next_debt")),
        "ttl_rounds": int(action.get("ttl_rounds", ttl_rounds) or ttl_rounds),
        "rounds_open": int(action.get("rounds_open", 0) or 0),
        "promotion_condition": normalize_text(action.get("promotion_condition") or "repayment MVE produces trusted mechanism evidence"),
        "pivot_condition": normalize_text(action.get("pivot_condition") or "repayment MVE changes the mechanism or evidence source"),
        "stop_condition": normalize_text(action.get("stop_condition") or "repayment MVE is missing or remains negative at TTL"),
        "owner_session": normalize_text(action.get("owner_session") or reflection.get("session_role") or "reflector"),
        "decision": normalize_text(reflection.get("verdict") or action.get("decision")),
        "debt_type": normalize_text(action.get("type")),
        "expiry_decision": normalize_text(action.get("expiry_decision") or "STOP").upper(),
    }
    record["debt_id"] = debt_id_for(record)
    return record


def validate_debt_record(record: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    required = (
        "source_reflect_id",
        "watched_mechanism",
        "current_evidence",
        "missing_evidence",
        "repayment_mve",
        "ttl_rounds",
        "promotion_condition",
        "pivot_condition",
        "stop_condition",
        "owner_session",
    )
    for field in required:
        if not normalize_text(record.get(field)):
            issues.append(f"{field} is required")
    if record.get("debt_type") not in DEBT_ACTION_TYPES:
        issues.append("debt_type must be refinement_debt or watch_debt")
    if record.get("decision", "").upper() not in {"REFINE", "WATCH"}:
        issues.append("decision debt must come from REFINE or WATCH")
    try:
        ttl = int(record.get("ttl_rounds", 0))
    except (TypeError, ValueError):
        ttl = 0
    if ttl <= 0:
        issues.append("ttl_rounds must be positive")
    if record.get("expiry_decision", "STOP").upper() not in {"STOP", "PIVOT"}:
        issues.append("expiry_decision must be STOP or PIVOT")
    return issues


def reflection_requires_debt(reflection: dict[str, Any]) -> bool:
    action = reflection.get("next_action", {}) if isinstance(reflection.get("next_action"), dict) else {}
    if action.get("type") == "watch_debt":
        return True
    return reflection.get("verdict") in {"REFINE", "WATCH"} and action.get("type") in DEBT_ACTION_TYPES


def open_decision_debt(paths: VibePaths, reflection: dict[str, Any]) -> dict[str, Any]:
    record = debt_record_from_reflection(reflection)
    issues = validate_debt_record(record)
    if issues:
        record["validation_issues"] = issues
        return record
    append_jsonl(kernel_path(paths, DEBT_LOG_FILE), record)
    write_open_debt_state(paths)
    append_open_debt_markdown(paths, record)
    return record


def load_latest_debts(paths: VibePaths) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(kernel_path(paths, DEBT_LOG_FILE)):
        debt_id = row.get("debt_id")
        if debt_id:
            latest[debt_id] = row
    return latest


def load_open_decision_debts(paths: VibePaths) -> list[dict[str, Any]]:
    return [row for row in load_latest_debts(paths).values() if row.get("status") == "open"]


def write_open_debt_state(paths: VibePaths) -> dict[str, Any]:
    state = {"updated_at": utc_now(), "open_debts": load_open_decision_debts(paths)}
    write_json(kernel_path(paths, DEBT_STATE_FILE), state)
    return state


def append_open_debt_markdown(paths: VibePaths, record: dict[str, Any]) -> None:
    path = paths.kernel / "OPEN_DEBTS.md"
    existing = path.read_text() if path.exists() else "# Open Debts\n\n"
    line = (
        f"- id: {record['debt_id']}\n"
        f"  watched_mechanism: {record['watched_mechanism']}\n"
        f"  missing_evidence: {record['missing_evidence']}\n"
        f"  repayment_mve: {record['repayment_mve']}\n"
        f"  ttl_rounds: {record['ttl_rounds']}\n"
    )
    write_text(path, existing.rstrip() + "\n\n" + line)


def planner_debt_diagnostic(paths: VibePaths, plan: dict[str, Any]) -> dict[str, str] | None:
    open_debts = load_open_decision_debts(paths)
    if not open_debts:
        return None
    plan_text = json.dumps(plan.get("plan", plan), sort_keys=True).lower()
    for debt in open_debts:
        tokens = [debt.get("debt_id", ""), debt.get("watched_mechanism", ""), debt.get("repayment_mve", "")]
        if any(token and str(token).lower() in plan_text for token in tokens):
            return {"level": "info", "code": "open_decision_debt_addressed", "message": f"draft addresses open debt {debt['debt_id']}"}
    return {"level": "warning", "code": "open_decision_debt_priority", "message": f"{len(open_debts)} open WATCH/REFINE debt(s) should be repaid before new ideas"}


def clear_expired_decision_debts(paths: VibePaths, *, rounds: int = 1) -> dict[str, Any]:
    cleared: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    for debt in load_open_decision_debts(paths):
        next_debt = dict(debt)
        next_debt["rounds_open"] = int(next_debt.get("rounds_open", 0)) + rounds
        next_debt["updated_at"] = utc_now()
        if next_debt["rounds_open"] >= int(next_debt.get("ttl_rounds", DEFAULT_TTL_ROUNDS)):
            decision = str(next_debt.get("expiry_decision", "STOP")).upper()
            next_debt["status"] = "stopped" if decision == "STOP" else "pivoted"
            next_debt["clearance_decision"] = decision
            next_debt["closed_at"] = utc_now()
            write_clearance_outputs(paths, next_debt, decision)
            record_registry_event(paths, event_type="decision_debt_clearance", payload=registry_payload(next_debt, decision))
            cleared.append(next_debt)
        else:
            updated.append(next_debt)
        append_jsonl(kernel_path(paths, DEBT_LOG_FILE), next_debt)
    state = write_open_debt_state(paths)
    return {"cleared": cleared, "updated": updated, "open_debts": state["open_debts"]}


def write_clearance_outputs(paths: VibePaths, debt: dict[str, Any], decision: str) -> None:
    if decision == "STOP":
        path = paths.kernel / "NEGATIVE_MEMORY.md"
        existing = path.read_text() if path.exists() else "# Negative Memory\n\n"
        line = f"- STOP debt {debt['debt_id']}: {debt.get('stop_condition', '')}; missing evidence: {debt.get('missing_evidence', '')}"
        write_text(path, existing.rstrip() + "\n\n" + line + "\n")
    else:
        append_jsonl(
            kernel_path(paths, PLAN_SEEDS_FILE),
            {
                "created_at": utc_now(),
                "source_debt_id": debt["debt_id"],
                "watched_mechanism": debt.get("watched_mechanism", ""),
                "repayment_mve": debt.get("repayment_mve", ""),
                "pivot_condition": debt.get("pivot_condition", ""),
                "reviewer_required": True,
            },
        )


def registry_payload(debt: dict[str, Any], decision: str) -> dict[str, Any]:
    return {
        "failure_anchor": debt.get("missing_evidence", ""),
        "mechanism": debt.get("watched_mechanism", ""),
        "minimum_experiment": debt.get("repayment_mve", ""),
        "expected_artifact": "decision_debt_ttl",
        "reflect_decision": decision,
        "evidence_type": "negative" if decision == "STOP" else "plan_seed",
        "debt_id": debt.get("debt_id", ""),
    }


def load_debt_state(paths: VibePaths) -> dict[str, Any]:
    return read_json(kernel_path(paths, DEBT_STATE_FILE), {"open_debts": []})
