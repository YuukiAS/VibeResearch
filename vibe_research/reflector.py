"""Independent Reflector Session interpretation of Executor outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import append_jsonl, read_json, read_jsonl, utc_now, write_json, write_text
from .mve import promotion_debt_for_success
from .paths import VibePaths
from .session_budget_guard import guard_session_action, load_budget_state, write_low_budget_checkpoint


REFLECT_VERDICTS = {"PROCEED", "REFINE", "PIVOT", "STOP", "ASK_HUMAN"}
REFLECT_REPORT = ".vibe/kernel/reflect_report.md"
REFLECT_MANIFEST = ".vibe/kernel/reflect_manifest.json"
REFLECT_REGISTRY = ".vibe/kernel/REFLECTION_REGISTRY.jsonl"
FEASIBILITY_TERMS = {"smoke", "import", "status", "cache", "readme", "summary"}


def load_reflection_inputs(paths: VibePaths, *, result_manifest: Path | None = None, execution_manifest: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    result_path = result_manifest or (paths.executor / "result_manifest.json")
    manifest_path = execution_manifest or (paths.kernel / "execution_manifest.json")
    return read_json(result_path, {}), read_json(manifest_path, {})


def reflect_executor_result(
    paths: VibePaths,
    *,
    result_manifest: Path | None = None,
    execution_manifest: Path | None = None,
    allow_partial: bool = True,
) -> dict[str, Any]:
    budget = guard_session_action(paths, role="reflector", phase="REFLECT")
    if not budget["ok"]:
        state = load_budget_state(paths)
        checkpoint = write_low_budget_checkpoint(paths, state, phase="REFLECT", reasons=budget["reasons"]) if allow_partial else {}
        reflection = build_reflection_manifest(
            verdict="ASK_HUMAN",
            evidence={"type": "partial_reflect", "summary": "budget guard blocked full reflection"},
            metric={"trusted": False, "summary": "not read under low quota"},
            guardrail={"status": "unknown", "summary": "not read under low quota"},
            belief_update="Partial reflect only; resume from checkpoint before interpreting results.",
            next_action={"type": "resume", "command": state.get("next_resume_command", "") if state else ""},
            issues=budget["reasons"],
            source_result=str(result_manifest or (paths.executor / "result_manifest.json")),
        )
        write_reflection_outputs(paths, reflection, partial=True)
        reflection["checkpoint_path"] = checkpoint.get("checkpoint_path", "")
        return reflection

    result, manifest = load_reflection_inputs(paths, result_manifest=result_manifest, execution_manifest=execution_manifest)
    reflection = interpret_reflection(paths, result, manifest, source_result=str(result_manifest or (paths.executor / "result_manifest.json")))
    write_reflection_outputs(paths, reflection)
    return reflection


def interpret_reflection(paths: VibePaths, result: dict[str, Any], manifest: dict[str, Any], *, source_result: str) -> dict[str, Any]:
    issues: list[str] = []
    records = result.get("artifact_inventory", [])
    if not isinstance(records, list):
        records = []
    expected_artifacts = manifest.get("expected_artifacts") or result.get("expected_artifacts") or []
    missing = [record.get("path", "") for record in records if isinstance(record, dict) and record.get("required") and not record.get("exists")]
    for artifact in expected_artifacts:
        if artifact and not (paths.root / str(artifact)).exists():
            missing.append(str(artifact))
    missing = sorted(set(filter(None, missing)))

    metric = read_metric_summary(paths.root, expected_artifacts)
    guardrail = guardrail_summary(metric)
    mve_contract = manifest.get("mve_contract", result.get("mve_contract", {}))
    mve_level = mve_contract.get("level", "one_case") if isinstance(mve_contract, dict) else "one_case"
    feasibility_only = any(any(term in str(path).lower() for term in FEASIBILITY_TERMS) for path in expected_artifacts)
    subset_failed = metric.get("subset_status") in {"fail", "failed", "negative"} or metric.get("subset_success") is False

    if missing:
        verdict = "STOP"
        evidence = {"type": "missing_artifact", "summary": "required execution artifact is missing", "artifacts": missing}
        next_action = {"type": "refinement_debt", "reason": "missing expected artifact", "artifacts": missing}
        belief = "No reliable belief update; execution did not produce the required artifact."
        issues.extend(f"missing artifact: {path}" for path in missing)
    elif guardrail["status"] == "regression":
        verdict = "PIVOT"
        evidence = {"type": "guardrail_regression", "summary": "metric artifact reports guardrail regression"}
        next_action = {"type": "negative_memory", "reason": guardrail["summary"]}
        belief = "Evidence is negative because guardrails regressed."
    elif feasibility_only or metric.get("evidence_type") == "feasibility":
        verdict = "REFINE"
        evidence = {"type": "feasibility", "summary": "smoke/import success is feasibility evidence only"}
        next_action = {"type": "refinement_debt", "reason": "replace smoke/import evidence with MVE artifact"}
        belief = "Feasibility improved, but research belief should not move without evidence-grade artifacts."
    elif subset_failed and mve_level in {"one_case", "component_dataset"}:
        verdict = "REFINE"
        evidence = {"type": "subset_failure", "summary": "one-case or component evidence did not survive subset check"}
        next_action = {"type": "refinement_debt", "reason": "subset failure blocks promotion"}
        belief = "Initial evidence is insufficient for promotion because subset validation failed."
    elif metric.get("trusted"):
        verdict = "PROCEED"
        evidence = {"type": "mve_success", "summary": "trusted MVE artifact supports the reviewed mechanism"}
        next_action = {"type": "promotion_debt", **promotion_debt_for_success({"mve_contract": mve_contract})}
        belief = "MVE evidence supports promotion to the next evidence debt, not mainline success."
    else:
        verdict = "ASK_HUMAN"
        evidence = {"type": "untrusted_metric", "summary": "artifact exists but metric/evidence cannot be trusted"}
        next_action = {"type": "human_question", "question": "Can this artifact be treated as trusted evidence?"}
        belief = "Artifact exists, but belief update is blocked until evidence trust is resolved."

    return build_reflection_manifest(
        verdict=verdict,
        evidence=evidence,
        metric=metric,
        guardrail=guardrail,
        belief_update=belief,
        next_action=next_action,
        issues=issues,
        source_result=source_result,
        execution_manifest=manifest,
    )


def read_metric_summary(root: Path, artifacts: list[Any]) -> dict[str, Any]:
    for artifact in artifacts:
        path = root / str(artifact)
        if path.exists() and path.suffix.lower() == ".json":
            data = read_json(path, {})
            if isinstance(data, dict):
                trusted = bool(data.get("trusted", True)) and not any(term in str(artifact).lower() for term in FEASIBILITY_TERMS)
                return {
                    "trusted": trusted,
                    "path": str(artifact),
                    "primary": data.get("primary", data.get("metric", data.get("score"))),
                    "guardrail": data.get("guardrail"),
                    "guardrail_regression": data.get("guardrail_regression", False),
                    "subset_status": data.get("subset_status"),
                    "subset_success": data.get("subset_success"),
                    "evidence_type": data.get("evidence_type", ""),
                    "summary": data.get("summary", "json metric artifact read"),
                }
    return {"trusted": False, "path": "", "summary": "no metric artifact read"}


def guardrail_summary(metric: dict[str, Any]) -> dict[str, Any]:
    if metric.get("guardrail_regression") is True:
        return {"status": "regression", "summary": "guardrail_regression=true"}
    guardrail = metric.get("guardrail")
    if isinstance(guardrail, (int, float)) and guardrail < 0:
        return {"status": "regression", "summary": f"guardrail is negative: {guardrail}"}
    if str(guardrail).lower() in {"fail", "failed", "regression"}:
        return {"status": "regression", "summary": f"guardrail status: {guardrail}"}
    return {"status": "ok" if metric.get("trusted") else "unknown", "summary": "no guardrail regression detected"}


def build_reflection_manifest(
    *,
    verdict: str,
    evidence: dict[str, Any],
    metric: dict[str, Any],
    guardrail: dict[str, Any],
    belief_update: str,
    next_action: dict[str, Any],
    issues: list[str],
    source_result: str,
    execution_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reflection = {
        "schema_version": 1,
        "created_at": utc_now(),
        "session_role": "reflector",
        "verdict": verdict,
        "source_result": source_result,
        "accepted_plan_id": (execution_manifest or {}).get("accepted_plan_id", ""),
        "review_approval_id": (execution_manifest or {}).get("review_approval_id", ""),
        "evidence": evidence,
        "metric": metric,
        "guardrail": guardrail,
        "belief_update": belief_update,
        "next_action": next_action,
        "issues": issues,
        "executor_cannot_declare_success": True,
    }
    validation = validate_reflection(reflection)
    if validation:
        reflection["validation_issues"] = validation
    return reflection


def validate_reflection(reflection: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if reflection.get("session_role") != "reflector":
        issues.append("session_role must be reflector")
    if reflection.get("verdict") not in REFLECT_VERDICTS:
        issues.append("invalid reflect verdict")
    for field in ("evidence", "metric", "guardrail", "belief_update", "next_action"):
        if not reflection.get(field):
            issues.append(f"{field} is required")
    if reflection.get("verdict") == "PROCEED" and reflection.get("next_action", {}).get("type") != "promotion_debt":
        issues.append("PROCEED requires promotion debt, not mainline success")
    return issues


def write_reflection_outputs(paths: VibePaths, reflection: dict[str, Any], *, partial: bool = False) -> dict[str, Path]:
    manifest_path = paths.root / REFLECT_MANIFEST
    report_path = paths.root / REFLECT_REPORT
    write_json(manifest_path, reflection)
    write_text(report_path, render_reflect_report(reflection, partial=partial))
    append_jsonl(paths.root / REFLECT_REGISTRY, reflection)
    if reflection["verdict"] in {"STOP", "PIVOT"}:
        append_negative_memory(paths, reflection)
    if reflection.get("next_action", {}).get("type") in {"promotion_debt", "refinement_debt"}:
        append_open_debt(paths, reflection)
    append_jsonl(
        paths.kernel / "EVIDENCE_LEDGER.jsonl",
        {
            "created_at": utc_now(),
            "session_role": "reflector",
            "source": str(report_path),
            "artifact": reflection.get("metric", {}).get("path", reflection.get("source_result", "")),
            "evidence_type": reflection.get("evidence", {}).get("type", ""),
            "belief_update": reflection.get("belief_update", ""),
            "next_action": reflection.get("next_action", {}).get("type", ""),
            "action": "reflect",
        },
    )
    return {"manifest": manifest_path, "report": report_path, "registry": paths.root / REFLECT_REGISTRY}


def render_reflect_report(reflection: dict[str, Any], *, partial: bool = False) -> str:
    return "\n".join(
        [
            "# Reflect Report",
            "",
            f"Verdict: {reflection.get('verdict', '')}",
            f"Partial: {str(partial).lower()}",
            "",
            "## Evidence",
            str(reflection.get("evidence", {}).get("summary", "")),
            "",
            "## Metric",
            str(reflection.get("metric", {}).get("summary", "")),
            "",
            "## Guardrail",
            str(reflection.get("guardrail", {}).get("summary", "")),
            "",
            "## Belief Update",
            str(reflection.get("belief_update", "")),
            "",
            "## Next Action",
            str(reflection.get("next_action", {})),
            "",
        ]
    )


def append_negative_memory(paths: VibePaths, reflection: dict[str, Any]) -> None:
    path = paths.kernel / "NEGATIVE_MEMORY.md"
    existing = path.read_text() if path.exists() else "# Negative Memory\n\n"
    write_text(path, existing.rstrip() + f"\n\n- {reflection['verdict']}: {reflection.get('belief_update', '')}\n")


def append_open_debt(paths: VibePaths, reflection: dict[str, Any]) -> None:
    path = paths.kernel / "OPEN_DEBTS.md"
    existing = path.read_text() if path.exists() else "# Open Debts\n\n"
    action = reflection.get("next_action", {})
    write_text(path, existing.rstrip() + f"\n\n- type: {action.get('type', '')}\n  source: reflect\n  detail: {action}\n")


def load_reflection(path: Path) -> dict[str, Any]:
    return read_json(path, {})
