"""Approval artifacts for high-impact scheduler actions."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .io import utc_now, write_json, write_text
from .paths import VibePaths


def fallback_requeue_command(
    target: Path,
    run_id: str,
    *,
    allow_outside_policy: bool = False,
    allow_carried_forward: bool = False,
    execute: bool = True,
) -> str:
    parts = [
        "vibe",
        "scheduler-requeue-fallback",
        "--target",
        str(target.resolve()),
        "--run-id",
        run_id,
    ]
    if execute:
        parts.append("--execute")
    if allow_outside_policy:
        parts.append("--allow-outside-policy")
    if allow_carried_forward:
        parts.append("--allow-carried-forward")
    return " ".join(shlex.quote(part) for part in parts)


def render_fallback_requeue_request(record: dict[str, Any]) -> str:
    lines = [
        "# Fallback Requeue Approval Request",
        "",
        f"Status: `{record.get('status')}`",
        f"Target: `{record.get('target')}`",
        f"Risk: {record.get('risk')}",
        "",
        "This artifact is dry-run evidence only. It did not cancel or resubmit live jobs.",
        "",
        "## Candidate Commands",
    ]
    rows = record.get("rows", []) if isinstance(record.get("rows"), list) else []
    if not rows:
        lines.append("- none")
    for row in rows:
        lines.extend(
            [
                f"- Run `{row.get('run_id', '')}` job `{row.get('job_id', '')}`",
                f"  - current partition: `{row.get('current_partition', '')}`",
                f"  - recommended partition: `{row.get('recommended_partition', '')}`",
                f"  - eligible: `{row.get('eligible')}` blocked: `{row.get('blocked_reason', '')}`",
                f"  - command: `{row.get('executable_command', '')}`",
            ]
        )
    return "\n".join(lines) + "\n"


def write_fallback_requeue_request(paths: VibePaths, rows: list[dict[str, Any]]) -> dict[str, Any]:
    created_at = utc_now()
    request_id = created_at.replace(":", "").replace("-", "").replace("Z", "Z")
    record = {
        "request_id": request_id,
        "created_at": created_at,
        "status": "dry_run_only_not_executed",
        "target": str(paths.root),
        "risk": "execution cancels and resubmits live scheduler jobs; explicit user approval is required before running any command",
        "rows": rows,
    }
    request_dir = paths.scheduler / "fallback_requeue_requests"
    write_json(request_dir / f"{request_id}.json", record)
    write_text(request_dir / f"{request_id}.md", render_fallback_requeue_request(record))
    write_json(request_dir / "latest.json", record)
    write_text(request_dir / "latest.md", render_fallback_requeue_request(record))
    return record
