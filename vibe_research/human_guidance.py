"""Structured human guidance inbox for Planner and Reviewer."""

from __future__ import annotations

import json
from typing import Any

from .io import append_jsonl, ensure_dir, next_numeric_id, read_jsonl, utc_now, write_text
from .paths import VibePaths
from .timeline import record_event


ACTIVE_GUIDANCE_STATUSES = {"ACTIVE", "NEEDS_MORE_EVIDENCE", "ASK_HUMAN", "PARTIALLY_APPLIED"}
GUIDANCE_STATUSES = ACTIVE_GUIDANCE_STATUSES | {"APPLIED", "REJECTED", "SUPERSEDED"}


def guidance_registry_path(paths: VibePaths):
    return paths.research / "human_guidance.jsonl"


def ensure_human_guidance(paths: VibePaths) -> None:
    ensure_dir(paths.research)
    if not guidance_registry_path(paths).exists():
        write_text(guidance_registry_path(paths), "")
    inbox = paths.research / "HUMAN_IDEA_INBOX.md"
    if not inbox.exists():
        write_text(inbox, "# Human Idea Inbox\n\nNo human guidance yet.\n")


def read_human_guidance(paths: VibePaths) -> list[dict[str, Any]]:
    ensure_human_guidance(paths)
    return read_jsonl(guidance_registry_path(paths))


def active_human_guidance(paths: VibePaths) -> list[dict[str, Any]]:
    return [row for row in read_human_guidance(paths) if row.get("status") in ACTIVE_GUIDANCE_STATUSES]


def add_human_guidance(
    paths: VibePaths,
    raw_text: str,
    *,
    source: str = "cli",
    language: str = "auto",
    priority: str = "high",
    linked_failure_signature: str = "",
    suggested_mechanism: str = "",
    linked_raw_id: str = "",
) -> dict[str, Any]:
    ensure_human_guidance(paths)
    guidance_id = next_numeric_id([row.get("guidance_id", "") for row in read_human_guidance(paths)], "guidance_")
    record = {
        "guidance_id": guidance_id,
        "timestamp": utc_now(),
        "updated_at": utc_now(),
        "source": source,
        "raw_text": raw_text,
        "language": normalize_language(language, raw_text),
        "priority": priority,
        "linked_failure_signature": linked_failure_signature,
        "suggested_mechanism": suggested_mechanism,
        "status": "ACTIVE",
        "review_decision": "PENDING",
        "applied_in_plan": "",
        "superseded_by": "",
        "linked_raw_id": linked_raw_id,
        "notes": "",
    }
    append_jsonl(guidance_registry_path(paths), record)
    render_human_guidance_inbox(paths)
    record_event(paths, "human_guidance_received", raw_text[:180], status="ACTIVE", payload={"guidance_id": guidance_id})
    return record


def update_human_guidance(paths: VibePaths, guidance_id: str, **updates: Any) -> dict[str, Any]:
    rows = read_human_guidance(paths)
    for row in rows:
        if row.get("guidance_id") != guidance_id:
            continue
        status = updates.get("status", row.get("status", "ACTIVE"))
        if status not in GUIDANCE_STATUSES:
            raise ValueError(f"Unsupported guidance status: {status}")
        row.update({key: value for key, value in updates.items() if value is not None})
        row["updated_at"] = utc_now()
        write_guidance_rows(paths, rows)
        record_event(paths, "human_guidance_updated", f"{guidance_id}: {row.get('status')}", status=row.get("status", ""), payload=row)
        return row
    raise ValueError(f"Unknown guidance: {guidance_id}")


def mark_guidance_considered(paths: VibePaths, plan: dict[str, Any]) -> list[dict[str, Any]]:
    body_text = json.dumps(plan, sort_keys=True).lower()
    plan_id = str(plan.get("created_at") or plan.get("plan_id") or "")
    updated = []
    for row in active_human_guidance(paths):
        tokens = guidance_tokens(row)
        if tokens and any(token in body_text for token in tokens):
            updated.append(
                update_human_guidance(
                    paths,
                    row["guidance_id"],
                    status="PARTIALLY_APPLIED",
                    review_decision="PLANNER_CONSIDERED",
                    applied_in_plan=plan_id,
                    notes="Planner draft referenced this guidance.",
                )
            )
    return updated


def sync_guidance_after_reflect(paths: VibePaths, target_id: str, evidence_text: str) -> list[dict[str, Any]]:
    updated = []
    text = evidence_text.lower()
    for row in read_human_guidance(paths):
        if row.get("applied_in_plan") and row.get("status") in {"PARTIALLY_APPLIED", "NEEDS_MORE_EVIDENCE"}:
            status = "APPLIED" if any(token in text for token in ["schema", "metric", "evidence", "trusted", "valid"]) else "NEEDS_MORE_EVIDENCE"
            updated.append(
                update_human_guidance(
                    paths,
                    row["guidance_id"],
                    status=status,
                    review_decision="REFLECTOR_UPDATED",
                    notes=f"Reflector updated after {target_id}.",
                )
            )
    return updated


def guidance_tokens(row: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(row.get(key, ""))
        for key in ["raw_text", "linked_failure_signature", "suggested_mechanism"]
    ).lower()
    return [token for token in text.replace("-", " ").replace("_", " ").split() if len(token) >= 5][:12]


def guidance_context(paths: VibePaths) -> dict[str, Any]:
    active = active_human_guidance(paths)
    return {
        "active_count": len(active),
        "active_guidance": active[-20:],
        "registry_path": ".vibe/research/human_guidance.jsonl",
        "inbox_path": ".vibe/research/HUMAN_IDEA_INBOX.md",
    }


def write_guidance_rows(paths: VibePaths, rows: list[dict[str, Any]]) -> None:
    ensure_human_guidance(paths)
    write_text(guidance_registry_path(paths), "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    render_human_guidance_inbox(paths)


def render_human_guidance_inbox(paths: VibePaths) -> None:
    rows = read_jsonl(guidance_registry_path(paths))
    lines = ["# Human Idea Inbox", "", "| Guidance | Status | Priority | Review | Applied In Plan | Text |", "|---|---|---|---|---|---|"]
    for row in rows:
        text = str(row.get("raw_text", "")).replace("|", "\\|")[:160]
        lines.append(
            f"| `{row.get('guidance_id', '')}` | `{row.get('status', '')}` | `{row.get('priority', '')}` | "
            f"`{row.get('review_decision', '')}` | `{row.get('applied_in_plan', '')}` | {text} |"
        )
    if len(lines) == 3:
        lines.append("| none | | | | | |")
    write_text(paths.research / "HUMAN_IDEA_INBOX.md", "\n".join(lines) + "\n")


def normalize_language(language: str, text: str) -> str:
    if language in {"zh", "en"}:
        return language
    return "zh" if any("\u4e00" <= char <= "\u9fff" for char in text) else "en"
