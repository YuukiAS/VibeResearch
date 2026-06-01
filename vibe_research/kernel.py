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


@dataclass(frozen=True)
class RoleProtocol:
    name: str
    role_type: str
    description: str
    readable_files: tuple[str, ...]
    writable_files: tuple[str, ...]
    allowed_actions: frozenset[str]
    forbidden_actions: tuple[str, ...]
    budget_obligations: tuple[str, ...]


@dataclass(frozen=True)
class RolePermissionCheck:
    ok: bool
    session_role: str
    action: str
    reasons: list[str]
    allowed_outputs: tuple[str, ...]


SESSION_ROLES = {
    "planner": RoleProtocol(
        name="Planner",
        role_type="standing",
        description="Proposes draft plans from kernel state, negative memory, open debts, and latest results.",
        readable_files=("PROJECT_KERNEL.md", "PROBLEM_STATE.md", "NEGATIVE_MEMORY.md", "OPEN_DEBTS.md", "EVIDENCE_LEDGER.jsonl", "result_report.md", "reflect_report.md"),
        writable_files=("draft_plan_manifest.json", "draft_plan.md"),
        allowed_actions=frozenset({"start", "read_kernel", "write_draft_plan", "checkpoint", "sleep", "resume"}),
        forbidden_actions=("review_plan", "approve_plan", "execute_manifest", "submit_job", "reflect_results", "modify_code"),
        budget_obligations=("start", "sleep", "resume"),
    ),
    "reviewer": RoleProtocol(
        name="Reviewer",
        role_type="standing",
        description="Reviews and revises draft plans before execution without running commands or filling results.",
        readable_files=("draft_plan_manifest.json", "draft_plan.md", "PROJECT_KERNEL.md", "NEGATIVE_MEMORY.md", "EVIDENCE_LEDGER.jsonl", "safety_policy.yaml"),
        writable_files=("plan_review_report.md", "reviewed_plan_manifest.json"),
        allowed_actions=frozenset({"start", "read_plan", "write_review", "request_revision", "revise", "checkpoint", "sleep", "resume"}),
        forbidden_actions=("execute_manifest", "submit_job", "modify_code", "write_result", "reflect_results"),
        budget_obligations=("start", "revise", "sleep", "resume"),
    ),
    "compiler": RoleProtocol(
        name="Compiler",
        role_type="standing",
        description="Translates reviewed plans into execution manifests and MVE contracts.",
        readable_files=("reviewed_plan_manifest.json", "plan_review_report.md", "mechanism_card.md", "PROJECT_KERNEL.md"),
        writable_files=("execution_manifest.json", "mve_contract.json"),
        allowed_actions=frozenset({"start", "read_reviewed_plan", "write_execution_manifest", "write_mve_contract", "checkpoint", "sleep", "resume"}),
        forbidden_actions=("approve_plan", "execute_manifest", "submit_job", "reflect_results", "change_scientific_goal"),
        budget_obligations=("start", "sleep", "resume"),
    ),
    "executor": RoleProtocol(
        name="Executor",
        role_type="standing",
        description="Executes accepted manifests, writes artifacts, and reports blockers without changing scientific direction.",
        readable_files=("execution_manifest.json", "reviewed_plan_manifest.json", "SESSION_BUDGET_STATE.json", "adapter.yaml"),
        writable_files=("result_report.md", "artifact_inventory.json", "execution_log.jsonl", "blocker_report.md", "RESUME.md"),
        allowed_actions=frozenset({"start", "execute_manifest", "submit_long_task", "submit_prepared_short_job", "write_result", "write_blocker", "checkpoint", "close", "summarize", "sleep", "resume"}),
        forbidden_actions=("write_draft_plan", "approve_plan", "change_failure_anchor", "change_hypothesis", "change_promotion_criteria", "reflect_results"),
        budget_obligations=("start", "submit_long_task", "sleep", "resume"),
    ),
    "reflector": RoleProtocol(
        name="Reflector",
        role_type="standing",
        description="Interprets results, updates belief and memory, and records next debts without running experiments.",
        readable_files=("result_report.md", "artifact_inventory.json", "metrics.csv", "execution_log.jsonl", "reviewed_plan_manifest.json", "execution_manifest.json"),
        writable_files=("reflect_report.md", "NEGATIVE_MEMORY.md", "OPEN_DEBTS.md", "EVIDENCE_LEDGER.jsonl", "belief_update.json"),
        allowed_actions=frozenset({"start", "read_results", "reflect", "reflect_results", "write_belief_update", "write_negative_memory", "checkpoint", "summarize", "sleep", "resume"}),
        forbidden_actions=("execute_manifest", "submit_job", "modify_code", "change_scientific_goal", "write_draft_plan"),
        budget_obligations=("start", "reflect", "sleep", "resume"),
    ),
    "scout": RoleProtocol(
        name="Scout",
        role_type="temporary",
        description="Searches papers, repositories, or leaderboards and emits mechanism cards only.",
        readable_files=("PROJECT_KERNEL.md", "PROBLEM_STATE.md", "FAILURE_SIGNATURES.md", "OPEN_DEBTS.md"),
        writable_files=("mechanism_card.md",),
        allowed_actions=frozenset({"start", "search_sources", "write_mechanism_card", "checkpoint", "sleep", "resume"}),
        forbidden_actions=("write_execution_manifest", "execute_manifest", "submit_job", "approve_plan", "reflect_results"),
        budget_obligations=("start", "sleep", "resume"),
    ),
    "archivist": RoleProtocol(
        name="Archivist",
        role_type="temporary",
        description="Compacts memory, cleans registry noise, and clears WATCH debt without executing experiments.",
        readable_files=("EVIDENCE_LEDGER.jsonl", "NEGATIVE_MEMORY.md", "OPEN_DEBTS.md", "reflect_report.md", "result_report.md"),
        writable_files=("memory_summary.md", "NEGATIVE_MEMORY.md", "OPEN_DEBTS.md", "EVIDENCE_LEDGER.jsonl"),
        allowed_actions=frozenset({"start", "compact_memory", "clear_watch_debt", "archive", "checkpoint", "sleep", "resume"}),
        forbidden_actions=("write_draft_plan", "approve_plan", "execute_manifest", "submit_job", "change_scientific_goal"),
        budget_obligations=("start", "sleep", "resume"),
    ),
}

