"""Slurm helpers used by the scheduler boundary.

The first implementation is intentionally dry-run friendly: it can render an
sbatch script and classify common failure text without requiring Slurm on the
developer machine. Actual submission is owned by scheduler commands.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any


def render_sbatch(
    manifest: dict[str, Any],
    *,
    workdir: Path,
    output: Path,
    error: Path,
    partition: str | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    resources = manifest.get("resources", {})
    config = config or {}
    slurm = config.get("execution", {}).get("slurm", {}) or config.get("slurm", {})
    partitions = resources.get("preferred_partitions") or ([slurm.get("default_partition")] if slurm.get("default_partition") else [])
    selected_partition = partition or (partitions[0] if partitions else "")
    gres = slurm_gres_for_partition(selected_partition, {"resource_request": resources}, config)
    account = resources.get("account") or slurm.get("account", "")
    qos = resources.get("qos") or slurm.get("qos", "")
    return "\n".join(
        [line for line in [
            "#!/usr/bin/env bash",
            f"#SBATCH --job-name={manifest.get('run_id', 'vibe')}",
            f"#SBATCH --partition={selected_partition}" if selected_partition else "",
            "#SBATCH --nodes=1",
            "#SBATCH --ntasks=1",
            f"#SBATCH --cpus-per-task={resources.get('cpus', 1)}",
            f"#SBATCH --mem={resources.get('mem_gb', 4)}G",
            f"#SBATCH --time={resources.get('time', '01:00:00')}",
            f"#SBATCH --output={output}",
            f"#SBATCH --error={error}",
            f"#SBATCH --gres={gres}" if gres else "",
            f"#SBATCH --account={account}" if account else "",
            f"#SBATCH --qos={qos}" if qos else "",
            "",
            "set -euo pipefail",
            f"cd {workdir}",
            *runtime_limit_exports(resources),
            manifest.get("entrypoint", {}).get("env_setup", ""),
            manifest.get("entrypoint", {}).get("command", "true"),
            "",
        ] if line]
    )


def runtime_limit_exports(resources: dict[str, Any]) -> list[str]:
    limits = resources.get("runtime_limits", {}) if isinstance(resources.get("runtime_limits"), dict) else {}
    lines = []
    if limits.get("max_run_hours"):
        lines.append(f"export VIBE_MAX_RUN_HOURS={limits['max_run_hours']}")
    if limits.get("max_epochs"):
        lines.append(f"export VIBE_MAX_EPOCHS={limits['max_epochs']}")
    return lines


def slurm_gres_for_partition(partition: str, launch: dict[str, Any], config: dict[str, Any]) -> str:
    resource = launch.get("resource_request") or {}
    gpu = int(resource.get("gpu", 0) or 0)
    if not gpu:
        return ""
    for source in [
        resource.get("gres_by_partition", {}),
        resource.get("partition_gres", {}),
        config.get("execution", {}).get("slurm", {}).get("gres_by_partition", {}),
        config.get("execution", {}).get("slurm", {}).get("partition_gres", {}),
    ]:
        if isinstance(source, dict) and source.get(partition):
            return str(source[partition]).format(gpu=gpu)
    profiles = {
        row.get("name"): row
        for row in config.get("execution", {}).get("slurm", {}).get("partitions", [])
        if isinstance(row, dict) and row.get("name")
    }
    profile_gres = profiles.get(partition, {}).get("gres")
    if profile_gres:
        return str(profile_gres).format(gpu=gpu)
    return "gpu:{gpu}".format(gpu=gpu)


def select_partition(manifest: dict[str, Any], config: dict[str, Any]) -> str:
    return choose_partition(manifest, config)[0]


def choose_partition(manifest: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    resources = manifest.get("resources", {})
    preferred = list(resources.get("preferred_partitions") or [])
    fallback = list(resources.get("fallback_partitions") or [])
    execution_slurm = config.get("execution", {}).get("slurm", {})
    if resources.get("force_partition"):
        return str(resources["force_partition"]), "forced_partition"
    if not preferred and execution_slurm.get("default_partition"):
        preferred = [execution_slurm["default_partition"]]
    if resources.get("strict_preferred_partition") or resources.get("prefer_configured_partition"):
        if not preferred:
            return "", "strict_preferred_partition_missing"
        compatibility = partition_compatibility(preferred[0], {"resource_request": resources}, config)
        if compatibility.get("compatible") is False:
            return "", "strict_preferred_partition_incompatible: " + ",".join(compatibility.get("reasons", []))
        return preferred[0], "strict_preferred_partition"
    candidates = preferred + [p for p in fallback if p not in preferred]
    if not candidates:
        return "", "no_partition_configured"
    compatible_candidates, skipped = compatible_partition_candidates(candidates, {"resource_request": resources}, config)
    if not compatible_candidates:
        return "", "no_compatible_partition: " + ";".join(f"{row['partition']}={','.join(row.get('reasons', []))}" for row in skipped)
    available, reason = probe_available_partitions()
    if available:
        for name in compatible_candidates:
            if name in available:
                selected_reason = "preferred_available" if name in preferred else f"fallback_available: {reason}"
                return name, append_compatibility_skip_reason(selected_reason, skipped)
    profiles = {row.get("name"): row for row in execution_slurm.get("partitions", []) if row.get("name")}
    if not profiles:
        return compatible_candidates[0], append_compatibility_skip_reason(reason or "no_partition_profiles", skipped)
    ranked = sorted(compatible_candidates, key=lambda name: profiles.get(name, {}).get("priority", 0), reverse=True)
    selected = ranked[0]
    if selected not in preferred:
        return selected, append_compatibility_skip_reason("fallback_by_config_priority", skipped)
    return selected, append_compatibility_skip_reason(reason or "selected_by_config_priority", skipped)


def compatible_partition_candidates(candidates: list[str], launch: dict[str, Any], config: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    compatible: list[str] = []
    skipped: list[dict[str, Any]] = []
    for partition in candidates:
        check = partition_compatibility(partition, launch, config)
        if check.get("compatible") is False:
            skipped.append(check)
        else:
            compatible.append(partition)
    return compatible, skipped


def append_compatibility_skip_reason(reason: str, skipped: list[dict[str, Any]]) -> str:
    if not skipped:
        return reason
    summary = ";".join(f"{row['partition']}={','.join(row.get('reasons', []))}" for row in skipped)
    return f"{reason}; skipped_incompatible={summary}"


def partition_compatibility(partition: str, launch: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Evaluate declared Slurm partition/runtime compatibility.

    The framework does not infer GPU architecture from partition names. It only
    uses metadata declared by a project profile or a run resource request.
    """

    resource = launch.get("resource_request") or launch.get("resources") or {}
    slurm = config.get("execution", {}).get("slurm", {}) if isinstance(config.get("execution"), dict) else {}
    legacy_slurm = config.get("slurm", {}) if isinstance(config.get("slurm"), dict) else {}
    profile = partition_profile(partition, config)
    metadata = partition_gpu_metadata(partition, config)
    runtime = {}
    for source in [
        legacy_slurm.get("runtime_requirements", {}),
        slurm.get("runtime_requirements", {}),
        resource.get("runtime_requirements", {}),
    ]:
        if isinstance(source, dict):
            runtime.update(source)
    if resource.get("min_cuda_compute_capability") is not None:
        runtime["min_cuda_compute_capability"] = resource.get("min_cuda_compute_capability")
    allowed_partitions = set(normalize_string_list(resource.get("allowed_partitions") or runtime.get("allowed_partitions") or slurm.get("allowed_partitions")))
    excluded_partitions = set(normalize_string_list(resource.get("excluded_partitions") or runtime.get("excluded_partitions") or slurm.get("excluded_partitions")))
    allowed_families = set(normalize_string_list(resource.get("allowed_gpu_families") or runtime.get("allowed_gpu_families") or slurm.get("allowed_gpu_families")))
    excluded_families = set(normalize_string_list(resource.get("excluded_gpu_families") or runtime.get("excluded_gpu_families") or slurm.get("excluded_gpu_families")))
    reasons: list[str] = []
    partition_key = partition.strip().lower()
    if allowed_partitions and partition_key not in allowed_partitions:
        reasons.append("partition_not_allowed")
    if partition_key in excluded_partitions:
        reasons.append("partition_excluded")
    family = str(metadata.get("gpu_family") or metadata.get("family") or profile.get("gpu_family") or profile.get("gpu_model") or "").strip().lower()
    if allowed_families and (not family or family not in allowed_families):
        reasons.append("gpu_family_not_allowed")
    if family and family in excluded_families:
        reasons.append("gpu_family_excluded")
    min_cc = parse_float(runtime.get("min_cuda_compute_capability"))
    cc = parse_float(
        metadata.get("cuda_compute_capability")
        or metadata.get("compute_capability")
        or profile.get("cuda_compute_capability")
        or profile.get("compute_capability")
    )
    if min_cc is not None:
        if cc is None:
            reasons.append("partition_compute_capability_unknown_for_requirement")
        elif cc < min_cc:
            reasons.append("cuda_compute_capability_below_requirement")
    checked = bool(runtime or allowed_partitions or excluded_partitions or allowed_families or excluded_families or metadata or profile)
    return {
        "partition": partition,
        "compatible": not reasons,
        "checked": checked,
        "reasons": reasons,
        "requirements": runtime,
        "metadata": {
            "gpu_family": family,
            "cuda_compute_capability": cc,
            **{k: v for k, v in metadata.items() if k not in {"gpu_family", "family", "cuda_compute_capability", "compute_capability"}},
        },
    }


