"""Generic resource policy normalization for compiled runs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_run_resources(resources: dict[str, Any], config: dict[str, Any], *, long_run_allowed: bool = False) -> dict[str, Any]:
    """Apply project scheduler defaults and bounded runtime limits to a run."""

    normalized = deepcopy(resources) if isinstance(resources, dict) else {}
    execution_slurm = config.get("execution", {}).get("slurm", {}) if isinstance(config.get("execution"), dict) else {}
    scheduler = config.get("scheduler", {}) if isinstance(config.get("scheduler"), dict) else {}
    preferred = list(normalized.get("preferred_partitions") or [])
    fallback = list(normalized.get("fallback_partitions") or [])
    if not preferred and execution_slurm.get("default_partition"):
        preferred = [execution_slurm["default_partition"]]
    if not fallback:
        fallback = list(execution_slurm.get("fallback_partitions") or config.get("slurm", {}).get("fallback_partitions", []))
    normalized["preferred_partitions"] = preferred
    normalized["fallback_partitions"] = fallback
    if "max_pending_start_plus_run_hours" not in normalized:
        normalized["max_pending_start_plus_run_hours"] = execution_slurm.get(
            "max_pending_start_plus_run_hours",
            config.get("slurm", {}).get("max_pending_start_plus_run_hours", 24),
        )
    allow_strict = bool(normalized.get("allow_strict_preferred_partition") or scheduler.get("allow_strict_preferred_partition", False))
    if fallback and not allow_strict:
        normalized.pop("strict_preferred_partition", None)
        normalized.pop("prefer_configured_partition", None)
    maturity = str(normalized.get("maturity", "")).lower()
    delivery_stage = maturity in {"delivery", "submission", "submit", "final", "final_delivery", "production_delivery"}
    normal_cap = float(scheduler.get("max_run_hours_per_experiment", scheduler.get("max_walltime_hours_per_run", 12)) or 0)
    mature_cap = float(scheduler.get("mature_max_run_hours_per_experiment", normal_cap or 24) or 0)
    delivery_cap = float(scheduler.get("delivery_max_run_hours_per_experiment", mature_cap or normal_cap or 0) or 0)
    max_hours = delivery_cap if delivery_stage else mature_cap if long_run_allowed or maturity in {"mature", "full", "production"} else normal_cap
    if max_hours > 0:
        current_hours = walltime_hours(str(normalized.get("time", "")))
        if current_hours <= 0 or current_hours > max_hours:
            normalized["time"] = hours_to_slurm_time(max_hours)
        normalized.setdefault("runtime_limits", {})["max_run_hours"] = max_hours
    max_epochs = int(scheduler.get("max_epochs_per_experiment", 0) or 0)
    mature_epochs = int(scheduler.get("mature_max_epochs_per_experiment", max_epochs) or 0)
    delivery_epochs = int(scheduler.get("delivery_max_epochs_per_experiment", mature_epochs or max_epochs) or 0)
    epoch_cap = delivery_epochs if delivery_stage else mature_epochs if long_run_allowed or maturity in {"mature", "full", "production"} else max_epochs
    if epoch_cap > 0:
        for key in ["epochs", "max_epochs"]:
            if key in normalized:
                try:
                    normalized[key] = min(int(normalized[key]), epoch_cap)
                except (TypeError, ValueError):
                    normalized[key] = epoch_cap
        normalized.setdefault("max_epochs", epoch_cap)
        normalized.setdefault("runtime_limits", {})["max_epochs"] = epoch_cap
    return normalized


def walltime_hours(value: str) -> float:
    parts = [part for part in value.strip().split(":") if part != ""]
    try:
        if len(parts) == 3:
            hours, minutes, seconds = [int(part) for part in parts]
            return hours + minutes / 60 + seconds / 3600
        if len(parts) == 2:
            minutes, seconds = [int(part) for part in parts]
            return minutes / 60 + seconds / 3600
        if len(parts) == 1 and parts[0]:
            return float(parts[0])
    except ValueError:
        return 0.0
    return 0.0


def hours_to_slurm_time(hours: float) -> str:
    total_seconds = max(60, int(round(hours * 3600)))
    hh, remainder = divmod(total_seconds, 3600)
    mm, ss = divmod(remainder, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}"