BUDGET_REQUIRED_ACTIONS = {"start", "submit_long_task", "revise", "reflect", "sleep", "resume"}
CRITICAL_LOW_QUOTA_ACTIONS = {"checkpoint", "sleep", "resume"}
LOW_QUOTA_CLOSE_ACTIONS = {"checkpoint", "close", "summarize", "submit_prepared_short_job", "sleep", "resume"}


def render_session_protocol() -> str:
    lines = [
        "# Session Protocol",
        "",
        "This file is generated from the VibeResearch role catalog. Edit policy",
        "through code or reviewed project policy changes, not by relying on chat",
        "memory.",
        "",
        "## Global Rules",
        "",
        "- A single session must not claim all of plan, review, execute, and reflect for the same target.",
        "- Unknown roles or new permanent roles require `ASK_HUMAN` before use.",
        "- Budget-sensitive actions require a fresh `SESSION_BUDGET_STATE.json` check.",
        "- Below 20% 5h quota, new Planner and Reviewer work pauses; Executor closure has priority, then Reflector preservation.",
        "- Below 10% 5h quota, sessions may only checkpoint, sleep, or resume.",
        "",
        "## Roles",
        "",
    ]
    for key, role in SESSION_ROLES.items():
        lines.extend(
            [
                f"### {role.name}",
                "",
                f"- Role key: `{key}`",
                f"- Type: `{role.role_type}`",
                f"- Description: {role.description}",
                "- Readable files: " + ", ".join(f"`{item}`" for item in role.readable_files),
                "- Writable files: " + ", ".join(f"`{item}`" for item in role.writable_files),
                "- Allowed actions: " + ", ".join(f"`{item}`" for item in sorted(role.allowed_actions)),
                "- Forbidden actions: " + ", ".join(f"`{item}`" for item in role.forbidden_actions),
                "- Budget checkpoints: " + ", ".join(f"`{item}`" for item in role.budget_obligations),
                "",
            ]
        )
    return "\n".join(lines)


def kernel_templates() -> dict[str, str]:
    templates = dict(CORE_MARKDOWN_FILES)
    templates["SESSION_PROTOCOL.md"] = render_session_protocol()
    return templates


def kernel_dir(paths: VibePaths) -> Path:
    return paths.kernel


def initialize_kernel(paths: VibePaths, *, force: bool = False, project_goal: str = "") -> list[Path]:
    """Create the shared kernel files without overwriting edited state."""

    ensure_dir(kernel_dir(paths))
    written: list[Path] = []
    for name, template in kernel_templates().items():
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


def output_allowed(output_path: str, allowed_outputs: tuple[str, ...]) -> bool:
    if not output_path:
        return True
    normalized = output_path.strip().replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return any(name == allowed or normalized.endswith("/" + allowed) for allowed in allowed_outputs)


def check_role_permission(
    *,
    session_role: str,
    action: str,
    output_path: str = "",
    budget_checked: bool = False,
    quota_percent: float | None = None,
) -> RolePermissionCheck:
    role_key = session_role.strip().lower()
    action_key = action.strip().lower()
    role = SESSION_ROLES.get(role_key)
    if role is None:
        return RolePermissionCheck(
            ok=False,
            session_role=role_key,
            action=action_key,
            reasons=[f"unknown role `{role_key}` requires ASK_HUMAN"],
            allowed_outputs=(),
        )

    reasons: list[str] = []
    if action_key in BUDGET_REQUIRED_ACTIONS and not budget_checked:
        reasons.append(f"action `{action_key}` requires a budget state check")
    if quota_percent is not None:
        if quota_percent < 10 and action_key not in CRITICAL_LOW_QUOTA_ACTIONS:
            reasons.append("5h quota below 10%; only checkpoint, sleep, or resume is allowed")
        elif quota_percent < 20:
            if role_key in {"planner", "reviewer"} and action_key not in CRITICAL_LOW_QUOTA_ACTIONS:
                reasons.append(f"5h quota below 20%; {role.name} must pause new work")
            elif role_key == "executor" and action_key not in LOW_QUOTA_CLOSE_ACTIONS:
                reasons.append("5h quota below 20%; Executor may only close, checkpoint, summarize, submit prepared short jobs, sleep, or resume")
            elif role_key == "reflector" and action_key not in LOW_QUOTA_CLOSE_ACTIONS | {"reflect_results", "write_belief_update", "write_negative_memory"}:
                reasons.append("5h quota below 20%; Reflector may only preserve results, checkpoint, sleep, or resume")
    if action_key in role.forbidden_actions:
        reasons.append(f"{role.name} forbids action `{action_key}`")
    if action_key not in role.allowed_actions:
        reasons.append(f"{role.name} does not allow action `{action_key}`")
    if output_path and not output_allowed(output_path, role.writable_files):
        reasons.append(f"{role.name} cannot write `{output_path}`")
    return RolePermissionCheck(ok=not reasons, session_role=role_key, action=action_key, reasons=reasons, allowed_outputs=role.writable_files)


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
