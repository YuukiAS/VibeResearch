"""VibeResearch OS beta closed-loop harness."""

from __future__ import annotations

from typing import Any

from .belief_ratchet import apply_belief_ratchet
from .compiler import compile_reviewed_plan, write_execution_package
from .decision_debt import clear_expired_decision_debts, open_decision_debt
from .executor import run_execution_manifest, validate_result_manifest
from .immune_registry import record_registry_event
from .io import read_json, utc_now, write_json, write_text
from .kernel import check_role_permission
from .paths import VibePaths
from .planner import build_draft_plan, write_draft_plan
from .reflector import reflect_executor_result
from .reviewer import review_draft_plan, write_review_outputs
from .session_budget_guard import guard_session_action, refresh_budget_from_status


OS_BETA_REPORT = "OS_BETA_HARNESS.json"
OS_BETA_REPORT_MD = "OS_BETA_HARNESS.md"


def os_beta_plan_kwargs(**overrides: str) -> dict[str, str]:
    data = {
        "mode": "invent",
        "failure_anchor": "remote false positives persist after baseline filtering",
        "hypothesis": "a component veto can remove remote false positives",
        "mechanism": "component-veto-with-shape-prior",
        "minimum_experiment": "one-case component veto MVE with saved metric artifact",
        "expected_artifact": ".vibe/runs/os_beta/component_veto_metrics.json",
        "expected_belief_update": "decide whether component veto has mechanism evidence",
        "compute_cost": "local cpu under 5 minutes",
        "risk": "may over-remove true positives",
        "fallback": "record negative evidence and try route-level filter",
        "stop_condition": "no component-level precision gain",
        "confidence": "speculative_mechanism",
    }
    data.update(overrides)
    return data


def run_closed_loop_harness(paths: VibePaths) -> dict[str, Any]:
    paths.require_initialized()
    if not (paths.kernel / "FAILURE_SIGNATURES.md").read_text().strip():
        write_text(paths.kernel / "FAILURE_SIGNATURES.md", "# Failure Signatures\n\nremote false positives persist after baseline filtering\n")

    budget_guards = {
        phase: guard_session_action(paths, role=role, phase=phase)
        for phase, role in (("PLAN", "planner"), ("REVIEW", "reviewer"), ("COMPILE", "compiler"), ("EXECUTE", "executor"), ("REFLECT", "reflector"))
    }

    draft = build_draft_plan(paths, **os_beta_plan_kwargs())
    draft_path = write_draft_plan(paths, draft)
    review = review_draft_plan(paths, draft)
    review_paths = write_review_outputs(paths, review)
    reviewed = read_json(review_paths["reviewed_manifest"], {})
    manifest = compile_reviewed_plan(paths, reviewed)
    package = write_execution_package(paths, manifest)
    result = run_execution_manifest(paths, manifest, manifest_path=package["manifest"])
    reflection = reflect_executor_result(paths)
    registry = record_registry_event(paths, event_type="os_beta_reflect", payload=reflection)
    ratchet = apply_belief_ratchet(paths)
    next_draft = build_draft_plan(
        paths,
        **os_beta_plan_kwargs(
            mechanism="new verifier proxy for component-veto-with-shape-prior",
            minimum_experiment="repay open promotion debt with subset verifier MVE",
            expected_artifact=".vibe/runs/os_beta_next/subset_verifier_metrics.json",
            expected_belief_update="decide whether the ratcheted mechanism survives subset evidence",
        ),
    )
    next_draft_path = write_draft_plan(paths, next_draft, output="next_draft_plan_manifest.json")

    validation = validate_closed_loop(paths)
    role_isolation = role_isolation_probe()
    duplicate_probe = registry_blocking_probe(paths)
    debt_probe = debt_clearing_probe(paths)
    low_quota_probe = low_quota_checkpoint_probe(paths)
    report = {
        "created_at": utc_now(),
        "chain_complete": validation["ok"],
        "budget_guards": budget_guards,
        "artifacts": {
            "draft_plan": str(draft_path.relative_to(paths.root)),
            "review_report": str(review_paths["report"].relative_to(paths.root)),
            "reviewed_manifest": str(review_paths["reviewed_manifest"].relative_to(paths.root)),
            "execution_manifest": str(package["manifest"].relative_to(paths.root)),
            "result_report": ".vibe/executor/result_report.md",
            "reflect_report": ".vibe/kernel/reflect_report.md",
            "registry": ".vibe/kernel/RESEARCH_REGISTRY.jsonl",
            "memory_update": ".vibe/kernel/belief_ratchet_record.json",
            "next_draft": str(next_draft_path.relative_to(paths.root)),
        },
        "review_before_execute": bool(result.get("review_approval_id")),
        "manifest_driven_execution": result.get("source_manifest", "").endswith("execution_manifest.json"),
        "reflect_before_next_plan": bool(reflection.get("created_at") and next_draft.get("created_at")),
        "registry_update": registry,
        "ratchet_update": ratchet,
        "validation": validation,
        "role_isolation": role_isolation,
        "registry_blocking": duplicate_probe,
        "debt_clearing": debt_probe,
        "low_quota_checkpoint": low_quota_probe,
    }
    write_json(paths.kernel / OS_BETA_REPORT, report)
    write_text(paths.kernel / OS_BETA_REPORT_MD, render_os_beta_report(report))
    return report


