"""Session-oriented research kernel file protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import append_jsonl, ensure_dir, read_jsonl, utc_now, write_text
from .paths import VibePaths


CORE_MARKDOWN_FILES = {
    "PROJECT_KERNEL.md": "# Project Kernel\n\n## Goal\n\nTBD\n\n## Boundaries\n\n- Preserve project-specific safety and resource policies.\n",
    "PROBLEM_STATE.md": "# Problem State\n\n## Current State\n\nTBD\n\n## Latest Belief\n\nTBD\n",
    "FAILURE_SIGNATURES.md": "# Failure Signatures\n\n- id: TBD\n  description: TBD\n  status: active\n",
    "OPEN_DEBTS.md": "# Open Debts\n\n- id: TBD\n  next_debt: Define the first reviewed research debt.\n  ttl: TBD\n",
    "NEGATIVE_MEMORY.md": "# Negative Memory\n\nNo negative evidence recorded yet.\n",
    "SESSION_PROTOCOL.md": "# Session Protocol\n\n## Standing Roles\n\n- Planner: may write draft plans only.\n- Reviewer: may write review reports and reviewed plans only.\n- Compiler: may write execution manifests from reviewed plans.\n- Executor: may execute accepted manifests and report artifacts.\n- Reflector: may interpret results and update belief state.\n- Scout: may write mechanism cards only.\n- Archivist: may compact memory and clear stale registry debt.\n\n## Closed Loop Rule\n\nA single session must not claim all of plan, review, execute, and reflect for the same target.\n",
}

LEDGER_FILE = "EVIDENCE_LEDGER.jsonl"
REQUIRED_FILES = tuple(CORE_MARKDOWN_FILES) + (LEDGER_FILE,)
CLOSED_LOOP_ACTIONS = {"plan", "review", "execute", "reflect"}
ROLE_ALLOWED_ACTIONS = {
    "planner": {"plan"},
    "reviewer": {"review"},
    "compiler": {"compile"},
    "executor": {"execute"},
    "reflector": {"reflect"},
    "scout": {"scout"},
    "archivist": {"archive"},
}


@dataclass(frozen=True)
class ProtocolCheck:
    ok: bool
    missing_files: list[str]
    violations: list[str]
    evidence_count: int


def kernel_dir(paths: VibePaths) -> Path:
    return paths.kernel


def initialize_kernel(paths: VibePaths, *, force: bool = False, project_goal: str = "") -> list[Path]:
    """Create the shared kernel files without overwriting edited state."""

    ensure_dir(kernel_dir(paths))
    written: list[Path] = []
    for name, template in CORE_MARKDOWN_FILES.items():
        path = kernel_dir(paths) / name
        if path.exists() and not force:
            continue
        text = template
        if name == "PROJECT_KERNEL.md" and project_goal:
            text = template.replace("TBD", project_goal, 1)
        write_text(path, text)
        written.append(path)
    ledger = kernel_dir(paths) / LEDGER_FILE
    if force or not ledger.exists():
        write_text(ledger, "")
        written.append(ledger)
    return written


def missing_kernel_files(paths: VibePaths) -> list[str]:
    return [name for name in REQUIRED_FILES if not (kernel_dir(paths) / name).exists()]


def kernel_status(paths: VibePaths) -> dict[str, Any]:
    missing = missing_kernel_files(paths)
    records = read_jsonl(kernel_dir(paths) / LEDGER_FILE)
    return {
        "ok": not missing,
        "kernel_dir": str(kernel_dir(paths)),
        "missing_files": missing,
        "evidence_count": len(records),
        "latest_evidence": records[-1] if records else None,
    }


def record_evidence(
    paths: VibePaths,
    *,
    session_role: str,
    source: str,
    artifact: str,
    evidence_type: str,
    belief_update: str,
    next_action: str,
    session_id: str = "",
    target_id: str = "",
    action: str = "",
) -> dict[str, Any]:
    missing = missing_kernel_files(paths)
    if missing:
        raise ValueError(f"missing kernel files: {', '.join(missing)}")
    required = {
        "session_role": session_role,
        "source": source,
        "artifact": artifact,
        "evidence_type": evidence_type,
        "belief_update": belief_update,
        "next_action": next_action,
    }
    blank = [key for key, value in required.items() if not str(value).strip()]
    if blank:
        raise ValueError(f"missing required evidence fields: {', '.join(blank)}")
    normalized_role = session_role.strip().lower()
    normalized_action = action.strip().lower()
    if normalized_action:
        allowed = ROLE_ALLOWED_ACTIONS.get(normalized_role)
        if allowed is not None and normalized_action not in allowed:
            raise ValueError(f"{normalized_role} session cannot claim {normalized_action} action")
    record = {
        "created_at": utc_now(),
        "session_role": normalized_role,
        "source": source,
        "artifact": artifact,
        "evidence_type": evidence_type,
        "belief_update": belief_update,
        "next_action": next_action,
        "session_id": session_id,
        "target_id": target_id,
        "action": normalized_action,
    }
    append_jsonl(kernel_dir(paths) / LEDGER_FILE, record)
    return record


def check_protocol(
    paths: VibePaths,
    *,
    proposed_session_id: str = "",
    proposed_target_id: str = "",
    proposed_action: str = "",
) -> ProtocolCheck:
    missing = missing_kernel_files(paths)
    records = read_jsonl(kernel_dir(paths) / LEDGER_FILE)
    claims: dict[tuple[str, str], set[str]] = {}
    for record in records:
        session_id = str(record.get("session_id", "")).strip()
        target_id = str(record.get("target_id", "")).strip()
        action = str(record.get("action", "")).strip().lower()
        if session_id and target_id and action:
            claims.setdefault((session_id, target_id), set()).add(action)
    if proposed_session_id and proposed_target_id and proposed_action:
        claims.setdefault((proposed_session_id, proposed_target_id), set()).add(proposed_action.strip().lower())

    violations: list[str] = []
    for (session_id, target_id), actions in sorted(claims.items()):
        if CLOSED_LOOP_ACTIONS <= actions:
            violations.append(f"session {session_id} claims closed-loop duties for {target_id}: {', '.join(sorted(actions))}")
    return ProtocolCheck(ok=not missing and not violations, missing_files=missing, violations=violations, evidence_count=len(records))
