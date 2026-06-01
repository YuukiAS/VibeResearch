"""Belief Ratchet records layered evidence from Reflector outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import append_jsonl, read_json, utc_now, write_json, write_text
from .paths import VibePaths


EVIDENCE_TYPES = {"feasibility", "mechanism", "metric", "robustness", "negative"}
RATCHET_RECORD = ".vibe/kernel/belief_ratchet_record.json"
RATCHET_REGISTRY = ".vibe/kernel/BELIEF_RATCHET_REGISTRY.jsonl"
PROBLEM_MEMORY = "PROBLEM_MEMORY.md"
MECHANISM_MEMORY = "MECHANISM_MEMORY.md"
EXPERIMENT_MEMORY = "EXPERIMENT_MEMORY.md"
OPEN_DEBT_MEMORY = "OPEN_DEBT_MEMORY.md"


def infer_evidence_type(reflection: dict[str, Any]) -> str:
    evidence = reflection.get("evidence", {}) if isinstance(reflection.get("evidence"), dict) else {}
    metric = reflection.get("metric", {}) if isinstance(reflection.get("metric"), dict) else {}
    verdict = str(reflection.get("verdict", "")).upper()
    raw_type = str(evidence.get("type", "")).lower()
    if raw_type in {"feasibility", "partial_reflect"} or metric.get("evidence_type") == "feasibility":
        return "feasibility"
    if verdict in {"STOP", "PIVOT"} or raw_type in {"missing_artifact", "guardrail_regression", "negative"}:
        return "negative"
    if metric.get("robustness") is True or metric.get("folds", 0) and int(metric.get("folds", 0)) > 1:
        return "robustness"
    if raw_type in {"mechanism", "mve_success"} and metric.get("mechanism_signal", True):
        return "mechanism"
    if metric.get("trusted") and metric.get("primary") is not None:
        return "metric"
    return "mechanism" if raw_type == "mve_success" else "feasibility"


def belief_delta_for(evidence_type: str, reflection: dict[str, Any]) -> dict[str, Any]:
    metric = reflection.get("metric", {}) if isinstance(reflection.get("metric"), dict) else {}
    verdict = str(reflection.get("verdict", "")).upper()
    if evidence_type == "feasibility":
        return {"feasibility": "updated", "metric_progress": False, "robustness": False}
    if evidence_type == "mechanism":
        return {"mechanism": "preserve", "metric_progress": bool(metric.get("primary") is not None and verdict == "PROCEED"), "robustness": False}
    if evidence_type == "metric":
        return {"metric_progress": verdict == "PROCEED", "primary": metric.get("primary"), "robustness": False}
    if evidence_type == "robustness":
        return {"robustness": True, "metric_progress": verdict == "PROCEED", "primary": metric.get("primary")}
    return {"negative": True, "avoid_repeat": True, "metric_progress": False, "robustness": False}


def build_ratchet_record(paths: VibePaths, reflection: dict[str, Any], *, execution_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = execution_manifest or read_json(paths.kernel / "execution_manifest.json", {})
    evidence_type = infer_evidence_type(reflection)
    metric = reflection.get("metric", {}) if isinstance(reflection.get("metric"), dict) else {}
    artifact = metric.get("path") or reflection.get("source_result", "")
    record = {
        "schema_version": 1,
        "created_at": utc_now(),
        "accepted_plan_id": reflection.get("accepted_plan_id") or manifest.get("accepted_plan_id", ""),
        "review_approval_id": reflection.get("review_approval_id") or manifest.get("review_approval_id", ""),
        "execution_manifest": str(paths.kernel / "execution_manifest.json"),
        "reflect_manifest": str(paths.kernel / "reflect_manifest.json"),
        "artifact_pointer": artifact,
        "metric_vector": metric,
        "evidence_type": evidence_type,
        "belief_delta": belief_delta_for(evidence_type, reflection),
        "next_debt": reflection.get("next_action", {}),
        "verdict": reflection.get("verdict", ""),
        "belief_update": reflection.get("belief_update", ""),
    }
    return record


def validate_ratchet_record(record: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if record.get("evidence_type") not in EVIDENCE_TYPES:
        issues.append("invalid evidence_type")
    for field in ("artifact_pointer", "metric_vector", "belief_delta", "next_debt", "belief_update"):
        if record.get(field) in ({}, [], "", None):
            issues.append(f"{field} is required")
    if record.get("evidence_type") == "feasibility" and record.get("belief_delta", {}).get("metric_progress"):
        issues.append("feasibility evidence cannot count as metric progress")
    if record.get("evidence_type") != "robustness" and record.get("belief_delta", {}).get("robustness"):
        issues.append("non-robustness evidence cannot create robustness belief")
    return issues


def apply_belief_ratchet(paths: VibePaths, *, reflection_path: Path | None = None, execution_manifest: Path | None = None) -> dict[str, Any]:
    reflection = read_json(reflection_path or (paths.kernel / "reflect_manifest.json"), {})
    manifest = read_json(execution_manifest or (paths.kernel / "execution_manifest.json"), {})
    record = build_ratchet_record(paths, reflection, execution_manifest=manifest)
    issues = validate_ratchet_record(record)
    if issues:
        record["validation_issues"] = issues
    write_json(paths.root / RATCHET_RECORD, record)
    append_jsonl(paths.root / RATCHET_REGISTRY, record)
    update_belief_memories(paths, record)
    return record


def update_belief_memories(paths: VibePaths, record: dict[str, Any]) -> None:
    evidence_type = record.get("evidence_type", "")
    line = render_memory_line(record)
    append_memory(paths.kernel / PROBLEM_MEMORY, line)
    if evidence_type == "mechanism":
        append_memory(paths.kernel / MECHANISM_MEMORY, line)
    elif evidence_type in {"metric", "robustness", "feasibility"}:
        append_memory(paths.kernel / EXPERIMENT_MEMORY, line)
    elif evidence_type == "negative":
        append_memory(paths.kernel / "NEGATIVE_MEMORY.md", line)
    if record.get("next_debt"):
        append_memory(paths.kernel / OPEN_DEBT_MEMORY, line)
        append_memory(paths.kernel / "OPEN_DEBTS.md", line)


def append_memory(path: Path, line: str) -> None:
    if path.exists():
        existing = path.read_text().rstrip()
    else:
        title = path.stem.replace("_", " ").title()
        existing = f"# {title}\n"
    write_text(path, existing + "\n\n" + line + "\n")


def render_memory_line(record: dict[str, Any]) -> str:
    return (
        f"- evidence_type: {record.get('evidence_type', '')}; "
        f"artifact: {record.get('artifact_pointer', '')}; "
        f"belief_delta: {record.get('belief_delta', {})}; "
        f"next_debt: {record.get('next_debt', {})}"
    )


def load_ratchet_record(path: Path) -> dict[str, Any]:
    return read_json(path, {})