def validate_closed_loop(paths: VibePaths) -> dict[str, Any]:
    required = {
        "draft_plan": paths.kernel / "draft_plan_manifest.json",
        "review_report": paths.kernel / "plan_review_report.md",
        "reviewed_manifest": paths.kernel / "reviewed_plan_manifest.json",
        "execution_manifest": paths.kernel / "execution_manifest.json",
        "result_report": paths.executor / "result_report.md",
        "reflect_report": paths.kernel / "reflect_report.md",
        "registry": paths.kernel / "RESEARCH_REGISTRY.jsonl",
        "memory_update": paths.kernel / "belief_ratchet_record.json",
        "next_draft": paths.kernel / "next_draft_plan_manifest.json",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    result = read_json(paths.executor / "result_manifest.json", {})
    result_issues = validate_result_manifest(paths, result) if result else ["result_manifest is required"]
    review = read_json(paths.kernel / "reviewed_plan_manifest.json", {})
    manifest = read_json(paths.kernel / "execution_manifest.json", {})
    invariants = {
        "review_before_execute": bool(review.get("review", {}).get("verdict") == "ACCEPT" and manifest.get("review_approval_id")),
        "manifest_driven_execution": result.get("source_manifest", "").endswith("execution_manifest.json"),
        "reflect_before_next_plan": required["reflect_report"].exists() and required["next_draft"].exists(),
    }
    issues = [f"missing {name}" for name in missing] + result_issues
    issues.extend(f"invariant failed: {key}" for key, value in invariants.items() if not value)
    return {"ok": not issues, "issues": issues, "invariants": invariants, "required": {name: str(path) for name, path in required.items()}}


def role_isolation_probe() -> dict[str, Any]:
    probes = {
        "planner_cannot_execute": check_role_permission(session_role="planner", action="execute_manifest", budget_checked=True, quota_percent=80).ok is False,
        "reviewer_cannot_run_command": check_role_permission(session_role="reviewer", action="execute_manifest", budget_checked=True, quota_percent=80).ok is False,
        "compiler_cannot_bypass_review": check_role_permission(session_role="compiler", action="approve_plan", budget_checked=True, quota_percent=80).ok is False,
        "executor_cannot_change_goal": check_role_permission(session_role="executor", action="change_scientific_goal", budget_checked=True, quota_percent=80).ok is False,
        "reflector_cannot_execute": check_role_permission(session_role="reflector", action="execute_manifest", budget_checked=True, quota_percent=80).ok is False,
        "archivist_cannot_delete_results": check_role_permission(session_role="archivist", action="delete_result", budget_checked=True, quota_percent=80).ok is False,
    }
    return {"ok": all(probes.values()), "probes": probes}


def registry_blocking_probe(paths: VibePaths) -> dict[str, Any]:
    record_registry_event(paths, event_type="reflect", payload={**os_beta_plan_kwargs(), "reflect_decision": "STOP", "evidence_type": "negative"})
    duplicate = build_draft_plan(paths, **os_beta_plan_kwargs(expected_artifact=".vibe/runs/os_beta_renamed/component_veto_metrics.json"))
    blocked = any(item.get("code") == "registry_repeat_route" for item in duplicate.get("diagnostics", []))
    return {"blocked": blocked, "diagnostics": duplicate.get("diagnostics", [])}


def debt_clearing_probe(paths: VibePaths) -> dict[str, Any]:
    open_decision_debt(
        paths,
        {
            "created_at": utc_now(),
            "session_role": "reflector",
            "verdict": "REFINE",
            "source_result": ".vibe/executor/result_manifest.json",
            "accepted_plan_id": "os-beta-debt",
            "evidence": {"type": "feasibility", "summary": "probe debt needs repayment"},
            "metric": {"trusted": False, "summary": "probe"},
            "guardrail": {"status": "ok", "summary": "probe"},
            "belief_update": "Probe debt remains open until TTL clearing.",
            "next_action": {
                "type": "refinement_debt",
                "missing_evidence": "probe subset evidence",
                "repayment_mve": "run probe subset MVE",
                "ttl_rounds": 2,
                "stop_condition": "probe remains unresolved",
            },
            "issues": [],
        },
    )
    result = clear_expired_decision_debts(paths, rounds=2)
    return {"cleared_count": len(result.get("cleared", [])), "open_debts": result.get("open_debts", [])}


def low_quota_checkpoint_probe(paths: VibePaths) -> dict[str, Any]:
    refresh_budget_from_status(paths, status_text="5h limit: 5% left\nweekly limit: 60% left", session_name="os-beta-plan", role="planner", resume_command="vibe os-beta run")
    guard = guard_session_action(paths, role="planner", phase="PLAN", checkpoint_on_block=True)
    return {"blocked": not guard["ok"], "checkpoint_path": guard.get("checkpoint_path", ""), "resume_exists": (paths.root / "RESUME.md").exists(), "reasons": guard["reasons"]}


def render_os_beta_report(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# OS Beta Harness",
            "",
            f"Chain complete: `{report.get('chain_complete')}`",
            f"Review before execute: `{report.get('review_before_execute')}`",
            f"Manifest-driven execution: `{report.get('manifest_driven_execution')}`",
            f"Reflect before next plan: `{report.get('reflect_before_next_plan')}`",
            f"Role isolation: `{report.get('role_isolation', {}).get('ok')}`",
            f"Registry duplicate blocked: `{report.get('registry_blocking', {}).get('blocked')}`",
            f"Debt cleared: `{report.get('debt_clearing', {}).get('cleared_count', 0)}`",
            f"Low quota checkpoint: `{report.get('low_quota_checkpoint', {}).get('checkpoint_path', '')}`",
            "",
        ]
    )
