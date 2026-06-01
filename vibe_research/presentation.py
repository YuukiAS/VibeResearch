"""Presentation-ready research package exports."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .adapter_schema import load_adapter_manifest
from .io import ensure_dir, read_json, read_jsonl, utc_now, write_json, write_text
from .optimization import optimization_paths
from .paths import VibePaths
from .research_manager import load_evidence, load_experiments, load_hypotheses, research_paths


TRACE_KEYS = {
    "evidence_id",
    "experiment_id",
    "run_id",
    "metrics_file",
    "artifact",
    "artifact_refs",
    "adapter_revision",
    "policy_revision",
    "code_commit",
    "memo",
}
NEGATIVE_EXPERIMENT_STATUSES = {"failed", "blocked", "stopped", "rejected", "negative"}


def presentation_dir(paths: VibePaths) -> Path:
    return ensure_dir(paths.research / "presentation")


def presentation_paths(paths: VibePaths) -> dict[str, Path]:
    base = presentation_dir(paths)
    return {
        "manifest": base / "manifest.json",
        "narrative": base / "narrative.json",
        "narrative_md": base / "narrative.md",
        "reproducibility": base / "reproducibility_package.json",
        "framework_spec": base / "framework_spec.json",
        "framework_spec_md": base / "framework_spec.md",
        "tables": ensure_dir(base / "tables"),
    }


def build_presentation_package(paths: VibePaths, *, claims: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    narrative = build_narrative(paths, claims=claims)
    reproducibility = build_reproducibility_package(paths)
    tables = export_presentation_tables(paths)
    framework_spec = build_framework_spec(paths)
    manifest = {
        "created_at": utc_now(),
        "package_dir": str(presentation_dir(paths).relative_to(paths.root)),
        "narrative": "narrative.json",
        "reproducibility_package": "reproducibility_package.json",
        "framework_spec": "framework_spec.json",
        "tables": {key: str(path.relative_to(paths.root)) for key, path in tables["table_files"].items()},
        "counts": {
            "traceable_claims": len(narrative.get("traceable_claims", [])),
            "speculation_or_future_work": len(narrative.get("speculation_or_future_work", [])),
            "reproducibility_rows": len(reproducibility.get("evidence_rows", [])),
            "framework_modules": len(framework_spec.get("modules", [])),
        },
    }
    write_json(presentation_paths(paths)["manifest"], manifest)
    return manifest


def build_narrative(paths: VibePaths, *, claims: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    hypotheses = load_hypotheses(paths)
    experiments = load_experiments(paths)
    evidence = load_evidence(paths)
    lineage = load_lineage_records(paths)
    scout = load_scout_records(paths)
    optimization = load_optimization_records(paths)
    owned = load_owned_records(paths)
    supplied_claims = claims if claims is not None else default_claims_from_state(hypotheses, experiments, evidence, scout)
    traceable_claims = [normalize_claim(claim) for claim in supplied_claims if is_traceable_claim(claim)]
    speculation = [normalize_claim(claim) for claim in supplied_claims if not is_traceable_claim(claim)]
    narrative = {
        "created_at": utc_now(),
        "project": read_project_context(paths),
        "hypothesis_history": sorted(hypotheses.values(), key=lambda row: row.get("created_at", "")),
        "experiment_history": sorted(experiments.values(), key=lambda row: row.get("created_at", "")),
        "lineage_history": lineage,
        "scout_history": scout,
        "internalization_history": lineage.get("internalization_decisions", []),
        "owned_framework_history": owned,
        "champion_history": optimization.get("champions", {}),
        "negative_results": collect_negative_results(hypotheses, experiments, evidence, scout),
        "traceable_claims": traceable_claims,
        "speculation_or_future_work": speculation,
    }
    files = presentation_paths(paths)
    write_json(files["narrative"], narrative)
    write_text(files["narrative_md"], render_narrative_markdown(narrative))
    return narrative


def build_reproducibility_package(paths: VibePaths) -> dict[str, Any]:
    hypotheses = load_hypotheses(paths)
    experiments = load_experiments(paths)
    evidence = load_evidence(paths)
    decisions = read_jsonl(research_paths(paths)["decisions"])
    state = read_json(paths.state / "state.json", {})
    code_commit = git_commit(paths.root)
    policy_revision = policy_revision_summary(paths)
    rows = []
    for ev in sorted(evidence.values(), key=lambda row: row.get("created_at", "")):
        exp = experiments.get(ev.get("experiment_id", ""), {})
        hyp = hypotheses.get(exp.get("hypothesis_id", ""), {})
        rows.append(
            {
                "evidence_id": ev.get("evidence_id", ""),
                "claim_basis": ev.get("summary") or ev.get("analysis_notes", ""),
                "hypothesis_id": hyp.get("hypothesis_id", ""),
                "experiment_id": ev.get("experiment_id", ""),
                "run_id": ev.get("run_id") or first_item(exp.get("run_ids", [])) or first_item(exp.get("linked_run_ids", [])),
                "metrics_file": ev.get("metrics_file", ""),
                "artifact_refs": ev.get("artifact_refs", []),
                "adapter_revision": exp.get("adapter_revision", ""),
                "policy_revision": policy_revision,
                "code_commit": code_commit,
                "memo": memo_for_evidence(paths, ev, exp),
                "trusted": bool(ev.get("trusted")),
                "schema_valid": bool(ev.get("schema_valid")),
                "trace_complete": trace_complete(ev, exp, policy_revision, code_commit),
            }
        )
    package = {
        "created_at": utc_now(),
        "code_commit": code_commit,
        "adapter_manifest": ".vibe/adapter/manifest.yaml",
        "adapter_revision": adapter_revision(paths),
        "policy_revision": policy_revision,
        "research_decisions": decisions,
        "state_runs": state.get("runs", {}),
        "evidence_rows": rows,
        "untraceable_evidence_ids": [row["evidence_id"] for row in rows if not row["trace_complete"]],
    }
    write_json(presentation_paths(paths)["reproducibility"], package)
    return package


def export_presentation_tables(paths: VibePaths) -> dict[str, Any]:
    hypotheses = load_hypotheses(paths)
    experiments = load_experiments(paths)
    evidence = load_evidence(paths)
    scout = load_scout_records(paths)
    lineage = load_lineage_records(paths)
    optimization = load_optimization_records(paths)
    tables = {
        "baseline_comparisons": baseline_comparison_rows(experiments, evidence),
        "ablations": read_jsonl(optimization_paths(paths)["ablations"]),
        "stage_gate_progression": stage_gate_rows(hypotheses, experiments, evidence, optimization),
        "budget_usage": budget_rows(paths, experiments),
        "hypothesis_outcomes": hypothesis_outcome_rows(hypotheses, experiments, evidence),
        "scout_to_experiment_trace": scout_trace_rows(scout, lineage, experiments),
        "external_to_owned_transition": external_to_owned_rows(lineage, load_owned_records(paths), optimization),
    }
    table_dir = presentation_paths(paths)["tables"]
    files = {}
    for name, rows in tables.items():
        file = table_dir / f"{name}.json"
        write_json(file, rows)
        files[name] = file
    return {"created_at": utc_now(), "tables": tables, "table_files": files}


def build_framework_spec(paths: VibePaths) -> dict[str, Any]:
    lineage = load_lineage_records(paths)
    owned = load_owned_records(paths)
    internal_caps = load_internal_capabilities(paths)
    optimization = load_optimization_records(paths)
    manifest = load_adapter_manifest(paths)
    active_caps = [cap for cap in manifest.capabilities if cap.status == "active"]
    proposals = lineage.get("framework_proposals", [])
    modules = []
    for proposal in proposals:
        modules.append(
            {
                "module_id": proposal.get("proposal_id", ""),
                "name": proposal.get("title", ""),
                "design_summary": proposal.get("design_summary", ""),
                "module_design": proposal.get("module_design", ""),
                "target": proposal.get("downstream_src_target", ""),
                "status": proposal.get("status", ""),
                "internalization_level": proposal.get("internalization_level", ""),
            }
        )
    for scaffold in owned.get("scaffolds", []):
        modules.append(
            {
                "module_id": scaffold.get("proposal_id", ""),
                "name": scaffold.get("framework_name", ""),
                "design_summary": "owned framework scaffold",
                "target": ", ".join(scaffold.get("files", [])),
                "status": scaffold.get("status", ""),
                "internalization_level": "owned_core_candidate",
            }
        )
    spec = {
        "created_at": utc_now(),
        "modules": modules,
        "interfaces": collect_interfaces(proposals, internal_caps, active_caps),
        "data_flow": [row.get("data_flow", "") for row in proposals if row.get("data_flow")],
        "train_entrypoints": [row.get("training_entrypoint", "") for row in proposals if row.get("training_entrypoint")],
        "inference_entrypoints": [cap.entrypoint.get("command", "") for cap in active_caps if "infer" in cap.id.lower()],
        "evaluation_entrypoints": collect_evaluation_entrypoints(proposals, internal_caps, active_caps),
        "dependencies": dependency_rows(lineage, manifest),
        "owned_core": owned_core_rows(owned, internal_caps, optimization),
        "optional_external_regression": optional_external_regression_rows(lineage, optimization),
        "alignment": framework_alignment_rows(proposals, internal_caps),
    }
    files = presentation_paths(paths)
    write_json(files["framework_spec"], spec)
    write_text(files["framework_spec_md"], render_framework_spec_markdown(spec))
    return spec


def load_lineage_records(paths: VibePaths) -> dict[str, Any]:
    base = paths.research / "lineage"
    return {
        "external_assets": read_jsonl(base / "external_assets.jsonl"),
        "relations": read_jsonl(base / "relations.jsonl"),
        "internalization_decisions": read_jsonl(base / "internalization_decisions.jsonl"),
        "framework_proposals": read_jsonl(base / "framework_proposals.jsonl"),
        "internalization_audits": read_jsonl(base / "internalization_audits.jsonl"),
    }


def load_scout_records(paths: VibePaths) -> dict[str, Any]:
    base = paths.research / "scout"
    return {
        "findings": read_jsonl(base / "findings.jsonl"),
        "triage": read_jsonl(base / "triage.jsonl"),
        "claims": read_jsonl(base / "claims.jsonl"),
        "negative_evidence": read_jsonl(base / "negative_evidence.jsonl"),
    }


def load_optimization_records(paths: VibePaths) -> dict[str, Any]:
    files = optimization_paths(paths)
    return {
        "champions": read_json(files["champions"], {}),
        "challengers": read_jsonl(files["challengers"]),
        "ablations": read_jsonl(files["ablations"]),
        "regressions": read_jsonl(files["regressions"]),
        "memory": read_jsonl(files["memory"]),
        "external_deemphasis": read_jsonl(files["external_deemphasis"]),
    }


def load_owned_records(paths: VibePaths) -> dict[str, Any]:
    base = paths.research / "owned"
    scaffolds = []
    audits = []
    contracts = []
    if base.exists():
        for file in sorted(base.rglob("scaffold.json")):
            scaffolds.append(read_json(file, {}))
        for file in sorted(base.rglob("design_audit.json")):
            audits.append(read_json(file, {}))
        for file in sorted(base.rglob("contract.json")):
            contracts.append(read_json(file, {}))
    return {"scaffolds": scaffolds, "design_audits": audits, "contracts": contracts}


def load_internal_capabilities(paths: VibePaths) -> list[dict[str, Any]]:
    base = paths.vibe / "adapter" / "internal_capabilities"
    if not base.exists():
        return []
    return [read_json(path, {}) for path in sorted(base.glob("*.json"))]


def read_project_context(paths: VibePaths) -> dict[str, Any]:
    config = read_json(paths.vibe / "config.json", {})
    brief = paths.project / "brief.md"
    return {"config_project": config.get("project", {}) if isinstance(config, dict) else {}, "brief_path": str(brief.relative_to(paths.root)) if brief.exists() else ""}


def default_claims_from_state(hypotheses: dict[str, Any], experiments: dict[str, Any], evidence: dict[str, Any], scout: dict[str, Any]) -> list[dict[str, Any]]:
    claims = []
    for ev in evidence.values():
        exp = experiments.get(ev.get("experiment_id", ""), {})
        hyp = hypotheses.get(exp.get("hypothesis_id", ""), {})
        claims.append(
            {
                "claim": ev.get("summary") or exp.get("analysis_summary") or hyp.get("title", ""),
                "hypothesis_id": hyp.get("hypothesis_id", ""),
                "experiment_id": ev.get("experiment_id", ""),
                "evidence_id": ev.get("evidence_id", ""),
                "run_id": ev.get("run_id", ""),
                "metrics_file": ev.get("metrics_file", ""),
                "artifact_refs": ev.get("artifact_refs", []),
            }
        )
    for claim in scout.get("claims", []):
        claims.append({"claim": claim.get("claim", ""), "scout_claim_id": claim.get("claim_id", ""), "support_finding_ids": claim.get("support_finding_ids", [])})
    return claims


def normalize_claim(claim: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in claim.items() if not empty_value(value)}


def empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def is_traceable_claim(claim: dict[str, Any]) -> bool:
    if claim.get("evidence_id"):
        return True
    if claim.get("experiment_id") and (claim.get("run_id") or claim.get("metrics_file") or claim.get("artifact") or claim.get("artifact_refs")):
        return True
    return any(claim.get(key) for key in TRACE_KEYS - {"adapter_revision", "policy_revision", "code_commit", "memo"})


def collect_negative_results(hypotheses: dict[str, Any], experiments: dict[str, Any], evidence: dict[str, Any], scout: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for hyp in hypotheses.values():
        if hyp.get("status") in {"stopped", "blocked", "downscoped"} or hyp.get("negative_evidence"):
            rows.append({"kind": "hypothesis", "hypothesis_id": hyp.get("hypothesis_id", ""), "status": hyp.get("status", ""), "reason": hyp.get("stop_reason") or hyp.get("failure_analysis", {})})
    for exp in experiments.values():
        if exp.get("status") in NEGATIVE_EXPERIMENT_STATUSES or exp.get("failure_analysis"):
            rows.append({"kind": "experiment", "experiment_id": exp.get("experiment_id", ""), "status": exp.get("status", ""), "failure_analysis": exp.get("failure_analysis", {})})
    for ev in evidence.values():
        if ev.get("failure_kind") not in {"", "none"} or ev.get("protected_metric_regressions") or negative_delta(ev.get("metric_deltas", {})):
            rows.append({"kind": "evidence", "evidence_id": ev.get("evidence_id", ""), "experiment_id": ev.get("experiment_id", ""), "failure_kind": ev.get("failure_kind", ""), "protected_metric_regressions": ev.get("protected_metric_regressions", []), "metric_deltas": ev.get("metric_deltas", {})})
    for row in scout.get("negative_evidence", []):
        rows.append({"kind": "scout", **row})
    return rows


def negative_delta(deltas: dict[str, Any]) -> bool:
    for value in deltas.values():
        if isinstance(value, (int, float)) and value < 0:
            return True
    return False


def trace_complete(ev: dict[str, Any], exp: dict[str, Any], policy_revision: str, code_commit: str) -> bool:
    return bool(
        ev.get("evidence_id")
        and ev.get("experiment_id")
        and (ev.get("run_id") or exp.get("run_ids") or exp.get("linked_run_ids"))
        and ev.get("metrics_file")
        and exp.get("adapter_revision")
        and policy_revision
        and code_commit
    )


def memo_for_evidence(paths: VibePaths, ev: dict[str, Any], exp: dict[str, Any]) -> str:
    run_id = ev.get("run_id") or first_item(exp.get("run_ids", []))
    if run_id and (paths.runs / run_id / "reflect.md").exists():
        return str((paths.runs / run_id / "reflect.md").relative_to(paths.root))
    daily = sorted(paths.memos.glob("*.md")) if paths.memos.exists() else []
    return str(daily[-1].relative_to(paths.root)) if daily else ""


def adapter_revision(paths: VibePaths) -> str:
    try:
        return str(load_adapter_manifest(paths).adapter_revision)
    except Exception:
        return ""


def policy_revision_summary(paths: VibePaths) -> str:
    parts = []
    for file in sorted((paths.vibe / "policies").glob("*.yaml")) if (paths.vibe / "policies").exists() else []:
        parts.append(f"{file.name}:{int(file.stat().st_mtime)}")
    return "|".join(parts)


def git_commit(root: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, check=True, text=True, capture_output=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def baseline_comparison_rows(experiments: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for ev in evidence.values():
        exp = experiments.get(ev.get("experiment_id", ""), {})
        comparison = ev.get("baseline_comparison") or exp.get("baseline_target") or {}
        if comparison or ev.get("metric_deltas"):
            rows.append({"experiment_id": ev.get("experiment_id", ""), "evidence_id": ev.get("evidence_id", ""), "run_id": ev.get("run_id", ""), "baseline_comparison": comparison, "metric_deltas": ev.get("metric_deltas", {}), "trusted": ev.get("trusted", False)})
    return rows


def stage_gate_rows(hypotheses: dict[str, Any], experiments: dict[str, Any], evidence: dict[str, Any], optimization: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for hyp in hypotheses.values():
        exp_ids = [exp_id for exp_id, exp in experiments.items() if exp.get("hypothesis_id") == hyp.get("hypothesis_id")]
        ev_ids = [ev_id for ev_id, ev in evidence.items() if ev.get("experiment_id") in exp_ids]
        rows.append({"item_type": "hypothesis", "item_id": hyp.get("hypothesis_id", ""), "stage": hyp.get("current_stage") or hyp.get("stage", ""), "status": hyp.get("status", ""), "experiment_ids": exp_ids, "evidence_ids": ev_ids})
    for stage, champion in optimization.get("champions", {}).items():
        rows.append({"item_type": "champion", "item_id": champion.get("candidate_id", ""), "stage": stage, "status": "champion", "evidence_ids": champion.get("evidence_ids", [])})
    return rows


def budget_rows(paths: VibePaths, experiments: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = read_jsonl(research_paths(paths)["budget"])
    rows = list(ledger)
    for exp in experiments.values():
        if exp.get("cost_estimated") or exp.get("cost_actual"):
            rows.append({"kind": "experiment_cost", "experiment_id": exp.get("experiment_id", ""), "estimated": exp.get("cost_estimated", {}), "actual": exp.get("cost_actual", {})})
    return rows


def hypothesis_outcome_rows(hypotheses: dict[str, Any], experiments: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for hyp in hypotheses.values():
        exp_ids = [exp_id for exp_id, exp in experiments.items() if exp.get("hypothesis_id") == hyp.get("hypothesis_id")]
        ev_ids = [ev_id for ev_id, ev in evidence.items() if ev.get("experiment_id") in exp_ids]
        rows.append({"hypothesis_id": hyp.get("hypothesis_id", ""), "title": hyp.get("title", ""), "status": hyp.get("status", ""), "stage": hyp.get("current_stage", ""), "best_evidence": hyp.get("best_evidence", []), "negative_evidence": hyp.get("negative_evidence", []), "experiment_ids": exp_ids, "evidence_ids": ev_ids})
    return rows


def scout_trace_rows(scout: dict[str, Any], lineage: dict[str, Any], experiments: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    claims = scout.get("claims", [])
    triage_by_finding = {row.get("finding_id", ""): row for row in scout.get("triage", [])}
    proposals = lineage.get("framework_proposals", [])
    for claim in claims:
        support = claim.get("support_finding_ids", [])
        linked_proposals = [row.get("proposal_id", "") for row in proposals if set(row.get("scout_evidence_ids", [])) & set(support)]
        linked_experiments = [exp.get("experiment_id", "") for exp in experiments.values() if claim.get("suggested_experiment") and claim.get("suggested_experiment") in exp.get("design_summary", "")]
        rows.append({"claim_id": claim.get("claim_id", ""), "support_finding_ids": support, "triage_categories": [triage_by_finding.get(item, {}).get("category", "") for item in support], "proposal_ids": linked_proposals, "experiment_ids": linked_experiments})
    return rows


def external_to_owned_rows(lineage: dict[str, Any], owned: dict[str, Any], optimization: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for asset in lineage.get("external_assets", []):
        rows.append({"event_type": "external_asset", "event_id": asset.get("asset_id", ""), "created_at": asset.get("created_at", ""), "level": asset.get("current_internalization_level", ""), "summary": asset.get("title") or asset.get("source", "")})
    for proposal in lineage.get("framework_proposals", []):
        rows.append({"event_type": "framework_proposal", "event_id": proposal.get("proposal_id", ""), "created_at": proposal.get("created_at", ""), "level": proposal.get("internalization_level", ""), "summary": proposal.get("title", ""), "external_baseline_asset_id": proposal.get("external_baseline_asset_id", "")})
    for scaffold in owned.get("scaffolds", []):
        rows.append({"event_type": "owned_scaffold", "event_id": scaffold.get("proposal_id", ""), "created_at": scaffold.get("created_at", ""), "level": "owned_core_candidate", "summary": scaffold.get("framework_name", "")})
    for row in optimization.get("external_deemphasis", []):
        rows.append({"event_type": "external_deemphasis", "event_id": row.get("created_at", ""), "created_at": row.get("created_at", ""), "level": "regression_only" if row.get("approved") else "blocked", "summary": row.get("rationale", "")})
    return sorted(rows, key=lambda row: row.get("created_at", ""))


def collect_interfaces(proposals: list[dict[str, Any]], internal_caps: list[dict[str, Any]], active_caps: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for proposal in proposals:
        for interface in proposal.get("interfaces", []):
            rows.append({"source": proposal.get("proposal_id", ""), "interface": interface})
    for cap in internal_caps:
        rows.append({"source": cap.get("capability_id", ""), "interface": cap.get("entrypoint", ""), "contracts": cap.get("contracts", [])})
    for cap in active_caps:
        rows.append({"source": cap.id, "interface": cap.entrypoint.get("command", ""), "contracts": cap.contracts})
    return rows


def collect_evaluation_entrypoints(proposals: list[dict[str, Any]], internal_caps: list[dict[str, Any]], active_caps: list[Any]) -> list[str]:
    values = [row.get("evaluation_entrypoint", "") for row in proposals if row.get("evaluation_entrypoint")]
    values.extend(str(cap.get("entrypoint", "")) for cap in internal_caps if cap.get("entrypoint"))
    values.extend(cap.entrypoint.get("command", "") for cap in active_caps if cap.entrypoint.get("command"))
    return dedupe(values)


def dependency_rows(lineage: dict[str, Any], manifest: Any) -> list[dict[str, Any]]:
    rows = []
    for asset in lineage.get("external_assets", []):
        rows.append({"dependency_id": asset.get("asset_id", ""), "source": asset.get("source", ""), "mode": asset.get("dependency_mode", ""), "purpose": asset.get("purpose", ""), "replacement_plan": asset.get("replacement_plan", "")})
    rows.extend({"dependency_id": cap.id, "source": "adapter_capability", "mode": cap.status, "purpose": "execution"} for cap in manifest.capabilities)
    return rows


def owned_core_rows(owned: dict[str, Any], internal_caps: list[dict[str, Any]], optimization: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for scaffold in owned.get("scaffolds", []):
        rows.append({"framework_name": scaffold.get("framework_name", ""), "proposal_id": scaffold.get("proposal_id", ""), "status": scaffold.get("status", ""), "capability": scaffold.get("capability", {})})
    for cap in internal_caps:
        rows.append({"framework_name": cap.get("capability_id", ""), "status": cap.get("status", ""), "capability": cap})
    for stage, champion in optimization.get("champions", {}).items():
        if champion.get("candidate_type") == "owned":
            rows.append({"framework_name": champion.get("candidate_id", ""), "status": "champion", "stage": stage, "evidence_ids": champion.get("evidence_ids", [])})
    return rows


def optional_external_regression_rows(lineage: dict[str, Any], optimization: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [{"asset_id": row.get("asset_id", ""), "source": row.get("source", ""), "purpose": row.get("purpose", "")} for row in lineage.get("external_assets", []) if row.get("purpose") in {"baseline", "comparison_target", "reference_implementation"}]
    rows.extend(optimization.get("external_deemphasis", []))
    return rows


def framework_alignment_rows(proposals: list[dict[str, Any]], internal_caps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    caps = {cap.get("proposal_id", ""): cap for cap in internal_caps if cap.get("proposal_id")}
    rows = []
    for proposal in proposals:
        rows.append({"proposal_id": proposal.get("proposal_id", ""), "has_internal_capability": proposal.get("proposal_id", "") in caps, "interfaces_declared": bool(proposal.get("interfaces")), "data_flow_declared": bool(proposal.get("data_flow")), "eval_declared": bool(proposal.get("evaluation_entrypoint") or proposal.get("metrics_schema_ref"))})
    return rows


def render_narrative_markdown(narrative: dict[str, Any]) -> str:
    lines = ["# Presentation Narrative", "", "## Traceable Claims"]
    for claim in narrative.get("traceable_claims", []):
        lines.append(f"- {claim.get('claim', '')} evidence={claim.get('evidence_id', '')} experiment={claim.get('experiment_id', '')} run={claim.get('run_id', '')}")
    if not narrative.get("traceable_claims"):
        lines.append("- none")
    lines.extend(["", "## Speculation Or Future Work"])
    if narrative.get("speculation_or_future_work"):
        lines.extend(f"- {claim.get('claim', '')}" for claim in narrative.get("speculation_or_future_work", []))
    else:
        lines.append("- none")
    lines.extend(["", "## Negative Results"])
    for row in narrative.get("negative_results", []):
        lines.append(f"- {row.get('kind')} {row.get('evidence_id') or row.get('experiment_id') or row.get('hypothesis_id') or row.get('finding_id', '')}")
    if not narrative.get("negative_results"):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def render_framework_spec_markdown(spec: dict[str, Any]) -> str:
    lines = ["# Framework Specification", "", "## Modules"]
    for row in spec.get("modules", []):
        lines.append(f"- `{row.get('module_id')}` {row.get('name')} status={row.get('status')} target={row.get('target')}")
    if not spec.get("modules"):
        lines.append("- none")
    lines.extend(["", "## Evaluation Entrypoints"])
    if spec.get("evaluation_entrypoints"):
        lines.extend(f"- `{item}`" for item in spec.get("evaluation_entrypoints", []))
    else:
        lines.append("- none")
    lines.extend(["", "## Optional External Regression"])
    for row in spec.get("optional_external_regression", []):
        lines.append(f"- `{row.get('asset_id', row.get('created_at', ''))}` {row.get('source', row.get('rationale', ''))}")
    if not spec.get("optional_external_regression"):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def first_item(values: Any) -> str:
    return values[0] if isinstance(values, list) and values else ""


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
