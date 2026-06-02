"""Knowledge lifecycle and orphan clearing for external research inputs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .immune_registry import record_registry_event
from .io import append_jsonl, read_json, read_jsonl, utc_now, write_json, write_text
from .paths import VibePaths


LIFECYCLE_FILE = "knowledge_lifecycle.jsonl"
ORPHAN_AUDIT_FILE = "orphan_audit.json"
ORPHAN_AUDIT_MD = "orphan_audit.md"
ACTIVE_STATUSES = {"INGESTED", "MECHANISM_CARD", "PLAN_CANDIDATE", "CYCLE_PLANNED"}
TERMINAL_STATUSES = {"ACTIVE_MECHANISM", "NEGATIVE_EVIDENCE", "ARCHIVED_REFERENCE", "EXPIRED_ORPHAN"}
LIFECYCLE_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
DEFAULT_TTL_CYCLES = 2


def lifecycle_path(paths: VibePaths):
    return paths.research / "knowledge" / LIFECYCLE_FILE


def knowledge_item_id(source_type: str, source: str, card_id: str = "") -> str:
    digest = hashlib.sha256(json.dumps({"source_type": source_type, "source": source, "card_id": card_id}, sort_keys=True).encode()).hexdigest()[:12]
    return "knowledge-" + digest


def record_knowledge_event(paths: VibePaths, *, source_type: str, source: str, status: str = "INGESTED", card_id: str = "", cycle_age: int = 0, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_status = status.strip().upper()
    if normalized_status not in LIFECYCLE_STATUSES:
        raise ValueError(f"unsupported knowledge lifecycle status: {status}")
    record = {
        "created_at": utc_now(),
        "item_id": knowledge_item_id(source_type, source, card_id),
        "source_type": source_type,
        "source": source,
        "card_id": card_id,
        "status": normalized_status,
        "cycle_age": cycle_age,
        "ttl_cycles": DEFAULT_TTL_CYCLES,
        "evidence": evidence or {},
    }
    append_jsonl(lifecycle_path(paths), record)
    return record


def record_card_lifecycle(paths: VibePaths, card: dict[str, Any]) -> dict[str, Any]:
    status = "ARCHIVED_REFERENCE" if card.get("status") == "ARCHIVED_NO_MVE" else "MECHANISM_CARD"
    return record_knowledge_event(
        paths,
        source_type=str(card.get("source_type", "")),
        source=str(card.get("source", "")),
        status=status,
        card_id=str(card.get("card_id", "")),
        evidence={"card_path": card.get("card_path", ""), "possible_mve": card.get("possible_mve", "")},
    )


def mark_card_plan_candidate(paths: VibePaths, card: dict[str, Any], *, draft_id: str) -> dict[str, Any]:
    return record_knowledge_event(
        paths,
        source_type=str(card.get("source_type", "")),
        source=str(card.get("source", "")),
        status="PLAN_CANDIDATE",
        card_id=str(card.get("card_id", "")),
        evidence={"draft_id": draft_id, "card_path": card.get("card_path", "")},
    )


def mark_card_active_mechanism(paths: VibePaths, card: dict[str, Any], *, manifest_id: str) -> dict[str, Any]:
    return record_knowledge_event(
        paths,
        source_type=str(card.get("source_type", "")),
        source=str(card.get("source", "")),
        status="ACTIVE_MECHANISM",
        card_id=str(card.get("card_id", "")),
        evidence={"manifest_id": manifest_id, "card_path": card.get("card_path", ""), "condition": "compiled MVE manifest"},
    )


def mark_card_cycle_planned(paths: VibePaths, card: dict[str, Any], *, cycle_id: str) -> dict[str, Any]:
    return record_knowledge_event(
        paths,
        source_type=str(card.get("source_type", "")),
        source=str(card.get("source", "")),
        status="CYCLE_PLANNED",
        card_id=str(card.get("card_id", "")),
        evidence={"cycle_id": cycle_id, "card_path": card.get("card_path", "")},
    )


def unconsumed_plan_candidate_cards(paths: VibePaths) -> list[dict[str, Any]]:
    latest = load_latest_knowledge(paths)
    plan_candidate_ids = {
        row.get("card_id", "")
        for row in latest.values()
        if row.get("status") == "PLAN_CANDIDATE" and row.get("card_id")
    }
    if not plan_candidate_ids:
        return []
    registry = {row.get("card_id", ""): row for row in read_jsonl(paths.research / "scout" / "mechanism_cards.jsonl")}
    cards: list[dict[str, Any]] = []
    for card_id in sorted(plan_candidate_ids):
        card = dict(registry.get(card_id, {}))
        if not card:
            lifecycle = next((row for row in latest.values() if row.get("card_id") == card_id), {})
            card = {
                "card_id": card_id,
                "source_type": lifecycle.get("source_type", ""),
                "source": lifecycle.get("source", ""),
                "card_path": lifecycle.get("evidence", {}).get("card_path", "") if isinstance(lifecycle.get("evidence"), dict) else "",
            }
        card["lifecycle_status"] = "PLAN_CANDIDATE"
        cards.append(card)
    return cards


def load_latest_knowledge(paths: VibePaths) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(lifecycle_path(paths)):
        item_id = row.get("item_id")
        if item_id:
            latest[item_id] = row
    return latest


def advance_knowledge_ttl(paths: VibePaths, *, cycles: int = 1) -> dict[str, Any]:
    expired: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    for item in load_latest_knowledge(paths).values():
        if item.get("status") not in ACTIVE_STATUSES:
            continue
        next_item = dict(item)
        next_item["created_at"] = utc_now()
        next_item["cycle_age"] = int(next_item.get("cycle_age", 0)) + cycles
        if next_item["cycle_age"] >= int(next_item.get("ttl_cycles", DEFAULT_TTL_CYCLES)):
            next_item["status"] = "EXPIRED_ORPHAN"
            next_item["expired_at"] = utc_now()
            record_registry_event(paths, event_type="expired_orphan", payload=orphan_registry_payload(next_item))
            expired.append(next_item)
        else:
            updated.append(next_item)
        append_jsonl(lifecycle_path(paths), next_item)
    audit = orphan_audit(paths)
    return {"expired": expired, "updated": updated, "audit": audit}


def orphan_registry_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "failure_anchor": "orphan knowledge expired before Planner/Reviewer/Compiler consumption",
        "mechanism": item.get("card_id") or item.get("source", ""),
        "minimum_experiment": "orphan knowledge clearing",
        "expected_artifact": "knowledge_lifecycle",
        "reflect_decision": "STOP",
        "evidence_type": "negative",
        "item_id": item.get("item_id", ""),
        "source_type": item.get("source_type", ""),
    }


def orphan_audit(paths: VibePaths) -> dict[str, Any]:
    latest = list(load_latest_knowledge(paths).values())
    counts: dict[str, int] = {status: 0 for status in sorted(LIFECYCLE_STATUSES)}
    for item in latest:
        status = str(item.get("status", ""))
        counts[status] = counts.get(status, 0) + 1
    audit = {
        "created_at": utc_now(),
        "new_knowledge": counts.get("INGESTED", 0),
        "mechanism_cards": counts.get("MECHANISM_CARD", 0),
        "plan_candidates": counts.get("PLAN_CANDIDATE", 0),
        "cycle_planned": counts.get("CYCLE_PLANNED", 0),
        "active_mechanisms": counts.get("ACTIVE_MECHANISM", 0),
        "negative_evidence": counts.get("NEGATIVE_EVIDENCE", 0),
        "archived_references": counts.get("ARCHIVED_REFERENCE", 0),
        "expired_orphans": counts.get("EXPIRED_ORPHAN", 0),
        "active_queue": [item for item in latest if item.get("status") in ACTIVE_STATUSES],
        "counts": counts,
    }
    base = paths.research / "knowledge"
    write_json(base / ORPHAN_AUDIT_FILE, audit)
    write_text(base / ORPHAN_AUDIT_MD, render_orphan_audit(audit))
    return audit


def render_orphan_audit(audit: dict[str, Any]) -> str:
    return (
        "# Orphan Knowledge Audit\n\n"
        f"New knowledge: `{audit.get('new_knowledge', 0)}`\n\n"
        f"Mechanism cards: `{audit.get('mechanism_cards', 0)}`\n\n"
        f"Archived references: `{audit.get('archived_references', 0)}`\n\n"
        f"Negative evidence: `{audit.get('negative_evidence', 0)}`\n\n"
        f"Expired orphans: `{audit.get('expired_orphans', 0)}`\n"
    )


def load_orphan_audit(paths: VibePaths) -> dict[str, Any]:
    return read_json(paths.research / "knowledge" / ORPHAN_AUDIT_FILE, {})
