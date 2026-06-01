"""Budget-aware session runtime state and guard checks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io import ensure_dir, read_json, utc_now, write_json, write_text
from .kernel import check_role_permission
from .paths import VibePaths


BUDGET_STATE = "SESSION_BUDGET_STATE.json"
ZERO_COST_WAIT = "ZERO_COST_WAIT.json"
WAIT_SCRIPT = "wait_until_budget_reset.sh"
PHASE_ACTIONS = {
    "PLAN": ("planner", "write_draft_plan"),
    "REVIEW": ("reviewer", "write_review"),
    "COMPILE": ("compiler", "write_execution_manifest"),
    "EXECUTE": ("executor", "execute_manifest"),
    "REFLECT": ("reflector", "reflect_results"),
    "SLEEP": ("executor", "sleep"),
    "CHECKPOINT": ("executor", "checkpoint"),
}


def budget_state_path(paths: VibePaths) -> Path:
    return paths.kernel / BUDGET_STATE


def default_budget_state(*, session_name: str = "", role: str = "", resume_command: str = "") -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": 1,
        "created_at": now,
        "updated_at": now,
        "session_name": session_name,
        "role": role,
        "five_hour_quota_percent": None,
        "weekly_quota_percent": None,
        "last_manual_observation_at": "",
        "estimated_reset_at": "",
        "has_running_slurm_job": False,
        "running_slurm_job_id": "",
        "active_owner": session_name,
        "next_resume_command": resume_command,
        "open_debts": [],
        "checkpoint_path": "",
        "quota_source": "unknown/manual",
    }


def initialize_budget_state(paths: VibePaths, *, force: bool = False, session_name: str = "", role: str = "", resume_command: str = "") -> Path:
    state_path = budget_state_path(paths)
    if state_path.exists() and not force:
        ensure_wait_script(paths)
        return state_path
    write_json(state_path, default_budget_state(session_name=session_name, role=role, resume_command=resume_command))
    ensure_wait_script(paths)
    return state_path


def load_budget_state(paths: VibePaths) -> dict[str, Any]:
    return read_json(budget_state_path(paths), {})


def save_budget_state(paths: VibePaths, state: dict[str, Any]) -> Path:
    state["updated_at"] = utc_now()
    write_json(budget_state_path(paths), state)
    return budget_state_path(paths)


def parse_codex_status(text: str) -> dict[str, float | None]:
    patterns = {
        "five_hour_quota_percent": r"(?:5h|5-hour|five[- ]hour)\s+limit[^0-9]*(\d+(?:\.\d+)?)\s*%\s+left",
        "weekly_quota_percent": r"weekly\s+limit[^0-9]*(\d+(?:\.\d+)?)\s*%\s+left",
    }
    parsed: dict[str, float | None] = {"five_hour_quota_percent": None, "weekly_quota_percent": None}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed[key] = float(match.group(1))
    return parsed


def refresh_budget_from_status(
    paths: VibePaths,
    *,
    status_text: str,
    session_name: str = "",
    role: str = "",
    estimated_reset_at: str = "",
    resume_command: str = "",
) -> dict[str, Any]:
    state = load_budget_state(paths) or default_budget_state()
    parsed = parse_codex_status(status_text)
    state.update({key: value for key, value in parsed.items() if value is not None})
    if session_name:
        state["session_name"] = session_name
        state["active_owner"] = session_name
    if role:
        state["role"] = role
    if estimated_reset_at:
        state["estimated_reset_at"] = estimated_reset_at
    if resume_command:
        state["next_resume_command"] = resume_command
    state["last_manual_observation_at"] = utc_now()
    state["quota_source"] = "codex_status_manual"
    save_budget_state(paths, state)
    return state


def guard_session_action(paths: VibePaths, *, role: str, phase: str, output_path: str = "", checkpoint_on_block: bool = False) -> dict[str, Any]:
    state = load_budget_state(paths)
    normalized_phase = phase.strip().upper()
    if not state:
        return {
            "ok": False,
            "phase": normalized_phase,
            "role": role,
            "action": "",
            "reasons": [f"{BUDGET_STATE} is required before session work"],
            "state_path": str(budget_state_path(paths)),
            "checkpoint_path": "",
        }
    mapped_role, action = PHASE_ACTIONS.get(normalized_phase, (role, normalized_phase.lower()))
    effective_role = role or mapped_role
    quota = state.get("five_hour_quota_percent")
    check = check_role_permission(
        session_role=effective_role,
        action=action,
        output_path=output_path,
        budget_checked=True,
        quota_percent=float(quota) if quota is not None else None,
    )
    reasons = list(check.reasons)
    if quota is not None and float(quota) < 20 and normalized_phase in {"PLAN", "REVIEW", "COMPILE", "EXECUTE"}:
        reasons.append(f"{normalized_phase} is blocked below 20% 5h quota; checkpoint, sleep, or preserve results instead")
    if quota is not None and float(quota) < 10 and normalized_phase != "SLEEP":
        reasons.append("5h quota below 10%; RESUME.md checkpoint is required")
    checkpoint_path = ""
    ok = not reasons
    if checkpoint_on_block and not ok:
        checkpoint = write_low_budget_checkpoint(paths, state, phase=normalized_phase, reasons=reasons)
        checkpoint_path = checkpoint["checkpoint_path"]
    return {
        "ok": ok,
        "phase": normalized_phase,
        "role": check.session_role,
        "action": check.action,
        "reasons": reasons,
        "state_path": str(budget_state_path(paths)),
        "checkpoint_path": checkpoint_path,
    }


def write_low_budget_checkpoint(paths: VibePaths, state: dict[str, Any], *, phase: str, reasons: list[str] | None = None) -> dict[str, Any]:
    session_name = state.get("session_name") or "session"
    checkpoint_dir = paths.kernel / "budget_checkpoints"
    checkpoint_path = checkpoint_dir / f"{session_name}-{phase.lower()}-checkpoint.json"
    checkpoint = {
        "schema_version": 1,
        "created_at": utc_now(),
        "session_name": session_name,
        "role": state.get("role", ""),
        "phase": phase,
        "five_hour_quota_percent": state.get("five_hour_quota_percent"),
        "weekly_quota_percent": state.get("weekly_quota_percent"),
        "has_running_slurm_job": state.get("has_running_slurm_job", False),
        "running_slurm_job_id": state.get("running_slurm_job_id", ""),
        "next_resume_command": state.get("next_resume_command", ""),
        "open_debts": state.get("open_debts", []),
        "reasons": reasons or [],
    }
    write_json(checkpoint_path, checkpoint)
    state["checkpoint_path"] = str(checkpoint_path.relative_to(paths.root))
    save_budget_state(paths, state)
    write_resume_markdown(paths, checkpoint)
    return {"checkpoint_path": str(checkpoint_path), "resume_path": str(paths.root / "RESUME.md")}


def write_resume_markdown(paths: VibePaths, checkpoint: dict[str, Any]) -> Path:
    lines = [
        "# RESUME",
        "",
        f"- Session: {checkpoint.get('session_name', '')}",
        f"- Role: {checkpoint.get('role', '')}",
        f"- Phase: {checkpoint.get('phase', '')}",
        f"- 5h quota left: {checkpoint.get('five_hour_quota_percent', 'unknown')}",
        f"- Weekly quota left: {checkpoint.get('weekly_quota_percent', 'unknown')}",
        f"- Running Slurm job: {checkpoint.get('running_slurm_job_id', '') or 'none'}",
        f"- Next resume command: `{checkpoint.get('next_resume_command', '')}`",
        "",
        "## Open Debts",
    ]
    debts = checkpoint.get("open_debts", [])
    lines.extend(f"- {debt}" for debt in debts) if debts else lines.append("- none")
    lines.extend(["", "## Block Reasons"])
    reasons = checkpoint.get("reasons", [])
    lines.extend(f"- {reason}" for reason in reasons) if reasons else lines.append("- none")
    lines.append("")
    write_text(paths.root / "RESUME.md", "\n".join(lines))
    return paths.root / "RESUME.md"


def record_zero_cost_wait(paths: VibePaths, *, wait_type: str, job_id: str = "", estimated_reset_at: str = "", resume_command: str = "") -> dict[str, Any]:
    normalized = wait_type.strip().lower().replace("_", "-")
    if normalized not in {"slurm-job", "quota-wait"}:
        raise ValueError("wait_type must be slurm-job or quota-wait")
    if normalized == "slurm-job" and not job_id:
        raise ValueError("job_id is required for slurm-job wait mode")
    state = load_budget_state(paths) or default_budget_state()
    if normalized == "slurm-job":
        state["has_running_slurm_job"] = True
        state["running_slurm_job_id"] = job_id
        command = f"squeue -j {job_id} || sacct -j {job_id}"
    else:
        state["estimated_reset_at"] = estimated_reset_at or state.get("estimated_reset_at", "")
        command = str(paths.root / WAIT_SCRIPT)
    if resume_command:
        state["next_resume_command"] = resume_command
    save_budget_state(paths, state)
    record = {
        "schema_version": 1,
        "created_at": utc_now(),
        "wait_type": normalized,
        "job_id": job_id,
        "estimated_reset_at": state.get("estimated_reset_at", ""),
        "resume_command": state.get("next_resume_command", ""),
        "zero_cost": True,
        "poll_command": command,
    }
    write_json(paths.kernel / ZERO_COST_WAIT, record)
    ensure_wait_script(paths)
    return record


def ensure_wait_script(paths: VibePaths) -> Path:
    script = paths.executor / WAIT_SCRIPT
    if script.exists():
        return script
    write_text(
        script,
        """#!/usr/bin/env bash
set -euo pipefail
echo "Quota wait mode: stop Codex reasoning and resume after the recorded reset time."
echo "Check .vibe/kernel/SESSION_BUDGET_STATE.json and RESUME.md before continuing."
""",
    )
    script.chmod(0o755)
    return script
