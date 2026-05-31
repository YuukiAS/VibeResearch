"""Research lineage and internalization readiness primitives."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from .io import append_jsonl, ensure_dir, next_numeric_id, read_jsonl, utc_now, write_json, write_text
from .paths import VibePaths
from .research_manager import load_evidence
from .scout import qualifying_scout_evidence


ASSET_PURPOSES = {
    "baseline",
    "reference_implementation",
    "dependency",
    "inspiration",
    "ablation_target",
    "temporary_wrapper",
    "comparison_target",
}
INTERNALIZATION_LEVELS = [
    "external_only",
    "wrapped_external",
    "shadow_internal",
    "hybrid_internal",
    "owned_core_candidate",
    "owned_core",
    "final_owned",
]


class ExternalAssetRecord(BaseModel):
    asset_id: str
    source: str
    title: str = ""
    asset_type: str = "external_repo"
    purpose: str = "reference_implementation"
    credibility: str = "unknown"
    license_or_restrictions: str = ""
    dependency_mode: str = "unknown"
    replacement_plan: str = ""
    current_internalization_level: str = "external_only"
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_fields(self) -> "ExternalAssetRecord":
        if self.purpose not in ASSET_PURPOSES:
            raise ValueError(f"unsupported external asset purpose: {self.purpose}")
        if self.current_internalization_level not in INTERNALIZATION_LEVELS:
            raise ValueError(f"unsupported internalization level: {self.current_internalization_level}")
        return self


class LineageRelationRecord(BaseModel):
    relation_id: str
    source_id: str
    target_id: str
    relation_type: str
    rationale: str = ""
    created_at: str = Field(default_factory=utc_now)


class InternalizationDecisionRecord(BaseModel):
    decision_id: str
    proposal_id: str = ""
    hypothesis_id: str = ""
    asset_id: str = ""
    internalize_what: str
    why_now: str
    expected_benefit: str
    risks: list[str] = Field(default_factory=list)
    downstream_src_target: str
    new_scripts_needed: list[str] = Field(default_factory=list)
    adapter_capability_impact: str = ""
    baseline_comparison: str
    rollback_plan: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: str = "proposed"
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_required_argumentation(self) -> "InternalizationDecisionRecord":
        missing = []
        for key in [
            "internalize_what",
            "why_now",
            "expected_benefit",
            "downstream_src_target",
            "baseline_comparison",
            "rollback_plan",
        ]:
            if not getattr(self, key):
                missing.append(key)
        if missing:
            raise ValueError("internalization decision missing fields: " + ", ".join(missing))
        return self


class FrameworkProposalRecord(BaseModel):
    proposal_id: str
    title: str
    hypothesis_id: str
    asset_id: str
    design_summary: str
    module_design: str
    data_flow: str
    interfaces: list[str] = Field(default_factory=list)
    training_entrypoint: str = ""
    evaluation_entrypoint: str = ""
    metrics_schema_ref: str
    external_baseline_asset_id: str
    expected_ablations: list[str] = Field(default_factory=list)
    rollback_strategy: str
    minimal_scope: str
    downstream_src_target: str
    remaining_upside: str
    trusted_evidence_ids: list[str] = Field(default_factory=list)
    scout_evidence_ids: list[str] = Field(default_factory=list)
    status: str = "proposed"
    internalization_level: str = "external_only"
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_level(self) -> "FrameworkProposalRecord":
        if self.internalization_level not in INTERNALIZATION_LEVELS:
            raise ValueError(f"unsupported internalization level: {self.internalization_level}")
        return self


def lineage_dir(paths: VibePaths):
    return ensure_dir(paths.research / "lineage")


def lineage_paths(paths: VibePaths) -> dict[str, Any]:
    base = lineage_dir(paths)
    return {
        "assets": base / "external_assets.jsonl",
        "relations": base / "relations.jsonl",
        "decisions": base / "internalization_decisions.jsonl",
        "proposals": base / "framework_proposals.jsonl",
        "audits": base / "internalization_audits.jsonl",
        "memory": base / "memory.md",
    }


def add_external_asset(
    paths: VibePaths,
    *,
    source: str,
    title: str = "",
    asset_type: str = "external_repo",
    purpose: str = "reference_implementation",
    credibility: str = "unknown",
    license_or_restrictions: str = "",
    dependency_mode: str = "unknown",
    replacement_plan: str = "",
) -> dict[str, Any]:
    files = lineage_paths(paths)
    existing = [row.get("asset_id", "") for row in read_jsonl(files["assets"])]
    record = ExternalAssetRecord(
        asset_id=next_numeric_id(existing, "asset_"),
        source=source,
        title=title,
        asset_type=asset_type,
        purpose=purpose,
        credibility=credibility,
        license_or_restrictions=license_or_restrictions,
        dependency_mode=dependency_mode,
        replacement_plan=replacement_plan,
        provenance={"source": "vibe lineage add-external-asset"},
    ).model_dump()
    append_jsonl(files["assets"], record)
    return record


def add_lineage_relation(paths: VibePaths, *, source_id: str, target_id: str, relation_type: str, rationale: str = "") -> dict[str, Any]:
    files = lineage_paths(paths)
    existing = [row.get("relation_id", "") for row in read_jsonl(files["relations"])]
    record = LineageRelationRecord(
        relation_id=next_numeric_id(existing, "relation_"),
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
        rationale=rationale,
    ).model_dump()
    append_jsonl(files["relations"], record)
    return record


def record_internalization_decision(
    paths: VibePaths,
    *,
    internalize_what: str,
    why_now: str,
    expected_benefit: str,
    downstream_src_target: str,
    baseline_comparison: str,
    rollback_plan: str,
    proposal_id: str = "",
    hypothesis_id: str = "",
    asset_id: str = "",
    risks: list[str] | None = None,
    new_scripts_needed: list[str] | None = None,
    adapter_capability_impact: str = "",
    evidence_ids: list[str] | None = None,
    status: str = "proposed",
) -> dict[str, Any]:
    files = lineage_paths(paths)
    existing = [row.get("decision_id", "") for row in read_jsonl(files["decisions"])]
    record = InternalizationDecisionRecord(
        decision_id=next_numeric_id(existing, "internalization_decision_"),
        proposal_id=proposal_id,
        hypothesis_id=hypothesis_id,
        asset_id=asset_id,
        internalize_what=internalize_what,
        why_now=why_now,
        expected_benefit=expected_benefit,
        risks=risks or [],
        downstream_src_target=downstream_src_target,
        new_scripts_needed=new_scripts_needed or [],
        adapter_capability_impact=adapter_capability_impact,
        baseline_comparison=baseline_comparison,
        rollback_plan=rollback_plan,
        evidence_ids=evidence_ids or [],
        status=status,
    ).model_dump()
    append_jsonl(files["decisions"], record)
    return record


def create_framework_proposal(
    paths: VibePaths,
    *,
    title: str,
    hypothesis_id: str,
    asset_id: str,
    design_summary: str,
    module_design: str,
    data_flow: str,
    metrics_schema_ref: str,
    external_baseline_asset_id: str,
    rollback_strategy: str,
    minimal_scope: str,
    downstream_src_target: str,
    remaining_upside: str,
    interfaces: list[str] | None = None,
    training_entrypoint: str = "",
    evaluation_entrypoint: str = "",
    expected_ablations: list[str] | None = None,
    trusted_evidence_ids: list[str] | None = None,
    scout_evidence_ids: list[str] | None = None,
    status: str = "proposed",
) -> dict[str, Any]:
    files = lineage_paths(paths)
    existing = [row.get("proposal_id", "") for row in read_jsonl(files["proposals"])]
    record = FrameworkProposalRecord(
        proposal_id=next_numeric_id(existing, "framework_proposal_"),
        title=title,
        hypothesis_id=hypothesis_id,
        asset_id=asset_id,
        design_summary=design_summary,
        module_design=module_design,
        data_flow=data_flow,
        interfaces=interfaces or [],
        training_entrypoint=training_entrypoint,
        evaluation_entrypoint=evaluation_entrypoint,
        metrics_schema_ref=metrics_schema_ref,
        external_baseline_asset_id=external_baseline_asset_id,
        expected_ablations=expected_ablations or [],
        rollback_strategy=rollback_strategy,
        minimal_scope=minimal_scope,
        downstream_src_target=downstream_src_target,
        remaining_upside=remaining_upside,
        trusted_evidence_ids=trusted_evidence_ids or [],
        scout_evidence_ids=scout_evidence_ids or [],
        status=status,
    ).model_dump()
    append_jsonl(files["proposals"], record)
    write_text(lineage_dir(paths) / f"{record['proposal_id']}.md", render_framework_proposal(record))
    return record


def internalization_readiness(paths: VibePaths, proposal_id: str, *, target_level: str = "shadow_internal") -> dict[str, Any]:
    files = lineage_paths(paths)
    proposals = read_jsonl(files["proposals"])
    assets = read_jsonl(files["assets"])
    proposal = next((row for row in proposals if row.get("proposal_id") == proposal_id), None)
    asset_by_id = {row.get("asset_id", ""): row for row in assets}
    blockers: list[str] = []
    warnings: list[str] = []
    if target_level not in INTERNALIZATION_LEVELS:
        blockers.append("unsupported_target_level")
    if not proposal:
        blockers.append("missing_framework_proposal")
    else:
        current_level = proposal.get("internalization_level", "external_only")
        if not next_internalization_allowed(current_level, target_level):
            blockers.append("internalization_level_skip_not_allowed")
        if not proposal.get("downstream_src_target"):
            blockers.append("missing_downstream_src_target")
        if not proposal.get("metrics_schema_ref"):
            blockers.append("missing_metrics_schema")
        if not proposal.get("remaining_upside"):
            blockers.append("missing_remaining_upside")
        baseline_id = proposal.get("external_baseline_asset_id", "")
        baseline = asset_by_id.get(baseline_id)
        if not baseline:
            blockers.append("missing_external_baseline")
        elif not baseline.get("source"):
            blockers.append("external_baseline_missing_source")
        if not proposal.get("minimal_scope"):
            blockers.append("missing_minimal_internal_module_scope")
        trusted_ids = set(proposal.get("trusted_evidence_ids", []))
        trusted_records = [
            row
            for row in load_evidence(paths).values()
            if row.get("evidence_id") in trusted_ids and row.get("trusted") and row.get("schema_valid")
        ]
        scout_records = qualifying_scout_evidence(paths, proposal.get("scout_evidence_ids", []))
        if not trusted_records and not scout_records:
            blockers.append("missing_trusted_or_qualifying_scout_evidence")
        if scout_records and not trusted_records:
            warnings.append("scout_evidence_supports_shadow_internal_but_does_not_replace_project_experiment_evidence")
        if proposal.get("status") not in {"approved", "reviewed", "proposed"}:
            warnings.append("proposal_status_not_ready")
    asset_blockers = external_asset_blockers(assets)
    blockers.extend(asset_blockers)
    result = {
        "created_at": utc_now(),
        "proposal_id": proposal_id,
        "target_level": target_level,
        "can_transition": not blockers,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "proposal": proposal or {},
    }
    append_jsonl(files["audits"], result)
    write_json(lineage_dir(paths) / "latest_readiness.json", result)
    return result


def next_internalization_allowed(current_level: str, target_level: str) -> bool:
    if current_level not in INTERNALIZATION_LEVELS or target_level not in INTERNALIZATION_LEVELS:
        return False
    if current_level == "external_only" and target_level == "shadow_internal":
        return True
    current = INTERNALIZATION_LEVELS.index(current_level)
    target = INTERNALIZATION_LEVELS.index(target_level)
    return target <= current + 1


def external_asset_blockers(assets: list[dict[str, Any]]) -> list[str]:
    blockers = []
    for asset in assets:
        asset_id = asset.get("asset_id", "unknown")
        if not asset.get("source"):
            blockers.append(f"{asset_id}:missing_source")
        if not asset.get("purpose"):
            blockers.append(f"{asset_id}:missing_purpose")
        if not asset.get("license_or_restrictions"):
            blockers.append(f"{asset_id}:missing_license_or_restrictions")
    return blockers


def build_lineage_memory(paths: VibePaths) -> dict[str, Any]:
    files = lineage_paths(paths)
    assets = read_jsonl(files["assets"])
    proposals = read_jsonl(files["proposals"])
    decisions = read_jsonl(files["decisions"])
    audits = read_jsonl(files["audits"])
    rejected = [row for row in proposals if row.get("status") == "rejected"]
    blocked = [row for row in audits if row.get("blockers")]
    memory = {
        "created_at": utc_now(),
        "external_dependencies": [row for row in assets if row.get("dependency_mode") not in {"none", "regression_only"}],
        "internal_candidates": [row for row in proposals if row.get("internalization_level") in {"shadow_internal", "hybrid_internal", "owned_core_candidate"} or row.get("status") in {"proposed", "approved", "reviewed"}],
        "failed_or_rejected_proposals": rejected,
        "blocked_readiness": blocked[-5:],
        "decisions": decisions[-10:],
    }
    write_json(lineage_dir(paths) / "memory.json", memory)
    write_text(files["memory"], render_lineage_memory(memory))
    return memory


def render_framework_proposal(record: dict[str, Any]) -> str:
    return (
        "# Framework Proposal\n\n"
        f"Proposal: `{record.get('proposal_id')}`\n\n"
        f"Title: {record.get('title')}\n\n"
        f"Design: {record.get('design_summary')}\n\n"
        f"Module: `{record.get('downstream_src_target')}`\n\n"
        f"External baseline: `{record.get('external_baseline_asset_id')}`\n\n"
        f"Rollback: {record.get('rollback_strategy')}\n"
    )


def render_lineage_memory(memory: dict[str, Any]) -> str:
    lines = ["# Lineage Memory", "", "## External Dependencies"]
    for row in memory.get("external_dependencies", []):
        lines.append(f"- `{row.get('asset_id')}` {row.get('title') or row.get('source')} purpose={row.get('purpose')} dependency={row.get('dependency_mode')}")
    if not memory.get("external_dependencies"):
        lines.append("- none")
    lines.extend(["", "## Internal Candidates"])
    for row in memory.get("internal_candidates", []):
        lines.append(f"- `{row.get('proposal_id')}` {row.get('title')} level={row.get('internalization_level')} status={row.get('status')}")
    if not memory.get("internal_candidates"):
        lines.append("- none")
    lines.extend(["", "## Failed Or Rejected Proposals"])
    for row in memory.get("failed_or_rejected_proposals", []):
        lines.append(f"- `{row.get('proposal_id')}` {row.get('title')} status={row.get('status')}")
    if not memory.get("failed_or_rejected_proposals"):
        lines.append("- none")
    lines.extend(["", "## Recent Blocked Readiness"])
    for row in memory.get("blocked_readiness", []):
        lines.append(f"- `{row.get('proposal_id')}` blockers={', '.join(row.get('blockers', []))}")
    if not memory.get("blocked_readiness"):
        lines.append("- none")
    return "\n".join(lines) + "\n"
