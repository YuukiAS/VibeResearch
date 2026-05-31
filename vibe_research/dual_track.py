"""External/internal/hybrid portfolio tracking and gates."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from .io import append_jsonl, ensure_dir, next_numeric_id, read_json, read_jsonl, read_yaml, utc_now, write_json, write_text
from .paths import VibePaths
from .research_manager import load_evidence, load_experiments, save_experiments


TRACKS = {"external", "internal", "hybrid"}
PROMOTION_LEVELS = {"shadow_internal", "hybrid_internal", "owned_core_candidate"}


class TrackExperimentRecord(BaseModel):
    track_record_id: str
    experiment_id: str
    track: str
    internalization_level: str = "external_only"
    external_baseline_asset_id: str = ""
    metrics_comparable: bool = False
    design_diff: dict[str, Any] = Field(default_factory=dict)
    protected_metric_gate: dict[str, Any] = Field(default_factory=dict)
    trusted_evidence_ids: list[str] = Field(default_factory=list)
    resource_units: dict[str, float] = Field(default_factory=dict)
    pseudo_internalization: bool = False
    pseudo_internalization_reason: str = ""
    status: str = "planned"
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_track(self) -> "TrackExperimentRecord":
        if self.track not in TRACKS:
            raise ValueError(f"unsupported track: {self.track}")
        return self


def track_dir(paths: VibePaths):
    return ensure_dir(paths.research / "tracks")


def track_paths(paths: VibePaths) -> dict[str, Any]:
    base = track_dir(paths)
    return {
        "experiments": base / "experiments.jsonl",
        "audits": base / "audits.jsonl",
        "comparison_plans": base / "comparison_plans.jsonl",
        "budget_audit": base / "budget_audit.json",
        "memo": base / "memo.md",
    }


def create_track_experiment(
    paths: VibePaths,
    *,
    experiment_id: str,
    track: str,
    internalization_level: str = "external_only",
    external_baseline_asset_id: str = "",
    metrics_comparable: bool = False,
    design_diff: dict[str, Any] | None = None,
    protected_metric_gate: dict[str, Any] | None = None,
    trusted_evidence_ids: list[str] | None = None,
    resource_units: dict[str, float] | None = None,
    pseudo_internalization: bool = False,
    pseudo_internalization_reason: str = "",
) -> dict[str, Any]:
    experiments = load_experiments(paths)
    if experiment_id not in experiments:
        raise ValueError(f"Unknown experiment: {experiment_id}")
    files = track_paths(paths)
    existing = [row.get("track_record_id", "") for row in read_jsonl(files["experiments"])]
    record = TrackExperimentRecord(
        track_record_id=next_numeric_id(existing, "track_"),
        experiment_id=experiment_id,
        track=track,
        internalization_level=internalization_level,
        external_baseline_asset_id=external_baseline_asset_id,
        metrics_comparable=metrics_comparable,
        design_diff=design_diff or {},
        protected_metric_gate=protected_metric_gate or {},
        trusted_evidence_ids=trusted_evidence_ids or [],
        resource_units=resource_units or {},
        pseudo_internalization=pseudo_internalization,
        pseudo_internalization_reason=pseudo_internalization_reason,
    ).model_dump()
    append_jsonl(files["experiments"], record)
    experiments[experiment_id].setdefault("track_metadata", {}).update(record)
    experiments[experiment_id]["track"] = track
    experiments[experiment_id]["updated_at"] = utc_now()
    save_experiments(paths, experiments)
    return record


def parallel_comparison_plan(paths: VibePaths, track_record_id: str, *, comparison_stage: str = "smoke") -> dict[str, Any]:
    record = get_track_record(paths, track_record_id)
    blockers = []
    if not record.get("external_baseline_asset_id"):
        blockers.append("missing_external_baseline")
    if not record.get("metrics_comparable"):
        blockers.append("missing_comparable_metrics")
    plan = {
        "created_at": utc_now(),
        "track_record_id": track_record_id,
        "experiment_id": record.get("experiment_id", ""),
        "comparison_stage": comparison_stage,
        "external_baseline_asset_id": record.get("external_baseline_asset_id", ""),
        "metrics_comparable": record.get("metrics_comparable", False),
        "required": record.get("track") in {"internal", "hybrid"},
        "blocked": bool(blockers),
        "blockers": blockers,
    }
    append_jsonl(track_paths(paths)["comparison_plans"], plan)
    return plan


def track_transition_audit(paths: VibePaths, track_record_id: str, *, target_level: str) -> dict[str, Any]:
    record = get_track_record(paths, track_record_id)
    blockers: list[str] = []
    warnings: list[str] = []
    if target_level not in PROMOTION_LEVELS:
        blockers.append("unsupported_target_level")
    if record.get("track") == "external" and target_level != "shadow_internal":
        blockers.append("external_track_cannot_promote_to_internal_core")
    if target_level in {"hybrid_internal", "owned_core_candidate"} and record.get("internalization_level") == "external_only":
        blockers.append("must_enter_shadow_internal_before_higher_internal_level")
    if record.get("track") in {"internal", "hybrid"}:
        if not record.get("external_baseline_asset_id"):
            blockers.append("missing_external_baseline")
        if not record.get("metrics_comparable"):
            blockers.append("missing_comparable_metrics")
        if not record.get("design_diff"):
            blockers.append("missing_external_to_internal_design_diff")
        if record.get("pseudo_internalization"):
            blockers.append("pseudo_internalization_detected")
        gate = record.get("protected_metric_gate", {})
        if gate and gate.get("passed") is False:
            blockers.append("protected_metric_regression")
        trusted = trusted_evidence_records(paths, record.get("trusted_evidence_ids", []))
        if not trusted:
            blockers.append("missing_trusted_evidence")
    if target_level == "shadow_internal":
        warnings.append("shadow_internal_may_run_but_must_not_replace_external_baseline_by_default")
    budget = track_budget_audit(paths)
    if record.get("track") in budget.get("blocked_tracks", []):
        blockers.append(f"track_budget_exceeded:{record.get('track')}")
    result = {
        "created_at": utc_now(),
        "track_record_id": track_record_id,
        "target_level": target_level,
        "can_transition": not blockers,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "record": record,
    }
    append_jsonl(track_paths(paths)["audits"], result)
    return result


def track_budget_audit(paths: VibePaths) -> dict[str, Any]:
    policy = read_yaml(paths.policies / "track_budget.yaml", {}) or {}
    ratios = policy.get("max_ratio", {}) if isinstance(policy.get("max_ratio"), dict) else {}
    records = read_jsonl(track_paths(paths)["experiments"])
    units_by_track = {track: 0.0 for track in TRACKS}
    for record in records:
        units = record.get("resource_units", {}) if isinstance(record.get("resource_units"), dict) else {}
        units_by_track[record.get("track", "external")] = units_by_track.get(record.get("track", "external"), 0.0) + float(units.get("gpu_hours", units.get("total", 0.0)) or 0.0)
    total = sum(units_by_track.values())
    ratios_observed = {track: (value / total if total else 0.0) for track, value in units_by_track.items()}
    blocked = [track for track, ratio in ratios_observed.items() if track in ratios and ratio > float(ratios[track])]
    result = {"created_at": utc_now(), "units_by_track": units_by_track, "ratios": ratios_observed, "policy": policy, "blocked_tracks": sorted(blocked)}
    write_json(track_paths(paths)["budget_audit"], result)
    return result


def track_memo(paths: VibePaths) -> dict[str, Any]:
    records = read_jsonl(track_paths(paths)["experiments"])
    audits = read_jsonl(track_paths(paths)["audits"])
    by_track = {track: [row for row in records if row.get("track") == track] for track in sorted(TRACKS)}
    result = {"created_at": utc_now(), "by_track": by_track, "recent_audits": audits[-5:]}
    write_text(track_paths(paths)["memo"], render_track_memo(result))
    return result


def get_track_record(paths: VibePaths, track_record_id: str) -> dict[str, Any]:
    record = next((row for row in read_jsonl(track_paths(paths)["experiments"]) if row.get("track_record_id") == track_record_id), None)
    if not record:
        raise ValueError(f"Unknown track record: {track_record_id}")
    return record


def trusted_evidence_records(paths: VibePaths, evidence_ids: list[str]) -> list[dict[str, Any]]:
    ids = set(evidence_ids)
    return [row for row in load_evidence(paths).values() if row.get("evidence_id") in ids and row.get("trusted") and row.get("schema_valid")]


def render_track_memo(result: dict[str, Any]) -> str:
    lines = ["# Dual-Track Portfolio Memo", ""]
    for track in ["external", "internal", "hybrid"]:
        rows = result.get("by_track", {}).get(track, [])
        lines.append(f"## {track.title()} Track")
        if rows:
            lines.extend([f"- `{row.get('track_record_id')}` experiment `{row.get('experiment_id')}` level={row.get('internalization_level')}" for row in rows])
        else:
            lines.append("- none")
        lines.append("")
    lines.append("## Recent Transition Audits")
    for audit in result.get("recent_audits", []):
        lines.append(f"- `{audit.get('track_record_id')}` target={audit.get('target_level')} blockers={', '.join(audit.get('blockers', [])) or 'none'}")
    if not result.get("recent_audits"):
        lines.append("- none")
    return "\n".join(lines) + "\n"
