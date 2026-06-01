"""Research registry and immune-system duplicate route guards."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .io import append_jsonl, read_json, read_jsonl, utc_now, write_json
from .paths import VibePaths


REGISTRY_FILE = "RESEARCH_REGISTRY.jsonl"
ANTIGEN_FILE = "FAILURE_ANTIGENS.jsonl"
BUDGET_RECOVERY_FILE = "BUDGET_RECOVERY_INDEX.json"
ANTIGEN_TRIGGERS = {"STOP", "PIVOT", "guardrail_regression", "adapter_impossible", "orphan_knowledge", "metadata_only_loop"}
NOVELTY_TERMS = {"new verifier", "new proxy", "new mechanism", "new artifact", "new evidence", "new information", "different split", "different source"}


def kernel_path(paths: VibePaths, name: str) -> Path:
    return paths.kernel / name


def normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def artifact_type(path: str) -> str:
    lowered = normalize(path)
    for key in ("metric", "metrics", "prediction", "mask", "qc", "softmax", "route", "failure", "smoke", "metadata", "readme"):
        if key in lowered:
            return key
    suffix = Path(lowered).suffix.lstrip(".")
    return suffix or "unknown"


def route_fingerprint(data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("plan", data)
    metric_vector = body.get("metric_vector", body.get("metric", {}))
    fields = {
        "failure_anchor": normalize(body.get("failure_anchor")),
        "mechanism": normalize(body.get("mechanism")),
        "base_model": normalize(body.get("base_model")),
        "data_split": normalize(body.get("data_split")),
        "action_type": normalize(body.get("action_type") or body.get("minimum_experiment")),
        "artifact_type": artifact_type(str(body.get("expected_artifact") or body.get("artifact_pointer") or body.get("artifact", ""))),
        "metric_vector": metric_vector if isinstance(metric_vector, dict) else {"value": metric_vector},
        "review_verdict": normalize(body.get("review_verdict")),
        "reflect_decision": normalize(body.get("reflect_decision") or body.get("verdict")),
        "evidence_type": normalize(body.get("evidence_type")),
    }
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]
    return {"fingerprint": digest, **fields}


def record_registry_event(paths: VibePaths, *, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    fingerprint = route_fingerprint(payload)
    record = {"created_at": utc_now(), "event_type": event_type, **fingerprint, "payload": payload}
    append_jsonl(kernel_path(paths, REGISTRY_FILE), record)
    maybe_antigen(paths, record)
    if event_type in {"budget_checkpoint", "resume", "low_quota_interruption"}:
        update_budget_recovery_index(paths, record)
    return record


def maybe_antigen(paths: VibePaths, record: dict[str, Any]) -> None:
    text = json.dumps(record, sort_keys=True).lower()
    if record.get("reflect_decision", "").upper() in {"STOP", "PIVOT"} or any(trigger.lower() in text for trigger in ANTIGEN_TRIGGERS):
        antigen = {
            "created_at": utc_now(),
            "antigen_id": "ag-" + record["fingerprint"],
            "source_fingerprint": record["fingerprint"],
            "failure_anchor": record.get("failure_anchor", ""),
            "mechanism": record.get("mechanism", ""),
            "action_type": record.get("action_type", ""),
            "artifact_type": record.get("artifact_type", ""),
            "evidence_type": record.get("evidence_type", ""),
            "reason": record.get("reflect_decision") or record.get("event_type"),
        }
        append_jsonl(kernel_path(paths, ANTIGEN_FILE), antigen)


def update_budget_recovery_index(paths: VibePaths, record: dict[str, Any]) -> None:
    index = read_json(kernel_path(paths, BUDGET_RECOVERY_FILE), {"records": []})
    index.setdefault("records", []).append(
        {
            "created_at": record["created_at"],
            "event_type": record["event_type"],
            "fingerprint": record["fingerprint"],
            "checkpoint_path": record.get("payload", {}).get("checkpoint_path", ""),
            "resume_command": record.get("payload", {}).get("resume_command", ""),
        }
    )
    write_json(kernel_path(paths, BUDGET_RECOVERY_FILE), index)


def has_novelty(plan: dict[str, Any]) -> bool:
    body = plan.get("plan", plan)
    text = " ".join(str(value).lower() for value in body.values())
    return any(term in text for term in NOVELTY_TERMS)


def similar_route(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    keys = ("failure_anchor", "mechanism", "action_type", "artifact_type")
    matches = sum(1 for key in keys if existing.get(key) and existing.get(key) == candidate.get(key))
    return matches >= 3


def immune_check(paths: VibePaths, plan: dict[str, Any]) -> dict[str, Any]:
    candidate = route_fingerprint(plan)
    records = read_jsonl(kernel_path(paths, REGISTRY_FILE))
    antigens = read_jsonl(kernel_path(paths, ANTIGEN_FILE))
    matches = [record for record in records if similar_route(record, candidate)]
    antigen_matches = [antigen for antigen in antigens if similar_route(antigen, candidate)]
    novelty = has_novelty(plan)
    blocked = bool((matches or antigen_matches) and not novelty)
    return {
        "blocked": blocked,
        "candidate": candidate,
        "matches": matches,
        "antigen_matches": antigen_matches,
        "novelty": novelty,
        "reason": "historical route repeats without new mechanism/source/artifact/evidence" if blocked else "",
    }


def planner_registry_diagnostic(paths: VibePaths, plan: dict[str, Any]) -> dict[str, str] | None:
    check = immune_check(paths, plan)
    if check["blocked"]:
        return {"level": "warning", "code": "registry_repeat_route", "message": check["reason"]}
    return None


def reviewer_registry_criterion(paths: VibePaths, draft: dict[str, Any]) -> dict[str, str] | None:
    check = immune_check(paths, draft)
    if check["blocked"]:
        return {"outcome": "reject", "code": "immune_repeat_route", "message": check["reason"]}
    return None


def load_budget_recovery(paths: VibePaths) -> dict[str, Any]:
    return read_json(kernel_path(paths, BUDGET_RECOVERY_FILE), {"records": []})
