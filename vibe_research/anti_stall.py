"""Anti-stall benchmark traps for VibeResearch role and evidence gates."""

from __future__ import annotations

import json
from typing import Any

from .compiler import compile_reviewed_plan
from .decision_debt import clear_expired_decision_debts, open_decision_debt
from .io import read_json, utc_now, write_json, write_text
from .knowledge_lifecycle import advance_knowledge_ttl, record_knowledge_event
from .mve import promotion_debt_for_success
from .os_beta import low_quota_checkpoint_probe, registry_blocking_probe, role_isolation_probe
from .paths import VibePaths
from .planner import build_draft_plan
from .reflector import build_reflection_manifest, validate_reflection
from .reviewer import review_draft_plan, write_review_outputs
from .scout import create_mechanism_card


ANTI_STALL_REPORT = "ANTI_STALL_BENCHMARK.json"
ANTI_STALL_REPORT_MD = "ANTI_STALL_BENCHMARK.md"


def trap_plan_kwargs(**overrides: str) -> dict[str, str]:
    data = {
        "mode": "invent",
        "failure_anchor": "remote false positives persist after baseline filtering",
        "hypothesis": "a component veto can remove remote false positives",
        "mechanism": "component-veto-with-shape-prior",
        "minimum_experiment": "one-case component veto MVE with saved mask artifact",
        "expected_artifact": ".vibe/runs/anti_stall/component_veto_metrics.json",
        "expected_belief_update": "decide whether component veto has mechanism evidence",
        "compute_cost": "local cpu under 5 minutes",
        "risk": "may over-remove true positives",
        "fallback": "record negative evidence and try route-level filter",
        "stop_condition": "no component-level precision gain",
        "confidence": "speculative_mechanism",
    }
    data.update(overrides)
    return data


def run_anti_stall_benchmark(paths: VibePaths) -> dict[str, Any]:
    paths.require_initialized()
    traps = {
        "generic_unet_rejected": generic_unet_trap(paths),
        "negative_memory_checked": negative_memory_trap(paths),
        "clone_repo_requires_mve": clone_repo_trap(paths),
        "one_case_promotes_subset_debt": one_case_promotion_trap(),
        "smoke_is_feasibility_only": smoke_feasibility_trap(),
        "watch_debt_cleared": watch_debt_trap(paths),
        "role_boundaries_hold": role_isolation_probe(),
        "orphan_knowledge_cleared": orphan_trap(paths),
        "registry_duplicate_blocked": registry_blocking_probe(paths),
        "low_quota_checkpoint_resume": low_quota_checkpoint_probe(paths),
    }
    score = score_traps(traps)
    report = {"created_at": utc_now(), "score": score, "traps": traps}
    write_json(paths.kernel / ANTI_STALL_REPORT, report)
    write_text(paths.kernel / ANTI_STALL_REPORT_MD, render_anti_stall_report(report))
    return report


def generic_unet_trap(paths: VibePaths) -> dict[str, Any]:
    draft = build_draft_plan(
        paths,
        **trap_plan_kwargs(
            mechanism="generic 3D U-Net rerun",
            hypothesis="another U-Net may improve the result",
            minimum_experiment="metadata import smoke only",
            expected_artifact=".vibe/runs/anti_stall/unet_metadata.md",
        ),
    )
    review = review_draft_plan(paths, draft)
    blocked = review["verdict"] == "REJECT" and any(item.get("code") in {"generic_architecture", "metadata_or_smoke_only"} for item in review.get("criteria", []))
    return {"passed": blocked, "verdict": review["verdict"], "criteria": review.get("criteria", [])}


def negative_memory_trap(paths: VibePaths) -> dict[str, Any]:
    (paths.kernel / "NEGATIVE_MEMORY.md").write_text("U-MyoPS rerun failed without new mechanism\n")
    draft = build_draft_plan(paths, **trap_plan_kwargs(mechanism="U-MyoPS rerun"))
    blocked = any(item.get("code") == "negative_memory_overlap" for item in draft.get("diagnostics", []))
    return {"passed": blocked, "diagnostics": draft.get("diagnostics", [])}


def clone_repo_trap(paths: VibePaths) -> dict[str, Any]:
    card = create_mechanism_card(
        paths,
        source_type="repo",
        source="https://example.invalid/foundation.git",
        claim="A foundation repo might help.",
        mechanism_extraction="foundation repo clone",
        why_it_matters="candidate external reference",
        failure_anchor="remote false positives persist after baseline filtering",
        possible_mve="",
        required_assets=["repo README"],
        risks=["clone-only work is not evidence"],
        stop_reason="no MVE extracted",
    )
    clone_only_blocked = False
    try:
        reviewed = accepted_reviewed_manifest(paths)
        reviewed["draft_plan"]["plan"]["minimum_experiment"] = "git clone https://example.invalid/foundation.git"
        compile_reviewed_plan(paths, reviewed)
    except ValueError as exc:
        clone_only_blocked = "clone/install" in str(exc)
    return {"passed": card["status"] == "ARCHIVED_NO_MVE" and clone_only_blocked, "card_status": card["status"], "clone_only_blocked": clone_only_blocked}


