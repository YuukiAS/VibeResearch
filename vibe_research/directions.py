"""Direction state management."""

from __future__ import annotations

import json

from .io import append_jsonl, read_jsonl, utc_now
from .paths import VibePaths
from .timeline import record_event


def set_direction_status(paths: VibePaths, direction_id: str, status: str, reason: str = "") -> None:
    record = {"direction_id": direction_id, "status": status, "reason": reason, "updated_at": utc_now()}
    append_jsonl(paths.directions / "registry.jsonl", record)
    record_event(paths, f"direction_{status}", reason or direction_id, direction_id=direction_id, status=status, payload=record)


def latest_direction_status(paths: VibePaths, direction_id: str) -> str:
    return latest_direction_record(paths, direction_id).get("status", "")


def latest_direction_record(paths: VibePaths, direction_id: str) -> dict:
    record = {}
    status = ""
    for row in read_jsonl(paths.directions / "registry.jsonl"):
        if row.get("direction_id") == direction_id:
            status = row.get("status", "")
            record = row
    if status and "status" not in record:
        record["status"] = status
    return record