def partition_profile(partition: str, config: dict[str, Any]) -> dict[str, Any]:
    slurm = config.get("execution", {}).get("slurm", {}) if isinstance(config.get("execution"), dict) else {}
    for row in slurm.get("partitions", []):
        if isinstance(row, dict) and row.get("name") == partition:
            return row
    return {}


def partition_gpu_metadata(partition: str, config: dict[str, Any]) -> dict[str, Any]:
    slurm = config.get("execution", {}).get("slurm", {}) if isinstance(config.get("execution"), dict) else {}
    legacy_slurm = config.get("slurm", {}) if isinstance(config.get("slurm"), dict) else {}
    metadata: dict[str, Any] = {}
    for slurm_source in [legacy_slurm, slurm]:
        for key in ["partition_gpu_metadata", "gpu_metadata_by_partition", "partition_gpu_capabilities"]:
            source = slurm_source.get(key, {})
            if isinstance(source, dict) and isinstance(source.get(partition), dict):
                metadata.update(source[partition])
            elif isinstance(source, dict) and source.get(partition) is not None:
                metadata["cuda_compute_capability"] = source[partition]
    return metadata


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip().lower()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    return []


def parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def probe_available_partitions() -> tuple[set[str], str]:
    try:
        result = subprocess.run(["sinfo", "-h", "-o", "%P|%a|%t"], text=True, capture_output=True, check=False, timeout=10)
    except Exception as exc:
        return set(), f"sinfo_unavailable: {exc}"
    if result.returncode != 0:
        return set(), result.stderr.strip() or "sinfo_failed"
    available: set[str] = set()
    for line in result.stdout.splitlines():
        name, _, rest = line.partition("|")
        active, _, state = rest.partition("|")
        clean = name.replace("*", "").strip()
        if clean and active.strip().lower() == "up" and state.strip().lower() not in {"down", "drain", "drained"}:
            available.add(clean)
    return available, "sinfo"


def classify_failure(text: str) -> str:
    lowered = text.lower()
    if "out of memory" in lowered or "oom" in lowered:
        return "oom"
    if "time limit" in lowered or "timeout" in lowered:
        return "timeout"
    if "nan" in lowered:
        return "nan"
    if "importerror" in lowered or "modulenotfounderror" in lowered:
        return "import_error"
    if "permission denied" in lowered or "operation not permitted" in lowered:
        return "permission"
    if "quota" in lowered or "no space left" in lowered:
        return "quota"
    return "unknown"