def accepted_reviewed_manifest(paths: VibePaths) -> dict[str, Any]:
    draft = build_draft_plan(paths, **trap_plan_kwargs())
    outputs = write_review_outputs(paths, review_draft_plan(paths, draft))
    return read_json(outputs["reviewed_manifest"], {})


def one_case_promotion_trap() -> dict[str, Any]:
    debt = promotion_debt_for_success({"mve_contract": {"level": "one_case"}})
    return {"passed": "subset" in json.dumps(debt).lower(), "debt": debt}


def smoke_feasibility_trap() -> dict[str, Any]:
    reflection = build_reflection_manifest(
        verdict="REFINE",
        evidence={"type": "feasibility", "summary": "smoke/import success is feasibility evidence only"},
        metric={"trusted": False, "evidence_type": "feasibility", "summary": "smoke metric"},
        guardrail={"status": "unknown", "summary": "smoke has no guardrail evidence"},
        belief_update="Feasibility improved, but research belief should not move without evidence-grade artifacts.",
        next_action={"type": "refinement_debt", "missing_evidence": "trusted metric evidence", "repayment_mve": "run subset MVE"},
        issues=[],
        source_result=".vibe/executor/result_manifest.json",
    )
    issues = validate_reflection(reflection)
    passed = reflection["verdict"] == "REFINE" and reflection["evidence"]["type"] == "feasibility" and not issues
    return {"passed": passed, "reflection": reflection, "issues": issues}


def watch_debt_trap(paths: VibePaths) -> dict[str, Any]:
    debt = open_decision_debt(
        paths,
        {
            "created_at": utc_now(),
            "session_role": "reflector",
            "verdict": "WATCH",
            "source_result": ".vibe/executor/result_manifest.json",
            "accepted_plan_id": "anti-stall-watch",
            "evidence": {"type": "mechanism", "summary": "watch requires repayment"},
            "metric": {"trusted": False, "summary": "watch metric"},
            "guardrail": {"status": "ok", "summary": "watch guardrail"},
            "belief_update": "WATCH cannot park indefinitely.",
            "next_action": {"type": "watch_debt", "missing_evidence": "subset robustness", "repayment_mve": "run subset MVE", "ttl_rounds": 2},
            "issues": [],
        },
    )
    cleared = clear_expired_decision_debts(paths, rounds=2)
    return {"passed": bool(cleared.get("cleared")), "debt_id": debt.get("debt_id", ""), "cleared": cleared.get("cleared", [])}


def orphan_trap(paths: VibePaths) -> dict[str, Any]:
    record_knowledge_event(paths, source_type="paper", source="https://example.invalid/background")
    result = advance_knowledge_ttl(paths, cycles=2)
    return {"passed": bool(result.get("expired")), "expired": result.get("expired", [])}


def score_traps(traps: dict[str, dict[str, Any]]) -> dict[str, Any]:
    categories = {
        "low_value_route_rejection": traps["generic_unet_rejected"].get("passed") and traps["negative_memory_checked"].get("passed") and traps["clone_repo_requires_mve"].get("passed"),
        "orphan_knowledge_clearing": traps["orphan_knowledge_cleared"].get("passed"),
        "registry_duplicate_blocking": traps["registry_duplicate_blocked"].get("blocked"),
        "decision_debt_clearing": traps["watch_debt_cleared"].get("passed"),
        "evidence_promotion": traps["one_case_promotes_subset_debt"].get("passed") and traps["smoke_is_feasibility_only"].get("passed"),
        "role_boundary_compliance": traps["role_boundaries_hold"].get("ok"),
        "budget_checkpoint_resume": traps["low_quota_checkpoint_resume"].get("blocked") and traps["low_quota_checkpoint_resume"].get("resume_exists"),
    }
    passed = sum(1 for value in categories.values() if value)
    total = len(categories)
    return {"passed": passed, "total": total, "ratio": passed / total if total else 0, "categories": categories}


def validate_anti_stall_report(report: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    score = report.get("score", {})
    categories = score.get("categories", {}) if isinstance(score, dict) else {}
    for name, passed in categories.items():
        if not passed:
            issues.append(f"category failed: {name}")
    if score.get("passed") != score.get("total"):
        issues.append("anti-stall benchmark did not pass every category")
    return issues


def render_anti_stall_report(report: dict[str, Any]) -> str:
    score = report.get("score", {})
    lines = ["# Anti-Stall Benchmark", "", f"Score: `{score.get('passed', 0)}/{score.get('total', 0)}`", ""]
    for name, passed in score.get("categories", {}).items():
        lines.append(f"- {name}: `{passed}`")
    return "\n".join(lines) + "\n"
